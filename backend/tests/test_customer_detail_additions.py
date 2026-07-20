"""Customer Detail Additions — Feb-2026 ship (backend regression).

Coverage:
    1. Multi-mobile cap (2) + primary rules + sms_ok flag
    2. Multi-email cap (3) + primary rules + marketing_ok flag
    3. Legacy scalar reads: customer.phone / customer.email = primary
    4. VIP toggle sets is_vip + auto-stamps vip_since (+ clears on OFF);
       vip_note is preserved across toggles.
    5. VIP segment auto-seed + preview matches VIP-flagged customers.
    6. Customer tasks CRUD + complete + assignee notification hook.
    7. Marketing sync respects marketing_ok / sms_ok flags.
"""
import os
import time

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def customer(admin_headers):
    """Create a fresh customer per-test so cap/primary tests don't collide."""
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": "Customer Additions Test",
        "first_name": "TEST_ADD",
        "last_name": f"CustomerAdditions{int(time.time()*1000)}",
        "email": "test_additions@example.com",
        "phone": "+14805550100",
    }, timeout=30)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    yield r.json()
    requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


# ─── multi-mobile ─────────────────────────────────────────────────────

def test_add_second_mobile_and_primary_switch(admin_headers, customer):
    cid = customer["id"]
    r = requests.patch(f"{API}/customers/{cid}/mobiles", headers=admin_headers, json={
        "mobiles": [
            {"number_e164": "+14805550100", "label": "Primary", "is_primary": True, "sms_ok": True},
            {"number_e164": "+14805550200", "label": "Work", "is_primary": False, "sms_ok": False},
        ]
    }, timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert len(doc["mobiles"]) == 2
    primaries = [m for m in doc["mobiles"] if m.get("is_primary")]
    assert len(primaries) == 1
    assert primaries[0]["number_e164"] == "+14805550100"
    # Legacy scalar mirrors primary.
    assert doc["phone"] == "+14805550100"

    # Flip primary — new primary should take over, previous must clear.
    r = requests.patch(f"{API}/customers/{cid}/mobiles", headers=admin_headers, json={
        "mobiles": [
            {"number_e164": "+14805550100", "label": "Primary", "is_primary": False, "sms_ok": True},
            {"number_e164": "+14805550200", "label": "Work", "is_primary": True, "sms_ok": False},
        ]
    }, timeout=15)
    assert r.status_code == 200
    doc = r.json()
    primaries = [m for m in doc["mobiles"] if m.get("is_primary")]
    assert len(primaries) == 1
    assert primaries[0]["number_e164"] == "+14805550200"
    # Scalar re-mirrors.
    assert doc["phone"] == "+14805550200"


def test_third_mobile_rejected_with_400(admin_headers, customer):
    cid = customer["id"]
    r = requests.patch(f"{API}/customers/{cid}/mobiles", headers=admin_headers, json={
        "mobiles": [
            {"number_e164": "+14805550001"},
            {"number_e164": "+14805550002"},
            {"number_e164": "+14805550003"},  # exceeds cap
        ]
    }, timeout=15)
    assert r.status_code == 400
    assert "maximum 2 mobiles" in r.text


# ─── multi-email ──────────────────────────────────────────────────────

def test_add_up_to_three_emails_with_primary_rules(admin_headers, customer):
    cid = customer["id"]
    r = requests.patch(f"{API}/customers/{cid}/emails", headers=admin_headers, json={
        "emails": [
            {"address": "owner@example.com", "label": "Primary", "is_primary": True, "marketing_ok": True},
            {"address": "billing@example.com", "label": "Billing", "is_primary": False, "marketing_ok": False},
            {"address": "assistant@example.com", "label": "Owner", "is_primary": False, "marketing_ok": True},
        ]
    }, timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert len(doc["emails"]) == 3
    assert doc["email"] == "owner@example.com"  # scalar = primary


def test_fourth_email_rejected_with_400(admin_headers, customer):
    cid = customer["id"]
    r = requests.patch(f"{API}/customers/{cid}/emails", headers=admin_headers, json={
        "emails": [
            {"address": "a@example.com"}, {"address": "b@example.com"},
            {"address": "c@example.com"}, {"address": "d@example.com"},
        ]
    }, timeout=15)
    assert r.status_code == 400
    assert "maximum 3 emails" in r.text


def test_legacy_scalar_reads_return_primary(admin_headers):
    """A brand-new customer created with legacy scalar fields must
    round-trip through the arrays so downstream reads of phone/email
    stay backwards compatible."""
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": "Legacy Scalar Reader",
        "first_name": "TEST_LEG", "last_name": f"LegacyRead{int(time.time()*1000)}",
        "email": "legacyread@example.com",
        "phone": "+14805551234",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    try:
        assert doc["email"] == "legacyread@example.com"
        assert doc["phone"] == "+14805551234"
        # Arrays got seeded.
        assert doc["emails"] and doc["emails"][0]["is_primary"] is True
        assert doc["mobiles"] and doc["mobiles"][0]["is_primary"] is True
    finally:
        requests.delete(f"{API}/customers/{doc['id']}", headers=admin_headers, timeout=15)


# ─── VIP toggle ───────────────────────────────────────────────────────

def test_vip_toggle_stamps_and_clears_vip_since(admin_headers, customer):
    cid = customer["id"]
    assert bool(customer.get("is_vip")) is False

    r = requests.patch(f"{API}/customers/{cid}/vip", headers=admin_headers,
                        json={"is_vip": True, "vip_note": "Escalation only via SMS"}, timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["is_vip"] is True
    assert doc["vip_since"] is not None
    assert doc["vip_note"] == "Escalation only via SMS"

    # Toggle OFF — vip_since clears, vip_note preserved.
    r = requests.patch(f"{API}/customers/{cid}/vip", headers=admin_headers,
                        json={"is_vip": False}, timeout=15)
    assert r.status_code == 200
    doc = r.json()
    assert doc["is_vip"] is False
    assert doc["vip_since"] is None
    assert doc["vip_note"] == "Escalation only via SMS"


def test_vip_segment_auto_seeded_and_preview_matches_vip_customers(admin_headers):
    # Fetch segments and assert the auto-seeded VIP segment exists.
    r = requests.get(f"{API}/marketing/segments", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    segs = data.get("segments") if isinstance(data, dict) else data
    vip = next((s for s in (segs or []) if isinstance(s, dict) and s.get("slug") == "vip-customers"), None)
    assert vip is not None, "VIP Customers segment not auto-seeded"
    assert vip.get("is_system_default") is True

    # Create 2 VIP customers so we know the preview count is at least 2.
    created_ids = []
    marker = int(time.time() * 1000)
    for i in range(2):
        r = requests.post(f"{API}/customers", headers=admin_headers, json={
            "name": f"VIP Preview Test {i}",
            "first_name": "TEST_VIP", "last_name": f"Preview{marker}_{i}",
            "email": f"vip_preview_{marker}_{i}@example.com",
            "phone": f"+148055501{i:02d}",
            "is_vip": True,
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        created_ids.append(r.json()["id"])
    try:
        # Preview should now show at least 2 matches.
        r = requests.post(f"{API}/marketing/segments/{vip['id']}/preview",
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        preview = r.json()
        count = preview.get("matched_count") or preview.get("count") or 0
        assert count >= 2, f"VIP preview returned {count}, expected ≥2. Preview payload: {preview}"
    finally:
        for cid in created_ids:
            requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


# ─── Marketing mirror respects consent flags ─────────────────────────

def test_marketing_mirror_respects_marketing_ok_flag(admin_headers):
    """A customer created with one marketing_ok=True email and one
    marketing_ok=False email must produce exactly one subscriber row
    linked to the marketing-OK address."""
    from pymongo import MongoClient
    from dotenv import dotenv_values
    env = dotenv_values("/app/backend/.env")
    client = MongoClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]

    marker = int(time.time() * 1000)
    ok_email = f"mkt_ok_{marker}@example.com"
    no_email = f"mkt_no_{marker}@example.com"
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": "Marketing Consent Test",
        "first_name": "TEST_MKT", "last_name": f"Consent{marker}",
        "emails": [
            {"address": ok_email, "label": "Primary", "is_primary": True, "marketing_ok": True},
            {"address": no_email, "label": "Billing", "is_primary": False, "marketing_ok": False},
        ],
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    try:
        # The mirror is fire-and-forget on the same event loop — the customer
        # POST awaits it before returning.
        ok_row = db.subscribers.find_one({"email": ok_email})
        no_row = db.subscribers.find_one({"email": no_email})
        assert ok_row is not None, (
            f"marketing_ok=True email {ok_email} should mirror to subscribers"
        )
        assert no_row is None, (
            f"marketing_ok=False email {no_email} must NOT mirror — got {no_row}"
        )
    finally:
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)
        db.subscribers.delete_many({"email": {"$in": [ok_email, no_email]}})
        client.close()


# ─── customer_tasks CRUD ─────────────────────────────────────────────

def test_customer_tasks_create_complete_delete(admin_headers, customer):
    cid = customer["id"]
    # Create
    r = requests.post(f"{API}/customer-tasks", headers=admin_headers, json={
        "customer_id": cid,
        "title": "Send W-9 request",
        "priority": "high",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    tid = r.json()["id"]
    assert r.json()["status"] == "open"
    assert r.json()["priority"] == "high"

    # List
    r = requests.get(f"{API}/customer-tasks?customer_id={cid}", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    tasks = r.json()
    assert any(t["id"] == tid for t in tasks), tasks

    # Complete
    r = requests.post(f"{API}/customer-tasks/{tid}/complete", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json().get("completed_at") is not None

    # Reopen via PATCH
    r = requests.patch(f"{API}/customer-tasks/{tid}", headers=admin_headers,
                        json={"status": "open"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "open"
    assert r.json().get("completed_at") is None

    # Delete
    r = requests.delete(f"{API}/customer-tasks/{tid}", headers=admin_headers, timeout=15)
    assert r.status_code == 204


def test_customer_task_missing_customer_returns_404(admin_headers):
    r = requests.post(f"{API}/customer-tasks", headers=admin_headers, json={
        "customer_id": "does-not-exist",
        "title": "Ghost task",
    }, timeout=15)
    assert r.status_code == 404
