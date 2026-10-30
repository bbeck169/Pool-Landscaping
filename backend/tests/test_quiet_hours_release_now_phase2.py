"""Feb-2026 · Quiet Hours Phase-2 UX — manual flush endpoint.

Covers ``POST /api/quiet-hours/queue/release-now`` with the 5
pytest cases locked in the operator dispatch for Commit B.
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

import pytest

from tests._phase34_http_shim import http
from tests._phase34_asyncio import batch_safe_run as _run


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = http.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


@pytest.fixture(scope="module")
def aq_tenant_id(db) -> str:
    async def _go():
        t = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        return t["id"]
    return _run(_go())


@pytest.fixture(scope="module")
def foreign_tenant_id(db, aq_tenant_id) -> Optional[str]:
    async def _go():
        other = await db.tenants.find_one(
            {"id": {"$ne": aq_tenant_id}}, {"_id": 0, "id": 1},
        )
        return other["id"] if other else None
    return _run(_go())


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_h() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── seed helpers ────────────────────────────────────────────────
def _plant_sms_row(db, *, tenant_id: str) -> str:
    rid = f"qh-rn-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.outbound_deferred.insert_one({
            "id": rid, "tenant_id": tenant_id,
            "channel": "sms",
            "payload": {"to_phone": "+15555550123", "body": "ping"},
            "scheduled_for": "2027-01-01T00:00:00+00:00",
            "created_at": "2026-02-15T08:00:00+00:00",
            "created_by": None, "released_at": None,
            "status": "pending",
        })
    _run(_go())
    return rid


def _plant_bogus_channel_row(db, *, tenant_id: str) -> str:
    """Row with an unknown channel — forces ``_dispatch_row`` down
    its early failure branch so the ``errors[]`` array populates."""
    rid = f"qh-rn-bogus-{uuid.uuid4().hex[:10]}"

    async def _go():
        await db.outbound_deferred.insert_one({
            "id": rid, "tenant_id": tenant_id,
            "channel": "carrier-pigeon",
            "payload": {"to": "nowhere"},
            "scheduled_for": "2027-01-01T00:00:00+00:00",
            "created_at": "2026-02-15T08:00:00+00:00",
            "created_by": None, "released_at": None,
            "status": "pending",
        })
    _run(_go())
    return rid


def _cleanup(db, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await db.outbound_deferred.delete_many({"id": {"$in": ids}})
    _run(_go())


def _hide_all_pending(db, tenant_id: str) -> None:
    async def _go():
        await db.outbound_deferred.update_many(
            {"tenant_id": tenant_id, "status": "pending"},
            {"$set": {"status": "__rn_hidden__"}},
        )
    _run(_go())


def _restore_hidden(db, tenant_id: str) -> None:
    async def _go():
        await db.outbound_deferred.update_many(
            {"tenant_id": tenant_id, "status": "__rn_hidden__"},
            {"$set": {"status": "pending"}},
        )
    _run(_go())


# ─── tests ───────────────────────────────────────────────────────
def test_release_now_01_admin_flushes_pending(db, admin_h, aq_tenant_id):
    """1. Admin POST → every pending aquaterra row released."""
    _hide_all_pending(db, aq_tenant_id)
    rid_a = _plant_sms_row(db, tenant_id=aq_tenant_id)
    rid_b = _plant_sms_row(db, tenant_id=aq_tenant_id)
    try:
        r = http.post(
            f"{API}/quiet-hours/queue/release-now",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) >= {"released_count", "errors"}
        assert body["released_count"] >= 2
        assert isinstance(body["errors"], list)

        async def _check():
            rows = await db.outbound_deferred.find(
                {"id": {"$in": [rid_a, rid_b]}},
                {"_id": 0, "id": 1, "status": 1,
                 "released_at": 1},
            ).to_list(length=10)
            return rows
        rows = _run(_check())
        for row in rows:
            assert row["status"] == "sent"
            assert row.get("released_at") is not None
    finally:
        _cleanup(db, [rid_a, rid_b])
        _restore_hidden(db, aq_tenant_id)


def test_release_now_02_non_admin_403(customer_h):
    """2. Non-admin POST → 403."""
    r = http.post(
        f"{API}/quiet-hours/queue/release-now",
        headers=customer_h, timeout=30,
    )
    assert r.status_code == 403, r.text


def test_release_now_03_cross_tenant_isolation(db, admin_h,
                                               aq_tenant_id,
                                               foreign_tenant_id):
    """3. Cross-tenant isolation — other tenant's rows untouched."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available")
    _hide_all_pending(db, aq_tenant_id)
    aq_rid = _plant_sms_row(db, tenant_id=aq_tenant_id)
    foreign_rid = _plant_sms_row(db, tenant_id=foreign_tenant_id)
    try:
        r = http.post(
            f"{API}/quiet-hours/queue/release-now",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200
        # Aquaterra row released.

        async def _aq():
            return await db.outbound_deferred.find_one(
                {"id": aq_rid}, {"_id": 0, "status": 1},
            )
        aq = _run(_aq())
        assert aq.get("status") == "sent"
        # Foreign row still pending.

        async def _f():
            return await db.outbound_deferred.find_one(
                {"id": foreign_rid}, {"_id": 0, "status": 1},
            )
        f = _run(_f())
        assert f.get("status") == "pending"
    finally:
        _cleanup(db, [aq_rid, foreign_rid])
        _restore_hidden(db, aq_tenant_id)


def test_release_now_04_empty_queue(db, admin_h, aq_tenant_id):
    """4. Empty queue → released_count=0, errors=[]."""
    _hide_all_pending(db, aq_tenant_id)
    try:
        r = http.post(
            f"{API}/quiet-hours/queue/release-now",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200
        body = r.json()
        assert body == {"released_count": 0, "errors": []}
    finally:
        _restore_hidden(db, aq_tenant_id)


def test_release_now_05_partial_failure(db, admin_h, aq_tenant_id):
    """5. Mixed queue — valid SMS releases; bogus-channel row
    surfaces an entry in ``errors[]`` and transitions to ``failed``."""
    _hide_all_pending(db, aq_tenant_id)
    good_rid = _plant_sms_row(db, tenant_id=aq_tenant_id)
    bogus_rid = _plant_bogus_channel_row(db, tenant_id=aq_tenant_id)
    try:
        r = http.post(
            f"{API}/quiet-hours/queue/release-now",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["released_count"] >= 1
        err_rids = {e.get("row_id") for e in body["errors"]}
        assert bogus_rid in err_rids
        assert good_rid not in err_rids

        async def _check():
            rows = await db.outbound_deferred.find(
                {"id": {"$in": [good_rid, bogus_rid]}},
                {"_id": 0, "id": 1, "status": 1},
            ).to_list(length=10)
            return {r["id"]: r["status"] for r in rows}
        statuses = _run(_check())
        assert statuses[good_rid] == "sent"
        assert statuses[bogus_rid] == "failed"
    finally:
        _cleanup(db, [good_rid, bogus_rid])
        _restore_hidden(db, aq_tenant_id)
