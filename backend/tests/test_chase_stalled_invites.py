"""Feb-2026 · Chase Stalled Invites — backend contract tests.

Locks the four behaviors the feature depends on:

  1. ``GET /api/customers?first_access=never&sort=stalest_first``
     returns customers ordered by ``temp_password_issued_at`` ASC
     with nulls LAST (docs without an invite stamp fall back to
     ``created_at``; docs with neither land at the end).
  2. ``POST /admin/customers/portal-invite/bulk`` response envelope
     includes the new ``{enqueued, rate_limited, failed}`` shape
     alongside the legacy counters.
  3. RBAC — the bulk endpoint 403s for a non-admin caller.
  4. Rate-limit — when the sliding-window budget is exhausted
     MID-batch (later invites in the same call are throttled), the
     throttled customer_ids appear in ``rate_limited`` but NOT in
     ``enqueued``.

Uses live HTTP against the running FastAPI instance — same pattern
as ``test_tenant_hq_geocode.py``. Seeds/cleans data via Motor so
tests are hermetic per-run.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


def _run(coro):
    """Run a Motor-bound coroutine on a fresh loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]], client


async def _tid(db):
    t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    return t["id"]


async def _seed_never_logged_in(db, tid, cid, *, invited_at=None,
                                 created_at=None, email=None,
                                 has_login=False):
    doc = {
        "id": cid, "tenant_id": tid, "name": cid,
        "email": email or f"{cid}@example.com",
        "is_active": True, "has_login": has_login,
    }
    if invited_at is not None:
        doc["temp_password_issued_at"] = invited_at
    if created_at is not None:
        doc["created_at"] = created_at
    await db.customers.insert_one(doc)


async def _cleanup(db, tid, prefix):
    await db.customers.delete_many({"tenant_id": tid,
                                        "id": {"$regex": f"^{prefix}"}})
    await db.portal_invite_rate_limit.delete_many({
        "tenant_id": tid,
        "customer_id": {"$regex": f"^{prefix}"},
    })
    await db.users.delete_many({"tenant_id": tid, "role": "customer",
                                    "email": {"$regex": f"^{prefix}"}})


# ═════════════════════════════════════════════════════════════════
# 1 · Sorted list — stalest first, nulls last.
# ═════════════════════════════════════════════════════════════════

def test_stalest_first_orders_by_invite_stamp_nulls_last(admin_headers):
    prefix = "CHASE_SORT_" + uuid.uuid4().hex[:6] + "_"

    async def _seed():
        db, client = await _db()
        try:
            tid = await _tid(db)
            await _cleanup(db, tid, prefix)
            oldest =  f"{prefix}oldest"
            older =   f"{prefix}older"
            newer =   f"{prefix}newer"
            newest =  f"{prefix}newest"
            created_only = f"{prefix}created_only"
            neither = f"{prefix}neither"
            await _seed_never_logged_in(
                db, tid, oldest, invited_at="2025-01-01T00:00:00+00:00")
            await _seed_never_logged_in(
                db, tid, older,  invited_at="2025-06-15T00:00:00+00:00")
            await _seed_never_logged_in(
                db, tid, newer,  invited_at="2025-12-01T00:00:00+00:00")
            await _seed_never_logged_in(
                db, tid, newest, invited_at="2026-01-15T00:00:00+00:00")
            await _seed_never_logged_in(
                db, tid, created_only, created_at="2026-02-01T00:00:00+00:00")
            await _seed_never_logged_in(db, tid, neither)
            return tid, [oldest, older, newer, newest, created_only, neither]
        finally:
            client.close()

    tid, seeded = _run(_seed())

    try:
        # Grab a large enough page to catch every seeded row (there
        # may be legit never-logged-in customers ahead of ours; we
        # filter by prefix below).
        r = requests.get(
            f"{API}/customers",
            params={"first_access": "never", "sort": "stalest_first",
                    "limit": 500},
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        docs = r.json()
        assert isinstance(docs, list)
        # Filter by our seed prefix for determinism.
        our = [d for d in docs if str(d.get("id", "")).startswith(prefix)]
        ids = [d["id"] for d in our]
        assert set(ids) == set(seeded), \
            f"expected all seeded ids in result: missing={set(seeded) - set(ids)}"
        oldest, older, newer, newest, created_only, neither = seeded
        assert ids.index(oldest) < ids.index(older) < ids.index(newer) < ids.index(newest), \
            f"invite-dated rows out of order: {ids}"
        # created_only (2026-02-01 created_at) is LATER (less stale)
        # than newest's 2026-01-15 invited_at → sorts AFTER newest.
        assert ids.index(newest) < ids.index(created_only), ids
        # ``neither`` has no stamp → sorts LAST among our seeded set.
        assert ids[-1] == neither, f"expected {neither} last, got {ids}"
    finally:
        async def _teardown():
            db, client = await _db()
            try:
                await _cleanup(db, tid, prefix)
            finally:
                client.close()
        _run(_teardown())


# ═════════════════════════════════════════════════════════════════
# 2 · Bulk endpoint response includes the new spec-shape keys.
# ═════════════════════════════════════════════════════════════════

def test_bulk_response_includes_enqueued_rate_limited_failed_shape(admin_headers):
    prefix = "CHASE_SHAPE_" + uuid.uuid4().hex[:6] + "_"

    async def _seed():
        db, client = await _db()
        try:
            tid = await _tid(db)
            await _cleanup(db, tid, prefix)
            cid_ok = f"{prefix}ok"
            cid_nc = f"{prefix}nc"
            await _seed_never_logged_in(db, tid, cid_ok,
                                          email=f"{prefix}ok@e.com")
            await db.customers.insert_one({
                "id": cid_nc, "tenant_id": tid, "name": cid_nc,
                "is_active": True, "has_login": False,
            })
            return tid, cid_ok, cid_nc
        finally:
            client.close()

    tid, cid_ok, cid_nc = _run(_seed())

    try:
        r = requests.post(
            f"{API}/admin/customers/portal-invite/bulk",
            headers={**admin_headers, "Content-Type": "application/json"},
            json={"customer_ids": [cid_ok, cid_nc],
                  "reason": f"{prefix}shape_probe"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        res = r.json()
        # Feb-2026 spec-shape keys.
        assert "enqueued" in res
        assert "rate_limited" in res
        assert "failed" in res
        assert res["enqueued"] == res["sent"] == 1
        assert isinstance(res["rate_limited"], list)
        assert res["rate_limited"] == []
        assert isinstance(res["failed"], list)
        assert len(res["failed"]) == 1
        entry = res["failed"][0]
        assert entry["id"] == cid_nc
        assert entry["reason"] == "no_email_or_phone"
        # Legacy fields still present.
        assert res["batch_id"]
        assert isinstance(res["failures"], list)
    finally:
        async def _teardown():
            db, client = await _db()
            try:
                await _cleanup(db, tid, prefix)
            finally:
                client.close()
        _run(_teardown())


# ═════════════════════════════════════════════════════════════════
# 3 · RBAC — technician role forbidden on the bulk endpoint.
# ═════════════════════════════════════════════════════════════════

def test_rbac_technician_forbidden_on_bulk(tech_headers):
    r = requests.post(
        f"{API}/admin/customers/portal-invite/bulk",
        headers={**tech_headers, "Content-Type": "application/json"},
        json={"customer_ids": ["irrelevant"]},
        timeout=30,
    )
    assert r.status_code == 403, r.text


def test_rbac_no_token_rejects_bulk():
    r = requests.post(
        f"{API}/admin/customers/portal-invite/bulk",
        json={"customer_ids": ["irrelevant"]},
        timeout=30,
    )
    # ``get_current_user`` returns 401 for missing token.
    assert r.status_code in (401, 403), r.text


# ═════════════════════════════════════════════════════════════════
# 4 · Rate-limit — mid-batch throttle surfaces ids in rate_limited.
# ═════════════════════════════════════════════════════════════════

def test_rate_limit_mid_batch_surfaces_ids_in_rate_limited(admin_headers):
    """Pre-populate ``db.portal_invite_rate_limit`` to consume
    ``_H1_RATE_MAX_PER_WINDOW - 1`` of the window budget, then post
    a batch of 3 customers. The first lands, the next two hit the
    mid-batch throttle → their ids appear in ``rate_limited``
    (never in ``enqueued`` / ``failed``)."""
    from routers.portal_admin import _H1_RATE_MAX_PER_WINDOW

    prefix = "CHASE_RL_" + uuid.uuid4().hex[:6] + "_"

    async def _seed():
        db, client = await _db()
        try:
            tid = await _tid(db)
            await _cleanup(db, tid, prefix)
            already = _H1_RATE_MAX_PER_WINDOW - 1
            now = datetime.now(timezone.utc).isoformat()
            if already > 0:
                await db.portal_invite_rate_limit.insert_many([
                    {"id": str(uuid.uuid4()), "tenant_id": tid,
                     "customer_id": f"{prefix}pre_{i}",
                     "batch_id": f"{prefix}pre",
                     "actor_id": "presetup", "sent_at": now}
                    for i in range(already)
                ])
            cids = [f"{prefix}A", f"{prefix}B", f"{prefix}C"]
            for cid in cids:
                await _seed_never_logged_in(db, tid, cid,
                                              email=f"{cid}@e.com")
            return tid, cids
        finally:
            client.close()

    tid, cids = _run(_seed())

    try:
        r = requests.post(
            f"{API}/admin/customers/portal-invite/bulk",
            headers={**admin_headers, "Content-Type": "application/json"},
            json={"customer_ids": cids,
                  "reason": f"{prefix}rl_probe"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["enqueued"] == 1, res
        # The two throttled ids are in rate_limited (order-agnostic set).
        assert set(res["rate_limited"]) == {cids[1], cids[2]}, res
        failed_ids = {f["id"] for f in res["failed"]}
        assert not (failed_ids & set(res["rate_limited"])), \
            f"partition leak: overlap={failed_ids & set(res['rate_limited'])}"
    finally:
        async def _teardown():
            db, client = await _db()
            try:
                await db.portal_invite_rate_limit.delete_many({
                    "tenant_id": tid, "batch_id": f"{prefix}pre",
                })
                await _cleanup(db, tid, prefix)
            finally:
                client.close()
        _run(_teardown())
