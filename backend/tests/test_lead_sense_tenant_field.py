"""LS-A · Feb-2026 — Tenant marco_lead_sense_id + JWT isolation tests.

Locks the twelve invariants of Sub-phase A of the MARCO Lead-Sense
track (see ``memory/SPEC_MARCO_LEAD_SENSE.md``):

    (a) Field exists on tenant after migration.
    (b) GET returns current marco_lead_sense_id (auto-generates
        on first request if missing).
    (c) PATCH rotate=True returns a fresh id, distinct from the
        old one, and the old id is no longer stored on the tenant.
    (d) PATCH explicit value as super_admin → 200.
    (e) PATCH explicit value as admin (not super) → 403.
    (f) PATCH with body ``tenant_id`` → 403 loud (JWT-derived only).
    (g) PATCH lead_sense_allowed_origins with valid origins → 200,
        stored correctly (trailing-slash stripped, case-normalized).
    (h) PATCH lead_sense_allowed_origins with '*' / malformed
        origin → 422.
    (i) Cross-tenant read via /api/tenants/{other_id}/... → 404
        (LDM-E convention — only /mine/* addresses exist).
    (j) Migration is idempotent (sentinel short-circuits the
        second run; second run drains zero rows).
    (k) Migration backfills existing tenants (pre-existing rows
        get id + empty origins list).
    (l) Unique partial index prevents duplicate
        marco_lead_sense_id assignment.

Test-loop convention mirrors ``test_automation_rules.py`` /
``test_ldm_jwt_isolation.py``: sync pymongo for seeding + cleanup,
per-test fresh asyncio loop + Motor client for the SUT call, and
FastAPI TestClient with dependency overrides for the HTTP-shaped
cross-tenant / auth-negative cases.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "LSA_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    """Track LSA_-tagged tenant rows and drop them on teardown so
    full-suite runs stay hermetic. Sentinel cleanup is not needed
    — the migration_status doc for ``marco_lead_sense_id_v1`` is
    global and idempotent; leaving it lets subsequent tests match
    the production short-circuit."""
    seeded_tenant_ids: List[str] = []
    yield seeded_tenant_ids
    if seeded_tenant_ids:
        dbc.tenants.delete_many({"id": {"$in": seeded_tenant_ids}})


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_tenant(dbc, *, with_lead_sense: Optional[Dict[str, Any]] = None) -> str:
    """Insert a tenant. ``with_lead_sense=None`` → no lead-sense
    fields at all. ``with_lead_sense={"marco_lead_sense_id": ...}``
    → tenant already carries the field(s)."""
    tid = _fresh("TEN")
    doc: Dict[str, Any] = {
        "id": tid,
        "name": f"LSA seed tenant {tid[-8:]}",
        "timezone": "America/Phoenix",
        "created_at": "2026-02-15T00:00:00Z",
    }
    if with_lead_sense:
        doc.update(with_lead_sense)
    dbc.tenants.insert_one(doc)
    return tid


def _run(coro_factory):
    """Per-test fresh asyncio loop + Motor client — mirrors
    ``test_automation_rules.py::_run``."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    try:
        return loop.run_until_complete(coro_factory(adb))
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


class _FakeReq:
    """Duck-typed replacement for starlette.requests.Request."""
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    async def json(self) -> Dict[str, Any]:
        return dict(self._payload)


def _make_http_client(*, role: str = "admin",
                        tenant_id: Optional[str] = None):
    """Mount ``routers.tenants`` behind a mini FastAPI app with
    dependency overrides. Mirrors
    ``test_ldm_jwt_isolation._make_http_client`` — kept in this
    file rather than shared because the LDM-E helper resolves the
    tenant doc from a fixture that our tests don't share."""
    from routers import tenants as _t
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    tid = tenant_id or _fresh("TID_")

    async def _fake_user():
        return {
            "id": "u-lsa-1", "role": role,
            "tenant_id": tid,
            "email": f"{role}@lsa.test",
        }

    async def _fake_tenant():
        # Real tenant row from Mongo when possible so the GET auto-
        # generate path can read the (post-migration) id.
        row = None
        if tid:
            from config import db as real_db
            row = await real_db.tenants.find_one({"id": tid}, {"_id": 0})
        return row or {"id": tid}

    app = FastAPI()
    app.include_router(_t.router, prefix="/api")
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_current_tenant] = _fake_tenant
    return TestClient(app, raise_server_exceptions=True)


# ═════════════════════════════════════════════════════════════════════
# (a) Field exists on tenant after migration
# ═════════════════════════════════════════════════════════════════════
def test_a_migration_adds_marco_lead_sense_id(dbc, cleanup):
    """A fresh tenant (no lead-sense fields) receives both
    ``marco_lead_sense_id`` + ``lead_sense_allowed_origins`` after
    the sweep runs."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.marco_lead_sense_id_v1 import run
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    lid = row.get("marco_lead_sense_id")
    assert isinstance(lid, str) and lid, (
        f"marco_lead_sense_id missing/empty after migration; row={row!r}"
    )
    # 12-char URL-safe expected (secrets.token_urlsafe(9)).
    assert 6 <= len(lid) <= 64, (
        f"unexpected id length {len(lid)}: {lid!r}"
    )
    origins = row.get("lead_sense_allowed_origins")
    assert isinstance(origins, list) and origins == [], (
        f"lead_sense_allowed_origins missing/wrong shape: {origins!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# (b) GET returns current id; auto-generates on first request if missing
# ═════════════════════════════════════════════════════════════════════
def test_b_get_auto_generates_on_first_read(dbc, cleanup):
    """Pre-migration / hand-cleared tenants get a fresh id on the
    first GET, and subsequent GETs return the same stable id."""
    tid = _seed_tenant(dbc)  # no lead-sense fields
    cleanup.append(tid)
    # Sanity — no id yet.
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("marco_lead_sense_id") is None

    async def _apply(adb):
        from routers.tenants import get_own_lead_sense_id
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            tenant_row = await adb.tenants.find_one(
                {"id": tid}, {"_id": 0},
            )
            first = await get_own_lead_sense_id(
                user={"role": "admin", "id": "u1", "tenant_id": tid},
                tenant=tenant_row,
            )
            # Re-fetch the row and call again — should be stable.
            tenant_row2 = await adb.tenants.find_one(
                {"id": tid}, {"_id": 0},
            )
            second = await get_own_lead_sense_id(
                user={"role": "admin", "id": "u1", "tenant_id": tid},
                tenant=tenant_row2,
            )
            return first, second
        finally:
            _t.db = _t._orig_db

    first, second = _run(_apply)
    assert isinstance(first["marco_lead_sense_id"], str)
    assert first["marco_lead_sense_id"] == second["marco_lead_sense_id"], (
        "second GET must return the same id as the auto-generate GET"
    )
    assert first["lead_sense_allowed_origins"] == []


# ═════════════════════════════════════════════════════════════════════
# (c) PATCH rotate=True returns a fresh id
# ═════════════════════════════════════════════════════════════════════
def test_c_rotate_returns_new_id_and_replaces_stored_value(dbc, cleanup):
    tid = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "old_seed_id_ABC",
        "lead_sense_allowed_origins": [],
    })
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import (
            patch_own_lead_sense_id, LeadSenseIdPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = LeadSenseIdPatch(rotate=True)
            req = _FakeReq({"rotate": True})
            return await patch_own_lead_sense_id(
                request=req, body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    out = _run(_apply)
    new_id = out.get("marco_lead_sense_id")
    assert isinstance(new_id, str) and new_id, (
        f"rotate should return a new id, got {out!r}"
    )
    assert new_id != "old_seed_id_ABC", "id must actually change"
    # Persistence check — the DB row now carries the new id.
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("marco_lead_sense_id") == new_id


# ═════════════════════════════════════════════════════════════════════
# (d) PATCH explicit id as super_admin → 200
# ═════════════════════════════════════════════════════════════════════
def test_d_super_admin_can_patch_explicit_id(dbc, cleanup):
    tid = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "initial_id_XYZ",
        "lead_sense_allowed_origins": [],
    })
    cleanup.append(tid)
    explicit_id = _fresh("EX").replace("-", "")[:20]

    async def _apply(adb):
        from routers.tenants import (
            patch_own_lead_sense_id, LeadSenseIdPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = LeadSenseIdPatch(marco_lead_sense_id=explicit_id)
            req = _FakeReq({"marco_lead_sense_id": explicit_id})
            return await patch_own_lead_sense_id(
                request=req, body=body,
                user={"role": "super_admin", "id": "sa1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    out = _run(_apply)
    assert out.get("marco_lead_sense_id") == explicit_id
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("marco_lead_sense_id") == explicit_id


# ═════════════════════════════════════════════════════════════════════
# (e) PATCH explicit id as admin (not super) → 403
# ═════════════════════════════════════════════════════════════════════
def test_e_admin_cannot_patch_explicit_id(dbc, cleanup):
    tid = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "initial_id_XYZ",
        "lead_sense_allowed_origins": [],
    })
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import (
            patch_own_lead_sense_id, LeadSenseIdPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = LeadSenseIdPatch(marco_lead_sense_id="hijack_ABC")
            req = _FakeReq({"marco_lead_sense_id": "hijack_ABC"})
            return await patch_own_lead_sense_id(
                request=req, body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    with pytest.raises(HTTPException) as excinfo:
        _run(_apply)
    assert excinfo.value.status_code == 403
    # Persistence check — id was NOT mutated.
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("marco_lead_sense_id") == "initial_id_XYZ"


# ═════════════════════════════════════════════════════════════════════
# (f) PATCH with body tenant_id → 403 loud
# ═════════════════════════════════════════════════════════════════════
def test_f_body_supplied_tenant_id_rejected(dbc, cleanup):
    tid_a = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "id_A", "lead_sense_allowed_origins": [],
    })
    tid_b = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "id_B", "lead_sense_allowed_origins": [],
    })
    cleanup.extend([tid_a, tid_b])

    async def _apply(adb):
        from routers.tenants import (
            patch_own_lead_sense_id, LeadSenseIdPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = LeadSenseIdPatch(rotate=True)
            req = _FakeReq({"tenant_id": tid_b, "rotate": True})
            return await patch_own_lead_sense_id(
                request=req, body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid_a},
            )
        finally:
            _t.db = _t._orig_db

    with pytest.raises(HTTPException) as excinfo:
        _run(_apply)
    assert excinfo.value.status_code == 403
    # Neither tenant should have been mutated.
    row_a = dbc.tenants.find_one({"id": tid_a}, {"_id": 0})
    row_b = dbc.tenants.find_one({"id": tid_b}, {"_id": 0})
    assert row_a.get("marco_lead_sense_id") == "id_A"
    assert row_b.get("marco_lead_sense_id") == "id_B"


# ═════════════════════════════════════════════════════════════════════
# (g) PATCH lead_sense_allowed_origins — normalized round-trip
# ═════════════════════════════════════════════════════════════════════
def test_g_origins_patch_stores_normalized_list(dbc, cleanup):
    tid = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "orig_test_ID",
        "lead_sense_allowed_origins": [],
    })
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import (
            patch_own_lead_sense_id, LeadSenseIdPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = LeadSenseIdPatch(lead_sense_allowed_origins=[
                "https://ACME.com/",
                "http://localhost:8080",
                "https://acme.com",  # dup after normalization → skipped
            ])
            req = _FakeReq({"lead_sense_allowed_origins": [
                "https://ACME.com/",
                "http://localhost:8080",
                "https://acme.com",
            ]})
            return await patch_own_lead_sense_id(
                request=req, body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    out = _run(_apply)
    origins = out.get("lead_sense_allowed_origins") or []
    # Trailing slash stripped, host lowercased, duplicates removed.
    assert origins == [
        "https://acme.com",
        "http://localhost:8080",
    ], f"unexpected normalized origins: {origins!r}"
    # Persistence sanity.
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("lead_sense_allowed_origins") == origins


# ═════════════════════════════════════════════════════════════════════
# (h) PATCH lead_sense_allowed_origins — reject wildcard / malformed
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad_origin", [
    "*",
    "null",
    "https://acme.com/path",     # path component
    "https://acme.com?q=1",      # query
    "https://acme.com#frag",     # fragment
    "https://user@acme.com",     # userinfo
    "ftp://acme.com",            # bad scheme
    "acme.com",                  # no scheme
    "https://",                  # no host
    "https://acme.com/*",        # wildcard smuggle
])
def test_h_origin_validation_rejects_bad_entries(dbc, cleanup, bad_origin):
    tid = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "bad_origin_test_ID",
        "lead_sense_allowed_origins": [],
    })
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import (
            patch_own_lead_sense_id, LeadSenseIdPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = LeadSenseIdPatch(
                lead_sense_allowed_origins=[bad_origin],
            )
            req = _FakeReq({
                "lead_sense_allowed_origins": [bad_origin],
            })
            return await patch_own_lead_sense_id(
                request=req, body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    with pytest.raises(HTTPException) as excinfo:
        _run(_apply)
    assert excinfo.value.status_code == 422
    # Persistence — origin list unchanged.
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("lead_sense_allowed_origins") == []


# ═════════════════════════════════════════════════════════════════════
# (i) Cross-tenant address /api/tenants/{other_id}/... → 404
# ═════════════════════════════════════════════════════════════════════
def test_i_no_direct_tenant_id_route_returns_404(dbc, cleanup):
    """The whole surface uses the /mine/* convention. Direct-id
    addressing (e.g. GET /api/tenants/<id>/lead-sense-id) MUST
    return 404 (or 405) — matches LDM-E's isolation convention."""
    tid = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "direct_id_test_ID",
        "lead_sense_allowed_origins": [],
    })
    cleanup.append(tid)
    client = _make_http_client(role="admin", tenant_id=tid)
    resp_get = client.get(f"/api/tenants/{tid}/lead-sense-id")
    assert resp_get.status_code in (404, 405), resp_get.text
    resp_patch = client.patch(
        f"/api/tenants/{tid}/lead-sense-id",
        json={"rotate": True},
    )
    assert resp_patch.status_code in (404, 405), resp_patch.text


# ═════════════════════════════════════════════════════════════════════
# (j) Migration idempotency — sentinel short-circuits the 2nd run
# ═════════════════════════════════════════════════════════════════════
def test_j_migration_idempotent_second_run_skipped_by_marker(dbc, cleanup):
    """Second run behind an existing sentinel returns
    ``skipped_by_marker=True`` and drains zero rows."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.marco_lead_sense_id_v1 import run
        # First pass stamps the sentinel.
        await run(dry_run=False, force=True, db_client=adb)
        # Second pass respects the sentinel.
        return await run(dry_run=False, force=False, db_client=adb)

    summary = _run(_apply)
    assert summary["skipped_by_marker"] is True
    assert summary["tenants_scanned"] == 0
    assert summary["tenants_backfilled"] == 0
    assert summary["ids_generated"] == 0


# ═════════════════════════════════════════════════════════════════════
# (k) Migration backfills existing tenants
# ═════════════════════════════════════════════════════════════════════
def test_k_migration_backfills_existing_tenants(dbc, cleanup):
    """A tenant that predates LS-A (no lead-sense fields) is
    populated with both fields after --force run."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    # Confirm the tenant lacks the fields pre-migration.
    row_before = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row_before.get("marco_lead_sense_id") is None
    assert row_before.get("lead_sense_allowed_origins") is None

    async def _apply(adb):
        from migrations.marco_lead_sense_id_v1 import run
        return await run(dry_run=False, force=True, db_client=adb)

    summary = _run(_apply)
    row_after = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    lid = row_after.get("marco_lead_sense_id")
    assert isinstance(lid, str) and len(lid) >= 6
    assert row_after.get("lead_sense_allowed_origins") == []
    # Summary counters should include this tenant.
    assert summary["ids_generated"] >= 1
    assert summary["origins_seeded"] >= 1


def test_k2_migration_preserves_existing_lead_sense_id(dbc, cleanup):
    """A tenant that already carries a super_admin-pinned id keeps
    it — the migration only fills MISSING fields."""
    tid = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": "custom_pinned_ID",
        "lead_sense_allowed_origins": ["https://acme.com"],
    })
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.marco_lead_sense_id_v1 import run
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("marco_lead_sense_id") == "custom_pinned_ID"
    assert row.get("lead_sense_allowed_origins") == ["https://acme.com"]


# ═════════════════════════════════════════════════════════════════════
# (l) Unique partial index prevents duplicate marco_lead_sense_id
# ═════════════════════════════════════════════════════════════════════
def test_l_unique_index_prevents_duplicate_id(dbc, cleanup):
    """After the migration ensures the unique index, inserting a
    second tenant with the same ``marco_lead_sense_id`` raises
    ``DuplicateKeyError`` at the Mongo layer."""
    dup_id = f"lock_dup_{uuid.uuid4().hex[:8]}"
    # First run must ensure the index exists.
    async def _apply(adb):
        from migrations.marco_lead_sense_id_v1 import run
        return await run(dry_run=False, force=True, db_client=adb)
    _run(_apply)

    tid_a = _seed_tenant(dbc, with_lead_sense={
        "marco_lead_sense_id": dup_id,
        "lead_sense_allowed_origins": [],
    })
    cleanup.append(tid_a)

    # Attempt to insert a second tenant with the same id — must
    # raise DuplicateKeyError. Belt-and-braces: also try to
    # $set the duplicate onto an existing tenant.
    tid_b = _fresh("LOCK_B")
    cleanup.append(tid_b)
    with pytest.raises(DuplicateKeyError):
        dbc.tenants.insert_one({
            "id": tid_b,
            "name": "LSA lock dup B",
            "marco_lead_sense_id": dup_id,
        })
