"""Feb-2026 · Rank Heatmap · cost telemetry.

Confirms ``tenants.metrics.dataforseo_heatmap_calls`` is incremented
by the number of REAL DFS calls per run — cache hits and mocked
degradations don't inflate the counter.
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


def _dfs_success() -> Tuple[int, Dict[str, Any], Optional[str]]:
    return (200, {"tasks": [{"result": [{"items": [
        {"rank_absolute": 9, "rank_group": 9,
         "url": "https://telemetry.example/",
         "domain": "telemetry.example", "title": "T"},
    ]}]}]}, None)


def test_cost_telemetry_increments_on_real_calls_only():
    from routers.seo_agentic import _generate_heatmap

    loop, client, adb = _loop_and_db()
    tid = f"telemetry-tenant-{uuid.uuid4().hex[:8]}"
    loop.run_until_complete(adb.tenants.insert_one({
        "id": tid, "name": "Telemetry",
        "settings": {"business_card": {"website_url": "https://telemetry.example"}},
    }))
    try:
        async def _serp_ok(kw, lat, lng, **kwargs):
            return _dfs_success()

        with patch("routers.seo_agentic._dfs.get_credentials_or_none",
                    return_value=("l", "p")), \
             patch("routers.seo_agentic._dfs.serp_google_organic_live",
                    side_effect=_serp_ok):

            # ── Real run: 3x3 grid = 9 real calls, counter should be 9.
            hid1 = f"hm-{uuid.uuid4().hex[:8]}"
            loop.run_until_complete(adb.seo_rank_heatmaps.insert_one({
                "id": hid1, "tenant_id": tid, "status": "queued",
                "points": [],
            }))
            loop.run_until_complete(_generate_heatmap(
                hid1, tid, "telemetry kw",
                center_lat=40.0, center_lng=-105.0,
                grid_size=3, radius_miles=3.0,
            ))
            t = loop.run_until_complete(adb.tenants.find_one({"id": tid}, {"_id": 0}))
            assert (t.get("metrics") or {}).get("dataforseo_heatmap_calls") == 9

            # ── Cache HIT: counter must NOT bump.
            hid2 = f"hm-{uuid.uuid4().hex[:8]}"
            loop.run_until_complete(adb.seo_rank_heatmaps.insert_one({
                "id": hid2, "tenant_id": tid, "status": "queued",
                "points": [],
            }))
            loop.run_until_complete(_generate_heatmap(
                hid2, tid, "telemetry kw",
                center_lat=40.0, center_lng=-105.0,
                grid_size=3, radius_miles=3.0,
            ))
            t = loop.run_until_complete(adb.tenants.find_one({"id": tid}, {"_id": 0}))
            assert (t.get("metrics") or {}).get("dataforseo_heatmap_calls") == 9, (
                "Cache HIT MUST NOT bump the telemetry counter"
            )

            # ── Bypass cache: another 9 real calls → total 18.
            hid3 = f"hm-{uuid.uuid4().hex[:8]}"
            loop.run_until_complete(adb.seo_rank_heatmaps.insert_one({
                "id": hid3, "tenant_id": tid, "status": "queued",
                "points": [],
            }))
            loop.run_until_complete(_generate_heatmap(
                hid3, tid, "telemetry kw",
                center_lat=40.0, center_lng=-105.0,
                grid_size=3, radius_miles=3.0, bypass_cache=True,
            ))
            t = loop.run_until_complete(adb.tenants.find_one({"id": tid}, {"_id": 0}))
            assert (t.get("metrics") or {}).get("dataforseo_heatmap_calls") == 18
    finally:
        loop.run_until_complete(adb.tenants.delete_one({"id": tid}))
        loop.run_until_complete(adb.seo_rank_heatmaps.delete_many({"tenant_id": tid}))
        loop.run_until_complete(adb.heatmap_run_cache.delete_many({"key": {"$regex": tid}}))
        _restore_db()
        client.close()
        loop.close()


def test_all_mocked_run_does_not_touch_telemetry():
    """DFS unset → mocked payload → zero real calls → counter untouched."""
    from routers.seo_agentic import _generate_heatmap

    loop, client, adb = _loop_and_db()
    tid = f"telemetry-mocked-{uuid.uuid4().hex[:8]}"
    loop.run_until_complete(adb.tenants.insert_one({
        "id": tid, "name": "Telemetry mocked",
        "settings": {"business_card": {"website_url": "https://telemetry.example"}},
    }))
    try:
        with patch("routers.seo_agentic._dfs.get_credentials_or_none",
                    return_value=None):
            hid = f"hm-{uuid.uuid4().hex[:8]}"
            loop.run_until_complete(adb.seo_rank_heatmaps.insert_one({
                "id": hid, "tenant_id": tid, "status": "queued", "points": [],
            }))
            loop.run_until_complete(_generate_heatmap(
                hid, tid, "mocked kw",
                center_lat=40.0, center_lng=-105.0,
                grid_size=3, radius_miles=3.0,
            ))
        t = loop.run_until_complete(adb.tenants.find_one({"id": tid}, {"_id": 0}))
        assert (t.get("metrics") or {}).get("dataforseo_heatmap_calls") is None, (
            "Mocked run MUST NOT create the metrics counter"
        )
    finally:
        loop.run_until_complete(adb.tenants.delete_one({"id": tid}))
        loop.run_until_complete(adb.seo_rank_heatmaps.delete_many({"tenant_id": tid}))
        _restore_db()
        client.close()
        loop.close()
