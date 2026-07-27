"""Reflow History · Feb 2026 — aggregation + pagination + tenant scoping."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def tid(db):
    async def _go():
        t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        return t["id"]
    return _run(_go())


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture(scope="module")
def seeded_audit(db, tid):
    """Plant a known set of audit rows across two actors + two calls
    so aggregation, cursor, and cross-tenant filtering can be tested."""
    async def _go():
        # Idempotent — purge prior seeds so the module can be re-run
        # against a shared DB without count drift.
        await db.audit_log.delete_many({"id": {"$regex": "^seed-"}})
        base = datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)
        # Call A — actor-1 shifted 3 jobs by +3d.
        for i in range(3):
            await db.audit_log.insert_one({
                "id": f"seed-a-{i}", "tenant_id": tid,
                "actor_user_id": "actor-1", "actor_email": "a1@t.local",
                "action": "job.bulk_update", "target_id": f"job-{i}",
                "at": _iso(base), "shift_days": 3,
                "anchored": (i == 0),
            })
        # Call B — actor-2 shifted 2 jobs by -7d one hour later.
        for i in range(2):
            await db.audit_log.insert_one({
                "id": f"seed-b-{i}", "tenant_id": tid,
                "actor_user_id": "actor-2", "actor_email": "a2@t.local",
                "action": "job.bulk_update", "target_id": f"jobB-{i}",
                "at": _iso(base + timedelta(hours=1)),
                "shift_days": -7, "anchored": False,
            })
        # Cross-tenant noise — must NOT surface.
        await db.audit_log.insert_one({
            "id": "seed-x-1", "tenant_id": "OTHER_TENANT_XYZ",
            "actor_user_id": "actor-9",
            "action": "job.bulk_update", "target_id": "job-x",
            "at": _iso(base), "shift_days": 3,
        })
        return {"base": base}
    return _run(_go())


def test_reflow_history_forbids_customer(customer_headers, seeded_audit):
    r = requests.get(f"{API}/admin/reflow-history", headers=customer_headers, timeout=30)
    assert r.status_code in (401, 403)


def test_reflow_history_aggregates_and_scopes(
        super_headers, seeded_audit):
    r = requests.get(f"{API}/admin/reflow-history",
                          headers=super_headers,
                          params={"since": "2026-02-20T00:00:00Z",
                                    "until": "2026-02-20T23:59:59Z"},
                          timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    # 2 grouped actions (Call A + Call B), no cross-tenant noise.
    assert len(items) >= 2
    call_a = next((it for it in items if it["shift_days"] == 3
                        and it["actor_user_id"] == "actor-1"), None)
    call_b = next((it for it in items if it["shift_days"] == -7
                        and it["actor_user_id"] == "actor-2"), None)
    assert call_a is not None
    assert call_b is not None
    assert call_a["count"] == 3
    assert call_a["anchored_count"] == 1
    assert call_b["count"] == 2
    assert call_b["anchored_count"] == 0
    # Cross-tenant noise excluded.
    assert not any(it["actor_user_id"] == "actor-9" for it in items)


def test_reflow_history_cursor_paginates(super_headers, seeded_audit):
    # limit=1 so we always get a cursor when >1 row exists.
    r = requests.get(f"{API}/admin/reflow-history",
                          headers=super_headers,
                          params={"since": "2026-02-20T00:00:00Z",
                                    "until": "2026-02-20T23:59:59Z",
                                    "limit": 1},
                          timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["cursor"] is not None
    r2 = requests.get(f"{API}/admin/reflow-history",
                            headers=super_headers,
                            params={"since": "2026-02-20T00:00:00Z",
                                      "until": "2026-02-20T23:59:59Z",
                                      "cursor": body["cursor"],
                                      "limit": 5},
                            timeout=30)
    body2 = r2.json()
    # First page's cursor is the newest item's ``at`` — page 2 should
    # start strictly earlier and therefore not repeat the first row.
    assert body2["items"], "page 2 should have at least one row"
    assert body["items"][0]["at"] != body2["items"][0]["at"]


def test_reflow_history_rejects_bad_since(super_headers):
    r = requests.get(f"{API}/admin/reflow-history",
                          headers=super_headers,
                          params={"since": "not-a-date"}, timeout=30)
    assert r.status_code == 422


def test_reflow_history_filters_by_actor(super_headers, seeded_audit):
    r = requests.get(f"{API}/admin/reflow-history",
                          headers=super_headers,
                          params={"since": "2026-02-20T00:00:00Z",
                                    "until": "2026-02-20T23:59:59Z",
                                    "actor_user_id": "actor-2"},
                          timeout=30)
    body = r.json()
    assert all(it["actor_user_id"] == "actor-2" for it in body["items"])
