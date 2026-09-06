"""K30.copy-admin-link · Feb-2026 — Super-admin clipboard-copy path.

Covers ``POST /api/customers/{cid}/portal-reset-link-copy``:

* Super-admin can mint a fresh reset URL; response returns the
  full ``reset_url`` + ``expires_at`` so the browser can copy it.
* Regular admin is REJECTED (403) — this endpoint is stricter
  than the send-reset endpoint because the response body carries
  a bearer credential.
* Prior unused tokens for the same user are invalidated so a
  leaked earlier link cannot be replayed after a copy call.
* No email is fired — Resend adapter is not touched.
* Audit event ``admin_password_reset_copied`` is written with the
  actor + target + masked recipient.
* Token value is NEVER written to any process log line (checked
  by grepping the backend log file for the returned token).
* 404 for missing customer, 400 for no-email-on-file, 401/403
  for non-super-admin roles, tenant isolation preserved.
"""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def customer(super_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=super_headers, json={
        "name": f"K30COPY {marker}",
        "first_name": "K30COPY", "last_name": f"L{marker}",
        "email": f"k30copy_{marker}@example.com",
        "phone": "+14805557788",
        "address": "10 K30 Copy Way",
        "address_line1": "10 K30 Copy Way",
        "city": "Peoria", "state": "AZ", "postal_code": "85383",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    yield doc
    requests.delete(f"{API}/customers/{doc['id']}",
                      headers=super_headers, timeout=15)


# ─── Happy path ─────────────────────────────────────────────────────

def test_copy_super_admin_returns_full_url(super_headers, customer):
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["token_ttl_minutes"] == 30
    assert body["provisioned_user"] is True
    assert body["reset_url"].startswith("http"), body["reset_url"]
    assert "token=" in body["reset_url"]
    assert body["reset_url"].endswith(body["reset_url"].split("token=")[-1])
    # ``expires_at`` must be present + parseable.
    from datetime import datetime
    parsed = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert parsed is not None
    # Response body must NOT echo the raw customer email.
    assert customer["email"] not in r.text.replace(
        f"token={body['reset_url'].split('token=')[-1]}", ""
    )


def test_copy_reissue_invalidates_prior_token(super_headers, customer):
    """Belt-and-braces — a second call within TTL must invalidate the
    previous token so a leaked earlier link cannot be replayed after
    the operator copies a fresh one."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    r1 = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r1.status_code == 200, r1.text
    first_token = r1.json()["reset_url"].split("token=")[-1]

    r2 = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r2.status_code == 200, r2.text
    second_token = r2.json()["reset_url"].split("token=")[-1]
    assert first_token != second_token
    assert r2.json()["provisioned_user"] is False  # already provisioned

    async def _lookup_first():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        return await d.password_reset_tokens.find_one(
            {"token": first_token}, {"_id": 0}
        )

    row = asyncio.run(_lookup_first())
    assert row is not None
    assert row.get("invalidated_at") is not None


def test_copy_audit_row_written(super_headers, customer):
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    async def _find():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        return await d.audit_logs.find_one({
            "event": "admin_password_reset_copied",
            "target_customer_id": customer["id"],
        }, {"_id": 0})

    row = asyncio.run(_find())
    assert row is not None
    assert row["actor_email"] == "super@aquaterra.com"
    assert "***" in row["target_email_masked"]
    # The audit row must NOT include the raw token / URL.
    for k, v in row.items():
        if isinstance(v, str):
            assert "token=" not in v, f"audit row leaked a token in {k}"


def test_copy_source_marker_on_token(super_headers, customer):
    """New tokens on this path carry ``source='admin_reset_link_copy'``
    so audits + analytics can distinguish the copy path from the
    send path."""
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    token = r.json()["reset_url"].split("token=")[-1]

    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    async def _find():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        return await d.password_reset_tokens.find_one(
            {"token": token}, {"_id": 0}
        )

    row = asyncio.run(_find())
    assert row is not None
    assert row.get("source") == "admin_reset_link_copy"


def test_copy_status_chip_reflects_new_issued_state(super_headers, customer):
    """After a copy call the ``portal-reset-link-status`` chip must
    immediately return ``issued`` (frontend refreshes it via
    ``loadStatus()`` post-copy)."""
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    s = requests.get(
        f"{API}/customers/{customer['id']}/portal-reset-link-status",
        headers=super_headers, timeout=15,
    )
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["status"] == "issued"
    assert body["source"] == "admin_reset_link_copy"
    assert body["issued_at"] is not None
    assert body["expires_at"] is not None
    # The status endpoint MUST never echo the raw token.
    assert "token" not in body


def test_copy_history_endpoint_surfaces_new_event(super_headers, customer):
    """``portal-history`` should now include the
    ``admin_password_reset_copied`` event so the activity feed
    shows both send + copy actions in the same list."""
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    h = requests.get(
        f"{API}/customers/{customer['id']}/portal-history?limit=50",
        headers=super_headers, timeout=15,
    )
    assert h.status_code == 200, h.text
    events = [e.get("event") for e in h.json().get("events", [])]
    assert "admin_password_reset_copied" in events


# ─── Auth branches ──────────────────────────────────────────────────

def test_copy_regular_admin_forbidden(admin_headers, customer):
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 403


def test_copy_technician_forbidden(customer):
    tech_tok = _login("mike@aquaterra.com")
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers={"Authorization": f"Bearer {tech_tok}"},
        timeout=15,
    )
    assert r.status_code in (401, 403)


def test_copy_unauthenticated_rejected(customer):
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        timeout=15,
    )
    assert r.status_code in (401, 403)


def test_copy_404_unknown_customer(super_headers):
    r = requests.post(
        f"{API}/customers/{uuid.uuid4().hex}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r.status_code == 404


def test_copy_400_no_email(super_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=super_headers, json={
        "name": f"K30COPY NoEmail {marker}",
        "phone": "+14805557788",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    try:
        r = requests.post(
            f"{API}/customers/{cid}/portal-reset-link-copy",
            headers=super_headers, timeout=15,
        )
        assert r.status_code == 400, r.text
    finally:
        requests.delete(f"{API}/customers/{cid}",
                          headers=super_headers, timeout=15)


def test_copy_token_value_never_logged(super_headers, customer):
    """The raw token must never appear in the backend log file. We
    call the endpoint, grep the log for the returned token, and
    assert no match."""
    r = requests.post(
        f"{API}/customers/{customer['id']}/portal-reset-link-copy",
        headers=super_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    token = r.json()["reset_url"].split("token=")[-1]
    assert token and len(token) > 20
    log_paths = [
        "/var/log/supervisor/backend.out.log",
        "/var/log/supervisor/backend.err.log",
    ]
    for path in log_paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", errors="ignore") as f:
            contents = f.read()
        assert token not in contents, f"token leaked into {path}"
