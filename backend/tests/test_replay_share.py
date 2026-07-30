"""Phase 2 · Feb-2026 — Route Replay share-link tests.

Coverage
--------
1. create → 200 with share_id, share_url, expires_at ~24h out
2. list → shows the new share, view_count starts at 0
3. public GET → 200 with read_only=True, no PII, view_count increments
4. revoke → subsequent public GET returns 410
5. expired share → returns 410 (fast-forward via monkeypatched _now)
6. tenant scope — a share created by tenant A cannot be revoked by tenant B
7. burst → 40 GETs in a window return ≥10 × 429
"""
from __future__ import annotations

import concurrent.futures
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

API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"


def _login_super() -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": "super@aquaterra.com",
                              "password": "password123"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _tech_id() -> str:
    u = _sync.users.find_one({"email": "landscaper@aquaterra.com"}, {"id": 1})
    assert u, "seed user landscaper@aquaterra.com must exist"
    return u["id"]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cleanup(share_id: str) -> None:
    _sync.route_replay_shares.delete_many({"share_id": share_id})


# ── 1 & 2 · create + list ──────────────────────────────────────────
def test_create_and_list_share():
    tok = _login_super()
    tech, date = _tech_id(), _today()
    r = requests.post(f"{API}/gps/replay/share",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"user_id": tech, "replay_date": date}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    sid = body["share_id"]
    try:
        assert len(sid) == 16
        assert body["share_url"].endswith(f"/replay/{sid}")
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta_h = (exp - now).total_seconds() / 3600
        assert 23 <= delta_h <= 24.1, f"expected ~24h, got {delta_h}h"

        r = requests.get(f"{API}/gps/replay/shares?user_id={tech}&date={date}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        mine = [i for i in items if i["share_id"] == sid][0]
        assert mine["status"] == "active"
        assert mine["view_count"] == 0
    finally:
        _cleanup(sid)


# ── 3 · public GET → 200, no PII, view_count increments ────────────
def test_public_get_no_pii_and_view_count():
    tok = _login_super()
    tech, date = _tech_id(), _today()
    r = requests.post(f"{API}/gps/replay/share",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"user_id": tech, "replay_date": date}, timeout=10)
    sid = r.json()["share_id"]
    try:
        # Fresh IP to avoid the RL bucket carrying over from a prior test.
        ip = f"198.51.100.{uuid.uuid4().int % 250 + 1}"
        r = requests.get(f"{API}/public/replay/{sid}",
                          headers={"X-Forwarded-For": ip}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["share_id"] == sid
        assert d["read_only"] is True
        assert d["view_count"] == 1

        # PII sweep — no phone, email, home_address anywhere in payload.
        banned = {"phone", "phone_number", "email",
                   "home_address", "tech_email", "tech_phone",
                   "attributed_customer_email",
                   "attributed_customer_phone"}
        leaks = []

        def scan(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in banned:
                        leaks.append(f"{path}.{k}={v!r}")
                    scan(v, f"{path}.{k}")
            elif isinstance(o, list):
                for i, x in enumerate(o):
                    scan(x, f"{path}[{i}]")
        scan(d)
        assert not leaks, f"PII leaked in public payload: {leaks}"

        # Second GET → view_count = 2 (fresh IP again to avoid the RL cache).
        ip2 = f"198.51.100.{(uuid.uuid4().int % 250) + 1}"
        r = requests.get(f"{API}/public/replay/{sid}",
                          headers={"X-Forwarded-For": ip2}, timeout=10)
        assert r.status_code == 200
        assert r.json()["view_count"] == 2
    finally:
        _cleanup(sid)


# ── 4 · revoke → 410 ────────────────────────────────────────────────
def test_revoke_returns_410():
    tok = _login_super()
    tech, date = _tech_id(), _today()
    sid = requests.post(f"{API}/gps/replay/share",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"user_id": tech, "replay_date": date},
                          timeout=10).json()["share_id"]
    try:
        r = requests.post(f"{API}/gps/replay/share/{sid}/revoke",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r = requests.get(f"{API}/public/replay/{sid}",
                          headers={"X-Forwarded-For": "10.0.0.1"}, timeout=10)
        assert r.status_code == 410, r.text
        assert r.json()["detail"] == "share_revoked"
    finally:
        _cleanup(sid)


# ── 5 · expired share → 410 ────────────────────────────────────────
def test_expired_share_returns_410():
    """Simulate TTL expiry by writing the row directly with an
    expires_at in the past (equivalent to fast-forwarding ``now``)."""
    tenant_id = _sync.users.find_one(
        {"email": "super@aquaterra.com"})["tenant_id"]
    sid = "TESTexpired" + uuid.uuid4().hex[:6]
    _sync.route_replay_shares.insert_one({
        "tenant_id": tenant_id,
        "share_id": sid,
        "user_id": _tech_id(),
        "replay_date": _today(),
        "created_by": "test",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=48),
        "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "revoked_at": None,
        "view_count": 0,
        "last_viewed_at": None,
        "viewer_ip_hash_last": None,
    })
    try:
        r = requests.get(f"{API}/public/replay/{sid}",
                          headers={"X-Forwarded-For": "10.0.0.2"}, timeout=10)
        assert r.status_code == 410, r.text
        assert r.json()["detail"] == "share_expired"
    finally:
        _cleanup(sid)


# ── 6 · tenant scope — cross-tenant revoke rejected ────────────────
def test_tenant_scope_isolation():
    tok = _login_super()
    su = _sync.users.find_one({"email": "super@aquaterra.com"})
    my_tenant = su["tenant_id"]

    # Create a share that *belongs to a different tenant* directly in Mongo.
    other_tid = "TEST_replayshare_" + uuid.uuid4().hex[:8]
    sid = "TESTcross" + uuid.uuid4().hex[:6]
    _sync.route_replay_shares.insert_one({
        "tenant_id": other_tid,  # NOT super_admin's tenant.
        "share_id": sid,
        "user_id": "other_tech",
        "replay_date": _today(),
        "created_by": "test",
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
        "revoked_at": None,
        "view_count": 0,
        "last_viewed_at": None,
        "viewer_ip_hash_last": None,
    })
    try:
        # super_admin (my_tenant) tries to revoke another tenant's share
        # → 404 (never leak that it existed).
        r = requests.post(f"{API}/gps/replay/share/{sid}/revoke",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 404, r.text
        # And the share must still be un-revoked in the DB.
        row = _sync.route_replay_shares.find_one({"share_id": sid})
        assert row["revoked_at"] is None
    finally:
        _cleanup(sid)


# ── 7 · burst → 429 ─────────────────────────────────────────────────
def test_public_get_rate_limit_burst():
    """40 concurrent GETs from a single IP → at least 10 must return 429.
    The limiter is 30/60s per (share_id, ip_hash)."""
    tok = _login_super()
    tech, date = _tech_id(), _today()
    sid = requests.post(f"{API}/gps/replay/share",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"user_id": tech, "replay_date": date},
                          timeout=10).json()["share_id"]
    try:
        ip = f"198.51.100.{uuid.uuid4().int % 250 + 1}"

        def fire(_i: int) -> int:
            r = requests.get(f"{API}/public/replay/{sid}",
                              headers={"X-Forwarded-For": ip}, timeout=15)
            return r.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            statuses = list(pool.map(fire, range(40)))

        ok = sum(1 for s in statuses if s == 200)
        limited = sum(1 for s in statuses if s == 429)
        # 30 accepted per minute, so at least 10 out of 40 must be 429.
        assert ok == 30, f"expected 30 × 200, got {ok} (statuses: {sorted(set(statuses))})"
        assert limited >= 10, f"expected ≥10 × 429, got {limited}"
    finally:
        _cleanup(sid)
