"""Phase G4 · Feb-2026 — GPS per-user controls + CSV exports."""
from __future__ import annotations

import asyncio
import os
import uuid
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

_REACT = dotenv_values(Path(__file__).resolve().parents[2]
                         / "frontend" / ".env")
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api")


def _login(email, pw="password123"):
    return requests.post(f"{API}/auth/login",
                            json={"email": email, "password": pw},
                            timeout=15).json()["access_token"]


def _h(email):
    return {"Authorization": f"Bearer {_login(email)}",
            "X-Tenant-Slug": "aquaterra"}


def _super(): return _h("super@aquaterra.com")
def _customer(): return _h("customer@aquaterra.com")


def _tech_email():
    t = _sync.users.find_one({"role": "technician",
                                "email": {"$exists": True, "$ne": None}})
    return t["email"]


def _pick_tech_id() -> str:
    t = _sync.users.find_one({"role": "technician",
                                "tenant_id": _sync.tenants.find_one(
                                    {"slug": "aquaterra"})["id"]},
                               {"_id": 0, "id": 1})
    return t["id"]


_AQUA_TID = None


def _aqua_tid():
    global _AQUA_TID
    if _AQUA_TID is None:
        _AQUA_TID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
    return _AQUA_TID


@pytest.fixture(autouse=True)
def _clean():
    _sync.users.update_many(
        {"tenant_id": _aqua_tid(), "role": "technician"},
        {"$unset": {"gps_tracking_opt_out": "",
                    "gps_retention_override_days": "",
                    "gps_tracking_note": "",
                    "gps_tracking_updated_at": "",
                    "gps_tracking_updated_by_user_id": ""}})
    _sync.audits.delete_many({"kind": "gps_user_override_changed"})
    yield


# ═══════════════════════ Tracking summary ══════════════════════════

class TestTrackingSummary:
    def test_customer_forbidden(self):
        r = requests.get(f"{API}/admin/gps/tracking-summary",
                          headers=_customer(), timeout=15)
        assert r.status_code == 403

    def test_summary_shape_and_counts(self):
        r = requests.get(f"{API}/admin/gps/tracking-summary",
                          headers=_super(), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "tenant_enabled" in body
        assert "hr_agreement_ack" in body
        counts = body["counts"]
        for k in ("total_technicians", "opted_in", "opted_out",
                    "clocked_in_now", "sending_pings_now"):
            assert k in counts
        assert isinstance(body["technicians"], list)


# ═══════════════════════ Patch user override ═══════════════════════

class TestPatchOverride:
    def test_customer_forbidden(self):
        r = requests.patch(f"{API}/admin/gps/users/x",
                            json={"gps_tracking_opt_out": True},
                            headers=_customer(), timeout=15)
        assert r.status_code == 403

    def test_opt_out_toggle_and_audit(self):
        uid = _pick_tech_id()
        r = requests.patch(f"{API}/admin/gps/users/{uid}",
                            json={"gps_tracking_opt_out": True,
                                    "gps_tracking_note": "vacation"},
                            headers=_super(), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] is True
        assert body["user"]["gps_tracking_opt_out"] is True
        # Audit row written.
        a = _sync.audits.find_one(
            {"kind": "gps_user_override_changed",
              "target_user_id": uid}, {"_id": 0})
        assert a is not None
        assert a["after"]["gps_tracking_opt_out"] is True

    def test_retention_range_enforced(self):
        uid = _pick_tech_id()
        # too small
        r = requests.patch(f"{API}/admin/gps/users/{uid}",
                            json={"gps_retention_override_days": 3},
                            headers=_super(), timeout=15)
        assert r.status_code == 422
        # too big
        r2 = requests.patch(f"{API}/admin/gps/users/{uid}",
                             json={"gps_retention_override_days": 400},
                             headers=_super(), timeout=15)
        assert r2.status_code == 422
        # in range
        r3 = requests.patch(f"{API}/admin/gps/users/{uid}",
                             json={"gps_retention_override_days": 14},
                             headers=_super(), timeout=15)
        assert r3.status_code == 200


# ═══════════════════════ Ingest 409 ═══════════════════════════════

class TestIngestOptOut:
    def test_opted_out_returns_409(self):
        tech_email = _tech_email()
        tech = _sync.users.find_one({"email": tech_email})
        uid = tech["id"]
        tid = tech["tenant_id"]
        # Enable tenant + hr ack (so opt-out is the ONLY blocker).
        _sync.gps_settings.update_one(
            {"tenant_id": tid},
            {"$set": {"tenant_id": tid, "enabled": True,
                        "hr_agreement_ack": True,
                        "ping_interval_foreground_s": 60,
                        "ping_interval_background_s": 300,
                        "retention_days": 90}},
            upsert=True)
        # Flip opt-out on
        _sync.users.update_one({"id": uid},
            {"$set": {"gps_tracking_opt_out": True}})
        # Try to POST a ping as this tech.
        h = {"Authorization": f"Bearer {_login(tech_email)}"}
        ts = datetime.now(timezone.utc).isoformat()
        r = requests.post(f"{API}/gps/pings",
            json={"lat": 33.5, "lon": -112.0, "accuracy_m": 10,
                    "source": "foreground", "captured_at": ts},
            headers=h, timeout=15)
        assert r.status_code == 409
        assert "user_opted_out" in r.text
        # Flip back off.
        _sync.users.update_one({"id": uid},
            {"$set": {"gps_tracking_opt_out": False}})


# ═══════════════════════ CSV exports ═══════════════════════════════

class TestCsvExports:
    def test_customer_forbidden(self):
        r = requests.get(
            f"{API}/admin/gps/export/activity.csv",
            params={"from": "2026-02-01T00:00:00Z",
                     "to":   "2026-02-02T00:00:00Z"},
            headers=_customer(), timeout=15)
        assert r.status_code == 403

    def test_range_too_large_400(self):
        r = requests.get(
            f"{API}/admin/gps/export/activity.csv",
            params={"from": "2026-01-01T00:00:00Z",
                     "to":   "2026-06-01T00:00:00Z"},
            headers=_super(), timeout=15)
        assert r.status_code == 400

    def test_activity_csv_headers_and_rows(self):
        tid = _aqua_tid()
        uid_tag = f"g4-tag-{uuid.uuid4().hex[:8]}"
        _sync.driver_stops.delete_many({"id": {"$regex":
                                                    "^g4-csv-"}})
        for i, hh in enumerate((9, 11)):
            _sync.driver_stops.insert_one({
                "id": f"g4-csv-{i}", "tenant_id": tid,
                "user_id": uid_tag,
                "started_at": f"2026-02-01T{hh:02d}:00:00Z",
                "ended_at":   f"2026-02-01T{hh:02d}:15:00Z",
                "duration_s": 900, "radius_m": 50,
                "center_lat": 33.5, "center_lon": -112.0,
                "ping_ids": ["p-a", "p-b"], "address": None,
                "address_status": "no_token",
                "created_at": "2026-02-01T00:00:00Z"})
        r = requests.get(
            f"{API}/admin/gps/export/activity.csv",
            params={"from": "2026-02-01T00:00:00Z",
                     "to":   "2026-02-01T23:59:59Z",
                     "user_id": uid_tag},
            headers=_super(), timeout=30)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers.get("content-disposition", "")
        lines = r.text.strip().split("\n")
        assert lines[0].startswith("user_id,user_name,started_at,ended_at,duration_s")
        assert len(lines) >= 3  # header + 2 rows
        assert uid_tag in lines[1]
        assert "2026-02-01T09:00:00Z" in lines[1]
        _sync.driver_stops.delete_many({"id": {"$regex":
                                                    "^g4-csv-"}})

    def test_pings_csv_headers(self):
        r = requests.get(
            f"{API}/admin/gps/export/pings.csv",
            params={"from": "2026-02-01T00:00:00Z",
                     "to":   "2026-02-01T23:59:59Z"},
            headers=_super(), timeout=30)
        assert r.status_code == 200
        header = r.text.splitlines()[0]
        assert header == ("user_id,user_name,captured_at,lat,lon,"
                            "accuracy_m,source,clock_in_id")


# ═══════════════════════ Purge respects override ═══════════════════

class TestPurgeRespectsOverrides:
    def test_short_override_purges_more(self):
        # This isolates the purge logic on synthetic pings.
        # Seed 2 users; user A has retention_override_days=7,
        # user B relies on tenant default 30.
        tid = _aqua_tid()
        uid_a = f"g4-purge-a-{uuid.uuid4().hex[:6]}"
        uid_b = f"g4-purge-b-{uuid.uuid4().hex[:6]}"
        _sync.users.insert_one({
            "id": uid_a, "tenant_id": tid, "role": "technician",
            "name": "Purge A", "email": f"{uid_a}@x", "deleted_at": None,
            "gps_retention_override_days": 7})
        _sync.users.insert_one({
            "id": uid_b, "tenant_id": tid, "role": "technician",
            "name": "Purge B", "email": f"{uid_b}@x", "deleted_at": None})
        # Force tenant retention_days to 30.
        _sync.gps_settings.update_one(
            {"tenant_id": tid},
            {"$set": {"retention_days": 30}}, upsert=True)
        now = datetime.now(timezone.utc)
        # 5-day-old ping (kept for both)
        # 10-day-old ping (kept for B, purged for A)
        # 40-day-old ping (purged for both)
        for uid in (uid_a, uid_b):
            for age_days in (5, 10, 40):
                _sync.gps_pings.insert_one({
                    "id": str(uuid.uuid4()),
                    "tenant_id": tid, "user_id": uid,
                    "lat": 33.5, "lon": -112.0,
                    "accuracy_m": 10,
                    "source": "foreground",
                    "captured_at": (now - timedelta(days=age_days)).isoformat(),
                    "received_at": now.isoformat(),
                })

        # Invoke the purge coroutine directly using the running
        # backend so we don't have to juggle motor+asyncio here.
        r = requests.post(f"{API}/admin/gps/settings",
                            json={},  # no-op patch, we just need router
                            headers=_super(), timeout=5)
        # There's no HTTP endpoint that triggers purge — use motor via
        # the router-registered scheduler? Simpler: import + run.
        from routers.gps_settings import purge_expired_pings
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            purge_expired_pings())

        remain_a = list(_sync.gps_pings.find(
            {"user_id": uid_a}, {"_id": 0, "captured_at": 1}))
        remain_b = list(_sync.gps_pings.find(
            {"user_id": uid_b}, {"_id": 0, "captured_at": 1}))
        # A (7d override): only the 5-day-old survives.
        assert len(remain_a) == 1
        # B (30d default): 5-day AND 10-day survive.
        assert len(remain_b) == 2
        # Cleanup.
        _sync.gps_pings.delete_many({"user_id": {"$in": [uid_a, uid_b]}})
        _sync.users.delete_many({"id": {"$in": [uid_a, uid_b]}})
