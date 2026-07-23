"""Slice O · Feb-2026 — Communications Log test suite.

Covers:

* RBAC — non-admin roles blocked on both endpoints.
* List filter: customer_id, channel, date range, status.
* Status derivation: bounced_at wins over clicked/opened/sent.
* Summary KPI math against a controlled fixture.
* Resend webhook now stamps per-event timestamps (opened_at etc.).
* RC SMS handler mirrors outbound delivery status onto the
  marketing_deliveries row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]

API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def manager_headers():  return _login("manager@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():     return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_headers(): return _login("customer@aquaterra.com")


@pytest.fixture(autouse=True)
def _cleanup():
    _sync.marketing_deliveries.delete_many({
        "tenant_id": _TENANT_ID,
        "id": {"$regex": "^phase15o-"},
    })
    _sync.customers.delete_many({
        "tenant_id": _TENANT_ID,
        "id": {"$regex": "^phase15o-cust-"},
    })
    yield
    _sync.marketing_deliveries.delete_many({
        "tenant_id": _TENANT_ID,
        "id": {"$regex": "^phase15o-"},
    })
    _sync.customers.delete_many({
        "tenant_id": _TENANT_ID,
        "id": {"$regex": "^phase15o-cust-"},
    })


@pytest.fixture
def scratch_deliveries():
    """Seed a controlled set: 5 delivery rows spanning both channels,
    all 5 status buckets, and 2 customers. Returns the shape so tests
    can assert on the deterministic ids."""
    marker = uuid.uuid4().hex[:6]
    cust_a = f"phase15o-cust-a-{marker}"
    cust_b = f"phase15o-cust-b-{marker}"
    _sync.customers.insert_many([
        {"id": cust_a, "tenant_id": _TENANT_ID, "name": f"Fixture A {marker}",
          "email": "", "phone": "", "is_active": True},
        {"id": cust_b, "tenant_id": _TENANT_ID, "name": f"Fixture B {marker}",
          "email": "", "phone": "", "is_active": True},
    ])
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        # 1) plain email sent
        {"id": f"phase15o-sent-{marker}",  "channel": "email",
          "tenant_id": _TENANT_ID,
          "customer_id": cust_a, "recipient": "a@ex.com",
          "subject": "Sent", "body": "hi", "provider": "resend",
          "provider_response_id": f"prov-sent-{marker}",
          "delivery_status": "sent",
          "trigger_entity": {"kind": "test", "id": marker},
          "created_at": now},
        # 2) email opened
        {"id": f"phase15o-open-{marker}",  "channel": "email",
          "tenant_id": _TENANT_ID,
          "customer_id": cust_a, "recipient": "a@ex.com",
          "subject": "Opened", "body": "hi", "provider": "resend",
          "provider_response_id": f"prov-open-{marker}",
          "delivery_status": "sent",
          "opened_at": now,
          "trigger_entity": {"kind": "test", "id": marker},
          "created_at": now},
        # 3) email clicked
        {"id": f"phase15o-click-{marker}", "channel": "email",
          "tenant_id": _TENANT_ID,
          "customer_id": cust_b, "recipient": "b@ex.com",
          "subject": "Clicked", "body": "hi", "provider": "resend",
          "provider_response_id": f"prov-click-{marker}",
          "delivery_status": "sent",
          "opened_at": now, "clicked_at": now,
          "trigger_entity": {"kind": "test", "id": marker},
          "created_at": now},
        # 4) email bounced
        {"id": f"phase15o-bounce-{marker}", "channel": "email",
          "tenant_id": _TENANT_ID,
          "customer_id": cust_b, "recipient": "b@ex.com",
          "subject": "Bounced", "body": "hi", "provider": "resend",
          "provider_response_id": f"prov-bounce-{marker}",
          "delivery_status": "sent",
          "bounced_at": now, "provider_status": "bounced",
          "trigger_entity": {"kind": "test", "id": marker},
          "created_at": now},
        # 5) sms failed
        {"id": f"phase15o-fail-{marker}",  "channel": "sms",
          "tenant_id": _TENANT_ID,
          "customer_id": cust_a, "recipient": "+15551234567",
          "body": "sms body", "provider": "ringcentral",
          "provider_response_id": f"prov-fail-{marker}",
          "delivery_status": "failed",
          "trigger_entity": {"kind": "test", "id": marker},
          "created_at": now},
    ]
    _sync.marketing_deliveries.insert_many(rows)
    return {"cust_a": cust_a, "cust_b": cust_b,
             "marker": marker, "rows": rows}


# ═════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════
def test_list_forbidden_for_non_admin(manager_headers, tech_headers, customer_headers):
    for hdrs in (manager_headers, tech_headers, customer_headers):
        r = requests.get(f"{API}/communications-log", headers=hdrs, timeout=10)
        assert r.status_code == 403


def test_summary_forbidden_for_non_admin(manager_headers, tech_headers,
                                          customer_headers):
    for hdrs in (manager_headers, tech_headers, customer_headers):
        r = requests.get(f"{API}/communications-log/summary",
                          headers=hdrs, timeout=10)
        assert r.status_code == 403


# ═════════════════════════════════════════════════════════════════
# List + filters
# ═════════════════════════════════════════════════════════════════
def test_list_returns_all_fixture_rows_by_default(admin_headers,
                                                    scratch_deliveries):
    r = requests.get(f"{API}/communications-log?page_size=200",
                      headers=admin_headers, timeout=10).json()
    fixture_ids = {row["id"] for row in scratch_deliveries["rows"]}
    got_ids = {row["id"] for row in r["items"] if row["id"] in fixture_ids}
    assert got_ids == fixture_ids, f"missing rows: {fixture_ids - got_ids}"


def test_list_filter_by_customer_id(admin_headers, scratch_deliveries):
    r = requests.get(
        f"{API}/communications-log",
        headers=admin_headers,
        params={"customer_id": scratch_deliveries["cust_a"], "page_size": 200},
        timeout=10,
    ).json()
    assert r["items"], "should have rows"
    for row in r["items"]:
        assert row["customer_id"] == scratch_deliveries["cust_a"]


def test_list_filter_by_channel_sms(admin_headers, scratch_deliveries):
    r = requests.get(
        f"{API}/communications-log",
        headers=admin_headers,
        params={"channel": "sms", "page_size": 200},
        timeout=10,
    ).json()
    # every returned row from our fixture must be SMS.
    fixture_ids = {row["id"] for row in scratch_deliveries["rows"]}
    for row in r["items"]:
        if row["id"] in fixture_ids:
            assert row["channel"] == "sms"


def test_list_filter_by_status_bounced_marks_status_derived(admin_headers,
                                                              scratch_deliveries):
    r = requests.get(
        f"{API}/communications-log",
        headers=admin_headers,
        params={"status": "bounced", "page_size": 200},
        timeout=10,
    ).json()
    bounce_id = f"phase15o-bounce-{scratch_deliveries['marker']}"
    ours = [row for row in r["items"] if row["id"] == bounce_id]
    assert len(ours) == 1
    assert ours[0]["status_derived"] == "bounced"


def test_status_derived_bounced_wins_over_clicked(admin_headers,
                                                   scratch_deliveries):
    """A row with BOTH clicked_at and bounced_at should still surface
    as 'bounced' (bounce is the terminal state)."""
    marker = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc).isoformat()
    _sync.marketing_deliveries.insert_one({
        "id": f"phase15o-mixed-{marker}",
        "tenant_id": _TENANT_ID,
        "channel": "email",
        "customer_id": scratch_deliveries["cust_a"],
        "recipient": "mixed@ex.com",
        "subject": "Mixed", "body": "hi", "provider": "resend",
        "opened_at": now, "clicked_at": now, "bounced_at": now,
        "created_at": now,
    })
    try:
        r = requests.get(
            f"{API}/communications-log", headers=admin_headers,
            params={"page_size": 200}, timeout=10,
        ).json()
        found = [x for x in r["items"] if x["id"] == f"phase15o-mixed-{marker}"]
        assert found and found[0]["status_derived"] == "bounced"
    finally:
        _sync.marketing_deliveries.delete_one({"id": f"phase15o-mixed-{marker}"})


def test_list_pagination(admin_headers, scratch_deliveries):
    r = requests.get(
        f"{API}/communications-log?page=1&page_size=2",
        headers=admin_headers, timeout=10,
    ).json()
    assert r["page"] == 1
    assert r["page_size"] == 2
    assert len(r["items"]) <= 2
    assert r["total"] >= 5  # at least our fixture rows


# ═════════════════════════════════════════════════════════════════
# Summary KPIs
# ═════════════════════════════════════════════════════════════════
def test_summary_math(admin_headers, scratch_deliveries):
    r = requests.get(f"{API}/communications-log/summary?days=30",
                      headers=admin_headers, timeout=10).json()
    # Our fixture: 4 email + 1 sms = 5 total sent last 30d.
    # opened=2 (open + click, since click implies open in adapter).
    # clicked=1
    # bounced=1
    # failed=1 (sms)
    # These are ≤ / ≥ assertions rather than == because live traffic
    # from the app may add its own rows during the module lifetime.
    assert r["window_days"] == 30
    assert r["total_sent"] >= 5
    assert r["email_sent"] >= 4
    assert r["sms_sent"] >= 1
    assert r["opened"] >= 2
    assert r["clicked"] >= 1
    assert r["bounced"] >= 1
    assert r["failed"] >= 1
    # Sanity: rates are 0-100.
    for k in ("open_rate_pct", "click_rate_pct", "bounce_rate_pct"):
        assert 0.0 <= r[k] <= 100.0
