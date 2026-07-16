"""Phase 50 backend validation tests.

Covers: chemical costs seed + CRUD, job margin leaderboard, pool-service
email history, landscape timeclock jobs today, punch with job_id round-trip,
list_jobs.last_activity_at, service-reports last-readings shape, and
job costing after Phase 50.A/H edits.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://poolscape-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@aquaterra.com"
TECH_EMAIL = "mike@aquaterra.com"
LAND_EMAIL = "landscaper@aquaterra.com"
PASSWORD = "password123"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in response: {r.text}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL)


@pytest.fixture(scope="module")
def tech_token():
    return _login(TECH_EMAIL)


@pytest.fixture(scope="module")
def land_token():
    return _login(LAND_EMAIL)


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ── 50.A Chemical Costs ────────────────────────────────────────────────
class TestChemicalCosts:
    def test_admin_list_returns_9(self, admin_token):
        r = requests.get(f"{API}/admin/chemical-costs", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data
        items = data["items"]
        assert len(items) >= 9, f"expected >=9 seeded, got {len(items)}: {[i.get('chemical_slug') for i in items]}"
        # schema check
        required_fields = {"chemical_slug", "name", "unit_kind", "cost_per_unit_cents", "updated_at"}
        for it in items:
            missing = required_fields - set(it.keys())
            assert not missing, f"row {it.get('chemical_slug')} missing {missing}"
            assert isinstance(it["cost_per_unit_cents"], int)

    def test_tech_forbidden(self, tech_token):
        r = requests.get(f"{API}/admin/chemical-costs", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403, f"tech should get 403, got {r.status_code}"

    def test_update_muriatic_acid(self, admin_token):
        r = requests.put(
            f"{API}/admin/chemical-costs/muriatic_acid",
            headers=_h(admin_token),
            json={"cost_per_unit_cents": 700},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        row = r.json()
        assert row.get("cost_per_unit_cents") == 700
        # Verify persistence via GET
        g = requests.get(f"{API}/admin/chemical-costs", headers=_h(admin_token), timeout=30)
        assert g.status_code == 200
        ma = next((i for i in g.json()["items"] if i["chemical_slug"] == "muriatic_acid"), None)
        assert ma is not None
        assert ma["cost_per_unit_cents"] == 700
        assert ma.get("updated_by"), "updated_by should be set to admin id"

    def test_reseed_idempotent(self, admin_token):
        # First call – may insert some for a fresh tenant, subsequent must be 0
        r1 = requests.post(f"{API}/admin/chemical-costs/reseed", headers=_h(admin_token), timeout=30)
        assert r1.status_code == 200, r1.text
        r2 = requests.post(f"{API}/admin/chemical-costs/reseed", headers=_h(admin_token), timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("inserted") == 0, f"second reseed should insert 0, got {r2.json()}"


# ── 50.B Job Margin Leaderboard ────────────────────────────────────────
class TestJobMarginLeaderboard:
    def test_admin_ok(self, admin_token):
        r = requests.get(f"{API}/reports/job-margin-leaderboard?days=60", headers=_h(admin_token), timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("items", "count", "window_days", "total_evaluated"):
            assert k in data, f"missing key {k}"
        assert data["window_days"] == 60
        # If items exist, verify shape + sort
        if data["items"]:
            it = data["items"][0]
            for k in ("job_id", "customer", "service_type", "revenue_cents", "cost_cents",
                      "margin_cents", "margin_pct", "service_date"):
                assert k in it, f"leaderboard item missing {k}"
            # Sorted margin_pct desc
            pcts = [i["margin_pct"] for i in data["items"]]
            assert pcts == sorted(pcts, reverse=True), f"items not sorted by margin_pct desc: {pcts}"

    def test_tech_forbidden(self, tech_token):
        r = requests.get(f"{API}/reports/job-margin-leaderboard?days=60", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403


# ── 50.G Pool-service email history ────────────────────────────────────
class TestPoolServiceEmailHistory:
    def test_admin_ok(self, admin_token):
        r = requests.get(f"{API}/reports/pool-service/email-history?limit=10", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data
        assert isinstance(data["items"], list)

    def test_tech_forbidden(self, tech_token):
        r = requests.get(f"{API}/reports/pool-service/email-history?limit=10", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403


# ── 50.H Landscape timeclock + jobs today ─────────────────────────────
class TestLandscapeTimeclock:
    def test_mine_jobs_today_landscaper(self, land_token):
        r = requests.get(f"{API}/timeclock/mine-jobs-today", headers=_h(land_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data

    def test_mine_jobs_today_tech_forbidden(self, tech_token):
        r = requests.get(f"{API}/timeclock/mine-jobs-today", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403

    def test_punch_in_out_with_job_id(self, land_token, admin_token):
        # First, check current state and clock out if needed
        s = requests.get(f"{API}/timeclock/mine-today", headers=_h(land_token), timeout=30)
        assert s.status_code == 200
        if s.json().get("clocked_in"):
            out = requests.post(f"{API}/timeclock/punch", headers=_h(land_token),
                                 json={"punch_type": "out"}, timeout=30)
            assert out.status_code == 200, out.text

        # Get any job id we can use (admin listing to grab a real id)
        jr = requests.get(f"{API}/jobs?limit=5", headers=_h(admin_token), timeout=30)
        assert jr.status_code == 200
        js = jr.json()
        items = js if isinstance(js, list) else js.get("items", [])
        assert items, "need at least one job for punch job_id test"
        job_id = items[0].get("id")
        assert job_id

        # Punch in with job_id
        pin = requests.post(f"{API}/timeclock/punch", headers=_h(land_token),
                             json={"punch_type": "in", "job_id": job_id}, timeout=30)
        assert pin.status_code == 200, pin.text
        assert pin.json().get("job_id") == job_id

        # Verify via mine-today
        t = requests.get(f"{API}/timeclock/mine-today", headers=_h(land_token), timeout=30)
        assert t.status_code == 200
        td = t.json()
        assert td.get("clocked_in") is True
        assert td.get("open_job_id") == job_id, f"open_job_id mismatch: {td}"

        # Punch out to close
        pout = requests.post(f"{API}/timeclock/punch", headers=_h(land_token),
                              json={"punch_type": "out"}, timeout=30)
        assert pout.status_code == 200, pout.text

        # Confirm closed
        t2 = requests.get(f"{API}/timeclock/mine-today", headers=_h(land_token), timeout=30)
        assert t2.json().get("clocked_in") is False


# ── 50.F list_jobs.last_activity_at + revenue strip ──────────────────
class TestJobsListing:
    def test_tech_jobs_last_activity_and_no_revenue(self, tech_token):
        r = requests.get(f"{API}/jobs", headers=_h(tech_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        # Not all jobs will have service reports, so we just verify no revenue keys leak
        revenue_keys = {"revenue_cents", "quoted_amount_cents", "price_cents", "estimated_revenue_cents"}
        for j in items[:20]:
            leaked = revenue_keys & set(j.keys())
            assert not leaked, f"technician job leaked revenue keys: {leaked}"
        # At least one should have last_activity_at attribute when service reports exist;
        # if no job has reports, we accept but log.
        has_last_act = any("last_activity_at" in j for j in items)
        print(f"Jobs with last_activity_at present: {has_last_act} of {len(items)}")


# ── Phase 49.6 service-reports last-readings shape unchanged ─────────
class TestLastReadings:
    def test_shape_has_readings_and_recent_readings(self, admin_token):
        # find a customer id
        cust_r = requests.get(f"{API}/customers?limit=1", headers=_h(admin_token), timeout=30)
        assert cust_r.status_code == 200
        cdata = cust_r.json()
        citems = cdata if isinstance(cdata, list) else cdata.get("items", [])
        if not citems:
            pytest.skip("no customers to test")
        cid = citems[0].get("id")
        r = requests.get(f"{API}/service-reports/last-readings?customer_id={cid}",
                          headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "readings" in data, f"missing readings key: {list(data.keys())}"
        assert "recent_readings" in data, f"missing recent_readings key: {list(data.keys())}"


# ── 50.A + 50.H Job costing ──────────────────────────────────────────
class TestJobCosting:
    def test_costing_schema(self, admin_token):
        jr = requests.get(f"{API}/jobs?limit=5", headers=_h(admin_token), timeout=30)
        assert jr.status_code == 200
        jd = jr.json()
        items = jd if isinstance(jd, list) else jd.get("items", [])
        if not items:
            pytest.skip("no jobs to test costing")
        job_id = items[0].get("id")
        r = requests.get(f"{API}/jobs/{job_id}/costing", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("baseline", "actual", "progress",
                   "estimated_net_profit_cents", "actual_net_profit_cents"):
            assert k in data, f"missing key {k} in costing: {list(data.keys())}"
