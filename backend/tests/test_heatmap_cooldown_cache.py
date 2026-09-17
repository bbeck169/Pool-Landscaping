"""Feb-2026 · Rank Heatmap · 6-hour cooldown cache tests.

Covers:
  • Cache MISS → real DFS call, result cached.
  • Immediate second run (same tenant + keyword + center) → HIT.
  • ``bypass_cache=True`` → real DFS call regardless of cache state.
  • 4dp rounding — micro-jitter in center coords hits the cache.
  • Different keyword → MISS.
  • All-mocked-degradation run is NOT cached.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple, Optional
from unittest.mock import patch

from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _loop_and_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
    adb = client[_ENV["DB_NAME"]]
    from routers import seo_agentic as _sa
    _sa._orig_db_for_test = getattr(_sa, "_orig_db_for_test", _sa.db)
    _sa.db = adb
    return loop, client, adb


def _restore_db():
    from routers import seo_agentic as _sa
    if hasattr(_sa, "_orig_db_for_test"):
        _sa.db = _sa._orig_db_for_test


def _seed_tenant(loop, adb, tid: str):
    loop.run_until_complete(adb.tenants.insert_one({
        "id": tid, "name": "Heatmap Cache Tenant",
        "settings": {"business_card": {"website_url": "https://cache-test.example"}},
    }))


def _seed_heatmap_row(loop, adb, tid: str) -> str:
    hid = f"hm-{uuid.uuid4().hex[:8]}"
    loop.run_until_complete(adb.seo_rank_heatmaps.insert_one({
        "id": hid, "tenant_id": tid, "status": "queued",
        "points": [], "avg_rank": None, "top_position_count": 0,
    }))
    return hid


def _drop(loop, client, adb, tid: str):
    loop.run_until_complete(adb.tenants.delete_one({"id": tid}))
    loop.run_until_complete(adb.seo_rank_heatmaps.delete_many({"tenant_id": tid}))
    loop.run_until_complete(adb.heatmap_run_cache.delete_many({"key": {"$regex": tid}}))
    _restore_db()
    client.close()


def _dfs_success(rank: int) -> Tuple[int, Dict[str, Any], Optional[str]]:
    return (200, {"tasks": [{"result": [{"items": [
        {"rank_absolute": rank, "rank_group": rank,
         "url": "https://cache-test.example/",
         "domain": "cache-test.example", "title": "T"},
    ]}]}]}, None)


def test_first_run_miss_second_run_hit_bypass_forces_miss():
    from routers.seo_agentic import _generate_heatmap

    loop, client, adb = _loop_and_db()
    tid = f"cache-tenant-{uuid.uuid4().hex[:8]}"
    _seed_tenant(loop, adb, tid)
    try:
        call_counter = {"n": 0}
        async def _fake_serp(kw, lat, lng, **kwargs):
            call_counter["n"] += 1
            return _dfs_success(rank=5)

        with patch("routers.seo_agentic._dfs.get_credentials_or_none",
                    return_value=("l", "p")), \
             patch("routers.seo_agentic._dfs.serp_google_organic_live",
                    side_effect=_fake_serp):

            # ── Run 1 (MISS) ───────────────────────────────────
            hid1 = _seed_heatmap_row(loop, adb, tid)
            loop.run_until_complete(_generate_heatmap(
                hid1, tid, "cache kw one",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=3, radius_miles=5.0,
            ))
            calls_after_run1 = call_counter["n"]
            row1 = loop.run_until_complete(
                adb.seo_rank_heatmaps.find_one({"id": hid1}, {"_id": 0}),
            )
            assert row1["served_from_cache"] is False
            assert calls_after_run1 == 9, calls_after_run1

            # ── Run 2 (HIT — same tenant+keyword+center) ───────
            hid2 = _seed_heatmap_row(loop, adb, tid)
            loop.run_until_complete(_generate_heatmap(
                hid2, tid, "cache kw one",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=3, radius_miles=5.0,
            ))
            assert call_counter["n"] == calls_after_run1, (
                "Cache HIT MUST NOT invoke DFS again"
            )
            row2 = loop.run_until_complete(
                adb.seo_rank_heatmaps.find_one({"id": hid2}, {"_id": 0}),
            )
            assert row2["served_from_cache"] is True
            assert row2["cached_at"], row2

            # ── Run 3 (bypass_cache=True — MISS forced) ────────
            hid3 = _seed_heatmap_row(loop, adb, tid)
            loop.run_until_complete(_generate_heatmap(
                hid3, tid, "cache kw one",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=3, radius_miles=5.0, bypass_cache=True,
            ))
            assert call_counter["n"] == calls_after_run1 + 9
            row3 = loop.run_until_complete(
                adb.seo_rank_heatmaps.find_one({"id": hid3}, {"_id": 0}),
            )
            assert row3["served_from_cache"] is False

            # ── Run 4 (4dp rounding — micro-jitter is a HIT) ───
            hid4 = _seed_heatmap_row(loop, adb, tid)
            loop.run_until_complete(_generate_heatmap(
                hid4, tid, "cache kw one",
                # 5dp of drift — rounds to the same 4dp key.
                center_lat=33.76951, center_lng=-112.25691,
                grid_size=3, radius_miles=5.0,
            ))
            assert call_counter["n"] == calls_after_run1 + 9, (
                "4dp rounding MUST hit the cache — no new DFS call"
            )
            row4 = loop.run_until_complete(
                adb.seo_rank_heatmaps.find_one({"id": hid4}, {"_id": 0}),
            )
            assert row4["served_from_cache"] is True

            # ── Run 5 (different keyword — MISS) ───────────────
            hid5 = _seed_heatmap_row(loop, adb, tid)
            loop.run_until_complete(_generate_heatmap(
                hid5, tid, "cache kw two",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=3, radius_miles=5.0,
            ))
            assert call_counter["n"] == calls_after_run1 + 18
            row5 = loop.run_until_complete(
                adb.seo_rank_heatmaps.find_one({"id": hid5}, {"_id": 0}),
            )
            assert row5["served_from_cache"] is False
    finally:
        _drop(loop, client, adb, tid)
        loop.close()


def test_all_mocked_degradation_is_not_cached():
    """When every point falls back to a mocked rank, DO NOT write
    the cache — a re-run should be free to pick up recovered DFS
    availability sooner than 6h."""
    from routers.seo_agentic import _generate_heatmap

    loop, client, adb = _loop_and_db()
    tid = f"cache-tenant-mocked-{uuid.uuid4().hex[:8]}"
    _seed_tenant(loop, adb, tid)
    try:
        # Every DFS call errors → all points degrade → top-level mocked.
        async def _all_error(kw, lat, lng, **kwargs):
            return (0, None, "transport_error: connection refused")

        with patch("routers.seo_agentic._dfs.get_credentials_or_none",
                    return_value=("l", "p")), \
             patch("routers.seo_agentic._dfs.serp_google_organic_live",
                    side_effect=_all_error):
            hid1 = _seed_heatmap_row(loop, adb, tid)
            loop.run_until_complete(_generate_heatmap(
                hid1, tid, "all mocked kw",
                center_lat=33.7695, center_lng=-112.2569,
                grid_size=3, radius_miles=5.0,
            ))
            row = loop.run_until_complete(
                adb.seo_rank_heatmaps.find_one({"id": hid1}, {"_id": 0}),
            )
            assert row["mocked"] is True, row

            # No cache entry written.
            cached = loop.run_until_complete(
                adb.heatmap_run_cache.find_one(
                    {"key": {"$regex": tid}}, {"_id": 0},
                ),
            )
            assert cached is None, (
                "All-mocked runs MUST NOT be cached — got %r" % cached
            )
    finally:
        _drop(loop, client, adb, tid)
        loop.close()
