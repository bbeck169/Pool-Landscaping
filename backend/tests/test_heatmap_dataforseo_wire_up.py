"""Feb-2026 · Rank Heatmap · DataForSEO wire-up.

Exercises the ``_generate_heatmap`` worker with the DFS client
mocked so we can drive every branch without spending credits:
  • Happy path — every grid point returns real ranks.
  • DFS not configured — top-level mocked payload preserved.
  • Per-point degradation — one point errors, others succeed.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _loop_and_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
    adb = client[_ENV["DB_NAME"]]
    # ``routers.seo_agentic`` imports ``db`` from ``config`` at module
    # load and rebinds it as a local name — Motor clients are bound
    # to whichever loop first touched them, so we swap in a client
    # created ON our test's loop for the duration of the test.
    from routers import seo_agentic as _sa
    _sa._orig_db_for_test = getattr(_sa, "_orig_db_for_test", _sa.db)
    _sa.db = adb
    return loop, client, adb


def _restore_db():
    from routers import seo_agentic as _sa
    if hasattr(_sa, "_orig_db_for_test"):
        _sa.db = _sa._orig_db_for_test


def _seed_tenant(loop, adb, tid: str, website: str = "https://vistancia-pools.com"):
    loop.run_until_complete(adb.tenants.insert_one({
        "id": tid, "name": "Heatmap Wire-up",
        "settings": {"business_card": {"website_url": website}},
    }))


def _seed_heatmap_row(loop, adb, tid: str) -> str:
    hid = f"hm-{uuid.uuid4().hex[:8]}"
    loop.run_until_complete(adb.seo_rank_heatmaps.insert_one({
        "id": hid, "tenant_id": tid, "status": "queued",
        "points": [], "avg_rank": None, "top_position_count": 0,
    }))
    return hid


def _drop(loop, client, adb, tid: str, hid: Optional[str] = None):
    loop.run_until_complete(adb.tenants.delete_one({"id": tid}))
    if hid:
        loop.run_until_complete(adb.seo_rank_heatmaps.delete_many({"id": hid}))
    loop.run_until_complete(adb.heatmap_run_cache.delete_many({"key": {"$regex": tid}}))
    _restore_db()
    client.close()


# ── Fixture DFS responses ─────────────────────────────────────────

def _dfs_success_response(rank: int, target_domain: str) -> Tuple[int, Dict[str, Any], Optional[str]]:
    return (200, {"tasks": [{"result": [{"items": [
        {"rank_absolute": rank, "rank_group": rank,
         "url": f"https://{target_domain}/services",
         "domain": target_domain, "title": "Vistancia Pools"},
        {"rank_absolute": rank + 1, "rank_group": rank + 1,
         "url": "https://competitor.com/", "domain": "competitor.com",
         "title": "Competitor"},
    ]}]}]}, None)


# ── Test 1: happy path ────────────────────────────────────────────

def test_heatmap_dataforseo_happy_path_all_real():
    from routers.seo_agentic import _generate_heatmap

    loop, client, adb = _loop_and_db()
    tid = f"heatmap-tenant-{uuid.uuid4().hex[:8]}"
    _seed_tenant(loop, adb, tid)
    hid = _seed_heatmap_row(loop, adb, tid)
    try:
        # Return a fresh success for every grid point (5x5 = 25 pts).
        async def _fake_serp(kw, lat, lng, **kwargs):
            return _dfs_success_response(rank=7, target_domain="vistancia-pools.com")

        with patch("routers.seo_agentic._dfs.get_credentials_or_none",
                    return_value=("test-login", "test-pw")), \
             patch("routers.seo_agentic._dfs.serp_google_organic_live",
                    side_effect=_fake_serp):
            loop.run_until_complete(_generate_heatmap(
                hid, tid, "pool cleaning peoria",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=5, radius_miles=5.0,
            ))

        row = loop.run_until_complete(
            adb.seo_rank_heatmaps.find_one({"id": hid}, {"_id": 0}),
        )
        assert row["status"] == "done"
        assert row["mocked"] is False, row
        assert row["served_from_cache"] is False, row
        assert row["avg_rank"] == 7, row
        assert row["top_position_count"] == 25, row  # 5x5 all rank 7 ≤ 10
        assert len(row["points"]) == 25
        for pt in row["points"]:
            assert pt["rank"] == 7
            assert pt["mocked"] is False, pt
            assert "vistancia-pools.com" in (pt.get("url_found") or "")
            assert len(pt["top_10_urls"]) >= 1
        # Cost telemetry incremented.
        t = loop.run_until_complete(adb.tenants.find_one({"id": tid}, {"_id": 0}))
        assert (t.get("metrics") or {}).get("dataforseo_heatmap_calls") == 25
        # Cache entry written.
        cached = loop.run_until_complete(
            adb.heatmap_run_cache.find_one({"key": {"$regex": tid}}, {"_id": 0}),
        )
        assert cached is not None
        assert cached["mocked"] is False
    finally:
        _drop(loop, client, adb, tid, hid)
        loop.close()


# ── Test 2: DFS not configured → mocked ───────────────────────────

def test_heatmap_dfs_unset_returns_top_level_mocked():
    from routers.seo_agentic import _generate_heatmap

    loop, client, adb = _loop_and_db()
    tid = f"heatmap-nocreds-{uuid.uuid4().hex[:8]}"
    _seed_tenant(loop, adb, tid)
    hid = _seed_heatmap_row(loop, adb, tid)
    try:
        with patch("routers.seo_agentic._dfs.get_credentials_or_none",
                    return_value=None) as gate, \
             patch("routers.seo_agentic._dfs.serp_google_organic_live") as serp:
            loop.run_until_complete(_generate_heatmap(
                hid, tid, "pool cleaning peoria",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=3, radius_miles=5.0,
            ))
            assert gate.called
            assert not serp.called, "DFS SERP MUST NOT be called when creds unset"

        row = loop.run_until_complete(
            adb.seo_rank_heatmaps.find_one({"id": hid}, {"_id": 0}),
        )
        assert row["status"] == "done"
        assert row["mocked"] is True
        assert row["mocked_reason"] == "dataforseo_not_configured"
        assert len(row["points"]) == 9  # 3x3
        for pt in row["points"]:
            assert pt["mocked"] is True

        # No cost telemetry when no real calls were made.
        t = loop.run_until_complete(adb.tenants.find_one({"id": tid}, {"_id": 0}))
        assert (t.get("metrics") or {}).get("dataforseo_heatmap_calls") is None
        # No cache entry written for a fully-mocked run.
        cached = loop.run_until_complete(
            adb.heatmap_run_cache.find_one({"key": {"$regex": tid}}, {"_id": 0}),
        )
        assert cached is None
    finally:
        _drop(loop, client, adb, tid, hid)
        loop.close()


# ── Test 3: one point errors, others succeed ──────────────────────

def test_heatmap_per_point_degradation():
    """One rate-limit response → that point is mocked+has ``error``,
    the rest are real, top-level ``mocked=False`` (majority real)."""
    from routers.seo_agentic import _generate_heatmap

    loop, client, adb = _loop_and_db()
    tid = f"heatmap-perpoint-{uuid.uuid4().hex[:8]}"
    _seed_tenant(loop, adb, tid)
    hid = _seed_heatmap_row(loop, adb, tid)
    try:
        # Return the rate-limit tuple for the very first call, success
        # for the rest. side_effect exhausts left-to-right so this is
        # deterministic.
        call_counter = {"n": 0}
        async def _fake_serp(kw, lat, lng, **kwargs):
            call_counter["n"] += 1
            if call_counter["n"] == 1:
                return (429, None, "api_status_code=40200: request rate limit")
            return _dfs_success_response(rank=4, target_domain="vistancia-pools.com")

        with patch("routers.seo_agentic._dfs.get_credentials_or_none",
                    return_value=("test-login", "test-pw")), \
             patch("routers.seo_agentic._dfs.serp_google_organic_live",
                    side_effect=_fake_serp):
            loop.run_until_complete(_generate_heatmap(
                hid, tid, "pool repair peoria",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=3, radius_miles=5.0,
            ))

        row = loop.run_until_complete(
            adb.seo_rank_heatmaps.find_one({"id": hid}, {"_id": 0}),
        )
        assert row["status"] == "done"
        assert row["mocked"] is False, row  # majority real → top-level real
        mocked_points = [p for p in row["points"] if p.get("mocked")]
        real_points = [p for p in row["points"] if not p.get("mocked")]
        assert len(mocked_points) == 1, mocked_points
        assert len(real_points) == 8
        # The mocked point carries an error field describing the DFS failure.
        assert "rate limit" in (mocked_points[0].get("error") or "").lower()
        assert mocked_points[0]["api_status"] == 429
        # Cost telemetry counts ONLY the 8 real calls.
        t = loop.run_until_complete(adb.tenants.find_one({"id": tid}, {"_id": 0}))
        assert (t.get("metrics") or {}).get("dataforseo_heatmap_calls") == 8
    finally:
        _drop(loop, client, adb, tid, hid)
        loop.close()
