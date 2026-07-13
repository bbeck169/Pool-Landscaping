"""Phase 15B — Advanced analytics + onboarding wizard."""
import os
from pathlib import Path

import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL must be set"
ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ─── Analytics ────────────────────────────────────────────────────────────
class TestAnalytics:
    def test_overview_shape(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/analytics/overview", headers=h, timeout=15)
        assert r.status_code == 200
        data = r.json()
        for k in ("this_month_revenue", "last_month_revenue", "mom_change_pct",
                  "cac", "avg_ltv", "active_customers", "new_customers_this_month"):
            assert k in data, f"missing {k}"

    def test_customer_ltv_shape_and_tier(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/analytics/customer-ltv", headers=h, timeout=15).json()
        assert "rows" in r and "tier_counts" in r
        assert set(r["tier_counts"].keys()) == {"platinum", "gold", "silver", "bronze"}
        if r["rows"]:
            row = r["rows"][0]
            assert "customer_name" in row
            assert row["tier"] in ("platinum", "gold", "silver", "bronze")
            # Sorted descending by revenue
            revenues = [x["revenue"] for x in r["rows"]]
            assert revenues == sorted(revenues, reverse=True)

    def test_churn_risk_scoring(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/analytics/churn-risk", headers=h, timeout=15).json()
        assert "rows" in r and "band_counts" in r
        assert set(r["band_counts"].keys()) == {"high", "medium", "low"}
        for row in r["rows"]:
            assert 0 <= row["risk_score"] <= 100
            assert row["band"] in ("high", "medium", "low")
            assert "factors" in row

    def test_tech_productivity_matrix(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/analytics/tech-productivity", headers=h, timeout=15).json()
        assert "matrix" in r
        assert r["weekdays"] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for row in r["matrix"]:
            assert len(row["cells"]) == 7

    def test_revenue_anomalies_series(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/analytics/revenue-anomalies?days=60", headers=h, timeout=15).json()
        assert "series" in r
        assert len(r["series"]) == 61  # inclusive: today - 60 .. today
        for pt in r["series"]:
            assert set(pt.keys()) >= {"date", "revenue", "anomaly", "score"}

    def test_forecast_v2_bands(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/analytics/forecast-v2?days=30", headers=h, timeout=15).json()
        assert len(r["series"]) == 30
        for pt in r["series"]:
            assert pt["p10"] <= pt["p50"] <= pt["p90"]
        totals = r["totals"]
        assert totals["p10"] <= totals["p50"] <= totals["p90"]

    def test_analytics_endpoints_forbidden_for_tech(self):
        h = _login(*TECH)
        for path in ("/analytics/overview", "/analytics/customer-ltv", "/analytics/churn-risk",
                     "/analytics/tech-productivity", "/analytics/revenue-anomalies", "/analytics/forecast-v2"):
            r = requests.get(f"{BASE}/api{path}", headers=h, timeout=10)
            assert r.status_code in (401, 403), f"{path} returned {r.status_code}"


# ─── Onboarding ───────────────────────────────────────────────────────────
class TestOnboarding:
    def test_demo_admin_pre_completed(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/onboarding", headers=h, timeout=15).json()
        assert r["completed"] is True, "demo admin should be marked complete on startup"
        assert r["current_step"] == r["total_steps"]

    def test_progress_persists(self):
        h = _login(*ADMIN)
        # Restart then advance
        requests.post(f"{BASE}/api/onboarding/restart", headers=h, timeout=15)
        r1 = requests.post(f"{BASE}/api/onboarding/progress", headers=h,
                           json={"current_step": 2, "data": {"business_name": "TEST_15B"}},
                           timeout=15).json()
        assert r1["current_step"] == 2
        assert r1["data"]["business_name"] == "TEST_15B"
        # Fetch fresh
        r2 = requests.get(f"{BASE}/api/onboarding", headers=h, timeout=15).json()
        assert r2["current_step"] == 2
        assert r2["data"]["business_name"] == "TEST_15B"
        # Advance and merge more data
        r3 = requests.post(f"{BASE}/api/onboarding/progress", headers=h,
                           json={"current_step": 3, "data": {"tone": "warm"}},
                           timeout=15).json()
        assert r3["data"]["business_name"] == "TEST_15B"  # merged, not replaced
        assert r3["data"]["tone"] == "warm"
        # Finish
        r4 = requests.post(f"{BASE}/api/onboarding/progress", headers=h,
                           json={"completed": True}, timeout=15).json()
        assert r4["completed"] is True

    def test_skip_all_marks_complete(self):
        h = _login(*ADMIN)
        requests.post(f"{BASE}/api/onboarding/restart", headers=h, timeout=15)
        r = requests.post(f"{BASE}/api/onboarding/progress", headers=h,
                          json={"skipped": True}, timeout=15).json()
        assert r["skipped"] is True
        assert r["completed"] is True

    def test_onboarding_forbidden_for_tech(self):
        h = _login(*TECH)
        r = requests.get(f"{BASE}/api/onboarding", headers=h, timeout=10)
        assert r.status_code in (401, 403)


def test_zzz_cleanup_restore_demo_completed():
    """Return the demo admin's onboarding state to completed=True so the demo isn't hijacked."""
    h = _login(*ADMIN)
    requests.post(f"{BASE}/api/onboarding/progress", headers=h,
                  json={"completed": True}, timeout=15)
