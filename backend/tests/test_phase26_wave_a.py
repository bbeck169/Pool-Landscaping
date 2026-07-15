"""Phase 26 · Wave A tests — dispatcher, weather-reschedule, batch checks,
payroll CSV. Split by module below."""
import io
import time
from pathlib import Path
from unittest.mock import patch

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


# ═══════════════════════════════════════════════════════════════════════
# Module 26.1 — Auto-Dispatcher
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def three_techs_scenario(dbc):
    """Seed a synthetic set of 3 technicians + their existing jobs today.
    Yields: {tenant_id, techs, cleanup} — cleanup drops the seeded rows."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    tenant_id = t["id"]
    today = time.strftime("%Y-%m-%d")
    tag = f"p26test-{int(time.time())}"

    techs = [
        {"id": f"{tag}-tech-a", "user_id": f"{tag}-user-a",
          "name": "Tech A (close)", "lat": 33.55, "lng": -112.10},
        {"id": f"{tag}-tech-b", "user_id": f"{tag}-user-b",
          "name": "Tech B (far)",  "lat": 34.20, "lng": -113.50},
        {"id": f"{tag}-tech-c", "user_id": f"{tag}-user-c",
          "name": "Tech C (empty route)"},
    ]
    for te in techs:
        dbc.technicians.insert_one({**te, "tenant_id": tenant_id,
                                       "is_active": True,
                                       "email": f"{te['id']}@test.local"})

    # Tech A has 1 job about 5km from new job (33.55/-112.10 ≈ 5km from
    # new job at 33.60/-112.10).
    dbc.jobs.insert_many([
        {"id": f"{tag}-jobA1", "tenant_id": tenant_id,
          "technician_id": f"{tag}-tech-a",
          "scheduled_date": today,
          "site_lat": 33.55, "site_lng": -112.10, "status": "scheduled",
          "customer_id": None, "customer_name": "existing-A"},
        # Tech B has 1 job ~140km away.
        {"id": f"{tag}-jobB1", "tenant_id": tenant_id,
          "technician_id": f"{tag}-tech-b",
          "scheduled_date": today,
          "site_lat": 34.20, "site_lng": -113.50, "status": "scheduled",
          "customer_id": None, "customer_name": "existing-B"},
    ])

    # The NEW job we'll dispatch.
    new_job = {
        "id": f"{tag}-newjob", "tenant_id": tenant_id,
        "customer_id": None, "customer_name": "new-job",
        "scheduled_date": today, "status": "scheduled",
        "site_lat": 33.60, "site_lng": -112.10,
        "service_type": "landscape",
    }
    dbc.jobs.insert_one(new_job)

    yield {"tenant_id": tenant_id, "tag": tag, "new_job_id": new_job["id"],
            "tech_ids": [te["id"] for te in techs]}

    dbc.technicians.delete_many({"id": {"$regex": f"^{tag}-tech-"}})
    dbc.jobs.delete_many({"id": {"$regex": f"^{tag}-"}})
    dbc.weather_reschedule_events.delete_many(
        {"job_id": {"$regex": f"^{tag}-"}})
    dbc.dispatch_audit.delete_many({"job_id": {"$regex": f"^{tag}-"}})


def test_auto_assign_picks_closest_tech(admin_h, three_techs_scenario):
    """Tech A (5km) should beat Tech B (140km). Tech C empty-route bonuses
    zero distance but time_pressure_factor still weighs — should still win
    against far techs though."""
    s = three_techs_scenario
    r = requests.post(f"{API}/dispatch/auto-assign", headers=admin_h,
                        json={"job_id": s["new_job_id"]}, timeout=15).json()
    assert "reasoning" in r
    ranked = r["reasoning"]
    # Only our 3 test techs matter; filter to them.
    ours = [x for x in ranked if x["tech_id"] in s["tech_ids"]]
    assert len(ours) == 3
    # Cheapest amongst ours is A or C (both near 0).
    ours.sort(key=lambda x: x["cost"])
    assert ours[0]["tech_id"] in (f"{s['tag']}-tech-a",
                                       f"{s['tag']}-tech-c"), ours
    # B (far) must be last of our 3.
    assert ours[-1]["tech_id"] == f"{s['tag']}-tech-b"


def test_preview_does_not_assign(admin_h, three_techs_scenario, dbc):
    s = three_techs_scenario
    before = dbc.jobs.find_one({"id": s["new_job_id"]})
    r = requests.get(f"{API}/dispatch/preview",
                       params={"job_id": s["new_job_id"]},
                       headers=admin_h, timeout=15).json()
    assert "reasoning" in r and "would_assign_to" in r
    after = dbc.jobs.find_one({"id": s["new_job_id"]})
    assert after.get("technician_id") == before.get("technician_id"), \
        "preview must not mutate the job"


def test_reassign_writes_audit(admin_h, three_techs_scenario, dbc):
    s = three_techs_scenario
    target = f"{s['tag']}-user-b"
    r = requests.post(f"{API}/dispatch/reassign", headers=admin_h,
                        json={"job_id": s["new_job_id"],
                                "user_id": target},
                        timeout=15).json()
    assert r["assigned_to"] == target
    audit = dbc.dispatch_audit.find_one(
        {"job_id": s["new_job_id"], "new_user_id": target})
    assert audit is not None
    assert audit["by_user_id"]  # admin who did it


def test_auto_assign_on_create_setting_off(admin_h, dbc):
    """When setting is off, new jobs are NOT auto-assigned."""
    # Ensure off
    requests.put(f"{API}/dispatch/settings", headers=admin_h,
                    json={"auto_assign_on_create": False}, timeout=15)
    # Find a real customer
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    cust = dbc.customers.find_one({"tenant_id": t["id"]})
    r = requests.post(f"{API}/jobs", headers=admin_h, json={
        "customer_id": cust["id"], "title": "Auto-assign-off test",
        "job_type": "maintenance",
        "service_type": "landscape",
        "scheduled_date": time.strftime("%Y-%m-%d"), "price": 50,
    }, timeout=15).json()
    assert "id" in r, r
    assert not r.get("technician_id")
    assert not r.get("auto_assigned")
    dbc.jobs.delete_one({"id": r["id"]})


def test_role_gating_dispatch(tech_h, customer_h):
    for h in (tech_h, customer_h):
        r = requests.post(f"{API}/dispatch/auto-assign", headers=h,
                           json={"job_id": "x"}, timeout=10)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Module 26.2 — Weather-Triggered Auto-Reschedule
# ═══════════════════════════════════════════════════════════════════════

def _mock_forecast_rainy(*args, **kwargs):
    async def _fake():
        return {
            time.strftime("%Y-%m-%d"): {"rain_prob": 90, "wind_mph": 5},
            time.strftime("%Y-%m-%d",
                            time.localtime(time.time() + 86400)):
                {"rain_prob": 85, "wind_mph": 5},
            time.strftime("%Y-%m-%d",
                            time.localtime(time.time() + 86400 * 3)):
                {"rain_prob": 10, "wind_mph": 5},
        }
    return _fake()


@pytest.fixture
def rainy_jobs_scenario(dbc):
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    tenant_id = t["id"]
    tomorrow = time.strftime("%Y-%m-%d",
                                time.localtime(time.time() + 86400))
    tag = f"p26weather-{int(time.time())}"
    dbc.jobs.insert_many([
        {"id": f"{tag}-outdoor1", "tenant_id": tenant_id,
          "scheduled_date": tomorrow, "service_type": "landscape",
          "site_lat": 33.6, "site_lng": -112.1, "status": "scheduled",
          "customer_id": None, "customer_name": "outdoor-1"},
        {"id": f"{tag}-outdoor2", "tenant_id": tenant_id,
          "scheduled_date": tomorrow, "service_type": "landscape",
          "site_lat": 33.7, "site_lng": -112.2, "status": "scheduled",
          "customer_id": None, "customer_name": "outdoor-2"},
        # An indoor job — must be ignored.
        {"id": f"{tag}-indoor", "tenant_id": tenant_id,
          "scheduled_date": tomorrow, "service_type": "pool interior",
          "site_lat": 33.6, "site_lng": -112.1, "status": "scheduled",
          "customer_id": None, "customer_name": "indoor"},
    ])
    yield {"tenant_id": tenant_id, "tag": tag, "tomorrow": tomorrow}
    dbc.jobs.delete_many({"id": {"$regex": f"^{tag}-"}})
    dbc.weather_reschedule_events.delete_many(
        {"job_id": {"$regex": f"^{tag}-"}})


def _mock_forecast_installed(dbc, tenant_id, tomorrow):
    """Persist a test-forecast override on the tenant so the running
    server picks it up on the next weather_scan call."""
    dbc.tenants.update_one({"id": tenant_id},
        {"$set": {"settings.dispatch._test_forecast": {
            time.strftime("%Y-%m-%d"): {"rain_prob": 90, "wind_mph": 5},
            tomorrow: {"rain_prob": 85, "wind_mph": 5},
            time.strftime("%Y-%m-%d",
                            time.localtime(time.time() + 86400 * 3)):
                {"rain_prob": 10, "wind_mph": 5},
        }}})


def _mock_forecast_clear(dbc, tenant_id):
    dbc.tenants.update_one({"id": tenant_id},
        {"$unset": {"settings.dispatch._test_forecast": ""}})


def test_weather_scan_manual_mode_creates_proposals(admin_h,
                                                         rainy_jobs_scenario,
                                                         dbc):
    requests.put(f"{API}/dispatch/settings", headers=admin_h,
                    json={"weather_reschedule_mode": "manual",
                            "rain_threshold_pct": 60,
                            "wind_threshold_mph": 25}, timeout=15)
    _mock_forecast_installed(dbc, rainy_jobs_scenario["tenant_id"],
                                rainy_jobs_scenario["tomorrow"])
    try:
        r = requests.post(f"{API}/dispatch/weather-scan",
                            headers=admin_h, timeout=25).json()
        assert r["scanned"] >= 2, r
        ours = [e for e in r["events"]
                  if e["job_id"].startswith(rainy_jobs_scenario["tag"])]
        assert len(ours) == 2, ours
        for e in ours:
            assert e["status"] == "proposed"
            assert e["proposed_date"] != rainy_jobs_scenario["tomorrow"]
        # Jobs are NOT moved yet in manual mode.
        j = dbc.jobs.find_one(
            {"id": f"{rainy_jobs_scenario['tag']}-outdoor1"})
        assert j["scheduled_date"] == rainy_jobs_scenario["tomorrow"]
    finally:
        _mock_forecast_clear(dbc, rainy_jobs_scenario["tenant_id"])


def test_weather_scan_auto_mode_moves_jobs(admin_h, rainy_jobs_scenario,
                                                dbc):
    requests.put(f"{API}/dispatch/settings", headers=admin_h,
                    json={"weather_reschedule_mode": "auto"},
                    timeout=15)
    dbc.weather_reschedule_events.delete_many(
        {"job_id": {"$regex": f"^{rainy_jobs_scenario['tag']}-"}})
    _mock_forecast_installed(dbc, rainy_jobs_scenario["tenant_id"],
                                rainy_jobs_scenario["tomorrow"])
    try:
        r = requests.post(f"{API}/dispatch/weather-scan",
                            headers=admin_h, timeout=25).json()
        ours = [e for e in r["events"]
                  if e["job_id"].startswith(rainy_jobs_scenario["tag"])]
        assert all(e["status"] == "auto_applied" for e in ours), ours
        j = dbc.jobs.find_one(
            {"id": f"{rainy_jobs_scenario['tag']}-outdoor1"})
        assert j["scheduled_date"] != rainy_jobs_scenario["tomorrow"], \
            f"job not moved: {j['scheduled_date']}"
    finally:
        _mock_forecast_clear(dbc, rainy_jobs_scenario["tenant_id"])
        requests.put(f"{API}/dispatch/settings", headers=admin_h,
                        json={"weather_reschedule_mode": "manual"},
                        timeout=15)


def test_weather_scan_idempotent(admin_h, rainy_jobs_scenario, dbc):
    requests.put(f"{API}/dispatch/settings", headers=admin_h,
                    json={"weather_reschedule_mode": "manual"}, timeout=15)
    _mock_forecast_installed(dbc, rainy_jobs_scenario["tenant_id"],
                                rainy_jobs_scenario["tomorrow"])
    try:
        r1 = requests.post(f"{API}/dispatch/weather-scan",
                             headers=admin_h, timeout=25).json()
        r2 = requests.post(f"{API}/dispatch/weather-scan",
                             headers=admin_h, timeout=25).json()
        fresh_r1 = [e for e in r1["events"]
                      if e["job_id"].startswith(rainy_jobs_scenario["tag"])
                      and not e.get("skipped")]
        fresh_r2 = [e for e in r2["events"]
                      if e["job_id"].startswith(rainy_jobs_scenario["tag"])
                      and not e.get("skipped")]
        assert len(fresh_r1) >= 1
        assert len(fresh_r2) == 0, fresh_r2
    finally:
        _mock_forecast_clear(dbc, rainy_jobs_scenario["tenant_id"])


# ═══════════════════════════════════════════════════════════════════════
# Module 26.3 — Batch checks + payroll CSV
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def batch_bank_account(admin_h, dbc):
    r = requests.post(f"{API}/checks/bank-accounts", headers=admin_h, json={
        "nickname": "Batch Test " + str(int(time.time())),
        "bank_name": "Batch Bank",
        "routing_number": "222000246",
        "account_number": "5551234567",
        "next_check_number": 8001,
        "starting_balance": 50000.0,
    }, timeout=15).json()
    yield r
    dbc.checks.delete_many({"bank_account_id": r["id"]})
    dbc.check_batches.delete_many({"bank_account_id": r["id"]})
    dbc.bank_accounts.delete_one({"id": r["id"]})


@pytest.fixture(scope="module")
def batch_payee(admin_h, dbc):
    r = requests.post(f"{API}/checks/payees", headers=admin_h,
                        json={"name": "Batch Payee "
                                        + str(int(time.time())),
                                "kind": "vendor"}, timeout=15).json()
    yield r
    dbc.check_payees.delete_one({"id": r["id"]})


def test_batch_create_sequential_numbers(admin_h, batch_bank_account,
                                              batch_payee, dbc):
    lines = [{"payee_id": batch_payee["id"], "amount": 100 + i,
                "date": "2026-02-15", "memo": f"batch line {i}"}
              for i in range(5)]
    r = requests.post(f"{API}/checks/batch", headers=admin_h, json={
        "bank_account_id": batch_bank_account["id"], "checks": lines,
    }, timeout=15).json()
    assert r["check_count"] == 5
    assert r["total_amount"] == round(sum(100 + i for i in range(5)), 2)
    # Fetch each check + assert sequential unique numbers.
    checks = list(dbc.checks.find({"id": {"$in": r["check_ids"]}}))
    assert len(checks) == 5
    numbers = sorted(c["check_number"] for c in checks)
    assert numbers == list(range(numbers[0], numbers[0] + 5))
    # Cleanup
    dbc.checks.delete_many({"id": {"$in": r["check_ids"]}})
    dbc.check_batches.delete_one({"id": r["id"]})


def test_batch_print_returns_real_pdf(admin_h, batch_bank_account,
                                            batch_payee, dbc):
    lines = [{"payee_id": batch_payee["id"], "amount": 50,
                "date": "2026-02-15"} for _ in range(3)]
    b = requests.post(f"{API}/checks/batch", headers=admin_h, json={
        "bank_account_id": batch_bank_account["id"], "checks": lines,
    }, timeout=15).json()
    p = requests.post(f"{API}/checks/batch/{b['id']}/print",
                        headers=admin_h, timeout=25)
    assert p.status_code == 200
    assert p.headers.get("content-type", "").startswith("application/pdf")
    assert p.content[:4] == b"%PDF"
    assert len(p.content) > 5000
    assert p.headers.get("X-Batch-Check-Count") == "3"
    dbc.checks.delete_many({"id": {"$in": b["check_ids"]}})
    dbc.check_batches.delete_one({"id": b["id"]})


def test_payroll_csv_preview_and_execute(admin_h, batch_bank_account, dbc):
    # Create an existing payee that CSV row will match by name.
    existing_name = "Existing Payee " + str(int(time.time()))
    existing = requests.post(f"{API}/checks/payees", headers=admin_h,
                                 json={"name": existing_name,
                                         "kind": "employee"},
                                 timeout=15).json()
    csv_body = (
        "payee_name,amount,memo,date,category\n"
        f"{existing_name},1500.00,Payroll,2026-02-15,payroll\n"
        f"New Person A-{int(time.time())},1200.50,Payroll,2026-02-15,payroll\n"
        f"New Person B-{int(time.time())},1100.00,Payroll,2026-02-15,payroll\n"
    )
    files = {"csv_file": ("payroll.csv", csv_body, "text/csv")}
    # Preview (execute=False)
    r = requests.post(f"{API}/checks/payroll/import-csv"
                        f"?bank_account_id={batch_bank_account['id']}",
                        headers=admin_h, files=files, timeout=15).json()
    assert r["valid_count"] == 3
    assert r["warning_count"] == 0
    matched_rows = [x for x in r["preview"] if x["matched_payee_id"]]
    new_rows = [x for x in r["preview"] if x["will_create_payee"]]
    assert len(matched_rows) == 1
    assert len(new_rows) == 2

    # Execute
    r2 = requests.post(
        f"{API}/checks/payroll/import-csv"
        f"?bank_account_id={batch_bank_account['id']}&execute=true",
        headers=admin_h, files=files, timeout=25).json()
    assert r2["executed"] is True
    assert r2["batch"]["check_count"] == 3
    # 2 new payees now exist
    new_created = list(dbc.check_payees.find(
        {"tenant_id": batch_bank_account["tenant_id"]
            if "tenant_id" in batch_bank_account
            else dbc.bank_accounts.find_one(
                {"id": batch_bank_account["id"]})["tenant_id"],
          "name": {"$regex": "^New Person"}}))
    assert len(new_created) >= 2
    # Cleanup
    dbc.checks.delete_many(
        {"id": {"$in": r2["batch"]["check_ids"]}})
    dbc.check_batches.delete_one({"id": r2["batch"]["id"]})
    dbc.check_payees.delete_one({"id": existing["id"]})
    dbc.check_payees.delete_many({"name": {"$regex": "^New Person"}})


def test_payroll_csv_invalid_rows_flagged(admin_h, batch_bank_account):
    csv_body = (
        "payee_name,amount\n"
        ",100\n"                # missing name
        "OK Person,not-a-number\n"  # bad amount
        "OK Person 2,500\n"
    )
    files = {"csv_file": ("bad.csv", csv_body, "text/csv")}
    r = requests.post(
        f"{API}/checks/payroll/import-csv"
        f"?bank_account_id={batch_bank_account['id']}",
        headers=admin_h, files=files, timeout=15).json()
    assert r["can_execute"] is False
    assert r["warning_count"] == 2
    # Executing should be blocked.
    r2 = requests.post(
        f"{API}/checks/payroll/import-csv"
        f"?bank_account_id={batch_bank_account['id']}&execute=true",
        headers=admin_h, files=files, timeout=15)
    assert r2.status_code == 422


def test_batch_role_gating(tech_h, customer_h, batch_bank_account,
                                batch_payee):
    body = {"bank_account_id": batch_bank_account["id"],
             "checks": [{"payee_id": batch_payee["id"], "amount": 1.0,
                            "date": "2026-02-15"}]}
    for h in (tech_h, customer_h):
        r = requests.post(f"{API}/checks/batch", headers=h,
                           json=body, timeout=10)
        assert r.status_code == 403
