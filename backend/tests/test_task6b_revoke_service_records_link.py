"""Task 6b · Feb 2026 — Revoke a service-records link.

Pins the following behaviours:

* ``GET /api/customers/{cid}/service-records-links`` returns the most
  recent sends for the customer with ``revoked_at`` state.
* ``POST /api/customers/{cid}/service-records-links/{token_id}/revoke``
  stamps ``revoked_at`` + ``revoked_by`` on the audit row and writes
  a ``service_records_link_revoked`` row to ``communications_log``.
* Revoke is idempotent — a second call returns 200 with
  ``already_revoked=true`` and preserves the original stamp.
* Revoke scope is a SINGLE token_id — sibling sends for the same
  customer stay live.
* Portal ``/api/portal/auto-login`` rejects a revoked token by
  redirecting to ``/portal/login?reason=link_revoked`` while still
  accepting the non-revoked sibling.
* Non-admin roles get 403 on the revoke endpoint.
* Unknown token_id / customer_id 404s cleanly.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = "http://localhost:8001/api"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME] if _MONGO_URL and _DB_NAME else None


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    body = r.json()
    if body.get("multi_account_choice_required"):
        pick = requests.post(
            f"{API}/auth/login/select-account",
            json={"choice_token": body["choice_token"],
                  "record_id": body["accounts"][0]["id"]},
            timeout=15,
        )
        pick.raise_for_status()
        return pick.json()["access_token"]
    return body["access_token"]


@pytest.fixture
def admin_token():
    return _login("admin@aquaterra.com")


@pytest.fixture
def customer():
    c = (_sync_db.customers.find_one({"email": "customer@aquaterra.com"}, {"_id": 0})
          or _sync_db.customers.find_one({"email": "brian@plofv.com"}, {"_id": 0}))
    if not c:
        pytest.skip("no seed customer available")
    yield c
    _sync_db.customer_link_sends.delete_many({"customer_id": c["id"]})


def _send(admin_token: str, cid: str, channel: str = "email",
           recipient: str | None = None) -> dict:
    payload = {"channel": channel}
    if recipient:
        payload["recipient"] = recipient
    r = requests.post(
        f"{API}/customers/{cid}/send-service-records-link",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _list(admin_token: str, cid: str) -> list[dict]:
    r = requests.get(
        f"{API}/customers/{cid}/service-records-links?limit=5",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["sends"]


def test_openapi_registers_revoke_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=45)
    r.raise_for_status()
    paths = r.json().get("paths", {})
    assert "/api/customers/{cid}/service-records-links" in paths
    assert (
        "/api/customers/{cid}/service-records-links/{token_id}/revoke"
        in paths
    )


def test_list_service_records_links(admin_token, customer):
    _sync_db.customer_link_sends.delete_many({"customer_id": customer["id"]})
    _send(admin_token, customer["id"])
    _send(admin_token, customer["id"])
    rows = _list(admin_token, customer["id"])
    assert len(rows) == 2
    for r in rows:
        assert r["channel"] == "email"
        assert r["revoked_at"] is None
        assert r["id"]


def test_revoke_marks_token_and_returns_stamp(admin_token, customer):
    _sync_db.customer_link_sends.delete_many({"customer_id": customer["id"]})
    _send(admin_token, customer["id"])
    row = _list(admin_token, customer["id"])[0]
    r = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/{row['id']}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["already_revoked"] is False
    assert body["revoked_at"]
    assert body["revoked_by_email"] == "admin@aquaterra.com"

    audit = _sync_db.customer_link_sends.find_one({"id": row["id"]})
    assert audit["revoked_at"] is not None
    assert audit["revoked_by_email"] == "admin@aquaterra.com"


def test_revoke_is_idempotent(admin_token, customer):
    _sync_db.customer_link_sends.delete_many({"customer_id": customer["id"]})
    _send(admin_token, customer["id"])
    row = _list(admin_token, customer["id"])[0]

    r1 = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/{row['id']}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r1.status_code == 200
    stamp1 = r1.json()["revoked_at"]

    r2 = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/{row['id']}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["already_revoked"] is True
    # Original stamp is preserved.
    assert body2["revoked_at"] == stamp1


def test_revoke_scope_is_single_token(admin_token, customer):
    """Revoking one link MUST NOT touch sibling sends."""
    _sync_db.customer_link_sends.delete_many({"customer_id": customer["id"]})
    _send(admin_token, customer["id"])
    _send(admin_token, customer["id"])
    rows = _list(admin_token, customer["id"])
    victim = rows[0]
    sibling = rows[1]

    r = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/{victim['id']}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text

    rows_after = _list(admin_token, customer["id"])
    for r in rows_after:
        if r["id"] == victim["id"]:
            assert r["revoked_at"] is not None
        elif r["id"] == sibling["id"]:
            assert r["revoked_at"] is None


def test_auto_login_rejects_revoked_token(admin_token, customer):
    """The full end-to-end contract — a revoked link 302s to
    ``/portal/login?reason=link_revoked`` at redemption time.
    """
    _sync_db.customer_link_sends.delete_many({"customer_id": customer["id"]})
    body = _send(admin_token, customer["id"])
    row = _list(admin_token, customer["id"])[0]

    # Revoke.
    r = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/{row['id']}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200

    # Extract token from URL and hit auto-login.
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(body["url"]).query)
    token = q["t"][0]

    resp = requests.get(
        f"{API}/portal/auto-login",
        params={"t": token, "redirect": "/portal/service-reports"},
        allow_redirects=False,
        timeout=15,
    )
    assert resp.status_code in (302, 303), (
        f"expected redirect, got {resp.status_code}: {resp.text[:200]}"
    )
    loc = resp.headers.get("Location", "")
    assert "reason=link_revoked" in loc, f"unexpected redirect: {loc}"


def test_auto_login_still_accepts_non_revoked_sibling(admin_token, customer):
    """Revoking one link MUST NOT invalidate a sibling send —
    end-to-end verification with the real auto-login redemption path.
    """
    _sync_db.customer_link_sends.delete_many({"customer_id": customer["id"]})
    victim_body = _send(admin_token, customer["id"])
    sibling_body = _send(admin_token, customer["id"])
    # Identify the two rows.
    rows = _list(admin_token, customer["id"])
    ids = {r["id"] for r in rows}
    assert len(ids) == 2
    from urllib.parse import urlparse, parse_qs

    # Revoke the FIRST send. We need to know which id corresponds to
    # which body — the ``customer_link_sends`` audit row is written
    # after the send response returns, so the newest row is the last
    # send. Use the ``token_hash`` to disambiguate.
    from services.service_records_link import hash_token
    victim_token = parse_qs(urlparse(victim_body["url"]).query)["t"][0]
    sibling_token = parse_qs(urlparse(sibling_body["url"]).query)["t"][0]
    victim_row = _sync_db.customer_link_sends.find_one(
        {"customer_id": customer["id"], "token_hash": hash_token(victim_token)},
    )
    assert victim_row, "victim row not found by token_hash"

    r = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/{victim_row['id']}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200

    # Sibling redemption still works — 200 interstitial with the redirect body.
    resp = requests.get(
        f"{API}/portal/auto-login",
        params={"t": sibling_token, "redirect": "/portal/service-reports"},
        allow_redirects=False,
        timeout=15,
    )
    # Success renders the "Signing you in…" HTML (200); failure would 302.
    assert resp.status_code == 200, (
        f"expected 200 interstitial, got {resp.status_code}: {resp.text[:200]}"
    )
    assert "/portal/service-reports" in resp.text


def test_revoke_unknown_token_returns_404(admin_token, customer):
    r = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/does-not-exist/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 404


def test_revoke_unknown_customer_returns_404(admin_token):
    r = requests.post(
        f"{API}/customers/does-not-exist"
        f"/service-records-links/some-id/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 404


def test_revoke_requires_admin(customer):
    tech = _sync_db.users.find_one(
        {"tenant_id": customer["tenant_id"],
         "role": {"$in": ["tech", "technician"]}},
        {"_id": 0, "email": 1},
    )
    if not tech:
        pytest.skip("no technician user seeded")
    tech_token = _login(tech["email"])
    # Seed a dummy row to attempt to revoke.
    row_id = str(uuid.uuid4())
    _sync_db.customer_link_sends.insert_one({
        "id": row_id,
        "tenant_id": customer["tenant_id"],
        "customer_id": customer["id"],
        "channel": "email",
        "recipient": "x@example.com",
        "token_hash": "test-hash",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(
            f"{API}/customers/{customer['id']}"
            f"/service-records-links/{row_id}/revoke",
            headers={"Authorization": f"Bearer {tech_token}"},
            timeout=15,
        )
        assert r.status_code == 403, r.text
    finally:
        _sync_db.customer_link_sends.delete_one({"id": row_id})


def test_revoked_link_writes_comms_log_row(admin_token, customer):
    _sync_db.customer_link_sends.delete_many({"customer_id": customer["id"]})
    _send(admin_token, customer["id"])
    row = _list(admin_token, customer["id"])[0]
    _sync_db.communications_log.delete_many({
        "trigger_entity.kind": "service_records_link_revoked",
        "trigger_entity.link_id": row["id"],
    })
    r = requests.post(
        f"{API}/customers/{customer['id']}"
        f"/service-records-links/{row['id']}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200

    log = _sync_db.communications_log.find_one({
        "trigger_entity.kind": "service_records_link_revoked",
        "trigger_entity.link_id": row["id"],
    })
    assert log is not None
    assert log["delivery_status"] == "revoked"
    assert log["customer_id"] == customer["id"]
