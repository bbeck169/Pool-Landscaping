"""Phase 54g · Feb-2026 — Supplier sync analytics tests.

Populates ``supplier_sync_jobs`` for one supplier with varying
histories and asserts the health signal transitions across the
locked thresholds. Runs against the LIVE backend on localhost:8001.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from tests.conftest import demo_pw


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"
LOCAL_API = "http://localhost:8001/api"
TIMEOUT = 30


def _login(email: str) -> str:
    r = requests.post(f"{LOCAL_API}/auth/login",
                      json={"email": email, "password": demo_pw(email)},
                      timeout=TIMEOUT)
    return r.json()["access_token"]


def _hdr(email: str = "admin@aquaterra.com") -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _sync_collections():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    db = mc[be["DB_NAME"]]
    return mc, db


def _get_supplier_row(slug: str):
    mc, db = _sync_collections()
    try:
        return db.suppliers.find_one({"tenant_id": TID, "slug": slug},
                                     {"_id": 0})
    finally:
        mc.close()


def _seed_jobs(slug: str, jobs: list):
    """Replace all ``supplier_sync_jobs`` for one supplier with the
    given fixture rows."""
    mc, db = _sync_collections()
    try:
        supp = db.suppliers.find_one({"tenant_id": TID, "slug": slug},
                                     {"_id": 0})
        assert supp, f"seed supplier row missing for {slug}"
        db.supplier_sync_jobs.delete_many(
            {"tenant_id": TID, "supplier_id": supp["id"]})
        rows = []
        for j in jobs:
            rows.append({
                "id": str(uuid.uuid4()),
                "tenant_id": TID, "supplier_id": supp["id"],
                **j,
            })
        if rows:
            db.supplier_sync_jobs.insert_many(rows)
        return supp
    finally:
        mc.close()


def _wipe(slug: str):
    mc, db = _sync_collections()
    try:
        supp = db.suppliers.find_one({"tenant_id": TID, "slug": slug},
                                     {"_id": 0})
        if supp:
            db.supplier_sync_jobs.delete_many(
                {"tenant_id": TID, "supplier_id": supp["id"]})
    finally:
        mc.close()


def _iso(offset_hours: float) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(hours=offset_hours)).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Role gate + range clamping
# ═══════════════════════════════════════════════════════════════════
def test_analytics_forbidden_for_manager():
    r = requests.get(f"{LOCAL_API}/suppliers/analytics",
                     headers=_hdr("manager@aquaterra.com"), timeout=TIMEOUT)
    assert r.status_code == 403


def test_analytics_days_clamped_to_90():
    r = requests.get(f"{LOCAL_API}/suppliers/analytics?days=999",
                     headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json()["range_days"] == 90


def test_analytics_zero_runs_returns_healthy_zero_row():
    _wipe("poolcorp")
    r = requests.get(f"{LOCAL_API}/suppliers/analytics?days=7",
                     headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    slugs = {s["slug"]: s for s in body["suppliers"]}
    assert "poolcorp" in slugs
    row = slugs["poolcorp"]
    assert row["total_runs"] == 0
    assert row["health_signal"] == "healthy"  # empty range is not a fault
    assert row["success_count"] == 0
    assert row["error_count"] == 0


# ═══════════════════════════════════════════════════════════════════
# Health-signal transitions
# ═══════════════════════════════════════════════════════════════════
def test_analytics_healthy_when_high_success_rate():
    _seed_jobs("siteone", [
        {"status": "success", "started_at": _iso(-24), "finished_at": _iso(-24),
         "items_added": 50, "items_updated": 3, "items_removed": 0},
        {"status": "success", "started_at": _iso(-48), "finished_at": _iso(-48),
         "items_added": 40, "items_updated": 2, "items_removed": 0},
        {"status": "success", "started_at": _iso(-72), "finished_at": _iso(-72),
         "items_added": 45, "items_updated": 1, "items_removed": 0},
    ])
    try:
        r = requests.get(f"{LOCAL_API}/suppliers/analytics?days=30",
                         headers=_hdr(), timeout=TIMEOUT)
        rows = {s["slug"]: s for s in r.json()["suppliers"]}
        assert rows["siteone"]["health_signal"] == "healthy"
        assert rows["siteone"]["success_rate"] == 1.0
    finally:
        _wipe("siteone")


def test_analytics_critical_when_consecutive_errors():
    _seed_jobs("ewing", [
        {"status": "success", "started_at": _iso(-24 * 5),
         "finished_at": _iso(-24 * 5), "items_added": 10,
         "items_updated": 0, "items_removed": 0},
        {"status": "error", "started_at": _iso(-72),
         "finished_at": _iso(-72), "items_added": 0,
         "items_updated": 0, "items_removed": 0,
         "error_message": "Layout changed — zero cards"},
        {"status": "error", "started_at": _iso(-48),
         "finished_at": _iso(-48), "items_added": 0,
         "items_updated": 0, "items_removed": 0,
         "error_message": "Layout changed — zero cards"},
        {"status": "error", "started_at": _iso(-24),
         "finished_at": _iso(-24), "items_added": 0,
         "items_updated": 0, "items_removed": 0,
         "error_message": "Layout changed — zero cards"},
    ])
    try:
        r = requests.get(f"{LOCAL_API}/suppliers/analytics?days=30",
                         headers=_hdr(), timeout=TIMEOUT)
        rows = {s["slug"]: s for s in r.json()["suppliers"]}
        assert rows["ewing"]["health_signal"] == "critical"
        assert rows["ewing"]["consecutive_errors"] == 3
        assert "Layout changed" in (rows["ewing"]["last_error_message"] or "")
    finally:
        _wipe("ewing")


def test_analytics_warning_when_success_rate_mid_range():
    # 7 success + 3 error interleaved so ``consecutive_errors`` stays
    # < 3 (otherwise the critical branch fires first). Overall 70%
    # success rate → warning band.
    _seed_jobs("heritage", [
        {"status": "error",   "started_at": _iso(-24 * 8),
         "finished_at": _iso(-24 * 8), "items_added": 0,
         "items_updated": 0, "items_removed": 0, "error_message": "Login failed"},
        {"status": "success", "started_at": _iso(-24 * 7),
         "finished_at": _iso(-24 * 7), "items_added": 20,
         "items_updated": 1, "items_removed": 0},
        {"status": "error",   "started_at": _iso(-24 * 6),
         "finished_at": _iso(-24 * 6), "items_added": 0,
         "items_updated": 0, "items_removed": 0, "error_message": "Login failed"},
        {"status": "success", "started_at": _iso(-24 * 5),
         "finished_at": _iso(-24 * 5), "items_added": 20,
         "items_updated": 1, "items_removed": 0},
        {"status": "success", "started_at": _iso(-24 * 4),
         "finished_at": _iso(-24 * 4), "items_added": 20,
         "items_updated": 1, "items_removed": 0},
        {"status": "error",   "started_at": _iso(-24 * 3),
         "finished_at": _iso(-24 * 3), "items_added": 0,
         "items_updated": 0, "items_removed": 0, "error_message": "Login failed"},
        {"status": "success", "started_at": _iso(-24 * 2),
         "finished_at": _iso(-24 * 2), "items_added": 20,
         "items_updated": 1, "items_removed": 0},
        {"status": "success", "started_at": _iso(-24 * 1.5),
         "finished_at": _iso(-24 * 1.5), "items_added": 20,
         "items_updated": 1, "items_removed": 0},
        {"status": "success", "started_at": _iso(-24 * 1.2),
         "finished_at": _iso(-24 * 1.2), "items_added": 20,
         "items_updated": 1, "items_removed": 0},
        {"status": "success", "started_at": _iso(-24 * 0.9),
         "finished_at": _iso(-24 * 0.9), "items_added": 20,
         "items_updated": 1, "items_removed": 0},
    ])
    try:
        r = requests.get(f"{LOCAL_API}/suppliers/analytics?days=30",
                         headers=_hdr(), timeout=TIMEOUT)
        rows = {s["slug"]: s for s in r.json()["suppliers"]}
        # 7 success + 3 error = 70% → warning band
        row = rows["heritage"]
        assert row["health_signal"] == "warning"
        assert 0.60 <= row["success_rate"] <= 0.90
    finally:
        _wipe("heritage")


def test_analytics_sorts_critical_before_healthy():
    _seed_jobs("epoolsupply", [
        {"status": "error", "started_at": _iso(-4),
         "finished_at": _iso(-4), "items_added": 0,
         "items_updated": 0, "items_removed": 0, "error_message": "e1"},
        {"status": "error", "started_at": _iso(-3),
         "finished_at": _iso(-3), "items_added": 0,
         "items_updated": 0, "items_removed": 0, "error_message": "e2"},
        {"status": "error", "started_at": _iso(-2),
         "finished_at": _iso(-2), "items_added": 0,
         "items_updated": 0, "items_removed": 0, "error_message": "e3"},
    ])
    try:
        r = requests.get(f"{LOCAL_API}/suppliers/analytics?days=30",
                         headers=_hdr(), timeout=TIMEOUT)
        body = r.json()
        signals = [s["health_signal"] for s in body["suppliers"]]
        # The critical epoolsupply row must not come after any
        # healthy row.
        crit_idx = next(i for i, s in enumerate(body["suppliers"])
                        if s["slug"] == "epoolsupply")
        for i, sig in enumerate(signals[:crit_idx]):
            assert sig == "critical"
    finally:
        _wipe("epoolsupply")


def test_analytics_daily_trend_buckets_populate():
    _seed_jobs("poolcorp", [
        {"status": "success", "started_at": _iso(-24),
         "finished_at": _iso(-24), "items_added": 5,
         "items_updated": 1, "items_removed": 0},
        {"status": "success", "started_at": _iso(-24),
         "finished_at": _iso(-24), "items_added": 3,
         "items_updated": 0, "items_removed": 0},
    ])
    try:
        r = requests.get(f"{LOCAL_API}/suppliers/analytics?days=7",
                         headers=_hdr(), timeout=TIMEOUT)
        rows = {s["slug"]: s for s in r.json()["suppliers"]}
        trend = rows["poolcorp"]["trend_daily"]
        assert len(trend) == 1
        assert trend[0]["runs"] == 2
        assert trend[0]["success"] == 2
        assert trend[0]["items_added"] == 8
    finally:
        _wipe("poolcorp")
