"""G1 · GPS Ingest integration tests (live server + requests).

Cases:
 1. 401 unauthenticated.
 2. 409 tracking_disabled when gps_settings.enabled=false.
 3. 409 not_clocked_in when no open time_entries row.
 4. 200 single ping → inserted=1, dedup_count=0, clock_in_id present, DB row correct.
 5. 200 batch of 3 pings → inserted=3.
 6. 200 dedup — repost same batch → inserted=0, dedup_count=3.
 7. 413 when batch is 61 pings.
 8. 422 when source="foo".
 9. 422 when captured_at is >24 h old.
10. 403 when customer role tries to POST.
11. GET /api/gps/config returns only the three permitted keys.
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
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from utils import new_id, now_iso


# ── Helpers ──────────────────────────────────────────────────────────

def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


def _customer_headers() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


def _tech_headers() -> dict:
    """Login as a technician — seed one if needed."""
    email = "gps_g1_tech@aquaterra.com"
    try:
        return {"Authorization": f"Bearer {_login(email)}"}
    except Exception:
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        tenant = _sync.tenants.find_one({})
        _sync.users.insert_one({
            "id": new_id(), "tenant_id": tenant["id"], "email": email,
            "role": "technician", "name": "G1 GPS Tech",
            "password_hash": pwd_ctx.hash("password123"),
            "is_active": True,
        })
        return {"Authorization": f"Bearer {_login(email)}"}


def _tech_user():
    return _sync.users.find_one({"email": "gps_g1_tech@aquaterra.com"})


def _tenant_id():
    return _sync.tenants.find_one({})["id"]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _ping(ts: str | None = None):
    return {
        "lat": 33.4484,
        "lon": -112.074,
        "accuracy_m": 10.0,
        "source": "foreground",
        "captured_at": ts or _now_iso(),
    }


def _enable_gps(tid: str):
    _sync.gps_settings.update_one(
        {"tenant_id": tid},
        {"$set": {"enabled": True, "hr_agreement_ack": True,
                  "ping_interval_foreground_s": 60,
                  "ping_interval_background_s": 300}},
        upsert=True,
    )


def _disable_gps(tid: str):
    _sync.gps_settings.update_one(
        {"tenant_id": tid},
        {"$set": {"enabled": False}},
        upsert=True,
    )


def _create_shift(tid: str, uid: str) -> str:
    sid = new_id()
    _sync.time_entries.insert_one({
        "id": sid, "tenant_id": tid, "user_id": uid,
        "clock_in_at": now_iso(), "clock_out_at": None,
        "job_id": new_id(),
    })
    return sid


@pytest.fixture(autouse=True)
def _cleanup():
    """Wipe test artifacts before/after each test."""
    tech = _sync.users.find_one({"email": "gps_g1_tech@aquaterra.com"})
    uid = tech["id"] if tech else None
    if uid:
        _sync.time_entries.delete_many({"user_id": uid})
        _sync.gps_pings.delete_many({"user_id": uid})
    yield
    if uid:
        _sync.time_entries.delete_many({"user_id": uid})
        _sync.gps_pings.delete_many({"user_id": uid})


# ── Tests ────────────────────────────────────────────────────────────

class TestGpsIngest:

    # 1. Unauthenticated → 401/403
    def test_401_unauthenticated(self):
        r = requests.post(f"{API}/gps/pings", json=_ping(), timeout=15)
        assert r.status_code in (401, 403)

    # 2. Tracking disabled → 409
    def test_409_tracking_disabled(self):
        h = _tech_headers()
        tid = _tenant_id()
        tech = _tech_user()
        _disable_gps(tid)
        # Need a shift for the "not_clocked_in" check to not fire first
        _create_shift(tid, tech["id"])
        r = requests.post(f"{API}/gps/pings", json=_ping(), headers=h, timeout=15)
        assert r.status_code == 409
        body = r.json()
        detail = body.get("detail", body)
        assert detail.get("error") == "tracking_disabled"

    # 3. Not clocked in → 409
    def test_409_not_clocked_in(self):
        h = _tech_headers()
        tid = _tenant_id()
        _enable_gps(tid)
        tech = _tech_user()
        _sync.time_entries.delete_many({"user_id": tech["id"], "clock_out_at": None})
        r = requests.post(f"{API}/gps/pings", json=_ping(), headers=h, timeout=15)
        assert r.status_code == 409
        body = r.json()
        detail = body.get("detail", body)
        assert detail.get("error") == "not_clocked_in"

    # 4. Single ping → 200
    def test_200_single_ping(self):
        h = _tech_headers()
        tid = _tenant_id()
        tech = _tech_user()
        _enable_gps(tid)
        sid = _create_shift(tid, tech["id"])

        ts = _now_iso()
        r = requests.post(f"{API}/gps/pings", json=_ping(ts), headers=h, timeout=15)
        assert r.status_code == 200, f"Unexpected {r.status_code}: {r.text}"
        body = r.json()
        assert body["inserted"] == 1
        assert body["dedup_count"] == 0
        assert body["clock_in_id"] == sid

        # Verify DB row
        row = _sync.gps_pings.find_one({"user_id": tech["id"], "captured_at": ts})
        assert row is not None
        assert row["tenant_id"] == tid
        assert row["user_id"] == tech["id"]
        assert row["received_at"] is not None
        assert row["lat"] == 33.4484
        assert row["accuracy_m"] == 10.0

    # 5. Batch of 3 → inserted=3
    def test_200_batch_three(self):
        h = _tech_headers()
        tid = _tenant_id()
        tech = _tech_user()
        _enable_gps(tid)
        _create_shift(tid, tech["id"])

        pings = []
        for i in range(3):
            ts = (datetime.now(timezone.utc) - timedelta(seconds=i * 10)).isoformat()
            pings.append({**_ping(ts), "lat": 33.0 + i * 0.001})
        r = requests.post(f"{API}/gps/pings", json={"pings": pings},
                          headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json()["inserted"] == 3

    # 6. Dedup — repost same batch → inserted=0, dedup_count=3
    def test_200_dedup(self):
        h = _tech_headers()
        tid = _tenant_id()
        tech = _tech_user()
        _enable_gps(tid)
        _create_shift(tid, tech["id"])

        pings = []
        for i in range(3):
            ts = (datetime.now(timezone.utc) - timedelta(seconds=100 + i * 10)).isoformat()
            pings.append({**_ping(ts)})

        # First POST
        r1 = requests.post(f"{API}/gps/pings", json={"pings": pings},
                           headers=h, timeout=15)
        assert r1.status_code == 200
        assert r1.json()["inserted"] == 3

        # Re-POST same pings
        r2 = requests.post(f"{API}/gps/pings", json={"pings": pings},
                           headers=h, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["inserted"] == 0
        assert r2.json()["dedup_count"] == 3

    # 7. Batch > 60 → 413
    def test_413_batch_too_large(self):
        h = _tech_headers()
        tid = _tenant_id()
        tech = _tech_user()
        _enable_gps(tid)
        _create_shift(tid, tech["id"])

        pings = []
        for i in range(61):
            ts = (datetime.now(timezone.utc) - timedelta(seconds=i)).isoformat()
            pings.append(_ping(ts))
        r = requests.post(f"{API}/gps/pings", json={"pings": pings},
                          headers=h, timeout=15)
        assert r.status_code == 413

    # 8. Invalid source → 422
    def test_422_bad_source(self):
        h = _tech_headers()
        tid = _tenant_id()
        tech = _tech_user()
        _enable_gps(tid)
        _create_shift(tid, tech["id"])

        bad = _ping()
        bad["source"] = "foo"
        r = requests.post(f"{API}/gps/pings", json={"pings": [bad]},
                          headers=h, timeout=15)
        assert r.status_code == 422

    # 9. Stale captured_at (>24 h ago) → 422
    def test_422_stale_ping(self):
        h = _tech_headers()
        tid = _tenant_id()
        tech = _tech_user()
        _enable_gps(tid)
        _create_shift(tid, tech["id"])

        stale_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        bad = _ping(stale_ts)
        r = requests.post(f"{API}/gps/pings", json={"pings": [bad]},
                          headers=h, timeout=15)
        assert r.status_code == 422

    # 10. Customer role → 403
    def test_403_customer_role(self):
        h = _customer_headers()
        r = requests.post(f"{API}/gps/pings", json=_ping(), headers=h, timeout=15)
        assert r.status_code == 403

    # 11. GET /api/gps/config — only three keys
    def test_gps_config_keys(self):
        h = _tech_headers()
        tid = _tenant_id()
        _sync.gps_settings.update_one(
            {"tenant_id": tid},
            {"$set": {"enabled": True, "ping_interval_foreground_s": 45,
                      "ping_interval_background_s": 120,
                      "hr_agreement_ack": True, "geocoder": "mapbox",
                      "retention_days": 90, "updated_by_user_id": "x"}},
            upsert=True,
        )
        r = requests.get(f"{API}/gps/config", headers=h, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"enabled", "ping_interval_foreground_s",
                                     "ping_interval_background_s"}
        assert body["enabled"] is True
        assert body["ping_interval_foreground_s"] == 45
        assert body["ping_interval_background_s"] == 120
