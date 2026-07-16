"""Phase 51 backend tests: seed closeout, recurring jobs, CFO finance wiring."""
import os
import datetime as dt
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    # fallback: read frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE}/api"
TIMEOUT = 30

CREDS = {
    "admin": ("admin@aquaterra.com", "password123"),
    "super": ("super@aquaterra.com", "password123"),
    "tech": ("mike@aquaterra.com", "password123"),
    "landscaper": ("landscaper@aquaterra.com", "password123"),
}


def _login(role):
    email, pw = CREDS[role]
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {role} failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _hdr(role):
    return {"Authorization": f"Bearer {_login(role)}"}


@pytest.fixture(scope="module")
def admin_h():
    return _hdr("admin")


@pytest.fixture(scope="module")
def tech_h():
    return _hdr("tech")


@pytest.fixture(scope="module")
def landscaper_h():
    return _hdr("landscaper")


# ---------------- 51.0 seed closeout ----------------

def _find_customer_by_name(headers, name):
    r = requests.get(f"{API}/customers", headers=headers, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    for c in items or []:
        if c.get("name", "").lower() == name.lower():
            return c
    return None


@pytest.mark.parametrize("name", ["Jennifer Carson", "Robert Blake"])
def test_prior_readings_seeded(admin_h, name):
    c = _find_customer_by_name(admin_h, name)
    assert c is not None, f"Customer {name} not found"
    cid = c["id"]
    r = requests.get(f"{API}/service-reports/last-readings", params={"customer_id": cid}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    recent = data.get("recent_readings") or data.get("recent") or {}
    # keys: ph, free_chlorine, combined_chlorine, total_alkalinity, cyanuric_acid
    keys = ["ph", "free_chlorine", "combined_chlorine", "total_alkalinity", "cyanuric_acid"]
    for k in keys:
        assert k in recent, f"{name}: missing key {k} in recent_readings: {list(recent.keys())}"
        assert len(recent[k]) >= 2, f"{name}: key {k} has {len(recent[k])} entries, expected >=2"


def test_today_filter_iso_datetime(landscaper_h):
    r = requests.get(f"{API}/timeclock/mine-jobs-today", headers=landscaper_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    # We just need it to return 200 successfully - the ability to find jobs with ISO dates
    data = r.json()
    assert isinstance(data, (list, dict))


# ---------------- 51.I Recurring Jobs ----------------

def _create_customer(admin_h, suffix):
    r = requests.post(
        f"{API}/customers",
        headers=admin_h,
        json={"name": f"TEST_RJ_{suffix}", "email": f"test_rj_{suffix}@t.com", "phone": "555-0001"},
        timeout=TIMEOUT,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def rj_customer_id(admin_h):
    return _create_customer(admin_h, "main")


def test_recurring_create(admin_h, rj_customer_id):
    body = {
        "customer_id": rj_customer_id,
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "day_of_week": 2,
        "start_date": "2026-02-01",
        "price_cents": 13000,
        "active": True,
    }
    r = requests.post(f"{API}/recurring-jobs", headers=admin_h, json=body, timeout=TIMEOUT)
    assert r.status_code in (200, 201), r.text
    j = r.json()
    assert "id" in j
    assert j.get("customer_name")  # auto-filled


def test_recurring_list(admin_h, tech_h):
    r = requests.get(f"{API}/recurring-jobs", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "items" in j and "count" in j
    if j["items"]:
        assert "upcoming" in j["items"][0]
        assert isinstance(j["items"][0]["upcoming"], list)
    # tech role gets 403
    r2 = requests.get(f"{API}/recurring-jobs", headers=tech_h, timeout=TIMEOUT)
    assert r2.status_code == 403, f"tech expected 403 got {r2.status_code}"


def test_recurring_generate_idempotent(admin_h):
    cid = _create_customer(admin_h, "gen1")
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=admin_h,
        json={
            "customer_id": cid,
            "service_type": "Weekly Pool Service",
            "frequency": "weekly",
            "day_of_week": 2,
            "start_date": "2026-01-01",
            "price_cents": 13000,
            "active": True,
        },
        timeout=TIMEOUT,
    )
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    through = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    r1 = requests.post(f"{API}/recurring-jobs/{rid}/generate", params={"through": through}, headers=admin_h, timeout=TIMEOUT)
    assert r1.status_code in (200, 201), r1.text
    j1 = r1.json()
    assert "inserted" in j1 and "skipped" in j1 and "dates" in j1
    r2 = requests.post(f"{API}/recurring-jobs/{rid}/generate", params={"through": through}, headers=admin_h, timeout=TIMEOUT)
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["inserted"] == 0, f"second call inserted {r2.json()['inserted']}, expected 0"


def test_recurring_validation(admin_h, rj_customer_id):
    # custom without interval_days
    r = requests.post(f"{API}/recurring-jobs", headers=admin_h, json={
        "customer_id": rj_customer_id, "service_type": "X", "frequency": "custom",
        "start_date": "2026-02-01", "price_cents": 100, "active": True,
    }, timeout=TIMEOUT)
    assert r.status_code == 422, f"custom no interval expected 422 got {r.status_code} {r.text}"
    # weekly without day_of_week
    r = requests.post(f"{API}/recurring-jobs", headers=admin_h, json={
        "customer_id": rj_customer_id, "service_type": "X", "frequency": "weekly",
        "start_date": "2026-02-01", "price_cents": 100, "active": True,
    }, timeout=TIMEOUT)
    assert r.status_code == 422, f"weekly no dow expected 422 got {r.status_code} {r.text}"
    # monthly without day_of_month
    r = requests.post(f"{API}/recurring-jobs", headers=admin_h, json={
        "customer_id": rj_customer_id, "service_type": "X", "frequency": "monthly",
        "start_date": "2026-02-01", "price_cents": 100, "active": True,
    }, timeout=TIMEOUT)
    assert r.status_code == 422, f"monthly no dom expected 422 got {r.status_code} {r.text}"


def test_recurring_sunday_skip(admin_h):
    cid1 = _create_customer(admin_h, "sun_skip")
    r = requests.post(f"{API}/recurring-jobs", headers=admin_h, json={
        "customer_id": cid1, "service_type": "Sun Svc", "frequency": "weekly",
        "day_of_week": 6, "start_date": "2026-01-01", "price_cents": 100, "active": True,
        "allow_sunday": False,
    }, timeout=TIMEOUT)
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    through = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    r1 = requests.post(f"{API}/recurring-jobs/{rid}/generate", params={"through": through}, headers=admin_h, timeout=TIMEOUT)
    assert r1.status_code in (200, 201), r1.text
    assert r1.json()["inserted"] == 0, f"sunday skip expected 0 inserted, got {r1.json()}"

    cid2 = _create_customer(admin_h, "sun_allow")
    r = requests.post(f"{API}/recurring-jobs", headers=admin_h, json={
        "customer_id": cid2, "service_type": "Sun Svc", "frequency": "weekly",
        "day_of_week": 6, "start_date": "2026-01-01", "price_cents": 100, "active": True,
        "allow_sunday": True,
    }, timeout=TIMEOUT)
    assert r.status_code in (200, 201), r.text
    rid2 = r.json()["id"]
    r2 = requests.post(f"{API}/recurring-jobs/{rid2}/generate", params={"through": through}, headers=admin_h, timeout=TIMEOUT)
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["inserted"] > 0, f"sunday allow expected >0 inserted, got {r2.json()}"


def test_recurring_patch_delete(admin_h):
    cid = _create_customer(admin_h, "patch_del")
    r = requests.post(f"{API}/recurring-jobs", headers=admin_h, json={
        "customer_id": cid, "service_type": "X", "frequency": "weekly",
        "day_of_week": 1, "start_date": "2026-02-01", "price_cents": 100, "active": True,
    }, timeout=TIMEOUT)
    rid = r.json()["id"]
    # PATCH pause
    rp = requests.patch(f"{API}/recurring-jobs/{rid}", headers=admin_h, json={"active": False}, timeout=TIMEOUT)
    assert rp.status_code == 200, rp.text
    assert rp.json().get("active") is False
    # DELETE soft
    rd = requests.delete(f"{API}/recurring-jobs/{rid}", headers=admin_h, timeout=TIMEOUT)
    assert rd.status_code in (200, 204), rd.text
    # Should still be queryable via direct GET
    rg = requests.get(f"{API}/recurring-jobs/{rid}", headers=admin_h, timeout=TIMEOUT)
    if rg.status_code == 200:
        assert rg.json().get("active") is False


# ---------------- 51.K CFO ----------------

def test_cfo_cogs(admin_h, tech_h):
    r = requests.get(f"{API}/cfo/cogs", params={"year": 2026, "month": 2}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ["materials_cents", "labor_cents", "equipment_cents", "total_cents"]:
        assert k in j, f"missing {k}"
        assert isinstance(j[k], int), f"{k} not int: {type(j[k])}"
    assert j.get("mocked") is False, f"mocked should be False, got {j.get('mocked')}"
    # tech 403
    r2 = requests.get(f"{API}/cfo/cogs", params={"year": 2026, "month": 2}, headers=tech_h, timeout=TIMEOUT)
    assert r2.status_code == 403


def test_cfo_ap_aging(admin_h):
    r = requests.get(f"{API}/cfo/ap-aging", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ["current_cents", "1_30_cents", "31_60_cents", "61_90_cents", "over_90_cents", "total_open_cents", "bill_ids"]:
        assert k in j, f"missing key {k}, keys={list(j.keys())}"
    assert j.get("mocked") is False
    assert j["total_open_cents"] > 0, f"total_open_cents={j['total_open_cents']}, expected >0 after seed"


def test_cfo_payroll(admin_h):
    r = requests.get(f"{API}/cfo/payroll", params={"period": "2026-02"}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ["total_cents", "employees", "employee_count"]:
        assert k in j, f"missing {k}"
    assert j.get("mocked") is False
    assert isinstance(j["employees"], list)
    for emp in j["employees"]:
        for k in ["user_id", "name", "hourly_rate_cents", "minutes", "cost_cents"]:
            assert k in emp, f"employee missing {k}"


def test_cfo_bills_crud(admin_h):
    body = {"vendor_name": "Test Vendor", "bill_date": "2026-01-15", "due_date": "2026-02-15", "amount_cents": 50000, "status": "open"}
    r = requests.post(f"{API}/cfo/bills", headers=admin_h, json=body, timeout=TIMEOUT)
    assert r.status_code in (200, 201), r.text
    bid = r.json()["id"]
    # LIST
    rl = requests.get(f"{API}/cfo/bills", headers=admin_h, timeout=TIMEOUT)
    assert rl.status_code == 200
    items = rl.json().get("items", rl.json())
    ids = [i.get("id") for i in items] if isinstance(items, list) else []
    assert bid in ids
    # PATCH
    rp = requests.patch(f"{API}/cfo/bills/{bid}", headers=admin_h, json={"status": "paid", "paid_amount_cents": 50000}, timeout=TIMEOUT)
    assert rp.status_code in (200, 204), rp.text
    # DELETE
    rd = requests.delete(f"{API}/cfo/bills/{bid}", headers=admin_h, timeout=TIMEOUT)
    assert rd.status_code in (200, 204), rd.text


def test_cfo_qna_ap_aging_context(admin_h):
    r = requests.post(f"{API}/cfo/qna", headers=admin_h, json={"question": "What is my AP aging?"}, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "answer" in j
    ctx = j.get("context") or {}
    mocked_fields = ctx.get("mocked_fields") or []
    assert "ap_aging" not in mocked_fields, f"ap_aging still in mocked_fields: {mocked_fields}"


def test_users_hourly_rate_cents(admin_h):
    # /api/users doesn't exist in this codebase; /api/team exposes the same info
    r = requests.get(f"{API}/team", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    users = data.get("items") if isinstance(data, dict) else data
    by_email = {u.get("email"): u for u in users if u.get("email")}
    mike = by_email.get("mike@aquaterra.com")
    ls = by_email.get("landscaper@aquaterra.com")
    assert mike is not None and ls is not None
    assert mike.get("hourly_rate_cents") == 2500, f"mike hourly_rate_cents={mike.get('hourly_rate_cents')}"
    assert ls.get("hourly_rate_cents") == 3000, f"landscaper hourly_rate_cents={ls.get('hourly_rate_cents')}"
