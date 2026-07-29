"""Feb-2026 · Tests for ``GET /api/gps/live-positions`` (Phase P2)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

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


def _super_headers() -> dict:
    return _hdr("super@aquaterra.com")


def _tech_headers() -> dict:
    # Pull the first technician from db and log in as them.
    tech = _sync.users.find_one({"role": "technician",
                                 "email": {"$exists": True, "$ne": None}})
    assert tech, "No technician user available in seed"
    return _hdr(tech["email"])


def _customer_headers() -> dict:
    return _hdr("customer@aquaterra.com")


def _tenant_id_of(email: str) -> str:
    u = _sync.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def isolated_settings_and_pings():
    """Snapshot + wipe gps_settings + gps_pings for the aquaterra tenant,
    and any test-only shifts we spin up, so each test starts clean and
    the fixture restores state on teardown."""
    tid = _tenant_id_of("super@aquaterra.com")
    prev_settings = _sync.gps_settings.find_one({"tenant_id": tid})
    prev_pings = list(_sync.gps_pings.find({"tenant_id": tid}))
    test_shift_ids: list = []
    test_ping_ids: list = []
    yield {
        "tid": tid,
        "test_shift_ids": test_shift_ids,
        "test_ping_ids": test_ping_ids,
    }
    # Cleanup: remove test-only data, restore original.
    if test_shift_ids:
        _sync.time_entries.delete_many({"id": {"$in": test_shift_ids}})
    if test_ping_ids:
        _sync.gps_pings.delete_many({"id": {"$in": test_ping_ids}})
    # Restore original gps_settings.
    _sync.gps_settings.delete_many({"tenant_id": tid})
    if prev_settings:
        prev_settings.pop("_id", None)
        _sync.gps_settings.insert_one(prev_settings)
    # Restore any pings that used to be there (typically none in dev).
    _sync.gps_pings.delete_many({"tenant_id": tid,
                                  "id": {"$nin": [p["id"] for p in prev_pings]}})
    for p in prev_pings:
        p.pop("_id", None)
        _sync.gps_pings.update_one({"id": p["id"]}, {"$set": p}, upsert=True)


def _enable_tracking(tid: str):
    _sync.gps_settings.update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid, "enabled": True,
                  "ping_interval_foreground_s": 60,
                  "ping_interval_background_s": 300,
                  "retention_days": 30}},
        upsert=True,
    )


def _disable_tracking(tid: str):
    _sync.gps_settings.update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid, "enabled": False}},
        upsert=True,
    )


def _open_shift(tid: str, uid: str, name: str) -> str:
    sid = f"test-shift-{uid}"
    _sync.time_entries.insert_one({
        "id": sid,
        "tenant_id": tid,
        "user_id": uid,
        "user_name": name,
        "clock_in_at": _iso(datetime.now(timezone.utc) - timedelta(minutes=30)),
        "clock_out_at": None,
        "status": "in_progress",
        "created_at": _iso(datetime.now(timezone.utc)),
    })
    return sid


def _insert_ping(tid: str, uid: str, clock_in_id: str,
                 captured: datetime, lat=33.7, lon=-112.22,
                 acc=15.0) -> str:
    pid = f"test-ping-{uid}-{captured.strftime('%H%M%S')}"
    _sync.gps_pings.insert_one({
        "id": pid,
        "tenant_id": tid,
        "user_id": uid,
        "clock_in_id": clock_in_id,
        "lat": lat, "lon": lon, "accuracy_m": acc,
        "source": "foreground",
        "captured_at": _iso(captured),
        "received_at": _iso(datetime.now(timezone.utc)),
    })
    return pid


# ─── Tests ───────────────────────────────────────────────────────────

def test_live_positions_technician_forbidden():
    r = requests.get(f"{API}/gps/live-positions",
                     headers=_tech_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_live_positions_customer_forbidden():
    r = requests.get(f"{API}/gps/live-positions",
                     headers=_customer_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_live_positions_anon_forbidden():
    r = requests.get(f"{API}/gps/live-positions", timeout=15)
    assert r.status_code in (401, 403), r.text


def test_live_positions_empty_when_tracking_disabled(isolated_settings_and_pings):
    ctx = isolated_settings_and_pings
    _disable_tracking(ctx["tid"])
    r = requests.get(f"{API}/gps/live-positions",
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["positions"] == []
    assert "as_of" in body


def test_live_positions_empty_when_no_open_shifts(isolated_settings_and_pings):
    """Requires enabled tracking + zero currently-open time_entries.
    The seed contains open shifts, so we skip when it does — the other
    tests cover the populated path."""
    ctx = isolated_settings_and_pings
    _enable_tracking(ctx["tid"])
    open_shifts = _sync.time_entries.count_documents(
        {"tenant_id": ctx["tid"], "clock_out_at": None},
    )
    if open_shifts > 0:
        pytest.skip("Seed has open shifts; covered by populated tests.")
    r = requests.get(f"{API}/gps/live-positions",
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["positions"] == []


def test_live_positions_empty_when_shifts_but_no_recent_pings(
    isolated_settings_and_pings,
):
    ctx = isolated_settings_and_pings
    _enable_tracking(ctx["tid"])
    # Seed shifts + zero pings within 5-min window — expect empty.
    r = requests.get(f"{API}/gps/live-positions",
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["positions"] == []


def test_live_positions_returns_recent_ping_row(isolated_settings_and_pings):
    ctx = isolated_settings_and_pings
    tid = ctx["tid"]
    _enable_tracking(tid)

    tech_user = _sync.users.find_one({"tenant_id": tid, "role": "technician"})
    assert tech_user is not None
    uid = tech_user["id"]

    sid = _open_shift(tid, uid, tech_user.get("name") or "Test Tech")
    ctx["test_shift_ids"].append(sid)
    pid = _insert_ping(tid, uid, sid,
                       datetime.now(timezone.utc) - timedelta(seconds=30))
    ctx["test_ping_ids"].append(pid)

    r = requests.get(f"{API}/gps/live-positions",
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    positions = r.json()["positions"]
    ours = [p for p in positions if p["user_id"] == uid]
    assert ours, f"Expected our test tech's ping to appear: {positions}"
    row = ours[0]
    assert 20 <= row["staleness_s"] <= 90, row
    assert row["lat"] and row["lon"]
    assert row["clock_in_id"] == sid


def test_live_positions_excludes_stale_pings(isolated_settings_and_pings):
    ctx = isolated_settings_and_pings
    tid = ctx["tid"]
    _enable_tracking(tid)

    tech_user = _sync.users.find_one({"tenant_id": tid, "role": "technician"})
    assert tech_user is not None
    uid = tech_user["id"]
    sid = _open_shift(tid, uid, tech_user.get("name") or "Test Tech")
    ctx["test_shift_ids"].append(sid)
    pid = _insert_ping(tid, uid, sid,
                       datetime.now(timezone.utc) - timedelta(minutes=10))
    ctx["test_ping_ids"].append(pid)

    r = requests.get(f"{API}/gps/live-positions",
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    ours = [p for p in r.json()["positions"] if p["user_id"] == uid]
    assert not ours, "10-minute-old ping should be filtered out"


def test_live_positions_no_cross_tenant_leak(isolated_settings_and_pings):
    ctx = isolated_settings_and_pings
    my_tid = ctx["tid"]
    _enable_tracking(my_tid)

    # Find a user in a different tenant.
    other = _sync.users.find_one({"role": "technician",
                                   "tenant_id": {"$ne": my_tid}})
    if not other:
        pytest.skip("No cross-tenant tech to test with.")
    _sync.gps_settings.update_one(
        {"tenant_id": other["tenant_id"]},
        {"$set": {"tenant_id": other["tenant_id"], "enabled": True}},
        upsert=True,
    )
    sid = _open_shift(other["tenant_id"], other["id"],
                      other.get("name") or "OtherTech")
    pid = _insert_ping(other["tenant_id"], other["id"], sid,
                       datetime.now(timezone.utc) - timedelta(seconds=45))
    try:
        r = requests.get(f"{API}/gps/live-positions",
                         headers=_super_headers(), timeout=15)
        assert r.status_code == 200, r.text
        ids = {p["user_id"] for p in r.json()["positions"]}
        assert other["id"] not in ids, "Cross-tenant leak!"
    finally:
        _sync.time_entries.delete_one({"id": sid})
        _sync.gps_pings.delete_one({"id": pid})
