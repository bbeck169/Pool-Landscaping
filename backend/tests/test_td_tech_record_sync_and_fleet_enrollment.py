"""TD-tech-record-sync-and-fleet-enrollment · Feb-2026
=====================================================

Regression lock for the P-ticket atomic payload:

  §1 — Pass A/B/C dry-run writes nothing (counts only).
  §2 — Pass A --apply creates technicians rows for true orphans,
       stamps users.technician_id, back-stamps technicians.user_id
       for the half-linked case.
  §3 — Pass B --apply re-points jobs.technician_id from the orphan
       user_id to the newly-created technicians.id, preserving the
       original in the breadcrumb field.
  §4 — Pass C --apply enrolls each tech-role user into
       fleet_membership with in_fleet=true (operator Q2 default).
  §5 — Idempotent re-run: Pass A/B/C re-apply no-ops (0 writes).
  §6 — Tenant isolation — --tenant <X> does not touch tenant Y.
  §7 — Soft-deleted / inactive users are SKIPPED in all passes.
  §8 — assert_user_linked_to_technician raises 409
       technician_not_linked for orphan tech-role users and
       no-ops for linked tech + non-tech roles.

Isolation
---------
Each test seeds under a unique tenant id (``TEST_tp1_<uuid>``) and
tears down every seeded row at the end.  No reliance on the shared
preview DB fixtures.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


@pytest.fixture()
def tenant_a() -> str:
    return f"TEST_tp1_{uuid4().hex[:12]}"


@pytest.fixture()
def tenant_b() -> str:
    return f"TEST_tp1_{uuid4().hex[:12]}"


def _seed_user(
    *, tenant_id: str, uid: str, role: str = "technician",
    email: str = None, name: str = None,
    technician_id: str = None,
    deleted_at: str = None,
    is_active: bool = True,
) -> Dict[str, Any]:
    doc = {
        "id": uid, "tenant_id": tenant_id, "role": role,
        "email": email or f"{uid}@fixture.test",
        "name": name or f"User {uid[:6]}",
        "phone": "+15555550123",
        "is_active": is_active,
    }
    if technician_id is not None:
        doc["technician_id"] = technician_id
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    _run(_DB.users.insert_one(doc))
    return doc


def _seed_tech(
    *, tenant_id: str, tid: str, user_id: str = None,
    name: str = "Fixture Tech",
    deleted_at: str = None,
) -> Dict[str, Any]:
    doc = {
        "id": tid, "tenant_id": tenant_id, "name": name,
        "email": f"{tid}@fixture.test", "active": True,
    }
    if user_id is not None:
        doc["user_id"] = user_id
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    _run(_DB.technicians.insert_one(doc))
    return doc


def _seed_job(
    *, tenant_id: str, jid: str, technician_id: str,
) -> Dict[str, Any]:
    doc = {
        "id": jid, "tenant_id": tenant_id,
        "technician_id": technician_id,
        "scheduled_date": "2026-02-20",
        "status": "pending",
    }
    _run(_DB.jobs.insert_one(doc))
    return doc


def _cleanup(tenant_ids: List[str]) -> None:
    for coll in ("users", "technicians", "jobs", "fleet_membership"):
        _run(_DB[coll].delete_many({"tenant_id": {"$in": tenant_ids}}))
    _run(_DB["_migrations"].delete_many(
        {"key": "tech_record_sync_and_fleet_enrollment_v1"}))


# ═══════════════════════════════════════════════════════════════════
# §1 — Dry-run writes nothing
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_writes_nothing(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid)
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=False))
        assert out["status"] == "dry-run"
        stats = out["stats"]
        assert stats["pass_a_orphans"] == 1
        assert stats["pass_c_to_enroll"] == 1
        # Verify no writes landed.
        assert _run(_DB.technicians.count_documents(
            {"tenant_id": tenant_a})) == 0
        assert _run(_DB.fleet_membership.count_documents(
            {"tenant_id": tenant_a})) == 0
        assert _run(_DB["_migrations"].find_one(
            {"key": "tech_record_sync_and_fleet_enrollment_v1"})) is None
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §2 — Pass A --apply: creates tech row + stamps both sides
# ═══════════════════════════════════════════════════════════════════
def test_pass_a_apply_creates_tech_and_stamps_both_sides(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid, email="orphan@fixture.test",
               name="Orphan Tech")
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True, passes="A"))
        assert out["status"] == "applied"
        assert out["stats"]["pass_a_created"] == 1
        # New tech row exists, linked to user.
        tech = _run(_DB.technicians.find_one(
            {"tenant_id": tenant_a, "user_id": uid}, {"_id": 0}))
        assert tech is not None
        assert tech["name"] == "Orphan Tech"
        assert tech["email"] == "orphan@fixture.test"
        assert tech["source"] == "tech_record_sync_and_fleet_enrollment_v1"
        # User side stamped.
        u = _run(_DB.users.find_one({"id": uid}, {"_id": 0}))
        assert u["technician_id"] == tech["id"]
        assert u.get("technician_backfill_v1_at")
    finally:
        _cleanup([tenant_a])


def test_pass_a_apply_backfills_half_linked_reverse(tenant_a):
    """users.technician_id → live tech but tech.user_id missing →
    Pass A back-stamps technicians.user_id."""
    uid = f"u-{uuid4().hex[:8]}"
    tid = f"t-{uuid4().hex[:8]}"
    _seed_tech(tenant_id=tenant_a, tid=tid, user_id=None)
    _seed_user(tenant_id=tenant_a, uid=uid, technician_id=tid)
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True, passes="A"))
        assert out["status"] == "applied"
        # No new tech row created — just a back-stamp.
        assert out["stats"]["pass_a_created"] == 0
        assert out["stats"]["pass_a_backfilled"] == 1
        tech = _run(_DB.technicians.find_one({"id": tid}, {"_id": 0}))
        assert tech["user_id"] == uid
        assert tech["linked_by"] == "tech_record_sync_and_fleet_enrollment_v1"
    finally:
        _cleanup([tenant_a])


def test_pass_a_apply_backfills_half_linked_forward(tenant_a):
    """technicians.user_id → user but users.technician_id missing →
    Pass A back-stamps users.technician_id."""
    uid = f"u-{uuid4().hex[:8]}"
    tid = f"t-{uuid4().hex[:8]}"
    _seed_tech(tenant_id=tenant_a, tid=tid, user_id=uid)
    _seed_user(tenant_id=tenant_a, uid=uid)  # no technician_id
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True, passes="A"))
        assert out["stats"]["pass_a_created"] == 0
        assert out["stats"]["pass_a_backfilled"] == 1
        u = _run(_DB.users.find_one({"id": uid}, {"_id": 0}))
        assert u["technician_id"] == tid
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §3 — Pass B --apply: re-points jobs with breadcrumb
# ═══════════════════════════════════════════════════════════════════
def test_pass_b_apply_repoints_jobs_from_user_id_to_new_tech_id(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    jid1 = f"j-{uuid4().hex[:8]}"
    jid2 = f"j-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid)
    # Both jobs keyed to the bare user_id — simulates the operator's bug.
    _seed_job(tenant_id=tenant_a, jid=jid1, technician_id=uid)
    _seed_job(tenant_id=tenant_a, jid=jid2, technician_id=uid)
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True, passes="AB"))
        assert out["status"] == "applied"
        assert out["stats"]["pass_a_created"] == 1
        assert out["stats"]["pass_b_moved"] == 2
        # Fetch the new tech id to assert the re-point.
        new_tech = _run(_DB.technicians.find_one(
            {"tenant_id": tenant_a, "user_id": uid}, {"_id": 0, "id": 1}))
        new_tech_id = new_tech["id"]
        for jid in (jid1, jid2):
            j = _run(_DB.jobs.find_one({"id": jid}, {"_id": 0}))
            assert j["technician_id"] == new_tech_id
            assert j["technician_id_td_tp1_before"] == uid
            assert j.get("technician_id_td_tp1_at")
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §4 — Pass C --apply: enrolls with in_fleet=true
# ═══════════════════════════════════════════════════════════════════
def test_pass_c_apply_enrolls_tech_users_with_in_fleet_true(tenant_a):
    uid1 = f"u-{uuid4().hex[:8]}"
    uid2 = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid1, role="technician")
    _seed_user(tenant_id=tenant_a, uid=uid2, role="tech")
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True, passes="C"))
        assert out["status"] == "applied"
        assert out["stats"]["pass_c_enrolled"] == 2
        for uid in (uid1, uid2):
            m = _run(_DB.fleet_membership.find_one(
                {"tenant_id": tenant_a, "tech_user_id": uid}, {"_id": 0}))
            assert m is not None
            assert m["in_fleet"] is True
            assert m["source"] == "tech_record_sync_and_fleet_enrollment_v1"
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §5 — Idempotent re-apply = 0 writes
# ═══════════════════════════════════════════════════════════════════
def test_idempotent_rerun_no_ops(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    jid = f"j-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid)
    _seed_job(tenant_id=tenant_a, jid=jid, technician_id=uid)
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        first = _run(run(tenant_id=tenant_a, apply=True, force=True))
        assert first["stats"]["pass_a_created"] == 1
        assert first["stats"]["pass_b_moved"] == 1
        assert first["stats"]["pass_c_enrolled"] == 1
        second = _run(run(tenant_id=tenant_a, apply=True, force=True))
        assert second["stats"]["pass_a_created"] == 0
        assert second["stats"]["pass_a_backfilled"] == 0
        assert second["stats"]["pass_b_moved"] == 0
        assert second["stats"]["pass_c_enrolled"] == 0
        # Still only one tech + one membership row.
        assert _run(_DB.technicians.count_documents(
            {"tenant_id": tenant_a})) == 1
        assert _run(_DB.fleet_membership.count_documents(
            {"tenant_id": tenant_a})) == 1
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §6 — Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_scope_does_not_touch_other_tenants(tenant_a, tenant_b):
    uid_a = f"u-{uuid4().hex[:8]}"
    uid_b = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid_a)
    _seed_user(tenant_id=tenant_b, uid=uid_b)
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["stats"]["pass_a_created"] == 1
        assert out["stats"]["tenants"] == 1
        # Tenant B untouched.
        assert _run(_DB.technicians.count_documents(
            {"tenant_id": tenant_b})) == 0
        assert _run(_DB.fleet_membership.count_documents(
            {"tenant_id": tenant_b})) == 0
    finally:
        _cleanup([tenant_a, tenant_b])


# ═══════════════════════════════════════════════════════════════════
# §7 — Soft-deleted / inactive users SKIPPED in all passes
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_user_skipped(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid,
               deleted_at="2026-02-01T00:00:00Z")
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["stats"]["pass_a_created"] == 0
        assert out["stats"]["pass_c_enrolled"] == 0
        assert _run(_DB.technicians.count_documents(
            {"tenant_id": tenant_a})) == 0
        assert _run(_DB.fleet_membership.count_documents(
            {"tenant_id": tenant_a})) == 0
    finally:
        _cleanup([tenant_a])


def test_inactive_user_skipped(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid, is_active=False)
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["stats"]["pass_a_created"] == 0
        assert out["stats"]["pass_c_enrolled"] == 0
    finally:
        _cleanup([tenant_a])


def test_active_false_user_skipped(tenant_a):
    """Legacy auth-side ``active=False`` flag (used by routers/auth.py's
    deactivated-user gate) must also exclude a user from all passes —
    preview DB has rows with ``is_active`` missing + ``active=False``
    that would otherwise slip through."""
    uid = f"u-{uuid4().hex[:8]}"
    # Seed WITHOUT is_active, then stamp active=False.
    _seed_user(tenant_id=tenant_a, uid=uid)
    _run(_DB.users.update_one(
        {"id": uid}, {"$set": {"active": False},
                       "$unset": {"is_active": ""}}))
    try:
        from migrations.tech_record_sync_and_fleet_enrollment_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["stats"]["pass_a_created"] == 0
        assert out["stats"]["pass_c_enrolled"] == 0
        assert _run(_DB.technicians.count_documents(
            {"tenant_id": tenant_a})) == 0
        assert _run(_DB.fleet_membership.count_documents(
            {"tenant_id": tenant_a})) == 0
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §8 — 409 gate semantics
# ═══════════════════════════════════════════════════════════════════
def test_gate_raises_for_orphan_tech_user(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid, role="technician")
    try:
        from services.mobile_tech_linkage import (
            assert_user_linked_to_technician,
        )
        user = _run(_DB.users.find_one({"id": uid}, {"_id": 0}))
        with pytest.raises(HTTPException) as exc:
            _run(assert_user_linked_to_technician(user, tenant_a))
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "technician_not_linked"
        assert exc.value.detail["user_id"] == uid
        assert exc.value.detail["tenant_id"] == tenant_a
    finally:
        _cleanup([tenant_a])


def test_gate_noop_for_linked_tech_user(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    tid = f"t-{uuid4().hex[:8]}"
    _seed_tech(tenant_id=tenant_a, tid=tid, user_id=uid)
    _seed_user(tenant_id=tenant_a, uid=uid, technician_id=tid)
    try:
        from services.mobile_tech_linkage import (
            assert_user_linked_to_technician,
        )
        user = _run(_DB.users.find_one({"id": uid}, {"_id": 0}))
        # Should NOT raise.
        _run(assert_user_linked_to_technician(user, tenant_a))
    finally:
        _cleanup([tenant_a])


def test_gate_noop_for_non_tech_role(tenant_a):
    uid = f"u-{uuid4().hex[:8]}"
    _seed_user(tenant_id=tenant_a, uid=uid, role="admin")
    try:
        from services.mobile_tech_linkage import (
            assert_user_linked_to_technician,
        )
        user = _run(_DB.users.find_one({"id": uid}, {"_id": 0}))
        # Should NOT raise — admins hit mobile endpoints for diagnostics.
        _run(assert_user_linked_to_technician(user, tenant_a))
    finally:
        _cleanup([tenant_a])


def test_gate_rejects_when_only_soft_deleted_tech_exists(tenant_a):
    """Stale ``users.technician_id`` pointing at a soft-deleted tech
    row should NOT pass the gate — otherwise an admin could pseudo-
    link a user by soft-deleting their tech."""
    uid = f"u-{uuid4().hex[:8]}"
    tid = f"t-{uuid4().hex[:8]}"
    _seed_tech(tenant_id=tenant_a, tid=tid, user_id=uid,
               deleted_at="2026-01-01T00:00:00Z")
    _seed_user(tenant_id=tenant_a, uid=uid, technician_id=tid)
    try:
        from services.mobile_tech_linkage import (
            assert_user_linked_to_technician,
        )
        user = _run(_DB.users.find_one({"id": uid}, {"_id": 0}))
        with pytest.raises(HTTPException) as exc:
            _run(assert_user_linked_to_technician(user, tenant_a))
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "technician_not_linked"
    finally:
        _cleanup([tenant_a])
