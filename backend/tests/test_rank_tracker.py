"""Feb-2026 · Phase 23-A — Local Rank Tracker pytest.

Covers CRUD, geo-grid utility, refresh-now cooldown gate, cron flag,
and graceful DataForSEO error handling.  These tests DO NOT hit the
real DataForSEO API — we monkey-patch the client shim so the suite
stays fast and never burns credits.
"""
from __future__ import annotations

import os
import uuid
import asyncio
import requests
import pytest
from pathlib import Path
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)
_sync_db = _sync[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else "http://localhost:8001/api"
)


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def _tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


def _tenant_id_for(email: str) -> str:
    u = _sync_db.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


@pytest.fixture(autouse=True)
def _clean_tenant_rt():
    """Reset the admin's rank tracker state before + after each test."""
    tid = _tenant_id_for("admin@aquaterra.com")
    _sync_db.tracked_keywords.delete_many({"tenant_id": tid})
    _sync_db.rank_snapshots.delete_many({"tenant_id": tid})
    yield
    _sync_db.tracked_keywords.delete_many({"tenant_id": tid})
    _sync_db.rank_snapshots.delete_many({"tenant_id": tid})


# ─────────────────────────────────────────────────────────────────────
# Geo grid utility
# ─────────────────────────────────────────────────────────────────────
def test_build_grid_is_3x3_and_centered():
    from routers.rank_tracker import build_grid
    grid = build_grid(33.77, -112.26, 2.0)
    assert len(grid) == 9
    # Center point index 4 = (dy=0, dx=0) — matches input.
    assert abs(grid[4]["lat"] - 33.77) < 1e-6
    assert abs(grid[4]["lng"] - (-112.26)) < 1e-6
    # Corners are ~2km from center (~0.018° lat, ~0.021° lng at 34°N).
    dlat = abs(grid[0]["lat"] - grid[4]["lat"])
    dlng = abs(grid[0]["lng"] - grid[4]["lng"])
    assert 0.015 < dlat < 0.022
    assert 0.018 < dlng < 0.026


# ─────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────
def test_add_and_list_keyword():
    h = _admin_headers()
    r = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                       json={"keyword": "pool cleaning peoria az"}, timeout=15)
    assert r.status_code == 200, r.text
    kw = r.json()
    assert kw["keyword"] == "pool cleaning peoria az"
    assert kw["market_geo"]["radius_km"] == 2.0
    assert kw["active"] is True
    # List returns it.
    lst = requests.get(f"{API}/rank-tracker/keywords", headers=h, timeout=15).json()
    assert lst["total"] == 1
    assert lst["keywords"][0]["id"] == kw["id"]


def test_duplicate_keyword_returns_409():
    h = _admin_headers()
    requests.post(f"{API}/rank-tracker/keywords", headers=h,
                   json={"keyword": "pool cleaning"}, timeout=15).raise_for_status()
    r = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                       json={"keyword": "Pool Cleaning"}, timeout=15)
    assert r.status_code == 409


def test_keyword_cap_at_50():
    h = _admin_headers()
    tid = _tenant_id_for("admin@aquaterra.com")
    # Seed 50 directly via mongo for speed.
    docs = [{
        "id": f"kw-{i}", "tenant_id": tid,
        "keyword": f"seed-{i}", "keyword_lc": f"seed-{i}",
        "market_geo": {"lat": 33.77, "lng": -112.26, "radius_km": 2},
        "active": True, "added_at": "2026-02-01",
    } for i in range(50)]
    _sync_db.tracked_keywords.insert_many(docs)
    r = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                       json={"keyword": "one too many"}, timeout=15)
    assert r.status_code == 400
    assert "limit" in r.json().get("detail", "").lower()


def test_delete_keyword_soft_deletes():
    h = _admin_headers()
    r = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                       json={"keyword": "delete me"}, timeout=15).json()
    d = requests.delete(f"{API}/rank-tracker/keywords/{r['id']}", headers=h, timeout=15)
    assert d.status_code == 200
    # List no longer surfaces it.
    lst = requests.get(f"{API}/rank-tracker/keywords", headers=h, timeout=15).json()
    assert lst["total"] == 0


def test_rank_tracker_requires_admin():
    tech_h = _tech_headers()
    r = requests.get(f"{API}/rank-tracker/keywords", headers=tech_h, timeout=15)
    assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────
# Refresh-now — cooldown + graceful DataForSEO errors
# ─────────────────────────────────────────────────────────────────────
def test_refresh_now_cooldown_returns_429_within_6h():
    h = _admin_headers()
    tid = _tenant_id_for("admin@aquaterra.com")
    kw_id = str(uuid.uuid4())
    _sync_db.tracked_keywords.insert_one({
        "id": kw_id, "tenant_id": tid,
        "keyword": "cooldown test", "keyword_lc": "cooldown test",
        "market_geo": {"lat": 33.77, "lng": -112.26, "radius_km": 2},
        "active": True,
        # Simulate a very recent refresh — cooldown must engage.
        "last_refreshed_at": "2999-12-31T00:00:00+00:00",
    })
    r = requests.post(f"{API}/rank-tracker/keywords/{kw_id}/refresh-now",
                        headers=h, timeout=15)
    assert r.status_code == 429


def test_refresh_now_without_domain_returns_400():
    """If the tenant's business_card has no website_url, we refuse the
    call — we have nothing to rank-check for."""
    from unittest import mock
    h = _admin_headers()
    tid = _tenant_id_for("admin@aquaterra.com")
    # Stash + null out the website.
    orig = _sync_db.tenants.find_one({"id": tid}, {"_id": 0, "settings": 1})
    orig_website = (((orig or {}).get("settings") or {}).get("business_card") or {}).get("website_url")
    _sync_db.tenants.update_one(
        {"id": tid},
        {"$set": {"settings.business_card.website_url": ""}},
    )
    try:
        kw = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                             json={"keyword": "no-website test"}, timeout=15).json()
        r = requests.post(f"{API}/rank-tracker/keywords/{kw['id']}/refresh-now",
                            headers=h, timeout=15)
        assert r.status_code == 400
        assert "website" in r.json().get("detail", "").lower()
    finally:
        _sync_db.tenants.update_one(
            {"id": tid},
            {"$set": {"settings.business_card.website_url": orig_website or ""}},
        )


def test_refresh_now_persists_grid_with_ranks_when_dataforseo_ok():
    """Monkey-patch the DFS shim to return a fake SERP; verify 9 rows
    are written and the target domain is found at rank 3.
    """
    from routers import rank_tracker as _rt
    from services import dataforseo_client as _dfs

    h = _admin_headers()
    kw = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                        json={"keyword": "monkeypatch test"}, timeout=15).json()

    # We can't monkey-patch the running server process from pytest —
    # instead we call the private helper directly (which imports the
    # DFS module at call time and awaits it). We patch here via a
    # local wrapper.
    async def run():
        original_serp = _dfs.serp_google_organic_live
        original_parse = _dfs.parse_serp_ranks

        async def fake_serp(kw_str, lat, lng, **kwargs):
            return 200, {"tasks": [{"result": [{"items": []}]}]}, None

        def fake_parse(body, targets):
            return {t: 3 for t in targets}

        _dfs.serp_google_organic_live = fake_serp
        _dfs.parse_serp_ranks = fake_parse
        try:
            kw_doc = _sync_db.tracked_keywords.find_one({"id": kw["id"]},
                                                          {"_id": 0})
            summary = await _rt._snapshot_keyword(
                kw_doc, kw_doc["tenant_id"], "example.com",
            )
            return summary
        finally:
            _dfs.serp_google_organic_live = original_serp
            _dfs.parse_serp_ranks = original_parse

    summary = asyncio.get_event_loop().run_until_complete(run())
    assert len(summary["results"]) == 9
    assert all(r["rank"] == 3 for r in summary["results"])
    # DB has 9 rows.
    n = _sync_db.rank_snapshots.count_documents({"keyword_id": kw["id"]})
    assert n == 9


def test_refresh_now_stops_early_on_out_of_credits():
    """When DFS returns 402 out_of_credits on the FIRST grid point, we
    must not burn 8 more requests. Only 1 row gets written."""
    from routers import rank_tracker as _rt
    from services import dataforseo_client as _dfs

    h = _admin_headers()
    kw = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                        json={"keyword": "credits stop test"}, timeout=15).json()

    async def run():
        original = _dfs.serp_google_organic_live

        async def fake_serp(*a, **k):
            return 402, None, "out_of_credits"

        _dfs.serp_google_organic_live = fake_serp
        try:
            kw_doc = _sync_db.tracked_keywords.find_one({"id": kw["id"]},
                                                          {"_id": 0})
            summary = await _rt._snapshot_keyword(
                kw_doc, kw_doc["tenant_id"], "example.com",
            )
            return summary
        finally:
            _dfs.serp_google_organic_live = original

    summary = asyncio.get_event_loop().run_until_complete(run())
    assert len(summary["results"]) == 1
    assert summary["results"][0]["api_error"] == "out_of_credits"
    n = _sync_db.rank_snapshots.count_documents({"keyword_id": kw["id"]})
    assert n == 1


# ─────────────────────────────────────────────────────────────────────
# Heatmap endpoint shape
# ─────────────────────────────────────────────────────────────────────
def test_heatmap_endpoint_returns_9_slots_and_history():
    h = _admin_headers()
    tid = _tenant_id_for("admin@aquaterra.com")
    kw = requests.post(f"{API}/rank-tracker/keywords", headers=h,
                        json={"keyword": "heatmap test"}, timeout=15).json()
    # Seed 9 snapshot rows + one older batch.
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    for batch, offset_h in ((0, 0), (1, 24 * 7)):
        for idx in range(9):
            _sync_db.rank_snapshots.insert_one({
                "id": f"snap-{batch}-{idx}",
                "tenant_id": tid, "keyword_id": kw["id"],
                "grid_point_index": idx, "grid_lat": 33.77, "grid_lng": -112.26,
                "checked_at": (now - timedelta(hours=offset_h)).isoformat(),
                "rank": (idx + 1) + batch * 5,
                "engine": "google", "target_domain": "example.com",
            })
    r = requests.get(f"{API}/rank-tracker/keywords/{kw['id']}/heatmap",
                       headers=h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["keyword"]["id"] == kw["id"]
    assert len(body["grid"]) == 9
    # Latest snapshot per point wins — every slot points to batch 0.
    for i, cell in enumerate(body["grid"]):
        assert cell is not None
        assert cell["rank"] == (i + 1)
    # History has 2 buckets (one per checked_at minute).
    assert len(body["history"]) >= 2


# ─────────────────────────────────────────────────────────────────────
# Weekly cron flag
# ─────────────────────────────────────────────────────────────────────
def test_weekly_rank_tracker_skips_when_flag_disabled():
    from routers.rank_tracker import run_weekly_rank_tracker
    prev = os.environ.get("RANK_TRACKER_CRON_ENABLED")
    os.environ["RANK_TRACKER_CRON_ENABLED"] = "false"
    try:
        res = asyncio.get_event_loop().run_until_complete(
            run_weekly_rank_tracker()
        )
        assert res == {"skipped": 1, "keywords": 0}
    finally:
        if prev is None:
            os.environ.pop("RANK_TRACKER_CRON_ENABLED", None)
        else:
            os.environ["RANK_TRACKER_CRON_ENABLED"] = prev


# ─────────────────────────────────────────────────────────────────────
# DataForSEO credentials endpoint — surfaces auth failure cleanly
# ─────────────────────────────────────────────────────────────────────
def test_credits_endpoint_surfaces_auth_failure_cleanly():
    """Regardless of whether creds work, the shape must be consistent."""
    h = _admin_headers()
    r = requests.get(f"{API}/rank-tracker/dataforseo-credits", headers=h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "available" in body
    # If unavailable, the reason string is populated so the UI can show it.
    if body["available"] is False:
        assert body.get("reason")
