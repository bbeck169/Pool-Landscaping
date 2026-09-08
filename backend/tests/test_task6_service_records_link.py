"""Task 6 · Feb 2026 — "Send service records link" (Customer admin page).

Pins the following behaviours:

* ``POST /api/customers/{cid}/send-service-records-link`` returns 200
  + a portal auto-login URL for a happy-path email send.
* SMS happy path also succeeds and inserts a ``customer_link_sends``
  audit row.
* Rate limit — 5 sends per hour per customer — triggers a structured
  429 with ``retry_after_seconds`` on the 6th send.
* Consent gate hard-blocks the request when the customer has
  ``channel_opt_in.email_marketing=false`` (or ``sms_marketing=false``).
  Admin CANNOT bypass — the 403 body carries a machine-readable
  ``reason`` so the modal can render the correct tooltip copy.
* Muted customers 403 with ``reason=muted`` regardless of channel.
* Recipient override MUST match one of the customer's mirrored
  contacts — arbitrary addresses/phones are rejected 400.
* Non-admin roles get 403 from the endpoint dependency.
* The signed token drops the customer on ``/portal/service-reports``
  when redeemed via ``/api/portal/auto-login``.
* ``GET /api/customers/{cid}/service-records-link-status`` mirrors
  the send counter used for rate limiting.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

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
    # Multi-account chooser returns a different shape (Task 4). Fall
    # back to the first account.
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
    """A tenant customer with a known email + mobile. Restored on teardown.

    We prefer the demo ``Jennifer Carson`` (aquaterra tenant) — she's
    seeded in every dev env and carries a mirrored mobile. Falls back
    to the legacy ``brian@plofv.com`` fixture when the demo customer
    isn't around.
    """
    c = (_sync_db.customers.find_one(
            {"email": "customer@aquaterra.com"}, {"_id": 0})
          or _sync_db.customers.find_one(
            {"email": "brian@plofv.com"}, {"_id": 0}))
    if not c:
        pytest.skip("no seed customer with email + mobile available")
    original = {
        "phones": list(c.get("phones") or []),
        "mobiles": list(c.get("mobiles") or []),
        "channel_opt_in": dict(c.get("channel_opt_in") or {}),
        "is_muted": c.get("is_muted"),
    }
    # Ensure a mirrored mobile number is present so SMS sends can
    # allow-list the recipient. Uses the fixed test line when we're
    # on the fallback ``brian`` customer.
    if not (c.get("mobiles") or []):
        _sync_db.customers.update_one(
            {"id": c["id"]},
            {"$push": {"mobiles": {"number_e164": "+16028874400",
                                     "label": "test",
                                     "is_primary": True,
                                     "sms_ok": True}}},
        )
    yield _sync_db.customers.find_one({"id": c["id"]}, {"_id": 0})
    _sync_db.customers.update_one(
        {"id": c["id"]},
        {"$set": {"phones": original["phones"],
                   "mobiles": original["mobiles"],
                   "channel_opt_in": original["channel_opt_in"],
                   "is_muted": original["is_muted"]}},
    )
    _sync_db.customer_link_sends.delete_many({"customer_id": c["id"]})


def _clear_rate(cid: str) -> None:
    if _sync_db is None:
        return
    _sync_db.customer_link_sends.delete_many({"customer_id": cid})


def test_openapi_registers_task6_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=45)
    r.raise_for_status()
    paths = r.json().get("paths", {})
    assert "/api/customers/{cid}/send-service-records-link" in paths
    assert "/api/customers/{cid}/service-records-link-status" in paths


def test_send_email_happy_path(admin_token, customer):
    _clear_rate(customer["id"])
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["channel"] == "email"
    assert body["ttl_hours"] == 168
    assert body["recipient"]
    url = body["url"]
    assert "/api/portal/auto-login?t=" in url
    assert "redirect=/portal/service-reports" in url

    audit = _sync_db.customer_link_sends.find_one(
        {"customer_id": customer["id"], "channel": "email"},
        sort=[("created_at", -1)],
    )
    assert audit is not None
    assert audit["recipient"] == body["recipient"]
    assert audit["token_hash"]
    assert audit["ttl_hours"] == 168


def test_send_sms_happy_path(admin_token, customer):
    _clear_rate(customer["id"])
    # Use the customer's primary mirrored mobile as the override so
    # the allow-list check passes regardless of which seed fixture
    # was picked.
    mobile = (customer.get("mobiles") or [{}])[0].get("number_e164")
    body = {"channel": "sms"}
    if mobile:
        body["recipient"] = mobile
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json=body,
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channel"] == "sms"
    assert body["recipient"]

    audit = _sync_db.customer_link_sends.find_one(
        {"customer_id": customer["id"], "channel": "sms"},
    )
    assert audit is not None


def test_rate_limit_5_per_hour(admin_token, customer):
    """After 5 successful sends in the same hour the 6th call returns
    a structured 429 with ``retry_after_seconds``.
    """
    _clear_rate(customer["id"])
    # Backfill 5 audit rows so we don't hammer the provider.
    now = datetime.now(timezone.utc)
    rows = [
        {"id": str(uuid.uuid4()),
         "tenant_id": customer["tenant_id"],
         "customer_id": customer["id"],
         "channel": "email",
         "recipient": "brian@plofv.com",
         "sent_by": "seed",
         "provider": "resend",
         "provider_status": "sent",
         "token_hash": f"seed-{i}",
         "ttl_hours": 168,
         "expires_at": (now + timedelta(hours=168)).isoformat(),
         "created_at": (now - timedelta(minutes=i * 5)).isoformat()}
        for i in range(5)
    ]
    _sync_db.customer_link_sends.insert_many(rows)

    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 429, r.text
    payload = r.json()["detail"]
    assert payload["detail"] == "rate_limited"
    assert payload["limit_per_hour"] == 5
    assert isinstance(payload["retry_after_seconds"], int)
    assert payload["retry_after_seconds"] > 0
    _clear_rate(customer["id"])


def test_consent_gate_blocks_email(admin_token, customer):
    _sync_db.customers.update_one(
        {"id": customer["id"]},
        {"$set": {"channel_opt_in.email_marketing": False}},
    )
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 403, r.text
    payload = r.json()["detail"]
    assert payload["detail"] == "consent_blocked"
    assert payload["reason"] == "email_consent_off"


def test_consent_gate_blocks_sms(admin_token, customer):
    _sync_db.customers.update_one(
        {"id": customer["id"]},
        {"$set": {"channel_opt_in.sms_marketing": False}},
    )
    mobile = ((customer.get("mobiles") or [{}])[0].get("number_e164")
               or "+16028874400")
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "sms", "recipient": mobile},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 403, r.text
    payload = r.json()["detail"]
    assert payload["detail"] == "consent_blocked"
    assert payload["reason"] == "sms_consent_off"


def test_muted_customer_blocked(admin_token, customer):
    _sync_db.customers.update_one(
        {"id": customer["id"]}, {"$set": {"is_muted": True}},
    )
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 403, r.text
    payload = r.json()["detail"]
    assert payload["detail"] == "consent_blocked"
    assert payload["reason"] == "muted"


def test_recipient_override_not_on_file_rejected(admin_token, customer):
    _clear_rate(customer["id"])
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "email", "recipient": "attacker@evil.example"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    payload = r.json()["detail"]
    assert payload["detail"] == "recipient_not_allowed"


def test_status_endpoint_reflects_send_count(admin_token, customer):
    _clear_rate(customer["id"])
    now = datetime.now(timezone.utc)
    _sync_db.customer_link_sends.insert_many([
        {"id": str(uuid.uuid4()),
         "tenant_id": customer["tenant_id"],
         "customer_id": customer["id"],
         "channel": "email",
         "recipient": "brian@plofv.com",
         "provider": "resend",
         "provider_status": "sent",
         "token_hash": f"status-{i}",
         "ttl_hours": 168,
         "created_at": (now - timedelta(minutes=i)).isoformat()}
        for i in range(3)
    ])
    r = requests.get(
        f"{API}/customers/{customer['id']}/service-records-link-status",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sends_last_hour"] == 3
    assert body["rate_limit"] == 5
    assert body["rate_limited"] is False
    assert body["last_send_at"]
    _clear_rate(customer["id"])


def test_status_endpoint_rate_limited_after_5(admin_token, customer):
    _clear_rate(customer["id"])
    now = datetime.now(timezone.utc)
    _sync_db.customer_link_sends.insert_many([
        {"id": str(uuid.uuid4()),
         "tenant_id": customer["tenant_id"],
         "customer_id": customer["id"],
         "channel": "email",
         "recipient": "brian@plofv.com",
         "provider": "resend",
         "provider_status": "sent",
         "token_hash": f"cap-{i}",
         "ttl_hours": 168,
         "created_at": (now - timedelta(minutes=i * 3)).isoformat()}
        for i in range(5)
    ])
    r = requests.get(
        f"{API}/customers/{customer['id']}/service-records-link-status",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rate_limited"] is True
    assert body["sends_last_hour"] == 5
    assert body["retry_after_seconds"] and body["retry_after_seconds"] > 0
    _clear_rate(customer["id"])


def test_token_redemption_lands_on_service_records(admin_token, customer):
    """Token minted via the endpoint MUST redeem via
    ``/api/portal/auto-login`` and redirect to ``/portal/service-reports``.
    """
    _clear_rate(customer["id"])
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    # Extract query params.
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    token = q.get("t", [""])[0]
    redirect = q.get("redirect", [""])[0]
    assert token, "token missing from URL"
    assert redirect == "/portal/service-reports"

    # Redeem — the auto-login endpoint returns a "Signing you in…"
    # HTML shim that sets cookies + performs a client-side redirect
    # (200 OK) OR issues a 302/303 depending on the browser hint. We
    # accept both and verify the target path appears in the body.
    resp = requests.get(
        f"{API}/portal/auto-login",
        params={"t": token, "redirect": redirect},
        allow_redirects=False,
        timeout=15,
    )
    assert resp.status_code in (200, 302, 303), f"unexpected {resp.status_code}: {resp.text[:200]}"
    if resp.status_code in (302, 303):
        loc = resp.headers.get("Location", "")
        assert "/portal/service-reports" in loc, f"unexpected redirect target: {loc}"
    else:
        assert "/portal/service-reports" in resp.text, (
            f"redirect target missing from body: {resp.text[:300]}"
        )


def test_non_admin_rejected(customer):
    """A technician (non-admin) cannot mint a service records link."""
    # Find a tech / technician account in the tenant.
    tech = _sync_db.users.find_one(
        {"tenant_id": customer["tenant_id"],
         "role": {"$in": ["tech", "technician"]}},
        {"_id": 0, "email": 1},
    )
    if not tech:
        pytest.skip("no technician user seeded")
    tech_token = _login(tech["email"])
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-service-records-link",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {tech_token}"},
        timeout=15,
    )
    assert r.status_code == 403, r.text


def test_missing_customer_404(admin_token):
    r = requests.post(
        f"{API}/customers/does-not-exist/send-service-records-link",
        json={"channel": "email"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 404, r.text
