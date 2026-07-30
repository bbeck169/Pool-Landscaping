"""MR3 · pytest — widget analytics endpoints (live-server pattern).

Uses the running backend (matches ``test_reverse_geocoder.py`` style).
Setup + inspection are done via synchronous PyMongo to avoid Motor
event-loop coupling across tests.

Coverage:
  1. Rate-limit — 60/min per ip_hash. The 61st call within the window
     returns 204 with ``X-Widget-Analytics: rate_limited`` and is NOT
     persisted.
  2. Raw IP never stored — only sha256(ip + tenant_id).
  3. Tenant isolation — summary + timeseries never leak another
     tenant's counts.
  4. Top-checkins ordering — sorted by clicks desc.

Each test uses a UNIQUE per-run slug so parallel / repeated runs
don't clash on the per-process in-memory rate limit bucket.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

# ── Config / API base ───────────────────────────────────────────────
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
# Point tests at the local backend directly. This is faster and avoids
# the preview ingress round-trip that can time out with the 60-shot
# rate-limit loop.
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"


def _mk_tenant(slug_suffix: str) -> tuple[str, str]:
    """Insert a throwaway tenant, return (id, slug). Slug is TEST_
    prefixed so ``conftest.py`` sweeps it after the session."""
    slug = f"TEST_mr3_{slug_suffix}_{uuid.uuid4().hex[:6]}"
    tid = f"TEST_mr3_{uuid.uuid4().hex[:12]}"
    _sync.tenants.insert_one({
        "id": tid, "slug": slug, "name": f"TEST Tenant {slug}",
        "created_at": datetime.now(timezone.utc),
    })
    return tid, slug


def _login_super() -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": "super@aquaterra.com",
                              "password": "password123"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _cleanup(tid: str) -> None:
    _sync.widget_analytics_events.delete_many({"tenant_id": tid})
    _sync.tenants.delete_many({"id": tid})


# ── 1. Rate limit ───────────────────────────────────────────────────
def test_track_rate_limit_60_per_min():
    tid, slug = _mk_tenant("rl")
    try:
        # Unique IP so we don't collide with other tests / real traffic.
        fake_ip = f"198.51.100.{uuid.uuid4().int % 250 + 1}"
        headers = {"Content-Type": "application/json",
                    "X-Forwarded-For": fake_ip}

        # 60 accepted.
        for i in range(60):
            r = requests.post(
                f"{API}/public/widget/analytics/track",
                headers=headers,
                json={"widget_id": slug, "event_type": "impression",
                       "session_id": f"s{i:03d}abcdef"},
                timeout=10,
            )
            assert r.status_code == 204, f"call {i}: {r.status_code} {r.text}"

        # 61st — rate limited.
        r = requests.post(
            f"{API}/public/widget/analytics/track",
            headers=headers,
            json={"widget_id": slug, "event_type": "impression",
                   "session_id": "s061abcdef"}, timeout=10,
        )
        assert r.status_code == 204
        assert r.headers.get("X-Widget-Analytics") == "rate_limited", \
            f"expected rate_limited header, got {dict(r.headers)}"

        # Exactly 60 rows persisted.
        n = _sync.widget_analytics_events.count_documents({"tenant_id": tid})
        assert n == 60, f"expected 60 rows, got {n}"
    finally:
        _cleanup(tid)


# ── 2. IP hash — never store raw IP ─────────────────────────────────
def test_track_never_stores_raw_ip():
    tid, slug = _mk_tenant("iph")
    try:
        raw_ip = "203.0.113.99"
        r = requests.post(
            f"{API}/public/widget/analytics/track",
            headers={"Content-Type": "application/json",
                      "X-Forwarded-For": raw_ip},
            json={"widget_id": slug, "event_type": "impression",
                   "session_id": "abcdef123456"}, timeout=10,
        )
        assert r.status_code == 204

        row = _sync.widget_analytics_events.find_one({"tenant_id": tid})
        assert row is not None
        # No 'ip' key on the doc. Only ip_hash allowed.
        assert "ip" not in row, f"raw ip field leaked: {row}"
        assert isinstance(row.get("ip_hash", ""), str) and len(row["ip_hash"]) == 64
        # And the raw IP string is not a substring anywhere on the doc.
        row.pop("_id", None)
        assert raw_ip not in str(row), f"raw ip leaked in doc: {row}"
    finally:
        _cleanup(tid)


# ── 3. Tenant isolation on summary ──────────────────────────────────
def test_summary_tenant_isolation():
    """Seed events under both the super_admin's native tenant AND a
    throwaway TEST tenant. Verify super_admin's summary counts only
    their own tenant."""
    # Native tenant of super@aquaterra.com — we look it up by email.
    su = _sync.users.find_one({"email": "super@aquaterra.com"})
    assert su, "super@aquaterra.com user must exist for this test"
    tid_a = su["tenant_id"]
    _sync.widget_analytics_events.delete_many({"tenant_id": tid_a,
                                                  "checkin_id": {"$regex": "^TEST_mr3_"}})
    tid_b, slug_b = _mk_tenant("isoB")
    try:
        now = datetime.now(timezone.utc)
        marker = f"TEST_mr3_{uuid.uuid4().hex[:6]}"
        # 3 impressions + 2 clicks on the super_admin's tenant.
        for i in range(3):
            _sync.widget_analytics_events.insert_one({
                "tenant_id": tid_a, "widget_id": "aquaterra",
                "checkin_id": marker, "event_type": "impression",
                "session_id": f"sa{i}", "referrer": "", "user_agent": "",
                "ip_hash": "x" * 64, "ts": now - timedelta(hours=1)})
        for i in range(2):
            _sync.widget_analytics_events.insert_one({
                "tenant_id": tid_a, "widget_id": "aquaterra",
                "checkin_id": marker, "event_type": "click",
                "session_id": f"sa{i}", "referrer": "", "user_agent": "",
                "ip_hash": "x" * 64, "ts": now - timedelta(hours=1)})
        # 100 impressions in tenant B — MUST NOT leak into A's summary.
        for i in range(100):
            _sync.widget_analytics_events.insert_one({
                "tenant_id": tid_b, "widget_id": slug_b,
                "checkin_id": "TEST_mr3_B_leak",
                "event_type": "impression",
                "session_id": f"sb{i}", "referrer": "", "user_agent": "",
                "ip_hash": "y" * 64, "ts": now - timedelta(hours=1)})

        r = requests.post(f"{API}/auth/login",
                           json={"email": "super@aquaterra.com",
                                  "password": "password123"}, timeout=10)
        r.raise_for_status()
        tok = r.json()["access_token"]
        r = requests.get(f"{API}/widget/analytics/summary?range=7d",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        # Our marker's counts must be present exactly.
        our_row = next((t for t in body["top_checkins"]
                        if t["checkin_id"] == marker), None)
        assert our_row is not None, f"top_checkins missing marker {marker}: {body['top_checkins']}"
        assert our_row["impressions"] == 3
        assert our_row["clicks"] == 2
        # CTR is server-rounded to 4 decimals (0.6667).
        assert our_row["ctr"] == round(2 / 3, 4)
        # And tenant B's marker must NOT appear.
        b_ids = [t["checkin_id"] for t in body["top_checkins"]]
        assert "TEST_mr3_B_leak" not in b_ids, \
            f"tenant B row leaked into A's summary: {b_ids}"
    finally:
        _sync.widget_analytics_events.delete_many({"tenant_id": tid_a,
                                                     "checkin_id": marker})
        _cleanup(tid_b)


# ── 4. Top-checkins ordering ────────────────────────────────────────
def test_top_checkins_ordered_by_clicks():
    """Seed events under super_admin's native tenant with three
    check-ins and verify the top-10 ordering is by clicks desc."""
    su = _sync.users.find_one({"email": "super@aquaterra.com"})
    assert su, "super@aquaterra.com user must exist for this test"
    tid = su["tenant_id"]
    marker_prefix = f"TEST_mr3_top_{uuid.uuid4().hex[:6]}"
    ck_ids = {f"{marker_prefix}_1": 1,
               f"{marker_prefix}_2": 5,
               f"{marker_prefix}_3": 3}
    try:
        now = datetime.now(timezone.utc)
        for ck, n_clicks in ck_ids.items():
            for i in range(10):
                _sync.widget_analytics_events.insert_one({
                    "tenant_id": tid, "widget_id": "aquaterra",
                    "checkin_id": ck, "event_type": "impression",
                    "session_id": f"s-{ck}-{i}", "referrer": "",
                    "user_agent": "", "ip_hash": "z" * 64,
                    "ts": now - timedelta(minutes=5)})
            for i in range(n_clicks):
                _sync.widget_analytics_events.insert_one({
                    "tenant_id": tid, "widget_id": "aquaterra",
                    "checkin_id": ck, "event_type": "click",
                    "session_id": f"s-{ck}-{i}", "referrer": "",
                    "user_agent": "", "ip_hash": "z" * 64,
                    "ts": now - timedelta(minutes=5)})

        r = requests.post(f"{API}/auth/login",
                           json={"email": "super@aquaterra.com",
                                  "password": "password123"}, timeout=10)
        r.raise_for_status()
        tok = r.json()["access_token"]
        r = requests.get(f"{API}/widget/analytics/summary?range=7d",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        top = r.json()["top_checkins"]
        # Filter to just our seeded rows (other test data may exist).
        mine = [t for t in top if t["checkin_id"].startswith(marker_prefix)]
        got = [t["checkin_id"] for t in mine]
        want = [f"{marker_prefix}_2", f"{marker_prefix}_3", f"{marker_prefix}_1"]
        assert got == want, f"top ordering wrong: got {got}, want {want}"
        assert mine[0]["ctr"] == 0.5
        assert mine[1]["ctr"] == 0.3
        assert mine[2]["ctr"] == 0.1
    finally:
        _sync.widget_analytics_events.delete_many({
            "tenant_id": tid,
            "checkin_id": {"$regex": f"^{marker_prefix}"},
        })
