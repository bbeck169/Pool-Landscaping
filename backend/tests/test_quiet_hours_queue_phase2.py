"""Feb-2026 · Quiet Hours Phase-2 UX — queue viewer + per-row cancel.

Covers ``GET /api/quiet-hours/queue`` + ``DELETE /api/quiet-hours/
queue/{row_id}`` with the 8 pytest cases locked in the operator
dispatch for Commit A.
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
def _plant_row(
    db, *, tenant_id: str, channel: str,
    scheduled_for: str,
    recipient: str = "test@example.com",
    subject: Optional[str] = None,
    status: str = "pending",
) -> str:
    rid = f"qh-{uuid.uuid4().hex[:12]}"
    if channel == "email":
        payload = {
            "from": "no-reply@example.com",
            "to": [recipient],
            "subject": subject or "Test Subject",
            "html": "<p>Hello</p>",
        }
    else:
        payload = {"to_phone": recipient, "body": "ping"}

    async def _go():
        await db.outbound_deferred.insert_one({
            "id": rid,
            "tenant_id": tenant_id,
            "channel": channel,
            "payload": payload,
            "scheduled_for": scheduled_for,
            "created_at": "2026-02-15T08:00:00+00:00",
            "created_by": None,
            "released_at": None,
            "status": status,
        })
    _run(_go())
    return rid


def _cleanup(db, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await db.outbound_deferred.delete_many({"id": {"$in": ids}})
    _run(_go())


# ─── tests ───────────────────────────────────────────────────────
def test_queue_01_admin_get_well_shaped(db, admin_h, aq_tenant_id):
    """1. Admin GET → 200 + well-shaped response."""
    rid = _plant_row(
        db, tenant_id=aq_tenant_id, channel="email",
        scheduled_for="2026-03-01T15:00:00+00:00",
        recipient="t1@example.com", subject="Hi one",
    )
    try:
        r = http.get(f"{API}/quiet-hours/queue",
                     headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) >= {"count", "next_release_at", "items"}
        assert body["count"] >= 1
        assert body["next_release_at"] is not None
        row = next((x for x in body["items"] if x["id"] == rid), None)
        assert row is not None
        assert set(row.keys()) >= {
            "id", "channel", "recipient",
            "scheduled_release_at", "deferred_at", "subject",
        }
        assert row["channel"] == "email"
        assert row["recipient"] == "t1@example.com"
        assert row["subject"] == "Hi one"
    finally:
        _cleanup(db, [rid])


def test_queue_02_non_admin_get_403(customer_h):
    """2. Non-admin GET → 403."""
    r = http.get(f"{API}/quiet-hours/queue",
                 headers=customer_h, timeout=30)
    assert r.status_code == 403, r.text


def test_queue_03_cross_tenant_get(db, admin_h, aq_tenant_id,
                                   foreign_tenant_id):
    """3. Cross-tenant GET → own-tenant rows only."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available")
    a_rid = _plant_row(
        db, tenant_id=aq_tenant_id, channel="email",
        scheduled_for="2026-03-02T15:00:00+00:00",
        recipient="aq@example.com",
    )
    b_rid = _plant_row(
        db, tenant_id=foreign_tenant_id, channel="email",
        scheduled_for="2026-03-02T15:00:00+00:00",
        recipient="foreign@example.com",
    )
    try:
        r = http.get(f"{API}/quiet-hours/queue",
                     headers=admin_h, timeout=30)
        assert r.status_code == 200
        ids = {x["id"] for x in r.json()["items"]}
        assert a_rid in ids
        assert b_rid not in ids
    finally:
        _cleanup(db, [a_rid, b_rid])


def test_queue_04_admin_delete_200(db, admin_h, aq_tenant_id):
    """4. Admin DELETE existing row → row gone + 200."""
    rid = _plant_row(
        db, tenant_id=aq_tenant_id, channel="sms",
        scheduled_for="2026-03-03T15:00:00+00:00",
        recipient="+15551234567",
    )
    try:
        r = http.delete(
            f"{API}/quiet-hours/queue/{rid}",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"deleted": True, "row_id": rid}

        async def _go():
            return await db.outbound_deferred.find_one({"id": rid})
        remaining = _run(_go())
        assert remaining is None
    finally:
        _cleanup(db, [rid])


def test_queue_05_delete_not_found_404(admin_h):
    """5. Admin DELETE non-existent row → 404."""
    r = http.delete(
        f"{API}/quiet-hours/queue/qh-does-not-exist-xyz",
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 404, r.text


def test_queue_06_cross_tenant_delete_404(db, admin_h,
                                          foreign_tenant_id):
    """6. Cross-tenant DELETE → 404, foreign row untouched."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available")
    foreign_rid = _plant_row(
        db, tenant_id=foreign_tenant_id, channel="email",
        scheduled_for="2026-03-04T15:00:00+00:00",
        recipient="foreign2@example.com",
    )
    try:
        r = http.delete(
            f"{API}/quiet-hours/queue/{foreign_rid}",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 404, r.text

        async def _go():
            return await db.outbound_deferred.find_one(
                {"id": foreign_rid},
            )
        still_there = _run(_go())
        assert still_there is not None
        assert still_there.get("status") == "pending"
    finally:
        _cleanup(db, [foreign_rid])


def test_queue_07_empty_state(db, admin_h, aq_tenant_id):
    """7. Empty queue → count=0, next_release_at=null, items=[]."""
    # Snapshot + wipe any live aquaterra pending rows for a clean
    # read, then restore them.

    async def _snapshot():
        rows = await db.outbound_deferred.find(
            {"tenant_id": aq_tenant_id, "status": "pending"},
            {"_id": 0},
        ).to_list(length=10000)
        return rows

    snapshot = _run(_snapshot())

    async def _wipe():
        await db.outbound_deferred.update_many(
            {"tenant_id": aq_tenant_id, "status": "pending"},
            {"$set": {"status": "__p2_test_hidden__"}},
        )
    _run(_wipe())

    try:
        r = http.get(f"{API}/quiet-hours/queue",
                     headers=admin_h, timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0
        assert body["next_release_at"] is None
        assert body["items"] == []
    finally:
        async def _restore():
            await db.outbound_deferred.update_many(
                {"tenant_id": aq_tenant_id,
                 "status": "__p2_test_hidden__"},
                {"$set": {"status": "pending"}},
            )
        _run(_restore())
        # Belt-and-braces: if any snapshot row somehow drifted, no-op.
        assert isinstance(snapshot, list)


def test_queue_08_channel_filter(db, admin_h, aq_tenant_id):
    """8. channel=email filter → only email rows returned."""
    e_rid = _plant_row(
        db, tenant_id=aq_tenant_id, channel="email",
        scheduled_for="2026-03-05T15:00:00+00:00",
        recipient="e@example.com",
    )
    s_rid = _plant_row(
        db, tenant_id=aq_tenant_id, channel="sms",
        scheduled_for="2026-03-05T15:00:00+00:00",
        recipient="+15559876543",
    )
    try:
        r = http.get(
            f"{API}/quiet-hours/queue?channel=email",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200
        ids = {x["id"] for x in r.json()["items"]}
        assert e_rid in ids
        assert s_rid not in ids
        # Invalid channel → 400.
        r2 = http.get(
            f"{API}/quiet-hours/queue?channel=carrier-pigeon",
            headers=admin_h, timeout=30,
        )
        assert r2.status_code == 400
    finally:
        _cleanup(db, [e_rid, s_rid])
