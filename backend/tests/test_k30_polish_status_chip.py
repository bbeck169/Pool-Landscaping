"""K30.status-chip · Feb-2026 — ``GET /api/customers/{cid}/portal-reset-link-status``.

Read-only endpoint powering the front-office "Reset link" chip on
the Portal Access panel. Covers all four status branches:

* ``none``    — customer has no portal user OR no token has ever
                 been minted.
* ``issued``  — token exists, not used, not expired.
* ``used``    — customer completed the reset (``used_at`` set).
* ``expired`` — token exists, unused, past TTL (or invalidated).

Also verifies the token value itself is NEVER echoed back, and
that non-admin roles are rejected.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def customer(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"K30chip {marker}",
        "first_name": "K30_CHIP", "last_name": f"L{marker}",
        "email": f"k30chip_{marker}@example.com",
        "phone": "+14805557788",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    yield doc
    requests.delete(f"{API}/customers/{doc['id']}",
                      headers=admin_headers, timeout=15)


def test_status_none_when_no_user_or_token(admin_headers, customer):
    r = requests.get(f"{API}/customers/{customer['id']}/portal-reset-link-status",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "none"
    assert body["issued_at"] in (None, "")
    assert body["used_at"] in (None, "")


def test_status_issued_after_reset_link(admin_headers, customer):
    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset-link",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/customers/{customer['id']}/portal-reset-link-status",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "issued"
    assert body["issued_at"]
    assert body["expires_at"]
    assert body["used_at"] in (None, "")
    assert body["source"] == "admin_reset_link"
    # Token value NEVER echoed back.
    assert "token" not in body
    assert not any(
        isinstance(v, str) and len(v) >= 48 and v.replace("-", "").replace("_", "").isalnum()
        for v in body.values()
    )


def test_status_used_after_completion(admin_headers, customer):
    """After the customer completes the reset, the chip flips to
    ``used`` — driven by ``password_reset_tokens.used_at`` being
    non-null."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset-link",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text

    async def _mark_used():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        cust_user = await db.users.find_one({
            "customer_id": customer["id"], "role": "customer",
        })
        assert cust_user is not None
        row = await db.password_reset_tokens.find_one(
            {"user_id": cust_user["id"]},
            sort=[("created_at", -1)],
        )
        assert row is not None
        await db.password_reset_tokens.update_one(
            {"id": row["id"]},
            {"$set": {"used_at": datetime.now(timezone.utc).isoformat(),
                      "used_ip": "127.0.0.1"}},
        )

    asyncio.run(_mark_used())

    r = requests.get(f"{API}/customers/{customer['id']}/portal-reset-link-status",
                       headers=admin_headers, timeout=15)
    body = r.json()
    assert body["status"] == "used"
    assert body["used_at"]


def test_status_expired_when_past_ttl(admin_headers, customer):
    """A token whose ``expires_at`` is in the past resolves as
    ``expired`` (unused branch)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset-link",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text

    async def _backdate():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        cust_user = await db.users.find_one({
            "customer_id": customer["id"], "role": "customer",
        })
        row = await db.password_reset_tokens.find_one(
            {"user_id": cust_user["id"]},
            sort=[("created_at", -1)],
        )
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await db.password_reset_tokens.update_one(
            {"id": row["id"]}, {"$set": {"expires_at": past}},
        )

    asyncio.run(_backdate())

    r = requests.get(f"{API}/customers/{customer['id']}/portal-reset-link-status",
                       headers=admin_headers, timeout=15)
    body = r.json()
    assert body["status"] == "expired"
    assert body["issued_at"]
    assert body["used_at"] in (None, "")


def test_status_404_unknown_customer(admin_headers):
    r = requests.get(f"{API}/customers/{uuid.uuid4().hex}/portal-reset-link-status",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404


def test_status_tech_forbidden(admin_headers, customer):
    tech_tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/customers/{customer['id']}/portal-reset-link-status",
                       headers={"Authorization": f"Bearer {tech_tok}"},
                       timeout=15)
    assert r.status_code in (401, 403)


def test_portal_history_includes_admin_reset_event(admin_headers, customer):
    """K30.polish — the ``admin_password_reset_triggered`` event now
    surfaces in the Portal Access activity feed (previously only 5
    events were surfaced)."""
    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset-link",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/customers/{customer['id']}/portal-history",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    events = {e["event"] for e in r.json()["events"]}
    assert "admin_password_reset_triggered" in events
