"""G0 · Feb-2026 — GPS driver-activity settings + purge tests."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
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


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


def _customer_headers() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


def _server_up() -> bool:
    try:
        requests.get(f"{API}/", timeout=2); return True
    except Exception:
        return False


needs_server = pytest.mark.skipif(
    not _server_up(), reason="backend server not reachable on :8001")


@pytest.fixture(autouse=True)
def _reset_settings():
    """Drop the tenant's settings row between tests so defaults are
    re-created cleanly."""
    tid = "3814833a-dd0d-4bd9-90ea-351c24924649"
    _sync.gps_settings.delete_many({"tenant_id": tid})
    yield
    _sync.gps_settings.delete_many({"tenant_id": tid})


# ══════════════════════════════════════════════════════════════════
# GET / defaults
# ══════════════════════════════════════════════════════════════════
@needs_server
def test_first_get_creates_default_row():
    r = requests.get(f"{API}/admin/gps/settings",
                       headers=_admin_headers(), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["hr_agreement_ack"] is False
    assert body["ping_interval_foreground_s"] == 60
    assert body["ping_interval_background_s"] == 300
    assert body["retention_days"] == 90
    assert body["geocoder"] == "mapbox"
    # Row persists in Mongo.
    row = _sync.gps_settings.find_one(
        {"tenant_id": body["tenant_id"]}, {"_id": 0})
    assert row is not None


# ══════════════════════════════════════════════════════════════════
# PUT validation
# ══════════════════════════════════════════════════════════════════
@needs_server
def test_put_enabled_without_ack_returns_422():
    requests.get(f"{API}/admin/gps/settings",
                  headers=_admin_headers(), timeout=15)
    r = requests.put(f"{API}/admin/gps/settings",
                       headers=_admin_headers(),
                       json={"enabled": True}, timeout=15)
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "hr_agreement_required"


@needs_server
def test_put_enabled_with_ack_same_payload_succeeds():
    r = requests.put(f"{API}/admin/gps/settings",
                       headers=_admin_headers(),
                       json={"hr_agreement_ack": True, "enabled": True,
                              "ping_interval_foreground_s": 60},
                       timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["hr_agreement_ack"] is True


@needs_server
def test_put_out_of_range_fg_interval_returns_422():
    r = requests.put(f"{API}/admin/gps/settings",
                       headers=_admin_headers(),
                       json={"ping_interval_foreground_s": 5},
                       timeout=15)
    assert r.status_code == 422


@needs_server
def test_put_out_of_range_bg_interval_returns_422():
    r = requests.put(f"{API}/admin/gps/settings",
                       headers=_admin_headers(),
                       json={"ping_interval_background_s": 999999},
                       timeout=15)
    assert r.status_code == 422


@needs_server
def test_put_out_of_range_retention_returns_422():
    r = requests.put(f"{API}/admin/gps/settings",
                       headers=_admin_headers(),
                       json={"retention_days": 1},
                       timeout=15)
    assert r.status_code == 422


@needs_server
def test_put_bad_geocoder_returns_422():
    r = requests.put(f"{API}/admin/gps/settings",
                       headers=_admin_headers(),
                       json={"geocoder": "google"},
                       timeout=15)
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "invalid_geocoder"


# ══════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════
@needs_server
def test_customer_get_returns_403():
    r = requests.get(f"{API}/admin/gps/settings",
                       headers=_customer_headers(), timeout=15)
    assert r.status_code == 403


@needs_server
def test_customer_put_returns_403():
    r = requests.put(f"{API}/admin/gps/settings",
                       headers=_customer_headers(),
                       json={"enabled": True}, timeout=15)
    assert r.status_code == 403


@needs_server
def test_unauth_returns_401_or_403():
    r = requests.get(f"{API}/admin/gps/settings", timeout=15)
    assert r.status_code in (401, 403)


# ══════════════════════════════════════════════════════════════════
# Purge cron
# ══════════════════════════════════════════════════════════════════
def test_purge_on_empty_collection_completes():
    from routers.gps_settings import purge_expired_pings
    result = asyncio.get_event_loop().run_until_complete(
        purge_expired_pings())
    assert isinstance(result, dict)
    assert "purged" in result and result["purged"] >= 0
    assert "tenants" in result


def test_purge_removes_expired_and_keeps_recent():
    """Seed 2 stale + 2 recent pings, run purge, verify only recent
    survive."""
    from routers.gps_settings import purge_expired_pings
    tid = "3814833a-dd0d-4bd9-90ea-351c24924649"
    # Ensure a settings row exists with default retention (90d).
    _sync.gps_settings.delete_many({"tenant_id": tid})
    _sync.gps_settings.insert_one({
        "id": uuid.uuid4().hex, "tenant_id": tid, "enabled": False,
        "hr_agreement_ack": True, "retention_days": 90,
        "ping_interval_foreground_s": 60,
        "ping_interval_background_s": 300, "geocoder": "mapbox",
    })
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(days=200)).isoformat()
    recent = (now - timedelta(days=1)).isoformat()
    seed_ids = [f"TEST-g0-{uuid.uuid4().hex[:6]}" for _ in range(4)]
    _sync.gps_pings.insert_many([
        {"id": seed_ids[0], "tenant_id": tid, "user_id": "u1",
          "lat": 0, "lon": 0, "captured_at": stale,
          "received_at": stale, "source": "foreground"},
        {"id": seed_ids[1], "tenant_id": tid, "user_id": "u1",
          "lat": 0, "lon": 0, "captured_at": stale,
          "received_at": stale, "source": "background"},
        {"id": seed_ids[2], "tenant_id": tid, "user_id": "u1",
          "lat": 0, "lon": 0, "captured_at": recent,
          "received_at": recent, "source": "foreground"},
        {"id": seed_ids[3], "tenant_id": tid, "user_id": "u1",
          "lat": 0, "lon": 0, "captured_at": recent,
          "received_at": recent, "source": "foreground"},
    ])
    try:
        asyncio.get_event_loop().run_until_complete(purge_expired_pings())
        remaining = list(_sync.gps_pings.find(
            {"id": {"$in": seed_ids}}, {"_id": 0, "id": 1}))
        remaining_ids = {r["id"] for r in remaining}
        assert seed_ids[0] not in remaining_ids
        assert seed_ids[1] not in remaining_ids
        assert seed_ids[2] in remaining_ids
        assert seed_ids[3] in remaining_ids
    finally:
        _sync.gps_pings.delete_many({"id": {"$in": seed_ids}})
        _sync.gps_settings.delete_many({"tenant_id": tid})
