"""TD-crew-silently-drop-orphan-members-and-backfill · Feb-2026
================================================================

Regression lock for the orphan-tech_ids ticket.

Coverage
--------
§1 — Backfill scan + apply
  §1a — dry-run writes nothing (crew doc + sentinel both unchanged)
  §1b — --apply strips orphan ids, keeps valid ids, writes
         breadcrumb + member_added_at pruned in lockstep
  §1c — foreign-tenant ids are LEFT ALONE (not dropped by this
         backfill)
  §1d — idempotent re-apply no-ops via breadcrumb skip
  §1e — tenant isolation — --tenant <X> doesn't touch tenant Y
  §1f — --force bypasses the per-doc breadcrumb skip

The router-level silent-drop behavior is locked by the sibling
``test_td_crew_edit_no_auto_remove_and_save_full_roster.py::
test_patch_silently_drops_orphan_and_returns_200`` which was
rewritten from the Ticket G strict-reject assertion as part of
this ticket.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List
from uuid import uuid4

import pytest
from dotenv import dotenv_values
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
    return f"TEST_td_crew_{uuid4().hex[:12]}"


@pytest.fixture()
def tenant_b() -> str:
    return f"TEST_td_crew_{uuid4().hex[:12]}"


def _seed_user(*, tenant_id: str, uid: str = None) -> str:
    uid = uid or f"u-{uuid4().hex[:12]}"
    _run(_DB.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "email": f"{uid}@fixture.test",
    }))
    return uid


def _seed_crew(
    *, tenant_id: str, cid: str = None, tech_ids: List[str] = None,
) -> str:
    cid = cid or f"c-{uuid4().hex[:12]}"
    tech_ids = tech_ids or []
    _run(_DB.crews.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": f"Fixture Crew {cid[:6]}",
        "tech_ids": tech_ids,
        "member_added_at": {
            tid: "2026-01-01T00:00:00Z" for tid in tech_ids
        },
    }))
    return cid


def _cleanup(tenants: List[str]) -> None:
    for coll in ("users", "crews", "technicians"):
        _run(_DB[coll].delete_many(
            {"tenant_id": {"$in": tenants}},
        ))
    _run(_DB["_migrations"].delete_many(
        {"key": "crew_tech_ids_orphan_cleanup_v1"},
    ))


# ═══════════════════════════════════════════════════════════════════
# §1a — dry-run writes nothing
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_writes_nothing(tenant_a):
    valid = _seed_user(tenant_id=tenant_a)
    orphan = f"ghost-{uuid4().hex[:8]}"
    cid = _seed_crew(tenant_id=tenant_a, tech_ids=[valid, orphan])
    try:
        from migrations.crew_tech_ids_orphan_cleanup_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=False))
        assert out["status"] == "dry-run"
        assert out["stats"]["crews_affected"] == 1
        assert out["stats"]["orphan_ids_removed"] == 1
        doc = _run(_DB.crews.find_one({"id": cid}, {"_id": 0}))
        assert orphan in doc["tech_ids"]
        assert "tech_ids_orphan_cleanup_v1_removed" not in doc
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §1b — --apply strips orphan, writes breadcrumb, prunes map
# ═══════════════════════════════════════════════════════════════════
def test_apply_strips_orphan_writes_breadcrumb(tenant_a):
    valid = _seed_user(tenant_id=tenant_a)
    orphan1 = f"ghost1-{uuid4().hex[:8]}"
    orphan2 = f"ghost2-{uuid4().hex[:8]}"
    cid = _seed_crew(
        tenant_id=tenant_a,
        tech_ids=[valid, orphan1, orphan2],
    )
    try:
        from migrations.crew_tech_ids_orphan_cleanup_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["status"] == "applied"
        assert out["stats"]["orphan_ids_removed"] == 2
        doc = _run(_DB.crews.find_one({"id": cid}, {"_id": 0}))
        assert doc["tech_ids"] == [valid]
        assert set(doc["tech_ids_orphan_cleanup_v1_removed"]) == {
            orphan1, orphan2,
        }
        assert doc.get("tech_ids_orphan_cleanup_v1_at")
        # member_added_at pruned in lockstep.
        assert set(doc["member_added_at"].keys()) == {valid}
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §1c — foreign-tenant ids LEFT ALONE
# ═══════════════════════════════════════════════════════════════════
def test_foreign_tenant_ids_left_alone(tenant_a, tenant_b):
    valid_a = _seed_user(tenant_id=tenant_a)
    foreign_b = _seed_user(tenant_id=tenant_b)
    orphan = f"ghost-{uuid4().hex[:8]}"
    cid = _seed_crew(
        tenant_id=tenant_a,
        tech_ids=[valid_a, foreign_b, orphan],
    )
    try:
        from migrations.crew_tech_ids_orphan_cleanup_v1 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["stats"]["orphan_ids_removed"] == 1
        assert out["stats"]["foreign_ids_left_alone"] == 1
        doc = _run(_DB.crews.find_one({"id": cid}, {"_id": 0}))
        # Foreign preserved; orphan removed.
        assert foreign_b in doc["tech_ids"]
        assert valid_a in doc["tech_ids"]
        assert orphan not in doc["tech_ids"]
    finally:
        _cleanup([tenant_a, tenant_b])


# ═══════════════════════════════════════════════════════════════════
# §1d — idempotent re-apply no-ops
# ═══════════════════════════════════════════════════════════════════
def test_idempotent_rerun(tenant_a):
    valid = _seed_user(tenant_id=tenant_a)
    orphan = f"ghost-{uuid4().hex[:8]}"
    cid = _seed_crew(tenant_id=tenant_a, tech_ids=[valid, orphan])
    try:
        from migrations.crew_tech_ids_orphan_cleanup_v1 import run
        first = _run(run(tenant_id=tenant_a, apply=True))
        assert first["stats"]["orphan_ids_removed"] == 1
        second = _run(run(tenant_id=tenant_a, apply=True, force=True))
        # The breadcrumb-skip was bypassed by force=True so the crew
        # IS re-scanned; but since the orphan is already gone the
        # scan reports 0 remaining orphan ids.
        assert second["stats"]["orphan_ids_removed"] == 0
        doc = _run(_DB.crews.find_one({"id": cid}, {"_id": 0}))
        assert orphan not in doc["tech_ids"]
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §1e — tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_scope_does_not_touch_other_tenants(
    tenant_a, tenant_b,
):
    valid_a = _seed_user(tenant_id=tenant_a)
    valid_b = _seed_user(tenant_id=tenant_b)
    orphan_a = f"ghost-a-{uuid4().hex[:8]}"
    orphan_b = f"ghost-b-{uuid4().hex[:8]}"
    cid_a = _seed_crew(
        tenant_id=tenant_a, tech_ids=[valid_a, orphan_a],
    )
    cid_b = _seed_crew(
        tenant_id=tenant_b, tech_ids=[valid_b, orphan_b],
    )
    try:
        from migrations.crew_tech_ids_orphan_cleanup_v1 import run
        _run(run(tenant_id=tenant_a, apply=True))
        doc_a = _run(_DB.crews.find_one({"id": cid_a}, {"_id": 0}))
        doc_b = _run(_DB.crews.find_one({"id": cid_b}, {"_id": 0}))
        # Tenant A cleaned.
        assert orphan_a not in doc_a["tech_ids"]
        # Tenant B untouched.
        assert orphan_b in doc_b["tech_ids"]
        assert "tech_ids_orphan_cleanup_v1_at" not in doc_b
    finally:
        _cleanup([tenant_a, tenant_b])


# ═══════════════════════════════════════════════════════════════════
# §1f — --force bypasses per-doc breadcrumb skip
# ═══════════════════════════════════════════════════════════════════
def test_force_bypasses_breadcrumb_skip(tenant_a):
    valid = _seed_user(tenant_id=tenant_a)
    orphan = f"ghost-{uuid4().hex[:8]}"
    cid = _seed_crew(tenant_id=tenant_a, tech_ids=[valid, orphan])
    try:
        from migrations.crew_tech_ids_orphan_cleanup_v1 import run
        _run(run(tenant_id=tenant_a, apply=True))
        # Second run WITHOUT --force skips the already-cleaned
        # crew via the breadcrumb check.
        second = _run(run(tenant_id=tenant_a, apply=True, force=False))
        assert second["stats"]["crews_skipped_already_cleaned"] >= 1
        # With --force the breadcrumb skip is bypassed but the
        # scan finds nothing to remove.
        third = _run(run(tenant_id=tenant_a, apply=True, force=True))
        assert third["stats"]["crews_skipped_already_cleaned"] == 0
    finally:
        _cleanup([tenant_a])
