"""G1 · GPS Ingest integration tests (live server).

Cases:
1. 409 when tracking disabled.
2. 409 when user not clocked in.
3. 200 when both green — ping row in db.gps_pings with correct fields.
4. 413 when batch > 60.
5. 401 when unauthenticated.
6. GET /api/gps/config returns settings.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from utils import new_id, now_iso


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


def _tech_headers() -> dict:
    """Login as a technician — create one if needed."""
    email = "gps_test_tech@aquaterra.com"
    try:
        return {"Authorization": f"Bearer {_login(email)}"}
    except Exception:
        # Create a technician user
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        tenant = _sync.tenants.find_one({})
        tid = tenant["id"]
        uid = new_id()
        _sync.users.insert_one({
            "id": uid, "tenant_id": tid, "email": email,
            "role": "technician", "name": "GPS Test Tech",
            "password_hash": pwd_context.hash("password123"),
            "is_active": True,
        })
        return {"Authorization": f"Bearer {_login(email)}"}


def _get_tech_user():
    return _sync.users.find_one({"email": "gps_test_tech@aquaterra.com"})


def _ping_body(ts: str | None = None):
    return {
        "lat": 33.4484,
        "lon": -112.0740,
        "accuracy_m": 10.0,
        "source": "foreground",
        "captured_at": ts or datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean test data before/after each test."""
    tech = _sync.users.find_one({"email": "gps_test_tech@aquaterra.com"})
    if tech:
        _sync.time_entries.delete_many({"user_id": tech["id"]})
        _sync.gps_pings.delete_many({"user_id": tech["id"]})
    yield
    if tech:
        _sync.time_entries.delete_many({"user_id": tech["id"]})
        _sync.gps_pings.delete_many({"user_id": tech["id"]})


class TestGpsIngest:
    """GPS Ping ingest endpoint tests."""

    def test_401_unauthenticated(self):
        r = requests.post(f"{API}/gps/pings", json=_ping_body(), timeout=15)
        assert r.status_code in (401, 403)

    def test_409_tracking_disabled(self):
        headers = _tech_headers()
        # Make sure GPS is disabled
        _sync.gps_settings.update_many({}, {"$set": {"enabled": False}})
        r = requests.post(f"{API}/gps/pings", json=_ping_body(),
                          headers=headers, timeout=15)
        assert r.status_code == 409
        body = r.json()
        detail = body.get("detail", body)
        assert detail.get("error") == "tracking_not_enabled"

    def test_409_not_clocked_in(self):
        headers = _tech_headers()
        tech = _get_tech_user()
        # Enable GPS settings
        tenant = _sync.tenants.find_one({})
        _sync.gps_settings.update_one(
            {"tenant_id": tenant["id"]},
            {"$set": {"enabled": True, "hr_agreement_ack": True}},
            upsert=True,
        )
        # Ensure no open shift
        _sync.time_entries.delete_many({"user_id": tech["id"], "clock_out_at": None})
        r = requests.post(f"{API}/gps/pings", json=_ping_body(),
                          headers=headers, timeout=15)
        assert r.status_code == 409
        body = r.json()
        detail = body.get("detail", body)
        assert detail.get("error") == "not_clocked_in"

    def test_200_ping_inserted(self):
        headers = _tech_headers()
        tech = _get_tech_user()
        tenant = _sync.tenants.find_one({})
        tid = tenant["id"]
        uid = tech["id"]

        # Enable GPS
        _sync.gps_settings.update_one(
            {"tenant_id": tid},
            {"$set": {"enabled": True, "hr_agreement_ack": True,
                      "ping_interval_foreground_s": 60,
                      "ping_interval_background_s": 300}},
            upsert=True,
        )
        # Create an open shift
        shift_id = new_id()
        _sync.time_entries.insert_one({
            "id": shift_id, "tenant_id": tid, "user_id": uid,
            "clock_in_at": now_iso(), "clock_out_at": None,
            "job_id": new_id(),
        })

        ts = datetime.now(timezone.utc).isoformat()
        r = requests.post(f"{API}/gps/pings", json=_ping_body(ts),
                          headers=headers, timeout=15)
        assert r.status_code == 200, f"unexpected {r.status_code}: {r.text}"
        body = r.json()
        assert body["inserted"] == 1
        assert body["clock_in_id"] == shift_id

        # Verify row in DB
        row = _sync.gps_pings.find_one({"tenant_id": tid, "user_id": uid})
        assert row is not None
        assert row["lat"] == 33.4484
        assert row["lon"] == -112.0740
        assert row["clock_in_id"] == shift_id

    def test_413_batch_too_large(self):
        headers = _tech_headers()
        tech = _get_tech_user()
        tenant = _sync.tenants.find_one({})
        tid = tenant["id"]
        uid = tech["id"]

        # Enable GPS + create shift
        _sync.gps_settings.update_one(
            {"tenant_id": tid},
            {"$set": {"enabled": True, "hr_agreement_ack": True}},
            upsert=True,
        )
        _sync.time_entries.insert_one({
            "id": new_id(), "tenant_id": tid, "user_id": uid,
            "clock_in_at": now_iso(), "clock_out_at": None,
            "job_id": new_id(),
        })

        ts = datetime.now(timezone.utc).isoformat()
        pings = [{"lat": 33.0, "lon": -112.0, "accuracy_m": 5,
                   "source": "foreground", "captured_at": ts}
                  for _ in range(61)]
        r = requests.post(f"{API}/gps/pings", json={"pings": pings},
                          headers=headers, timeout=15)
        assert r.status_code == 413

    def test_gps_config(self):
        headers = _tech_headers()
        tenant = _sync.tenants.find_one({})
        _sync.gps_settings.update_one(
            {"tenant_id": tenant["id"]},
            {"$set": {"enabled": True, "ping_interval_foreground_s": 45,
                      "ping_interval_background_s": 120}},
            upsert=True,
        )
        r = requests.get(f"{API}/gps/config", headers=headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["ping_interval_foreground_s"] == 45
        assert body["ping_interval_background_s"] == 120
