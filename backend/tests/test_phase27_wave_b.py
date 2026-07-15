"""Phase 27 Wave B tests — LIVE Claude via EMERGENT_LLM_KEY (no mocks)."""
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(e, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": e, "password": pw},
                       timeout=15)
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
# 27.1 · Churn analyzer (LIVE Claude)
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def at_risk_customer(dbc):
    """Customer with LOW NPS + NO recent completed job + cancelled history."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    tag = f"p27r-{int(time.time())}"
    cid = f"{tag}-cid"
    dbc.customers.insert_one({
        "id": cid, "tenant_id": t["id"], "name": "At-Risk Test",
        "email": "atrisk@test.local", "created_at":
            "2025-01-01T00:00:00Z", "tags": ["premium"],
    })
    dbc.csat_responses.insert_many([
        {"tenant_id": t["id"], "customer_id": cid, "score": 2,
          "created_at": "2026-06-01T00:00:00Z"},
        {"tenant_id": t["id"], "customer_id": cid, "score": 3,
          "created_at": "2026-06-15T00:00:00Z"},
    ])
    dbc.jobs.insert_many([
        {"id": f"{tag}-cxjob-{i}", "tenant_id": t["id"],
          "customer_id": cid, "status": "cancelled"}
        for i in range(3)
    ])
    yield {"tenant_id": t["id"], "customer_id": cid, "tag": tag}
    dbc.customers.delete_one({"id": cid})
    dbc.csat_responses.delete_many({"customer_id": cid})
    dbc.jobs.delete_many({"id": {"$regex": f"^{tag}-"}})
    dbc.customer_churn_scores.delete_many({"customer_id": cid})


@pytest.fixture
def happy_customer(dbc):
    """Customer with HIGH NPS + 4 completed jobs / 90d."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    tag = f"p27h-{int(time.time())}"
    cid = f"{tag}-cid"
    now = time.strftime("%Y-%m-%d")
    dbc.customers.insert_one({
        "id": cid, "tenant_id": t["id"], "name": "Happy Test",
        "email": "happy@test.local",
        "created_at": "2023-05-01T00:00:00Z", "tags": ["vip"],
    })
    dbc.csat_responses.insert_many([
        {"tenant_id": t["id"], "customer_id": cid, "score": s,
          "created_at": f"2026-06-{i+10:02d}T00:00:00Z"}
        for i, s in enumerate([9, 10, 10, 9])
    ])
    dbc.jobs.insert_many([
        {"id": f"{tag}-hxjob-{i}", "tenant_id": t["id"],
          "customer_id": cid, "status": "completed",
          "scheduled_date": now, "created_at": f"2026-06-{i+1:02d}T00:00:00Z"}
        for i in range(4)
    ])
    yield {"tenant_id": t["id"], "customer_id": cid, "tag": tag}
    dbc.customers.delete_one({"id": cid})
    dbc.csat_responses.delete_many({"customer_id": cid})
    dbc.jobs.delete_many({"id": {"$regex": f"^{tag}-"}})
    dbc.customer_churn_scores.delete_many({"customer_id": cid})


def test_at_risk_customer_scores_high(admin_h, at_risk_customer):
    r = requests.post(
        f"{API}/churn/analyze/{at_risk_customer['customer_id']}",
        headers=admin_h, timeout=45).json()
    assert r.get("mocked") is False, f"claude call was mocked: {r}"
    assert r["risk_score"] >= 55, f"expected high, got {r['risk_score']}"
    assert r["tier"] in ("high", "critical")


def test_happy_customer_scores_low(admin_h, happy_customer):
    r = requests.post(
        f"{API}/churn/analyze/{happy_customer['customer_id']}",
        headers=admin_h, timeout=45).json()
    assert r.get("mocked") is False
    assert r["risk_score"] < 55, f"expected low, got {r['risk_score']}"
    assert r["tier"] in ("low", "medium")


def test_churn_scores_list_and_tenant_isolation(admin_h,
                                                     at_risk_customer):
    # Ensure a score exists
    requests.post(f"{API}/churn/analyze/{at_risk_customer['customer_id']}",
                    headers=admin_h, timeout=45)
    r = requests.get(f"{API}/churn/scores", headers=admin_h,
                       timeout=10).json()
    assert "counts_by_tier" in r
    assert any(x["customer_id"] == at_risk_customer["customer_id"]
                for x in r["items"])


def test_churn_role_gating(tech_h, customer_h):
    for h in (tech_h, customer_h):
        r = requests.get(f"{API}/churn/scores", headers=h, timeout=10)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# 27.2 · Content Refresh (LIVE Claude)
# ═══════════════════════════════════════════════════════════════════════

def test_content_refresh_scan(admin_h, dbc):
    """Scan a real public blog root — Vercel's own /blog is stable +
    small enough for the extractor to find URLs. Falls back to any 200
    result set with >=1 URL if that path changes."""
    r = requests.post(f"{API}/seo/content-refresh/scan",
                        headers=admin_h,
                        json={"blog_root_url": "https://vercel.com/blog"},
                        timeout=60)
    if r.status_code == 404:
        pytest.skip("blog root URL discovery not available in sandbox")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"]
    assert len(body["urls_scored"]) >= 1
    # Cleanup
    dbc.content_refresh_scans.delete_one({"id": body["id"]})


def test_content_refresh_role_gating(tech_h, customer_h):
    for h in (tech_h, customer_h):
        r = requests.post(f"{API}/seo/content-refresh/scan",
                           headers=h,
                           json={"blog_root_url": "https://x.com/blog"},
                           timeout=10)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# 27.3 · Water photo analysis (LIVE Claude Vision)
# ═══════════════════════════════════════════════════════════════════════

CANNED_POOL_PHOTO = (
    "https://images.unsplash.com/photo-1519046904884-53103b34b206"
    "?auto=format&fit=crop&w=1200"
)


def test_water_photo_analysis(tech_h, dbc):
    r = requests.post(f"{API}/service-report/analyze-water-photo",
                        headers=tech_h,
                        json={"photo_url": CANNED_POOL_PHOTO,
                                "current_readings": {"ph": 7.2,
                                                       "chlorine": 0.4,
                                                       "alkalinity": 90},
                                "pool_gallons": 15000},
                        timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("mocked") is False, f"claude was mocked: {body}"
    assert body["clarity"] in ("crystal", "clear", "hazy", "cloudy",
                                     "green", "black"), body["clarity"]
    assert len(body["recommendations"]) >= 1
    rec0 = body["recommendations"][0]
    assert "chemical" in rec0 and "amount" in rec0 and "urgency" in rec0
    dbc.water_photo_analyses.delete_one({"id": body["id"]})


def test_water_photo_customer_forbidden(customer_h):
    r = requests.post(f"{API}/service-report/analyze-water-photo",
                        headers=customer_h,
                        json={"photo_url": CANNED_POOL_PHOTO}, timeout=10)
    assert r.status_code == 403


def test_water_photo_analysis_persisted(tech_h, dbc):
    r = requests.post(f"{API}/service-report/analyze-water-photo",
                        headers=tech_h,
                        json={"photo_url": CANNED_POOL_PHOTO},
                        timeout=60).json()
    stored = dbc.water_photo_analyses.find_one({"id": r["id"]})
    assert stored is not None
    assert stored["mocked"] is False
    dbc.water_photo_analyses.delete_one({"id": r["id"]})
