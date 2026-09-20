"""G2 · Feb-2026 — Integration tests for the stops batch, the query
endpoint, and admin rebuild.

Live-server (requests) paradigm, same as the rest of the suite.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _super_headers():
    return _hdr("super@aquaterra.com")


def _tech_headers():
    tech = _sync.users.find_one({"role": "technician",
                                  "email": {"$exists": True, "$ne": None}})
    return _hdr(tech["email"])


def _customer_headers():
    return _hdr("customer@aquaterra.com")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── Fixture: isolate tenant + tech + seed 30 pings ─────────────────

@pytest.fixture
def seeded_shift():
    """Enable tracking, open a shift, drop 30 pings forming TWO stops:

    * 0–7 min: 8 pings at anchor A → 7-min stop.
    * 8–14 min: 7 pings walking > 200 m away (driving).
    * 15–30 min: 15 pings at anchor B, 60 s apart → 15-min stop.

    Total 30 pings, two expected stops.
    """
    su = _sync.users.find_one({"email": "super@aquaterra.com"},
                                {"_id": 0, "tenant_id": 1})
    tid = su["tenant_id"]

    tech = _sync.users.find_one({"tenant_id": tid, "role": "technician"},
                                  {"_id": 0, "id": 1, "name": 1})
    assert tech, "no technician available in aquaterra seed"
    uid = tech["id"]

    prev_settings = _sync.gps_settings.find_one({"tenant_id": tid})
    _sync.gps_settings.update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid, "enabled": True,
                    "hr_agreement_ack": True,
                    "ping_interval_foreground_s": 60,
                    "ping_interval_background_s": 300,
                    "retention_days": 30,
                    "stop_radius_m": 75,
                    "stop_min_duration_s": 300,
                    "stop_gap_close_s": 120,
                    "stop_batch_window_min": 60}},
        upsert=True,
    )

    now_dt = datetime.now(timezone.utc)
    shift_id = f"g2-test-shift-{uid}"
    _sync.time_entries.insert_one({
        "id": shift_id, "tenant_id": tid,
        "user_id": uid, "user_name": tech.get("name") or "TestTech",
        "clock_in_at": _iso(now_dt - timedelta(minutes=45)),
        "clock_out_at": None, "status": "in_progress",
    })

    def _mk_ping(idx: int, lat: float, lon: float, when: datetime):
        pid = f"g2-test-ping-{uid}-{idx:02d}"
        _sync.gps_pings.insert_one({
            "id": pid, "tenant_id": tid, "user_id": uid,
            "clock_in_id": shift_id,
            "lat": lat, "lon": lon, "accuracy_m": 10.0,
            "source": "foreground",
            "captured_at": _iso(when),
            "received_at": _iso(datetime.now(timezone.utc)),
        })
        return pid

    ping_ids: list = []
    base = now_dt - timedelta(minutes=32)
    # Stop A — 8 pings at (33.700, -112.200)
    for i in range(8):
        ping_ids.append(_mk_ping(i, 33.7000, -112.2000,
                                    base + timedelta(seconds=60 * i)))
    # Driving — 7 pings walking east (< 60 s apart is fine, radius busts it)
    for i in range(7):
        ping_ids.append(_mk_ping(8 + i,
                                    33.7000 + 0.0006 * (i + 1),
                                    -112.2000 + 0.0006 * (i + 1),
                                    base + timedelta(minutes=8, seconds=60 * i)))
    # Stop B — 15 pings at (33.7100, -112.1900) starting min 15
    for i in range(15):
        ping_ids.append(_mk_ping(15 + i, 33.7100, -112.1900,
                                    base + timedelta(minutes=15, seconds=60 * i)))

    _sync.driver_stops.delete_many({"tenant_id": tid, "user_id": uid})
    _sync.gps_stops_batch_meta.delete_many({"tenant_id": tid})

    yield {"tenant_id": tid, "user_id": uid,
            "shift_id": shift_id, "ping_ids": ping_ids,
            "user_name": tech.get("name") or "TestTech"}

    # Teardown
    _sync.gps_pings.delete_many({"id": {"$in": ping_ids}})
    _sync.time_entries.delete_one({"id": shift_id})
    _sync.driver_stops.delete_many({"tenant_id": tid, "user_id": uid})
    _sync.gps_stops_batch_meta.delete_many({"tenant_id": tid})
    _sync.gps_settings.delete_one({"tenant_id": tid})
    if prev_settings:
        prev_settings.pop("_id", None)
        _sync.gps_settings.insert_one(prev_settings)


# ─── Extended settings validation ───────────────────────────────────

def test_settings_accepts_new_tunables():
    r = requests.put(f"{API}/admin/gps/settings",
                        json={"stop_radius_m": 100,
                                "stop_min_duration_s": 600,
                                "stop_gap_close_s": 180,
                                "stop_batch_window_min": 30},
                        headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stop_radius_m"] == 100
    assert body["stop_min_duration_s"] == 600
    assert body["stop_gap_close_s"] == 180
    assert body["stop_batch_window_min"] == 30


def test_settings_rejects_out_of_range_radius():
    r = requests.put(f"{API}/admin/gps/settings",
                        json={"stop_radius_m": 5},
                        headers=_super_headers(), timeout=15)
    assert r.status_code == 422


def test_settings_rejects_out_of_range_duration():
    r = requests.put(f"{API}/admin/gps/settings",
                        json={"stop_min_duration_s": 30},
                        headers=_super_headers(), timeout=15)
    assert r.status_code == 422


# ─── Batch processor + query endpoint ───────────────────────────────

def _run_batch_via_api() -> dict:
    """Trigger the stops-batch cron via the live-server admin endpoint
    so Motor's client stays on the app's own event loop (calling
    ``asyncio.run(run_gps_stops_batch())`` from within a pytest process
    creates a fresh loop and Motor complains that the loop is closed)."""
    r = requests.post(f"{API}/admin/gps/stops/run-batch",
                       headers=_super_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def test_batch_emits_expected_stops(seeded_shift):
    result = _run_batch_via_api()
    assert result["stops_emitted"] >= 2, result
    stops = list(_sync.driver_stops.find(
        {"tenant_id": seeded_shift["tenant_id"],
          "user_id": seeded_shift["user_id"]},
        {"_id": 0},
    ).sort("started_at", 1))
    assert len(stops) == 2, [s.get("duration_s") for s in stops]
    assert stops[0]["duration_s"] >= 300
    assert stops[1]["duration_s"] >= 300
    # Centres are close to the seeded anchors.
    assert abs(stops[0]["center_lat"] - 33.7000) < 0.001
    assert abs(stops[1]["center_lat"] - 33.7100) < 0.001


def test_batch_is_idempotent(seeded_shift):
    _run_batch_via_api()
    count1 = _sync.driver_stops.count_documents(
        {"tenant_id": seeded_shift["tenant_id"],
          "user_id": seeded_shift["user_id"]})
    _run_batch_via_api()
    count2 = _sync.driver_stops.count_documents(
        {"tenant_id": seeded_shift["tenant_id"],
          "user_id": seeded_shift["user_id"]})
    assert count1 == count2, f"expected idempotent, got {count1} → {count2}"


def test_query_endpoint_returns_stops(seeded_shift):
    _run_batch_via_api()

    now_dt = datetime.now(timezone.utc)
    r = requests.get(
        f"{API}/gps/stops",
        params={"user_id": seeded_shift["user_id"],
                  "from": _iso(now_dt - timedelta(hours=2)),
                  "to": _iso(now_dt + timedelta(minutes=1))},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == seeded_shift["user_id"]
    assert body["count"] >= 2
    for s in body["stops"]:
        for k in ("id", "started_at", "ended_at", "duration_s",
                    "center_lat", "center_lon", "ping_count"):
            assert k in s, s


def test_query_rejects_wide_window():
    now_dt = datetime.now(timezone.utc)
    r = requests.get(
        f"{API}/gps/stops",
        params={"user_id": "any",
                  "from": _iso(now_dt - timedelta(days=60)),
                  "to": _iso(now_dt)},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 422


def test_query_forbidden_for_tech():
    now_dt = datetime.now(timezone.utc)
    r = requests.get(
        f"{API}/gps/stops",
        params={"user_id": "any",
                  "from": _iso(now_dt - timedelta(hours=1)),
                  "to": _iso(now_dt)},
        headers=_tech_headers(), timeout=15,
    )
    assert r.status_code == 403


def test_query_forbidden_for_customer():
    now_dt = datetime.now(timezone.utc)
    r = requests.get(
        f"{API}/gps/stops",
        params={"user_id": "any",
                  "from": _iso(now_dt - timedelta(hours=1)),
                  "to": _iso(now_dt)},
        headers=_customer_headers(), timeout=15,
    )
    assert r.status_code == 403


def test_rebuild_wipes_and_recreates(seeded_shift):
    _run_batch_via_api()
    initial = _sync.driver_stops.count_documents(
        {"tenant_id": seeded_shift["tenant_id"],
          "user_id": seeded_shift["user_id"]})
    assert initial >= 2

    now_dt = datetime.now(timezone.utc)
    r = requests.post(
        f"{API}/admin/gps/stops/rebuild",
        json={"user_id": seeded_shift["user_id"],
                "from": _iso(now_dt - timedelta(hours=2)),
                "to": _iso(now_dt + timedelta(minutes=1))},
        headers=_super_headers(), timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stops_created"] == initial

    # And post-rebuild the collection still contains 2 stops.
    after = _sync.driver_stops.count_documents(
        {"tenant_id": seeded_shift["tenant_id"],
          "user_id": seeded_shift["user_id"]})
    assert after == initial


def test_rebuild_forbidden_for_tech():
    r = requests.post(f"{API}/admin/gps/stops/rebuild",
                        json={}, headers=_tech_headers(), timeout=15)
    assert r.status_code == 403


def test_cross_tenant_isolation(seeded_shift):
    """A user from tenant B must not see stops from tenant A even if
    seeded_shift emitted rows for tenant A."""
    _run_batch_via_api()
    # Find a super from another tenant
    other = _sync.users.find_one(
        {"role": "super_admin",
          "tenant_id": {"$ne": seeded_shift["tenant_id"]},
          "email": {"$exists": True}})
    if not other:
        pytest.skip("no cross-tenant super to test with")
    tok = _login(other["email"])
    now_dt = datetime.now(timezone.utc)
    r = requests.get(
        f"{API}/gps/stops",
        params={"user_id": seeded_shift["user_id"],
                  "from": _iso(now_dt - timedelta(hours=2)),
                  "to": _iso(now_dt + timedelta(minutes=1))},
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )
    # Either 404 (user_not_found in caller's tenant) or empty stops list.
    assert r.status_code in (200, 404), r.text
    if r.status_code == 200:
        assert r.json()["count"] == 0
