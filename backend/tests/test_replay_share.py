"""Phase 2 · Feb-2026 REWORK — Route Replay share (admin-only) tests.

Coverage
--------
1. Create share as admin (manager@ aquaterra role=admin) → 200
2. List shares → 200
3. Authed GET share → 200 with same payload shape, no PII fields
4. Revoke → subsequent authed GET returns 410
5. Expired share → 410 (fast-forward via direct Mongo write)
6. Cross-tenant scope — admin from tenant A cannot GET/revoke a share
   that lives in tenant B (404, not 403, to avoid share-existence leak)
7. Technician role → 403 on every share endpoint
8. Customer role  → 403 on every share endpoint
9. Un-authed call → 401/403 (auth middleware rejects, not our handler)
10. Public route `GET /api/public/replay/{share_id}` is GONE (404)
"""
from __future__ import annotations

import os
import uuid
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
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_token() -> str:
    # manager@aquaterra.com has role="admin" per the seed data — perfect.
    return _login("manager@aquaterra.com")


def _tech_token() -> str:
    return _login("landscaper@aquaterra.com")


def _customer_token() -> str:
    return _login("customer@aquaterra.com")


def _tech_id() -> str:
    u = _sync.users.find_one({"email": "landscaper@aquaterra.com"}, {"id": 1})
    assert u
    return u["id"]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cleanup(share_id: str) -> None:
    _sync.route_replay_shares.delete_many({"share_id": share_id})


# ── 1 & 2 · create + list ──────────────────────────────────────────
def test_create_and_list_share():
    tok = _admin_token()
    tech, date = _tech_id(), _today()
    r = requests.post(f"{API}/gps/replay/share",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"user_id": tech, "replay_date": date}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    sid = body["share_id"]
    try:
        assert len(sid) == 16
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        h = (exp - datetime.now(timezone.utc)).total_seconds() / 3600
        assert 23 <= h <= 24.1

        r = requests.get(f"{API}/gps/replay/shares?user_id={tech}&date={date}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200
        assert any(i["share_id"] == sid for i in r.json()["items"])
    finally:
        _cleanup(sid)


# ── 3 · authed GET returns full payload, no PII ────────────────────
def test_authed_get_no_pii_and_view_count():
    tok = _admin_token()
    tech, date = _tech_id(), _today()
    sid = requests.post(f"{API}/gps/replay/share",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"user_id": tech, "replay_date": date},
                          timeout=10).json()["share_id"]
    try:
        r = requests.get(f"{API}/gps/replay/share/{sid}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["share_id"] == sid
        assert d["read_only"] is True
        assert d["view_count"] == 1
        # Payload shape stayed the same as pre-rework.
        for key in ("user_id", "user_name", "tenant_name", "replay_date",
                     "stops", "pings", "geofence_events",
                     "playback_duration_s", "expires_at"):
            assert key in d, f"missing key {key} in payload"
        # PII sweep.
        banned = {"phone", "phone_number", "email",
                   "home_address", "tech_email", "tech_phone",
                   "attributed_customer_email", "attributed_customer_phone"}
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
        assert not leaks, f"PII leaked in authed payload: {leaks}"

        # Second GET increments view_count.
        r2 = requests.get(f"{API}/gps/replay/share/{sid}",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r2.json()["view_count"] == 2
    finally:
        _cleanup(sid)


# ── 4 · revoke → subsequent authed GET returns 410 ─────────────────
def test_revoke_returns_410_on_authed_get():
    tok = _admin_token()
    tech, date = _tech_id(), _today()
    sid = requests.post(f"{API}/gps/replay/share",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"user_id": tech, "replay_date": date},
                          timeout=10).json()["share_id"]
    try:
        r = requests.post(f"{API}/gps/replay/share/{sid}/revoke",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 200 and r.json()["ok"] is True
        r = requests.get(f"{API}/gps/replay/share/{sid}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 410, r.text
        assert r.json()["detail"] == "share_revoked"
    finally:
        _cleanup(sid)


# ── 5 · expired share → 410 ────────────────────────────────────────
def test_expired_share_returns_410_on_authed_get():
    su = _sync.users.find_one({"email": "manager@aquaterra.com"})
    tenant_id = su["tenant_id"]
    sid = "TESTexpired" + uuid.uuid4().hex[:6]
    _sync.route_replay_shares.insert_one({
        "tenant_id": tenant_id, "share_id": sid,
        "user_id": _tech_id(), "replay_date": _today(),
        "created_by": "test",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=48),
        "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "revoked_at": None, "view_count": 0, "last_viewed_at": None,
        "viewer_ip_hash_last": None,
    })
    try:
        tok = _admin_token()
        r = requests.get(f"{API}/gps/replay/share/{sid}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 410
        assert r.json()["detail"] == "share_expired"
    finally:
        _cleanup(sid)


# ── 6 · cross-tenant scope ─────────────────────────────────────────
def test_cross_tenant_scope_returns_404():
    tok = _admin_token()
    sid = "TESTcross" + uuid.uuid4().hex[:6]
    other_tid = "TEST_ct_" + uuid.uuid4().hex[:8]
    _sync.route_replay_shares.insert_one({
        "tenant_id": other_tid, "share_id": sid, "user_id": "x",
        "replay_date": _today(), "created_by": "test",
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
        "revoked_at": None, "view_count": 0, "last_viewed_at": None,
        "viewer_ip_hash_last": None,
    })
    try:
        # Admin from a different tenant → 404 on GET.
        r = requests.get(f"{API}/gps/replay/share/{sid}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 404, r.text
        # Also 404 on revoke.
        r = requests.post(f"{API}/gps/replay/share/{sid}/revoke",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 404
        row = _sync.route_replay_shares.find_one({"share_id": sid})
        assert row["revoked_at"] is None
    finally:
        _cleanup(sid)


# ── 7 · technician → 403 on ALL share endpoints ───────────────────
def test_technician_forbidden_on_all_share_endpoints():
    tok = _tech_token()
    tech, date = _tech_id(), _today()
    r = requests.post(f"{API}/gps/replay/share",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"user_id": tech, "replay_date": date}, timeout=10)
    assert r.status_code == 403, r.text
    r = requests.get(f"{API}/gps/replay/shares?user_id={tech}&date={date}",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403
    r = requests.get(f"{API}/gps/replay/share/anything12345678",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403
    r = requests.post(f"{API}/gps/replay/share/anything12345678/revoke",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403


# ── 8 · customer → 403 on ALL share endpoints ─────────────────────
def test_customer_forbidden_on_all_share_endpoints():
    tok = _customer_token()
    r = requests.post(f"{API}/gps/replay/share",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"user_id": "x", "replay_date": _today()}, timeout=10)
    assert r.status_code == 403
    r = requests.get(f"{API}/gps/replay/shares?user_id=x&date={_today()}",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403
    r = requests.get(f"{API}/gps/replay/share/anything12345678",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403
    r = requests.post(f"{API}/gps/replay/share/anything12345678/revoke",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403


# ── 9 · un-authed → auth middleware rejects (401 or 403) ──────────
def test_unauthed_requests_rejected():
    for method, path in [
        ("POST", "/gps/replay/share"),
        ("GET", f"/gps/replay/shares?user_id=x&date={_today()}"),
        ("GET", "/gps/replay/share/anything12345678"),
        ("POST", "/gps/replay/share/anything12345678/revoke"),
    ]:
        if method == "POST":
            r = requests.post(f"{API}{path}", json={}, timeout=10)
        else:
            r = requests.get(f"{API}{path}", timeout=10)
        assert r.status_code in (401, 403), f"{method} {path} → {r.status_code}"


# ── 10 · public route is GONE ──────────────────────────────────────
def test_public_route_removed():
    """The pre-rework `/api/public/replay/{id}` endpoint must return
    404 for ANY share_id (route removed entirely)."""
    r = requests.get(f"{API}/public/replay/anything", timeout=10)
    assert r.status_code == 404, r.text
    # Also confirm it's not in the OpenAPI schema anymore.
    r = requests.get(f"{API}/openapi.json", timeout=10)
    paths = r.json().get("paths", {})
    assert "/api/public/replay/{share_id}" not in paths
    assert "/public/replay/{share_id}" not in paths
