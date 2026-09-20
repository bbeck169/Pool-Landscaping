"""Phase G5a · Feb-2026 — Geofences API + ingest-hook integration tests.

Runs against the live FastAPI backend on http://localhost:8001.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from passlib.context import CryptContext
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
from utils import new_id, now_iso  # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────────

def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


def _customer_headers() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


def _seed_tech(email: str = "gps_g5a_tech@aquaterra.com") -> dict:
    tech = _sync.users.find_one({"email": email})
    if tech:
        return tech
    tenant = _sync.tenants.find_one({})
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _sync.users.insert_one({
        "id": new_id(), "tenant_id": tenant["id"], "email": email,
        "role": "technician", "name": "G5a GPS Tech",
        "password_hash": pwd.hash("password123"),
        "is_active": True,
    })
    return _sync.users.find_one({"email": email})


def _tech_headers() -> dict:
    _seed_tech()
    return {"Authorization": f"Bearer {_login('gps_g5a_tech@aquaterra.com')}"}


def _tenant_id() -> str:
    return _sync.tenants.find_one({})["id"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ping(lat, lon, ts=None):
    return {"lat": lat, "lon": lon, "accuracy_m": 10.0,
            "source": "foreground", "captured_at": ts or _now_iso()}


def _enable_gps(tid: str) -> None:
    _sync.gps_settings.update_one(
        {"tenant_id": tid},
        {"$set": {"enabled": True, "hr_agreement_ack": True,
                  "ping_interval_foreground_s": 60,
                  "ping_interval_background_s": 300}},
        upsert=True)


def _open_shift(tid: str, uid: str) -> str:
    sid = new_id()
    _sync.time_entries.insert_one({
        "id": sid, "tenant_id": tid, "user_id": uid,
        "clock_in_at": now_iso(), "clock_out_at": None,
        "job_id": new_id()})
    return sid


@pytest.fixture(autouse=True)
def _cleanup():
    tid = _tenant_id()
    tech = _sync.users.find_one({"email": "gps_g5a_tech@aquaterra.com"})
    uid = tech["id"] if tech else None
    # Wipe any G5a-* named fences (test + smoke) to keep tenant clean.
    _sync.geofences.delete_many({"tenant_id": tid,
                                 "name": {"$regex": r"^G5a-"}})
    _sync.geofence_events.delete_many({"tenant_id": tid,
                                       "geofence_name": {"$regex": r"^G5a-"}})
    if uid:
        _sync.time_entries.delete_many({"user_id": uid})
        _sync.gps_pings.delete_many({"user_id": uid})
        _sync.geofence_state.delete_many({"user_id": uid})
        _sync.geofence_events.delete_many({"user_id": uid})
    yield
    _sync.geofences.delete_many({"tenant_id": tid,
                                 "name": {"$regex": r"^G5a-"}})
    _sync.geofence_events.delete_many({"tenant_id": tid,
                                       "geofence_name": {"$regex": r"^G5a-"}})
    if uid:
        _sync.time_entries.delete_many({"user_id": uid})
        _sync.gps_pings.delete_many({"user_id": uid})
        _sync.geofence_state.delete_many({"user_id": uid})
        _sync.geofence_events.delete_many({"user_id": uid})


# ── Tests ───────────────────────────────────────────────────────────

class TestGeofencesCrud:
    def test_403_customer_cannot_create(self):
        r = requests.post(f"{API}/geofences", headers=_customer_headers(),
                          json={"name":"G5a-test-forbid","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,"radius_m":100},
                          timeout=15)
        assert r.status_code == 403

    def test_401_unauthenticated(self):
        r = requests.post(f"{API}/geofences",
                          json={"name":"x","shape":"circle","center_lat":0,
                                "center_lon":0,"radius_m":10}, timeout=15)
        assert r.status_code in (401, 403)

    def test_422_invalid_circle_missing_fields(self):
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-bad-circle","shape":"circle"},
                          timeout=15)
        assert r.status_code == 422

    def test_422_polygon_needs_three_points(self):
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-bad-poly","shape":"polygon",
                                "points":[{"lat":33.5,"lon":-112.0},
                                          {"lat":33.5,"lon":-111.9}]},
                          timeout=15)
        assert r.status_code == 422

    def test_200_create_and_get_circle(self):
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-CircleA","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,"radius_m":150,
                                "alert_on_enter":True,"alert_on_exit":True},
                          timeout=15)
        assert r.status_code == 200, r.text
        fid = r.json()["id"]
        # bbox computed
        assert r.json()["bbox"]["max_lat"] > 33.5
        # Get single with recent_events
        g = requests.get(f"{API}/geofences/{fid}",
                         headers=_admin_headers(), timeout=15)
        assert g.status_code == 200
        assert g.json()["id"] == fid
        assert "recent_events" in g.json()

    def test_200_patch_recomputes_bbox(self):
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-PatchMe","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,"radius_m":100},
                          timeout=15)
        fid = r.json()["id"]
        old_bbox = r.json()["bbox"]
        p = requests.patch(f"{API}/geofences/{fid}", headers=_admin_headers(),
                           json={"radius_m": 500}, timeout=15)
        assert p.status_code == 200
        new_bbox = p.json()["bbox"]
        assert new_bbox["max_lat"] > old_bbox["max_lat"]

    def test_delete_soft_archives(self):
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-DeleteMe","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,"radius_m":100},
                          timeout=15).json()
        d = requests.delete(f"{API}/geofences/{r['id']}",
                            headers=_admin_headers(), timeout=15)
        assert d.status_code == 200
        row = _sync.geofences.find_one({"id": r["id"]})
        assert row["active"] is False

    def test_test_point_utility(self):
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-Utility","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,"radius_m":200},
                          timeout=15).json()
        # Inside
        t = requests.post(f"{API}/geofences/{r['id']}/test-point",
                          headers=_admin_headers(),
                          json={"lat":33.5,"lon":-112.0}, timeout=15).json()
        assert t["inside"] is True
        assert t["distance_m"] == pytest.approx(0.0, abs=0.5)
        # Outside
        t2 = requests.post(f"{API}/geofences/{r['id']}/test-point",
                           headers=_admin_headers(),
                           json={"lat":34.0,"lon":-113.0}, timeout=15).json()
        assert t2["inside"] is False


class TestIngestHook:

    def _seed(self):
        tid = _tenant_id()
        _enable_gps(tid)
        tech = _seed_tech()
        _open_shift(tid, tech["id"])
        return tid, tech

    def test_enter_then_still_inside_then_exit(self):
        tid, tech = self._seed()
        # Fence at (33.5, -112.0) with 200m radius, enter+exit.
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-CrossFlow","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,
                                "radius_m":200,
                                "alert_on_enter":True,"alert_on_exit":True},
                          timeout=15).json()

        h = _tech_headers()
        now = datetime.now(timezone.utc)

        # 1) Enter — first inside ping.
        b1 = requests.post(f"{API}/gps/pings", headers=h,
            json=_ping(33.5, -112.0, now.isoformat()), timeout=15).json()
        assert b1["crossings_detected"] == 1

        # 2) Still inside — 0 new.
        b2 = requests.post(f"{API}/gps/pings", headers=h,
            json=_ping(33.5001, -112.0001, (now + timedelta(seconds=1)).isoformat()),
            timeout=15).json()
        assert b2["crossings_detected"] == 0

        # 3) Exit — outside ping.
        b3 = requests.post(f"{API}/gps/pings", headers=h,
            json=_ping(33.6, -112.1, (now + timedelta(seconds=2)).isoformat()),
            timeout=15).json()
        assert b3["crossings_detected"] == 1

        events = list(_sync.geofence_events.find(
            {"tenant_id": tid, "geofence_id": r["id"]}, {"_id":0}))
        crossings = sorted(e["crossing"] for e in events)
        assert crossings == ["enter", "exit"]

    def test_disabled_fence_ignored(self):
        tid, tech = self._seed()
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-DisabledFence","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,"radius_m":200,
                                "alert_on_enter":True,"active":False},
                          timeout=15).json()
        b = requests.post(f"{API}/gps/pings", headers=_tech_headers(),
            json=_ping(33.5, -112.0), timeout=15).json()
        assert b["crossings_detected"] == 0
        assert _sync.geofence_events.count_documents(
            {"tenant_id": tid, "geofence_id": r["id"]}) == 0

    def test_alert_off_suppresses_event_but_flips_state(self):
        tid, tech = self._seed()
        r = requests.post(f"{API}/geofences", headers=_admin_headers(),
                          json={"name":"G5a-test-QuietEnter","shape":"circle",
                                "center_lat":33.5,"center_lon":-112.0,"radius_m":200,
                                "alert_on_enter":False,"alert_on_exit":True},
                          timeout=15).json()
        h = _tech_headers()
        now = datetime.now(timezone.utc)
        # Enter — suppressed.
        b1 = requests.post(f"{API}/gps/pings", headers=h,
            json=_ping(33.5, -112.0, now.isoformat()), timeout=15).json()
        assert b1["crossings_detected"] == 0
        # Exit — must fire because state flipped even without an event.
        b2 = requests.post(f"{API}/gps/pings", headers=h,
            json=_ping(33.6, -112.1, (now + timedelta(seconds=1)).isoformat()),
            timeout=15).json()
        assert b2["crossings_detected"] == 1
        # Only 1 event total (exit).
        cnt = _sync.geofence_events.count_documents(
            {"tenant_id": tid, "geofence_id": r["id"]})
        assert cnt == 1

    def test_live_positions_carries_recent_crossings(self):
        tid, tech = self._seed()
        requests.post(f"{API}/geofences", headers=_admin_headers(),
                     json={"name":"G5a-test-LivePosFence","shape":"circle",
                           "center_lat":33.5,"center_lon":-112.0,"radius_m":200,
                           "alert_on_enter":True},
                     timeout=15)
        requests.post(f"{API}/gps/pings", headers=_tech_headers(),
            json=_ping(33.5, -112.0), timeout=15)
        lp = requests.get(f"{API}/gps/live-positions",
                          headers=_admin_headers(), timeout=15).json()
        assert "recent_crossings" in lp
        matches = [c for c in lp["recent_crossings"]
                   if c.get("geofence_name") == "G5a-test-LivePosFence"]
        assert len(matches) == 1
        assert matches[0]["crossing"] == "enter"

    def test_ingest_response_shape_backwards_compat(self):
        tid, tech = self._seed()
        # No fences — response must still include crossings_detected=0
        b = requests.post(f"{API}/gps/pings", headers=_tech_headers(),
            json=_ping(33.5, -112.0), timeout=15).json()
        assert b["inserted"] == 1
        assert b.get("crossings_detected", 0) == 0
