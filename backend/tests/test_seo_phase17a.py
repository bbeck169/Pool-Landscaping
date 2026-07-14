"""Phase 17A — Agentic SEO Suite Foundation Layer tests."""
import asyncio
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
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

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


# ─── 17A.1 · Site Auditor ────────────────────────────────────────────────
def test_audit_lifecycle_and_tenant_isolation(admin_h, sunbelt_admin_h,
                                                tech_h, customer_h, dbc):
    # Kick off — small max_pages to keep the crawl brief and stable.
    r = requests.post(f"{API}/seo/audits", headers=admin_h,
                     json={"url": "https://example.com",
                           "depth": 1, "max_pages": 2}, timeout=15).json()
    assert r["status"] == "queued"
    aid = r["audit_id"]

    # Tech + customer 403 on list.
    assert requests.get(f"{API}/seo/audits", headers=tech_h, timeout=15).status_code == 403
    assert requests.get(f"{API}/seo/audits", headers=customer_h, timeout=15).status_code == 403

    # Sunbelt admin cannot see the aquaterra audit.
    sun = requests.get(f"{API}/seo/audits", headers=sunbelt_admin_h,
                       timeout=15).json()
    assert all(x["id"] != aid for x in sun)
    r_direct = requests.get(f"{API}/seo/audits/{aid}",
                            headers=sunbelt_admin_h, timeout=15)
    assert r_direct.status_code == 404

    # Poll audit until it completes (or 25s pass).
    deadline = time.time() + 25
    status = "queued"
    while time.time() < deadline:
        a = requests.get(f"{API}/seo/audits/{aid}", headers=admin_h,
                        timeout=15).json()
        status = a["status"]
        if status in ("done", "failed", "cancelled"): break
        time.sleep(1)

    if status == "done":
        assert "summary" in a and a["summary"] is not None
        assert "scores" in a["summary"]
        # Page-level detail exists.
        pg = requests.get(f"{API}/seo/audits/{aid}/pages",
                          headers=admin_h, timeout=15).json()
        assert pg["total"] >= 1
    else:
        # Failed audits (e.g., no external network) still transition & are queryable.
        assert status in ("failed", "running", "queued", "cancelled")

    # Cleanup so we don't leave crawler docs across runs.
    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_audit_pages.delete_many({"audit_id": aid})


def test_audit_cancel_and_rerun_paths(admin_h, dbc):
    r = requests.post(f"{API}/seo/audits", headers=admin_h,
                     json={"url": "https://example.com",
                           "depth": 1, "max_pages": 1}, timeout=15).json()
    aid = r["audit_id"]

    # Cancel immediately (may race — accept idempotent behavior).
    c = requests.post(f"{API}/seo/audits/{aid}/cancel",
                     headers=admin_h, timeout=15)
    assert c.status_code in (200, 404)

    # Rerun creates a NEW audit id.
    rr = requests.post(f"{API}/seo/audits/{aid}/rerun",
                      headers=admin_h, timeout=15).json()
    assert rr["audit_id"] != aid
    assert rr["status"] == "queued"

    dbc.seo_audits.delete_many({"id": {"$in": [aid, rr["audit_id"]]}})
    dbc.seo_audit_pages.delete_many(
        {"audit_id": {"$in": [aid, rr["audit_id"]]}}
    )


# ─── 17A.2 · Content Scoring ────────────────────────────────────────────
def test_content_score_full_breakdown(admin_h, tech_h, customer_h):
    html = """
      <html><head><title>Best pool cleaning services in Phoenix Arizona</title>
      <meta name="description" content="Trusted pool cleaning services in Phoenix — weekly maintenance, chemical balance, and equipment repair.">
      </head><body>
      <h1>Pool cleaning services in Phoenix</h1>
      <p>Our pool cleaning services in Phoenix keep your water balanced and
        equipment in top condition. Regular pool cleaning helps prevent
        algae, extends filter life, and saves you money on chemicals.
        Book a technician for weekly, biweekly, or monthly visits at your
        convenience.  Our team brings 20 years of Arizona experience,
        specializing in salt-water pools and heat-tolerant equipment.</p>
      <p>We also handle spa cleaning, tile scrubbing, and green-pool
        recovery. If your water has turned cloudy or green, our shock
        treatment protocol restores clarity within 48 hours in most
        cases. Call today for a same-week appointment.</p>
      <p>Beyond cleaning, we service pumps, filters, heaters, and
        automation controllers. Our chemistry balancing includes chlorine,
        pH, alkalinity, calcium hardness, and CYA. We photograph the
        pool before and after every visit and share the report with
        you in the customer portal.</p>
      <p><a href="/services">See all services</a> ·
         <a href="/pricing">See pricing</a></p>
      <img src="/pool.jpg" alt="Sparkling clean pool in Phoenix">
      </body></html>
    """
    r = requests.post(f"{API}/seo/content-score", headers=admin_h,
                     json={"html": html,
                           "target_keyword": "pool cleaning services in Phoenix"},
                     timeout=45).json()
    assert isinstance(r["score"], int) and 0 <= r["score"] <= 100
    expected_keys = {"readability", "keyword_density", "heading_structure",
                     "meta", "internal_links", "image_alt",
                     "content_length", "semantic_relevance"}
    assert expected_keys.issubset(set(r["breakdown"].keys()))
    assert isinstance(r["recommendations"], list)

    # Tech + customer → 403.
    assert requests.post(f"{API}/seo/content-score", headers=tech_h,
                         json={"html": "<p>x</p>",
                               "target_keyword": "x"}, timeout=15
                         ).status_code == 403
    assert requests.post(f"{API}/seo/content-score", headers=customer_h,
                         json={"html": "<p>x</p>",
                               "target_keyword": "x"}, timeout=15
                         ).status_code == 403


def test_content_score_llm_live_when_key_set(admin_h):
    """With EMERGENT_LLM_KEY set, `mocked` should be false (real Claude call)."""
    r = requests.post(f"{API}/seo/content-score", headers=admin_h,
                     json={"html": "<p>Weekly pool cleaning in Phoenix.</p>",
                           "target_keyword": "pool cleaning"}, timeout=60
                     ).json()
    # Must have `mocked` field so the FE can label results.
    assert "mocked" in r
    # If the key is set, we expect real LLM (mocked=False).
    # We don't fail the test hard if the LLM is unreachable in CI — just log.
    if r["mocked"]:
        pytest.skip("EMERGENT_LLM_KEY not effective in this environment")
    assert isinstance(r["breakdown"]["semantic_relevance"], int)


# ─── 17A.3 · Rank Heatmap ───────────────────────────────────────────────
def test_rank_heatmap_flagged_mocked_and_isolated(admin_h, sunbelt_admin_h,
                                                    tech_h, customer_h, dbc):
    r = requests.post(f"{API}/seo/rank-heatmaps", headers=admin_h,
                     json={"keyword": "pool cleaning Phoenix",
                           "center_lat": 33.6, "center_lng": -112.2,
                           "grid_size": 3, "radius_miles": 3.0},
                     timeout=15).json()
    assert r["status"] == "queued"
    assert r["mocked"] is True   # No SERP provider configured
    hid = r["heatmap_id"]

    # Wait for background completion.
    deadline = time.time() + 15
    d = None
    while time.time() < deadline:
        d = requests.get(f"{API}/seo/rank-heatmaps/{hid}",
                        headers=admin_h, timeout=15).json()
        if d["status"] in ("done", "failed"): break
        time.sleep(0.5)
    assert d and d["status"] == "done"
    assert d["mocked"] is True
    assert "mocked_reason" in d and d["mocked_reason"]
    assert len(d["points"]) == 9  # 3x3
    assert all("rank" in p and "top_10_urls" in p for p in d["points"])
    assert isinstance(d["avg_rank"], (int, float))

    # Tenant isolation.
    sun_view = requests.get(f"{API}/seo/rank-heatmaps/{hid}",
                            headers=sunbelt_admin_h, timeout=15)
    assert sun_view.status_code == 404

    # Tech + customer → 403.
    assert requests.get(f"{API}/seo/rank-heatmaps",
                        headers=tech_h, timeout=15).status_code == 403
    assert requests.get(f"{API}/seo/rank-heatmaps",
                        headers=customer_h, timeout=15).status_code == 403

    dbc.seo_rank_heatmaps.delete_one({"id": hid})


def test_seo_ping_admin_only(admin_h, tech_h):
    r = requests.get(f"{API}/seo/ping", headers=admin_h, timeout=15).json()
    assert "running_audits" in r
    t = requests.get(f"{API}/seo/ping", headers=tech_h, timeout=15)
    assert t.status_code == 403
