"""Phase 8 · pytest — Weekly AEO PDF Digest."""
from __future__ import annotations
import asyncio, uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest, requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop(); asyncio.set_event_loop(_LOOP)
from services import aeo_digest as _ad  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_ad.db = _FRESH[_ENV["DB_NAME"]]


def _run(c):
    try: asyncio.set_event_loop(_LOOP)
    except Exception: pass
    return _LOOP.run_until_complete(c)


def _login(email):
    r = requests.post(f"{API}/auth/login",
        json={"email": email, "password": "password123"}, timeout=10)
    return r.json()["access_token"]


def _tid():
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


# 1. Snapshot with empty data — never crash
def test_snapshot_empty_week_no_crash():
    tid = f"tenant_p8_{uuid.uuid4().hex[:6]}"
    r = _run(_ad.build_snapshot({"id": tid, "name": "Empty Co"},
                                  period_end=date(2026, 7, 26)))
    assert r["aeo_score"]["current"] == 0
    assert r["ai_visibility"]["total_probes"] == 0
    assert r["brand_mentions"]["total_new"] == 0
    assert r["action_items"]["pending_fixes"] == 0


# 2. PDF renders (magic bytes + size < 500KB)
def test_pdf_render_bytes_and_size():
    snap = _run(_ad.build_snapshot({"id": f"empty_{uuid.uuid4().hex[:6]}",
                                       "name": "PDF Tenant"},
                                      period_end=date(2026, 7, 26)))
    pdf = _ad.render_pdf(snap)
    assert pdf[:4] == b"%PDF", pdf[:8]
    assert len(pdf) < 500_000, f"pdf size {len(pdf)}"


# 3. Signature helpers
def test_signed_url_and_verify():
    from services.aeo_digest import sign_pdf_url, verify_pdf_signature
    url = sign_pdf_url("t1", "d1", ttl_sec=60)
    # Parse: /api/aeo/digest/pdf/d1?tid=t1&exp=X&sig=Y
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(url).query)
    assert verify_pdf_signature("t1", "d1", int(q["exp"][0]), q["sig"][0])
    assert not verify_pdf_signature("t1", "d1", int(q["exp"][0]), "bad")


# 4. Metrics snapshot with seeded data
def test_snapshot_with_seeded_metrics():
    tid = f"tenant_p8s_{uuid.uuid4().hex[:6]}"
    period_end = date(2026, 7, 26); period_start = date(2026, 7, 20)
    now_in_week = period_start.strftime("%Y-%m-%dT10:00:00+00:00")
    # Seed 2 probes + 3 mentions + 1 fix + 1 draft.
    _sync.aeo_visibility_probes.insert_many([
        {"tenant_id": tid, "probe_id": "p1", "ran_at": now_in_week,
          "score": 80, "brand_mentioned": True,
          "query_template": "Best pool in {city}", "llm_provider": "anthropic-claude"},
        {"tenant_id": tid, "probe_id": "p2", "ran_at": now_in_week,
          "score": 20, "brand_mentioned": False,
          "query_template": "Best pool in {city}", "llm_provider": "anthropic-claude"},
    ])
    _sync.brand_mentions.insert_many([
        {"tenant_id": tid, "mention_id": "m1", "discovered_at": now_in_week,
          "sentiment": "positive", "domain": "yelp.com", "snippet": "great",
          "title": "t"},
        {"tenant_id": tid, "mention_id": "m2", "discovered_at": now_in_week,
          "sentiment": "negative", "domain": "reddit.com",
          "snippet": "bad experience with pool", "title": "t"},
    ])
    _sync.aeo_fixes.insert_one({"tenant_id": tid, "sub_signal": "schema",
                                   "applied": False, "superseded": False})
    _sync.mention_response_drafts.insert_one({"tenant_id": tid,
        "status": "draft", "mention_id": "m2"})
    try:
        snap = _run(_ad.build_snapshot({"id": tid, "name": "SeedCo"},
                                          period_end=period_end))
        assert snap["ai_visibility"]["total_probes"] == 2
        assert snap["ai_visibility"]["avg_score"] == 50.0
        assert snap["ai_visibility"]["brand_mention_rate"] == 50.0
        assert snap["brand_mentions"]["total_new"] == 2
        assert snap["brand_mentions"]["sentiment"]["negative"] == 1
        assert snap["action_items"]["pending_fixes"] == 1
        assert snap["action_items"]["pending_drafts"] == 1
    finally:
        _sync.aeo_visibility_probes.delete_many({"tenant_id": tid})
        _sync.brand_mentions.delete_many({"tenant_id": tid})
        _sync.aeo_fixes.delete_many({"tenant_id": tid})
        _sync.mention_response_drafts.delete_many({"tenant_id": tid})


# 5. Resend stub gets subject + recipients + attachment
def test_deliver_email_calls_stub_with_attachment():
    calls = {}
    async def resend_stub(recipients, subject, html, text, attachment):
        calls.update({"recipients": recipients, "subject": subject,
                       "attachment_filename": attachment["filename"],
                       "content_len": len(attachment["content_b64"])})
        return {"ok": True}
    snap = _run(_ad.build_snapshot({"id": f"t_{uuid.uuid4().hex[:6]}",
                                       "name": "AttachCo"},
                                      period_end=date(2026, 7, 26)))
    pdf = _ad.render_pdf(snap)
    r = _run(_ad.deliver_email(tenant_name="AttachCo", snapshot=snap,
                                   pdf_bytes=pdf,
                                   recipients=["a@b.com", "c@d.com"],
                                   resend_send=resend_stub))
    assert r["sent"] is True
    assert calls["recipients"] == ["a@b.com", "c@d.com"]
    assert "Weekly AEO Digest · AttachCo" in calls["subject"]
    assert calls["attachment_filename"].startswith("aeo-digest-")
    assert calls["content_len"] > 100


# 6. Cron dedup
def test_cron_dedup_same_week():
    tid = f"tenant_p8d_{uuid.uuid4().hex[:6]}"
    ps = date(2026, 7, 20)
    _sync.aeo_digest_runs.delete_many({"tenant_id": tid})
    assert _run(_ad.already_generated_this_week(tid, ps)) is False
    _sync.aeo_digest_runs.insert_one({
        "tenant_id": tid, "digest_id": "seed",
        "period_start": "2026-07-20",
        "generated_at": datetime.now(timezone.utc).isoformat()})
    try:
        assert _run(_ad.already_generated_this_week(tid, ps)) is True
    finally:
        _sync.aeo_digest_runs.delete_many({"tenant_id": tid})


# 7. Live settings + role guard
def test_live_settings_and_role_guard():
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/aeo/digest/settings",
        headers={"Authorization": f"Bearer {tok}"},
        json={"enabled": True, "recipient_emails": ["owner@vistancia.example"],
               "day_of_week": 1, "hour_utc": 15,
               "include_negative_snippets": True}, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["enabled"] is True
    assert d["recipient_emails"] == ["owner@vistancia.example"]
    for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
        t2 = _login(email)
        h = {"Authorization": f"Bearer {t2}"}
        assert requests.get(f"{API}/aeo/digest/settings", headers=h, timeout=10).status_code == 403
        assert requests.post(f"{API}/aeo/digest/preview", headers=h, json={}, timeout=10).status_code == 403
        assert requests.post(f"{API}/aeo/digest/run-now", headers=h, json={}, timeout=10).status_code == 403
        assert requests.get(f"{API}/aeo/digest/history", headers=h, timeout=10).status_code == 403


# 8. Live preview returns pdf_url + valid PDF via signed download
def test_live_preview_returns_downloadable_pdf():
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/aeo/digest/preview",
        headers={"Authorization": f"Bearer {tok}"}, json={}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["pdf_url"].startswith("/api/aeo/digest/pdf/")
    # Follow the signed URL WITHOUT auth (signature only).
    from urllib.parse import urljoin
    dl = requests.get(urljoin(API + "/", d["pdf_url"].lstrip("/api/").lstrip("/") ),
                        timeout=10)
    # Path adjustment — build full URL from API base.
    full = "http://localhost:8001" + d["pdf_url"]
    dl = requests.get(full, timeout=10)
    assert dl.status_code == 200, dl.status_code
    assert dl.content[:4] == b"%PDF", dl.content[:8]
    assert len(dl.content) < 500_000
