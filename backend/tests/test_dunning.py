"""Phase 22 · Dunning backend tests."""
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(_BE["MONGO_URL"])[_BE["DB_NAME"]]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def sunbelt_admin_h():
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt admin")


def _seed_invoice(dbc, days_past: int = 0,
                    tenant_slug: str = "aquaterra") -> str:
    """Insert an invoice-flavored quote doc directly. Returns id."""
    t = dbc.tenants.find_one({"slug": tenant_slug})
    c = dbc.customers.find_one({"tenant_id": t["id"],
                                  "email": {"$regex": ".+@.+"}})
    due = (datetime.now(timezone.utc)
             - timedelta(days=days_past)).date().isoformat()
    iid = "test-inv-" + str(int(time.time() * 1000))
    dbc.quotes.insert_one({
        "id": iid, "tenant_id": t["id"], "doc_type": "invoice",
        "title": "Test invoice", "status": "sent",
        "payment_status": "unpaid",
        "customer_id": c["id"], "customer_name": c["name"],
        "total": 250.0, "amount_paid": 0.0,
        "tax_rate": 0.0, "tax": 0.0, "subtotal": 250.0,
        "line_items": [{"description": "Service", "quantity": 1,
                          "unit_price": 250.0}],
        "due_date": due,
        "created_at": (datetime.now(timezone.utc)
                          - timedelta(days=days_past + 14)).isoformat(),
    })
    return iid


# ═══════════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════════

def test_default_settings_seeded_on_first_get(admin_h, dbc):
    dbc.dunning_settings.delete_many({"tenant_id":
        dbc.tenants.find_one({"slug": "aquaterra"})["id"]})
    r = requests.get(f"{API}/dunning/settings",
                      headers=admin_h, timeout=15).json()
    assert r["enabled"] is True
    ids = [s["id"] for s in r["stages"]]
    for req in ("pre_due_3d", "on_due_day", "past_due_7d",
                 "past_due_14d", "past_due_30d", "past_due_60d"):
        assert req in ids, f"default stage missing: {req}"
    assert r["escalation"]["at_risk_days"] == 30
    assert r["escalation"]["in_collections_days"] == 60


def test_put_settings_validates(admin_h):
    # Duplicate offset_days should be rejected
    r = requests.put(f"{API}/dunning/settings", headers=admin_h,
                      json={"stages": [
                          {"id": "a", "name": "A", "offset_days": 3,
                            "channels": ["email"], "body_template": "..."},
                          {"id": "b", "name": "B", "offset_days": 3,
                            "channels": ["email"], "body_template": "..."},
                      ]}, timeout=15)
    assert r.status_code == 400
    # Empty channels rejected
    r2 = requests.put(f"{API}/dunning/settings", headers=admin_h,
                       json={"stages": [
                           {"id": "a", "name": "A", "offset_days": 5,
                             "channels": [], "body_template": "..."},
                       ]}, timeout=15)
    assert r2.status_code == 400
    # Reset restores defaults
    r3 = requests.post(f"{API}/dunning/settings/reset-defaults",
                        headers=admin_h, timeout=15).json()
    assert "past_due_7d" in {s["id"] for s in r3["stages"]}


# ═══════════════════════════════════════════════════════════════════════
# Manual send + Twilio placeholder
# ═══════════════════════════════════════════════════════════════════════

def test_manual_send_reminder_persists(admin_h, dbc):
    iid = _seed_invoice(dbc, days_past=1)
    r = requests.post(f"{API}/dunning/invoices/{iid}/send-reminder",
                       headers=admin_h,
                       json={"stage_id": "on_due_day",
                              "channels": ["email"]},
                       timeout=30).json()
    assert r["count"] == 1
    assert r["reminders"][0]["channel"] == "email"
    # Real states from _send_email:
    #  - "sent" when Resend key is present AND recipient is deliverable
    #  - "pending_resend" when RESEND_API_KEY is unset
    #  - "failed" when Resend rejected the send (e.g., test-mode domain
    #     restrictions). All three are honest, persisted states — no
    #     silent mocking.
    assert r["reminders"][0]["status"] in {"sent", "pending_resend", "failed"}
    if r["reminders"][0]["status"] == "failed":
        assert r["reminders"][0]["error"]  # error reason must be surfaced
    # History reflects it
    h = requests.get(f"{API}/dunning/invoices/{iid}/history",
                      headers=admin_h, timeout=15).json()
    assert h["total"] >= 1
    assert any(x["stage_id"] == "on_due_day" for x in h["items"])
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


def test_sms_returns_pending_sms_when_key_absent(admin_h, dbc,
                                                        monkeypatch):
    iid = _seed_invoice(dbc, days_past=14)
    # Force-unset RC env vars in the running process is not possible
    # from an external request; instead assert the behavior via a direct
    # send with a stage that includes sms — if RC is not configured
    # (which is the default in this env), the SMS row must be "pending_sms".
    r = requests.post(f"{API}/dunning/invoices/{iid}/send-reminder",
                       headers=admin_h,
                       json={"stage_id": "past_due_14d"}, timeout=30).json()
    sms_rows = [x for x in r["reminders"] if x["channel"] == "sms"]
    if not sms_rows:
        pytest.skip("stage did not include sms — env config")
    row = sms_rows[0]
    # Either sent (RC keys present) or the honest pending_sms.
    assert row["status"] in {"sent", "pending_sms"}
    # If pending, never silently mocked — must expose a reason.
    if row["status"] == "pending_sms":
        assert row["error"] == "sms-not-configured"
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


# ═══════════════════════════════════════════════════════════════════════
# Scanner
# ═══════════════════════════════════════════════════════════════════════

def test_scanner_fires_and_is_idempotent(admin_h, dbc):
    """Invoice 8 days past due → past_due_7d must fire exactly once."""
    iid = _seed_invoice(dbc, days_past=8)
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    # Ensure clean slate for this stage on this invoice.
    dbc.dunning_reminders.delete_many({"invoice_id": iid})

    import asyncio
    from routers.dunning import run_dunning_scan
    r1 = asyncio.get_event_loop().run_until_complete(run_dunning_scan())
    fired1 = r1["total_fired"]
    fired_7d = list(dbc.dunning_reminders.find({
        "invoice_id": iid, "stage_id": "past_due_7d"}))
    assert len(fired_7d) >= 1, "past_due_7d did not fire"

    # Second scan should NOT create a duplicate for past_due_7d.
    r2 = asyncio.get_event_loop().run_until_complete(run_dunning_scan())
    fired_7d_after = list(dbc.dunning_reminders.find({
        "invoice_id": iid, "stage_id": "past_due_7d"}))
    assert len(fired_7d_after) == len(fired_7d), (
        "scanner re-fired past_due_7d — idempotency broken")

    # And status should have been auto-flipped sent → past_due.
    inv = dbc.quotes.find_one({"id": iid})
    assert inv["status"] == "past_due"

    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


def test_scanner_respects_pause(admin_h, dbc):
    iid = _seed_invoice(dbc, days_past=8)
    requests.post(f"{API}/dunning/pause/{iid}",
                   headers=admin_h, timeout=15)
    dbc.dunning_reminders.delete_many({"invoice_id": iid})
    import asyncio
    from routers.dunning import run_dunning_scan
    asyncio.get_event_loop().run_until_complete(run_dunning_scan())
    n = dbc.dunning_reminders.count_documents({"invoice_id": iid})
    assert n == 0, "scanner fired despite pause"
    # Resume + scan again → now it fires.
    requests.post(f"{API}/dunning/resume/{iid}",
                   headers=admin_h, timeout=15)
    asyncio.get_event_loop().run_until_complete(run_dunning_scan())
    n2 = dbc.dunning_reminders.count_documents({"invoice_id": iid})
    assert n2 >= 1
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


def test_scanner_escalation(admin_h, dbc):
    """31d past due → at_risk. 61d past due → in_collections."""
    # Ensure defaults so escalation thresholds are 30/60.
    requests.post(f"{API}/dunning/settings/reset-defaults",
                    headers=admin_h, timeout=15)
    iid_31 = _seed_invoice(dbc, days_past=31)
    iid_61 = _seed_invoice(dbc, days_past=61)
    import asyncio
    from routers.dunning import run_dunning_scan
    asyncio.get_event_loop().run_until_complete(run_dunning_scan())
    inv31 = dbc.quotes.find_one({"id": iid_31})
    inv61 = dbc.quotes.find_one({"id": iid_61})
    assert inv31["risk_status"] == "at_risk"
    assert inv61["risk_status"] == "in_collections"
    dbc.quotes.delete_many({"id": {"$in": [iid_31, iid_61]}})
    dbc.dunning_reminders.delete_many(
        {"invoice_id": {"$in": [iid_31, iid_61]}})


# ═══════════════════════════════════════════════════════════════════════
# Queue + AR aging
# ═══════════════════════════════════════════════════════════════════════

def test_queue_lists_upcoming(admin_h, dbc):
    # Invoice with due date 2 days in the future → pre_due_3d should NOT
    # fire yet (needs 3 days ahead). But invoice with due date +3 days ahead
    # should show pre_due_3d today (fire_date == today).
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    c = dbc.customers.find_one({"tenant_id": tenant["id"]})
    due = (datetime.now(timezone.utc)
             + timedelta(days=3)).date().isoformat()
    iid = "queue-" + str(int(time.time() * 1000))
    dbc.quotes.insert_one({
        "id": iid, "tenant_id": tenant["id"], "doc_type": "invoice",
        "status": "sent", "payment_status": "unpaid",
        "customer_id": c["id"], "customer_name": c["name"],
        "total": 100.0, "amount_paid": 0.0,
        "due_date": due,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    q = requests.get(f"{API}/dunning/queue?days=10",
                      headers=admin_h, timeout=15).json()
    assert any(x["invoice_id"] == iid for x in q["items"])
    dbc.quotes.delete_one({"id": iid})


def test_ar_aging_analytics(admin_h, dbc):
    # Seed 4 invoices across each bucket. Then assert the endpoint's
    # aggregate values increase by at least the seeded amounts.
    before = requests.get(f"{API}/dunning/analytics/ar-aging",
                           headers=admin_h, timeout=15).json()
    ids = [
        _seed_invoice(dbc, days_past=-1),   # current  (due tomorrow)
        _seed_invoice(dbc, days_past=15),   # aging_30
        _seed_invoice(dbc, days_past=45),   # aging_60
        _seed_invoice(dbc, days_past=95),   # aging_90
    ]
    after = requests.get(f"{API}/dunning/analytics/ar-aging",
                          headers=admin_h, timeout=15).json()
    for k in ("current", "aging_30", "aging_60", "aging_90", "aging_total"):
        assert k in after
    # Each bucket should have grown by at least $250.
    assert after["current"] - before["current"] >= 250 - 0.5
    assert after["aging_30"] - before["aging_30"] >= 250 - 0.5
    assert after["aging_60"] - before["aging_60"] >= 250 - 0.5
    assert after["aging_90"] - before["aging_90"] >= 250 - 0.5
    assert after["aging_total"] - before["aging_total"] >= 1000 - 1
    dbc.quotes.delete_many({"id": {"$in": ids}})


# ═══════════════════════════════════════════════════════════════════════
# Isolation + role gating
# ═══════════════════════════════════════════════════════════════════════

def test_tenant_isolation(admin_h, sunbelt_admin_h, dbc):
    iid = _seed_invoice(dbc, days_past=5)
    r = requests.get(f"{API}/dunning/invoices/{iid}/history",
                      headers=sunbelt_admin_h, timeout=15)
    assert r.status_code == 404
    dbc.quotes.delete_one({"id": iid})


def test_role_gating(tech_h, customer_h, dbc):
    iid = _seed_invoice(dbc, days_past=1)
    for h in (tech_h, customer_h):
        for path in ("/dunning/settings", "/dunning/queue",
                      "/dunning/analytics/ar-aging",
                      f"/dunning/invoices/{iid}/history"):
            r = requests.get(f"{API}{path}", headers=h, timeout=15)
            assert r.status_code == 403, (
                f"{h!r} got {r.status_code} on GET {path}")
        r2 = requests.post(f"{API}/dunning/invoices/{iid}/send-reminder",
                            headers=h, json={"stage_id": "on_due_day"},
                            timeout=15)
        assert r2.status_code == 403
    dbc.quotes.delete_one({"id": iid})


# ═══════════════════════════════════════════════════════════════════════
# Fix 1 · Dev test-hook driven scanner tests
# ═══════════════════════════════════════════════════════════════════════

def _run_scan(admin_h):
    r = requests.post(f"{API}/dunning/_test/run-scan-now",
                       headers=admin_h, timeout=60)
    assert r.status_code == 200, (
        f"test hook returned {r.status_code}: {r.text[:200]}")
    return r.json()


def test_dunning_test_hook_available(admin_h):
    r = _run_scan(admin_h)
    for k in ("ran", "reminders_created", "invoices_escalated",
              "scanned_at", "tenants"):
        assert k in r
    assert r["ran"] is True


def test_scanner_creates_reminder_at_stage(admin_h, dbc):
    # Ensure defaults (past_due_7d at offset 7).
    requests.post(f"{API}/dunning/settings/reset-defaults",
                   headers=admin_h, timeout=15)
    iid = _seed_invoice(dbc, days_past=8)
    dbc.dunning_reminders.delete_many({"invoice_id": iid})
    _run_scan(admin_h)
    n = dbc.dunning_reminders.count_documents({
        "invoice_id": iid, "stage_id": "past_due_7d"})
    assert n == 1, f"past_due_7d should have fired once, got {n}"
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


def test_scanner_idempotency(admin_h, dbc):
    requests.post(f"{API}/dunning/settings/reset-defaults",
                   headers=admin_h, timeout=15)
    iid = _seed_invoice(dbc, days_past=8)
    dbc.dunning_reminders.delete_many({"invoice_id": iid})
    _run_scan(admin_h)
    n1 = dbc.dunning_reminders.count_documents({"invoice_id": iid})
    _run_scan(admin_h)
    n2 = dbc.dunning_reminders.count_documents({"invoice_id": iid})
    assert n1 == n2, (
        f"second scan created duplicates: before={n1}, after={n2}")
    assert n1 >= 1
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


def test_scanner_escalates_at_risk_at_30d(admin_h, dbc):
    requests.post(f"{API}/dunning/settings/reset-defaults",
                   headers=admin_h, timeout=15)
    iid = _seed_invoice(dbc, days_past=32)
    _run_scan(admin_h)
    inv = dbc.quotes.find_one({"id": iid})
    assert inv["risk_status"] == "at_risk", (
        f"expected at_risk at 32d past due, got {inv.get('risk_status')}")
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


def test_scanner_escalates_in_collections_at_60d(admin_h, dbc):
    requests.post(f"{API}/dunning/settings/reset-defaults",
                   headers=admin_h, timeout=15)
    iid = _seed_invoice(dbc, days_past=62)
    _run_scan(admin_h)
    inv = dbc.quotes.find_one({"id": iid})
    assert inv["risk_status"] == "in_collections", (
        f"expected in_collections at 62d past due, got "
        f"{inv.get('risk_status')}")
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


def test_scanner_skips_paused_invoice(admin_h, dbc):
    requests.post(f"{API}/dunning/settings/reset-defaults",
                   headers=admin_h, timeout=15)
    iid = _seed_invoice(dbc, days_past=8)
    dbc.dunning_reminders.delete_many({"invoice_id": iid})
    requests.post(f"{API}/dunning/pause/{iid}",
                   headers=admin_h, timeout=15)
    _run_scan(admin_h)
    n_after_pause = dbc.dunning_reminders.count_documents(
        {"invoice_id": iid})
    assert n_after_pause == 0, (
        f"paused invoice should NOT get reminders, got {n_after_pause}")
    # Resume + rescan → now it fires.
    requests.post(f"{API}/dunning/resume/{iid}",
                   headers=admin_h, timeout=15)
    _run_scan(admin_h)
    n_after_resume = dbc.dunning_reminders.count_documents(
        {"invoice_id": iid})
    assert n_after_resume >= 1
    dbc.quotes.delete_one({"id": iid})
    dbc.dunning_reminders.delete_many({"invoice_id": iid})


# ═══════════════════════════════════════════════════════════════════════
# Fix 2 · Queue response alias
# ═══════════════════════════════════════════════════════════════════════

def test_queue_has_fire_at_alias(admin_h, dbc):
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    c = dbc.customers.find_one({"tenant_id": tenant["id"]})
    due = (datetime.now(timezone.utc)
             + timedelta(days=3)).date().isoformat()
    iid = "queue-alias-" + str(int(time.time() * 1000))
    dbc.quotes.insert_one({
        "id": iid, "tenant_id": tenant["id"], "doc_type": "invoice",
        "status": "sent", "payment_status": "unpaid",
        "customer_id": c["id"], "customer_name": c["name"],
        "total": 100.0, "amount_paid": 0.0,
        "due_date": due,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    q = requests.get(f"{API}/dunning/queue?days=10",
                      headers=admin_h, timeout=15).json()
    # Envelope shape preserved
    for k in ("items", "total", "window_days"):
        assert k in q
    row = next((x for x in q["items"] if x["invoice_id"] == iid), None)
    assert row is not None
    # Both canonical + deprecated alias present with identical dates
    assert "fire_date" in row
    assert "fire_at" in row
    assert row["fire_at"].startswith(row["fire_date"])
    # fire_at is a full ISO datetime
    datetime.fromisoformat(row["fire_at"])
    dbc.quotes.delete_one({"id": iid})
