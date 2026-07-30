"""Phase G5c · Feb-2026 — GET /api/gps/route playback metadata.

Verifies the three additive fields (``playback_duration_s``,
``first_ping_at``, ``last_ping_at``) added for the Route Replay UI.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
from utils import new_id  # noqa: E402


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


TAG = "G5c-replay-test"
UID = "tech-g5c-replay"


@pytest.fixture(autouse=True)
def _cleanup():
    tid = _sync.tenants.find_one({})["id"]
    _sync.gps_pings.delete_many({"tenant_id": tid, "user_id": UID})
    _sync.driver_stops.delete_many({"tenant_id": tid, "user_id": UID,
                                     "source": "g5c-replay"})
    if not _sync.users.find_one({"id": UID}):
        _sync.users.insert_one({"id": UID, "tenant_id": tid,
                                 "email": f"{UID}@aquaterra.com",
                                 "role": "technician",
                                 "name": "G5c Replay Tech",
                                 "is_active": True})
    yield
    _sync.gps_pings.delete_many({"tenant_id": tid, "user_id": UID})
    _sync.driver_stops.delete_many({"tenant_id": tid, "user_id": UID,
                                     "source": "g5c-replay"})


def _seed_pings(tid, day, n=5):
    base = datetime.fromisoformat(f"{day}T09:00:00+00:00")
    pings = []
    for i in range(n):
        pings.append({
            "id": new_id(), "tenant_id": tid, "user_id": UID,
            "lat": 33.5 + 0.0002 * i,
            "lon": -112.0 + 0.0002 * i,
            "accuracy_m": 10.0, "source": "foreground",
            "captured_at": (base + timedelta(seconds=30 * i))
                            .isoformat().replace("+00:00", "Z"),
            "received_at": (base + timedelta(seconds=30 * i))
                            .isoformat().replace("+00:00", "Z"),
        })
    _sync.gps_pings.insert_many(pings)
    return pings


class TestPlaybackMeta:

    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def test_fields_present_with_pings(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _seed_pings(tid, day, n=5)
        r = requests.get(
            f"{API}/gps/route?user_id={UID}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "playback_duration_s" in body
        assert "first_ping_at" in body
        assert "last_ping_at" in body
        # 5 pings, 30s apart → 120s span.
        assert body["playback_duration_s"] == 120
        assert body["first_ping_at"].startswith(f"{day}T09:00:00")
        assert body["last_ping_at"].startswith(f"{day}T09:02:00")
        assert len(body["pings"]) == 5

    def test_zero_pings_returns_null_and_zero(self):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(
            f"{API}/gps/route?user_id={UID}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["pings"] == []
        assert body["first_ping_at"] is None
        assert body["last_ping_at"] is None
        assert body["playback_duration_s"] == 0

    def test_single_ping_returns_duration_zero(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _seed_pings(tid, day, n=1)
        r = requests.get(
            f"{API}/gps/route?user_id={UID}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z",
            headers=_admin_headers(), timeout=15)
        body = r.json()
        assert len(body["pings"]) == 1
        assert body["first_ping_at"] == body["last_ping_at"]
        assert body["playback_duration_s"] == 0

    def test_search_filters_still_work_with_playback_meta(self):
        """Ensure the addendum #2 filters didn't break when we added
        the playback meta fields (they wrap the same return dict)."""
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _seed_pings(tid, day, n=3)
        r = requests.get(
            f"{API}/gps/route?user_id={UID}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z"
            f"&q_customer=NoSuchName",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        # No stops match → stops list is empty but pings + meta remain.
        body = r.json()
        assert body["stops"] == []
        assert len(body["pings"]) == 3
        assert body["playback_duration_s"] == 60  # 3 pings, 30s apart
