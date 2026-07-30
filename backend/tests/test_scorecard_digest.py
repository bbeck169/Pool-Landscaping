"""Phase 7 · pytest — Weekly Scorecard Digest.

Stubs Slack + Resend. Uses a shared event loop / rebound motor db to
survive cross-test motor loop issues.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
from services import scorecard_digest as _sd  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_sd.db = _FRESH[_ENV["DB_NAME"]]


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    return _LOOP.run_until_complete(coro)


def _login(email):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"}, timeout=10)
    return r.json()["access_token"]


def _tenant_id(email="manager@aquaterra.com"):
    return _sync.users.find_one({"email": email})["tenant_id"]


# ── 1. Period math ───────────────────────────────────────────────
def test_last_completed_week_bounds():
    from services.scorecard_digest import last_completed_week, prior_week
    m, s = last_completed_week(date(2026, 7, 30))  # Thu
    assert m == date(2026, 7, 20) and s == date(2026, 7, 26)
    p1, p2 = prior_week(m, s)
    assert p1 == date(2026, 7, 13) and p2 == date(2026, 7, 19)


# ── 2. Composite math + delta ───────────────────────────────────
def test_composite_and_delta():
    from services.scorecard_digest import (_tech_composite, _sales_composite,
                                              _delta_pct)
    assert _tech_composite(20, 5000, 5.0) == 100.0
    assert _tech_composite(0, 0, None) == 0.0
    assert _sales_composite(15, 10, 20000) == 100.0
    assert _delta_pct(120, 100) == 20.0
    assert _delta_pct(80, 100) == -20.0
    assert _delta_pct(50, 0) is None
    assert _delta_pct(50, None) is None


# ── 3. Slack block kit shape ────────────────────────────────────
def test_slack_blocks_valid_shape():
    from services.scorecard_digest import build_slack_blocks
    digest = {
        "period_start": "2026-07-20", "period_end": "2026-07-26",
        "generated_at": "2026-07-27T14:00:00+00:00",
        "departments": {
            "field": {"top": [
                {"user_id": "u1", "name": "Alice", "composite": 92.4, "delta_pct": 5.0},
                {"user_id": "u2", "name": "Bob",   "composite": 84.1, "delta_pct": -2.0},
            ], "bottom": [
                {"user_id": "u3", "name": "Carl", "composite": 41.0, "delta_pct": None},
            ]},
        },
    }
    payload = build_slack_blocks("Test Co", digest)
    # Round-trip through JSON to ensure serialisability.
    text = json.dumps(payload, ensure_ascii=False)
    assert "blocks" in payload
    types = [b["type"] for b in payload["blocks"]]
    assert types[0] == "header"
    assert "divider" in types
    assert any(b["type"] == "context" for b in payload["blocks"])
    assert "🥇" in text and "🥈" in text
    assert "↑ 5.0%" in text and "↓ 2.0%" in text


# ── 4. Email HTML shape ─────────────────────────────────────────
def test_email_html_and_subject():
    from services.scorecard_digest import build_email_html
    digest = {
        "period_start": "2026-07-20", "period_end": "2026-07-26",
        "generated_at": "2026-07-27T14:00:00+00:00",
        "departments": {
            "sales": {"top": [{"user_id": "s1", "name": "Sam", "composite": 88,
                                  "delta_pct": 12.0}],
                       "bottom": []},
        },
    }
    subject, html, text = build_email_html("Test Co", digest)
    assert "Weekly Scorecard · Test Co" in subject
    assert "Week of 2026-07-20" in subject
    assert "Weekly Scorecard" in html
    assert "Sam" in html and "88" in html
    assert "↑ 12.0%" in html
    assert "Sales" in text


# ── 5. Delivery adapters called with stubs ──────────────────────
def test_deliver_uses_stubs_and_records_status():
    from services.scorecard_digest import deliver_digest
    calls = {"slack": None, "email": None}
    async def slack_stub(url, payload):
        calls["slack"] = {"url": url, "payload": payload}
        return {"ok": True, "status": 200}
    async def resend_stub(to, subject, html, text):
        calls["email"] = {"to": to, "subject": subject, "html_len": len(html)}
        return {"ok": True, "status": 202}
    digest = {"period_start": "2026-07-20", "period_end": "2026-07-26",
              "generated_at": "2026-07-27", "departments": {}}
    settings = {"slack_webhook_url": "https://hooks.slack/x",
                 "slack_channel": "#alerts",
                 "recipient_emails": ["owner@example.com"]}
    r = _run(deliver_digest(tenant={"name": "Test"}, digest=digest,
                                settings=settings, channels=["slack", "email"],
                                slack_post=slack_stub, resend_send=resend_stub))
    assert r["slack"]["sent"] is True
    assert r["email"]["sent"] is True
    assert calls["slack"]["url"].endswith("/x")
    assert "Weekly Scorecard" in calls["email"]["subject"]


# ── 6. Empty department omitted ─────────────────────────────────
def test_empty_departments_omitted():
    from services.scorecard_digest import compute_digest
    tid = f"tenant_p7_{uuid.uuid4().hex[:6]}"
    tenant = {"id": tid, "name": "Empty Co"}
    r = _run(compute_digest(tenant, period_end=date(2026, 7, 26)))
    # No jobs / dispatch audit / quotes seeded → all departments empty.
    assert r["departments"] == {}
    assert r["period_start"] == "2026-07-20"


# ── 7. Settings mask + persistence ──────────────────────────────
def test_settings_mask():
    from services.scorecard_digest import _mask_webhook
    assert _mask_webhook("") == ""
    assert _mask_webhook("https://hooks.slack.com/services/AA/BB/verylongtoken") == "…gtoken"
    assert _mask_webhook("short") == "***"


# ── 8. Live HTTP settings round-trip + masking ─────────────────
def test_live_settings_masks_webhook():
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/scorecard/digest/settings",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"slack_webhook_url": "https://hooks.slack.com/services/AAA/BBB/SECRETLONGTOKEN",
                              "recipient_emails": ["owner@vistancia.example"],
                              "enabled": True, "day_of_week": 1, "hour_utc": 14},
                       timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "slack_webhook_url" not in d
    assert d["slack_webhook_url_masked"].endswith("GTOKEN")
    # GET returns masked as well.
    g = requests.get(f"{API}/scorecard/digest/settings",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert "slack_webhook_url" not in g.json()
    assert g.json()["slack_webhook_url_masked"].endswith("GTOKEN")


# ── 9. Role guard on all 5 endpoints ───────────────────────────
@pytest.mark.parametrize("email", ["landscaper@aquaterra.com",
                                    "customer@aquaterra.com"])
def test_role_guard(email):
    tok = _login(email)
    h = {"Authorization": f"Bearer {tok}"}
    for method, path, body in [
        ("post", "/scorecard/digest/run-now", {}),
        ("get",  "/scorecard/digest/preview", None),
        ("get",  "/scorecard/digest/history", None),
        ("post", "/scorecard/digest/settings", {}),
        ("get",  "/scorecard/digest/settings", None),
    ]:
        if method == "post":
            r = requests.post(f"{API}{path}", headers=h, json=body or {}, timeout=10)
        else:
            r = requests.get(f"{API}{path}", headers=h, timeout=10)
        assert r.status_code == 403, f"{email} {method} {path} → {r.status_code}"


# ── 10. Cron dedup — same week twice → no double write ─────────
def test_cron_dedup_guard():
    from services.scorecard_digest import already_generated_this_week
    tid = f"tenant_p7d_{uuid.uuid4().hex[:6]}"
    _sync.scorecard_digests.delete_many({"tenant_id": tid})
    period_start = date(2026, 7, 20)
    assert _run(already_generated_this_week(tid, period_start)) is False
    _sync.scorecard_digests.insert_one({
        "tenant_id": tid, "digest_id": "seed",
        "period_start": "2026-07-20", "period_end": "2026-07-26",
        "generated_at": datetime.now(timezone.utc).isoformat()})
    try:
        assert _run(already_generated_this_week(tid, period_start)) is True
    finally:
        _sync.scorecard_digests.delete_many({"tenant_id": tid})
