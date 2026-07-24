"""Feb-2026 · BUG F — Customer Contact page send-email + send-sms.

Root cause: the Customer Detail composer's SMS button was POSTing to
``/api/sms/send`` — a route that never existed — which 404'd with
"not found". The `send-email` route existed but wasn't logging the
send to ``communications_log``.

This suite pins the fix in place:
* GET /api/openapi.json includes both ``send-email`` + ``send-sms``.
* send-email: allow-list recipient, delivery via Resend adapter,
  comms_log row with ``trigger_entity.kind="customer_direct_message"``.
* send-sms: allow-list recipient (digits-normalised), delivery via
  RingCentral adapter, comms_log row.
* Both endpoints return 400 for a recipient not on the customer.
* Both endpoints require admin (403 for tech/customer).
* Both endpoints 404 for an unknown customer id.
"""
import os
import uuid

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
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def customer():
    """A tenant customer with a known email + phone we can allow-list
    against. Restored to its original phones list on teardown."""
    c = _sync_db.customers.find_one(
        {"email": "brian@plofv.com"}, {"_id": 0},
    )
    if not c:
        pytest.skip("brian customer not seeded")
    original_phones = list(c.get("phones") or [])
    # Ensure a known allow-listed phone is present.
    if not any("6028874400" in "".join(ch for ch in (p.get("number") or "") if ch.isdigit())
               for p in original_phones):
        _sync_db.customers.update_one(
            {"id": c["id"]},
            {"$push": {"phones": {"number": "+16028874400", "label": "test"}}},
        )
    yield _sync_db.customers.find_one({"id": c["id"]}, {"_id": 0})
    _sync_db.customers.update_one(
        {"id": c["id"]}, {"$set": {"phones": original_phones}},
    )


def test_openapi_registers_both_send_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=45)
    r.raise_for_status()
    paths = r.json().get("paths", {})
    assert "/api/customers/{cid}/send-email" in paths
    assert "/api/customers/{cid}/send-sms" in paths
    # And there is NO retired ``/api/sms/send`` route (that was the 404).
    assert "/api/sms/send" not in paths


# ── send-email ─────────────────────────────────────────────────
def test_customer_send_email_success_and_comms_log(customer):
    admin = _login("admin@aquaterra.com")
    marker = f"bugf-{uuid.uuid4().hex[:8]}"
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-email",
        json={"to": "brian@plofv.com",
              "subject": f"BUG F pytest {marker}",
              "body": f"test {marker}",
              "customer_id": customer["id"]},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("status") in ("sent", "queued", "mocked", "skipped_opted_out")

    # Comms log persisted with the fixed trigger kind.
    row = _sync_db.communications_log.find_one(
        {"customer_id": customer["id"],
         "channel": "email",
         "subject": f"BUG F pytest {marker}"},
        {"_id": 0},
    )
    assert row is not None
    assert row["trigger_entity"]["kind"] == "customer_direct_message"
    assert row["recipient"] == "brian@plofv.com"
    assert row["provider"] == "resend"


def test_customer_send_email_recipient_not_allowed_400(customer):
    admin = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-email",
        json={"to": "someone-else@example.com",
              "subject": "s", "body": "b",
              "customer_id": customer["id"]},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=15,
    )
    assert r.status_code == 400


def test_customer_send_email_unknown_customer_404():
    admin = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/customers/does-not-exist-{uuid.uuid4().hex}/send-email",
        json={"to": "brian@plofv.com", "subject": "s", "body": "b"},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=15,
    )
    assert r.status_code == 404


def test_customer_send_email_requires_admin(customer):
    tech = _login("mike@aquaterra.com")
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-email",
        json={"to": "brian@plofv.com", "subject": "s", "body": "b"},
        headers={"Authorization": f"Bearer {tech}"},
        timeout=15,
    )
    assert r.status_code == 403


# ── send-sms ──────────────────────────────────────────────────
def test_customer_send_sms_success_and_comms_log(customer):
    admin = _login("admin@aquaterra.com")
    marker = f"bugf-sms-{uuid.uuid4().hex[:8]}"
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-sms",
        json={"to": "+16028874400",
              "body": f"test {marker}",
              "customer_id": customer["id"]},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=25,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("provider_status") in ("sent", "queued", "mocked", "suppressed")

    row = _sync_db.communications_log.find_one(
        {"customer_id": customer["id"], "channel": "sms",
         "body": {"$regex": marker}},
        {"_id": 0},
    )
    assert row is not None
    assert row["trigger_entity"]["kind"] == "customer_direct_message"
    assert row["recipient"] == "+16028874400"
    assert row["provider"] in ("ringcentral", "mock")


def test_customer_send_sms_recipient_not_allowed_400(customer):
    admin = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-sms",
        json={"to": "+15550000000", "body": "hi"},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=15,
    )
    assert r.status_code == 400


def test_customer_send_sms_unknown_customer_404():
    admin = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/customers/does-not-exist-{uuid.uuid4().hex}/send-sms",
        json={"to": "+16028874400", "body": "hi"},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=15,
    )
    assert r.status_code == 404


def test_customer_send_sms_requires_admin(customer):
    tech = _login("mike@aquaterra.com")
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-sms",
        json={"to": "+16028874400", "body": "hi"},
        headers={"Authorization": f"Bearer {tech}"},
        timeout=15,
    )
    assert r.status_code == 403


def test_customer_send_sms_normalises_phone_variants(customer):
    """A (602) 887-4400 style input should match the +16028874400 on
    the customer record — the endpoint strips non-digits and matches
    on the last 10 digits."""
    admin = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/customers/{customer['id']}/send-sms",
        json={"to": "(602) 887-4400", "body": "normalised"},
        headers={"Authorization": f"Bearer {admin}"},
        timeout=25,
    )
    # 200 (validated + sent) — must NOT be 400.
    assert r.status_code == 200, r.text
