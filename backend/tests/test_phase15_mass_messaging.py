"""Phase 15 · Feb-2026 — Mass Text + Email broadcast test suite.

Covers the invariants promised in the spec:

* Admin can preview + send.
* Manager, tech, customer → 403 on preview + send + list.
* Rate limit trips on 2nd send inside 5 min → 429.
* Audience > 5000 → 400 AUDIENCE_TOO_LARGE.
* Suppression respected — a customer on the suppression list is not
  sent to and counts as ``suppressed``.
* Customer without email → not attempted on email (counts as
  ``no_contact_email``).
* Delivery rows persisted with ``trigger_entity.kind='mass_broadcast'``
  and correct ``batch_id``.
* Idempotency: same ``confirm_token`` can't fire twice.
* Merge-tag rendering happy path — one substitution resolves.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
_TENANT_ID = _TENANT["id"]

API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def manager_headers():
    return _login("manager@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_headers():
    return _login("customer@aquaterra.com")


@pytest.fixture(autouse=True)
def _clean_slate():
    """Reset per-test so batches + confirm tokens don't leak between
    cases. Keeps the rate-limit + idempotency tests honest."""
    _sync.mass_messaging_batches.delete_many({"tenant_id": _TENANT_ID})
    _sync.mass_messaging_confirm_tokens.delete_many({"tenant_id": _TENANT_ID})
    _sync.marketing_deliveries.delete_many({
        "tenant_id": _TENANT_ID,
        "trigger_entity.kind": "mass_broadcast",
    })
    yield


@pytest.fixture
def scratch_customers():
    """Two ephemeral customers on the aquaterra tenant. One has email
    + phone, the other has neither. Yielded ids; teardown removes
    them + any deliveries they collected."""
    marker = uuid.uuid4().hex[:8]
    docs = [
        {
            "id": f"phase15-a-{marker}",
            "tenant_id": _TENANT_ID,
            "name": f"Phase15 A {marker}",
            "first_name": "Ada", "last_name": "Test",
            "email": f"ada-{marker}@pytest.local",
            "phone": "+15550001111",
            "is_active": True,
        },
        {
            "id": f"phase15-b-{marker}",
            "tenant_id": _TENANT_ID,
            "name": f"Phase15 B {marker}",
            "first_name": "Bob", "last_name": "NoContact",
            "email": "", "phone": "",  # deliberately empty
            "is_active": True,
        },
    ]
    _sync.customers.insert_many(docs)
    ids = [d["id"] for d in docs]
    try:
        yield ids
    finally:
        _sync.customers.delete_many({"id": {"$in": ids}})
        _sync.marketing_deliveries.delete_many({"customer_id": {"$in": ids}})


# ═════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════
def test_preview_forbidden_for_non_admin(manager_headers, tech_headers,
                                          customer_headers, scratch_customers):
    body = {"channels": ["email"], "audience": "all_active_customers",
             "subject": "Hi", "body": "Hello {{customer.first_name}}"}
    for hdrs, label in [(manager_headers, "manager"),
                         (tech_headers, "tech"),
                         (customer_headers, "customer")]:
        r = requests.post(f"{API}/mass-messaging/preview", json=body,
                           headers=hdrs, timeout=10)
        assert r.status_code == 403, f"{label} expected 403, got {r.status_code}"


def test_send_forbidden_for_non_admin(manager_headers, tech_headers,
                                       customer_headers, scratch_customers):
    body = {"channels": ["email"], "audience": "all_active_customers",
             "subject": "Hi", "body": "Hello", "confirm_token": "irrelevant"}
    for hdrs in (manager_headers, tech_headers, customer_headers):
        r = requests.post(f"{API}/mass-messaging/send", json=body,
                           headers=hdrs, timeout=10)
        assert r.status_code == 403


def test_list_batches_forbidden_for_non_admin(manager_headers, tech_headers,
                                                customer_headers):
    for hdrs in (manager_headers, tech_headers, customer_headers):
        r = requests.get(f"{API}/mass-messaging/batches",
                          headers=hdrs, timeout=10)
        assert r.status_code == 403


# ═════════════════════════════════════════════════════════════════
# Happy path
# ═════════════════════════════════════════════════════════════════
def test_preview_returns_recipients_sample_and_confirm_token(admin_headers,
                                                              scratch_customers):
    body = {
        "channels": ["email", "sms"],
        "audience": "all_active_customers",
        "subject": "Hello {{customer.first_name}}",
        "body": "Hi {{customer.first_name}} — reminder from the pool team!",
    }
    r = requests.post(f"{API}/mass-messaging/preview", json=body,
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["estimated_recipients"]["email"] >= 1, \
        "at least one scratch customer with email must be counted"
    assert d["estimated_recipients"]["sms"] >= 1
    # Merge-tag substitution — the sample_customer's first name must
    # appear in the rendered subject/body/sms. Which customer gets
    # picked for the sample depends on ordering + who else is active
    # on the tenant at test time; we assert against the actual
    # sample_customer.id so the test is robust to that.
    sample_cust_id = d["sample_render"]["sample_customer"]["id"]
    sample_cust = _sync.customers.find_one({"id": sample_cust_id}, {"_id": 0})
    first = (sample_cust or {}).get("first_name") or ""
    assert first, "sample customer must have a first_name"
    assert (first in d["sample_render"]["email_subject"]
             or first in d["sample_render"]["email_body_html"]
             or first in d["sample_render"]["sms_body"])
    assert d["confirm_token"], "preview must issue a confirm_token"
    assert d["stats"]["no_contact_email"] >= 1  # Bob has no email


def test_send_persists_batch_and_delivery_rows(admin_headers, scratch_customers):
    prev_body = {
        "channels": ["email"],
        "audience": "all_active_customers",
        "subject": "Broadcast",
        "body": "Body for {{customer.first_name}}",
    }
    prev = requests.post(f"{API}/mass-messaging/preview", json=prev_body,
                          headers=admin_headers, timeout=15).json()

    send_body = {**prev_body, "confirm_token": prev["confirm_token"]}
    r = requests.post(f"{API}/mass-messaging/send", json=send_body,
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    # Background task fanout is fast in mocked mode — poll briefly.
    deadline = time.time() + 10
    row = None
    while time.time() < deadline:
        row = _sync.mass_messaging_batches.find_one({"id": batch_id})
        if row and row.get("status") == "completed":
            break
        time.sleep(0.5)
    assert row, "batch row must persist"
    assert row["initiated_by_user_id"], "batch must record initiator"
    assert row["channels"] == ["email"]
    assert row.get("status") in ("completed", "running")

    # Delivery rows carry the trigger_entity + batch_id we promised.
    dlv = list(_sync.marketing_deliveries.find({"batch_id": batch_id}))
    assert dlv, "at least one delivery row must land"
    for d in dlv:
        assert d["trigger_entity"]["kind"] == "mass_broadcast"
        assert d["trigger_entity"]["id"] == batch_id
        assert d["channel"] == "email"


def test_no_contact_email_is_counted_and_not_attempted(admin_headers,
                                                        scratch_customers):
    """Bob (no email) should count as no_contact and NOT receive a
    provider-attempt delivery row (status='no_contact' instead)."""
    body = {"channels": ["email"], "audience": "all_active_customers",
             "subject": "S", "body": "B"}
    prev = requests.post(f"{API}/mass-messaging/preview", json=body,
                          headers=admin_headers, timeout=15).json()
    send = requests.post(f"{API}/mass-messaging/send",
                          json={**body, "confirm_token": prev["confirm_token"]},
                          headers=admin_headers, timeout=15).json()
    batch_id = send["batch_id"]
    time.sleep(2.0)
    bob_id = [c for c in scratch_customers if "b-" in c][0]
    dlv = _sync.marketing_deliveries.find_one({
        "batch_id": batch_id, "customer_id": bob_id,
    })
    assert dlv, "bob must have a delivery row"
    assert dlv["delivery_status"] == "no_contact"
    assert dlv["recipient"] == ""


# ═════════════════════════════════════════════════════════════════
# Suppression
# ═════════════════════════════════════════════════════════════════
def test_suppression_counted_and_not_sent(admin_headers, scratch_customers):
    """Add Ada's email to the suppression list; preview must count
    her as suppressed_email; send must not attempt to reach her."""
    ada_id = [c for c in scratch_customers if "a-" in c][0]
    ada = _sync.customers.find_one({"id": ada_id})
    _sync.marketing_suppressions.insert_one({
        "id": f"supp-{uuid.uuid4().hex[:8]}",
        "tenant_id": _TENANT_ID,
        "channel": "email",
        "address": (ada["email"] or "").lower(),
        "category": "marketing",
        "reason": "phase15 test",
        "deleted_at": None,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    try:
        body = {"channels": ["email"], "audience": "all_active_customers",
                 "subject": "S", "body": "B"}
        prev = requests.post(f"{API}/mass-messaging/preview", json=body,
                              headers=admin_headers, timeout=15).json()
        assert prev["stats"]["suppressed_email"] >= 1, \
            "Ada must appear in suppressed_email count"
        # Ada's email should NOT appear in estimated eligible count
        # unless there's another eligible customer (there isn't for
        # this test fixture besides seed leads).
        send = requests.post(f"{API}/mass-messaging/send",
                              json={**body, "confirm_token": prev["confirm_token"]},
                              headers=admin_headers, timeout=15).json()
        batch_id = send["batch_id"]
        time.sleep(2.0)
        ada_row = _sync.marketing_deliveries.find_one({
            "batch_id": batch_id, "customer_id": ada_id,
        })
        # Ada should be either absent (adapter refused before insert)
        # or logged as 'suppressed'. Either way she must NOT be 'sent'.
        if ada_row:
            assert ada_row["delivery_status"] != "sent"
    finally:
        _sync.marketing_suppressions.delete_many({
            "tenant_id": _TENANT_ID, "reason": "phase15 test",
        })


# ═════════════════════════════════════════════════════════════════
# Rate limit
# ═════════════════════════════════════════════════════════════════
def test_rate_limit_second_send_within_5_min_returns_429(admin_headers,
                                                          scratch_customers):
    body = {"channels": ["email"], "audience": "all_active_customers",
             "subject": "S", "body": "B"}
    # 1st send — must succeed.
    p1 = requests.post(f"{API}/mass-messaging/preview", json=body,
                        headers=admin_headers, timeout=15).json()
    r1 = requests.post(f"{API}/mass-messaging/send",
                        json={**body, "confirm_token": p1["confirm_token"]},
                        headers=admin_headers, timeout=15)
    assert r1.status_code == 200

    # 2nd send — must be rate-limited.
    p2 = requests.post(f"{API}/mass-messaging/preview", json=body,
                        headers=admin_headers, timeout=15).json()
    r2 = requests.post(f"{API}/mass-messaging/send",
                        json={**body, "confirm_token": p2["confirm_token"]},
                        headers=admin_headers, timeout=15)
    assert r2.status_code == 429, r2.text
    detail = r2.json().get("detail") or {}
    assert detail.get("code") == "RATE_LIMITED"


# ═════════════════════════════════════════════════════════════════
# Audience cap
# ═════════════════════════════════════════════════════════════════
def test_audience_over_5000_returns_400_audience_too_large(admin_headers):
    """Insert 5001 stub customers, then preview → 400.  Teardown
    deletes them all before yielding control."""
    marker = uuid.uuid4().hex[:6]
    docs = [{
        "id": f"cap-{marker}-{i}",
        "tenant_id": _TENANT_ID,
        "name": f"Cap {marker} {i}",
        "email": f"cap-{marker}-{i}@pytest.local",
        "phone": "",
        "is_active": True,
    } for i in range(5001)]
    _sync.customers.insert_many(docs)
    try:
        body = {"channels": ["email"], "audience": "all_active_customers",
                 "subject": "S", "body": "B"}
        r = requests.post(f"{API}/mass-messaging/preview", json=body,
                           headers=admin_headers, timeout=20)
        assert r.status_code == 400
        det = r.json().get("detail") or {}
        assert det.get("code") == "AUDIENCE_TOO_LARGE"
    finally:
        _sync.customers.delete_many({"id": {"$regex": f"^cap-{marker}-"}})


# ═════════════════════════════════════════════════════════════════
# Idempotency
# ═════════════════════════════════════════════════════════════════
def test_confirm_token_single_use(admin_headers, scratch_customers):
    body = {"channels": ["email"], "audience": "all_active_customers",
             "subject": "S", "body": "B"}
    prev = requests.post(f"{API}/mass-messaging/preview", json=body,
                          headers=admin_headers, timeout=15).json()
    r1 = requests.post(f"{API}/mass-messaging/send",
                        json={**body, "confirm_token": prev["confirm_token"]},
                        headers=admin_headers, timeout=15)
    assert r1.status_code == 200
    # 2nd call with the SAME token — even ignoring the rate limit
    # (which fires first), the token must be single-use.
    # We wipe the batches row to skip the rate-limit path and prove
    # the idempotency guard.
    _sync.mass_messaging_batches.delete_many({"tenant_id": _TENANT_ID})
    r2 = requests.post(f"{API}/mass-messaging/send",
                        json={**body, "confirm_token": prev["confirm_token"]},
                        headers=admin_headers, timeout=15)
    assert r2.status_code == 400
    det = r2.json().get("detail") or {}
    assert det.get("code") in ("CONFIRM_TOKEN_ALREADY_USED",
                                 "INVALID_CONFIRM_TOKEN")


def test_confirm_token_mismatched_channels_rejected(admin_headers,
                                                     scratch_customers):
    """A preview issued for ['email'] can't authorize a send for
    ['email','sms']. Prevents preview-of-A-authorises-send-of-B."""
    prev = requests.post(f"{API}/mass-messaging/preview",
                          json={"channels": ["email"],
                                 "audience": "all_active_customers",
                                 "subject": "S", "body": "B"},
                          headers=admin_headers, timeout=15).json()
    r = requests.post(f"{API}/mass-messaging/send",
                       json={"channels": ["email", "sms"],
                              "audience": "all_active_customers",
                              "subject": "S", "body": "B",
                              "confirm_token": prev["confirm_token"]},
                       headers=admin_headers, timeout=15)
    assert r.status_code == 400
    det = r.json().get("detail") or {}
    assert det.get("code") == "CONFIRM_TOKEN_CHANNELS_MISMATCH"


# ═════════════════════════════════════════════════════════════════
# Batches listing + detail
# ═════════════════════════════════════════════════════════════════
def test_list_and_read_batch(admin_headers, scratch_customers):
    body = {"channels": ["email"], "audience": "all_active_customers",
             "subject": "S", "body": "B"}
    prev = requests.post(f"{API}/mass-messaging/preview", json=body,
                          headers=admin_headers, timeout=15).json()
    send = requests.post(f"{API}/mass-messaging/send",
                          json={**body, "confirm_token": prev["confirm_token"]},
                          headers=admin_headers, timeout=15).json()
    batch_id = send["batch_id"]
    time.sleep(2.0)

    lst = requests.get(f"{API}/mass-messaging/batches",
                        headers=admin_headers, timeout=10).json()
    assert lst["total"] >= 1
    assert any(b["id"] == batch_id for b in lst["items"])

    detail = requests.get(f"{API}/mass-messaging/batches/{batch_id}",
                           headers=admin_headers, timeout=10).json()
    assert detail["batch"]["id"] == batch_id
    assert detail["deliveries"]["total"] >= 1
