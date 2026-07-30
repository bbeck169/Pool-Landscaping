"""Phase 10 · sub-item D — Response Draft Library."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop(); asyncio.set_event_loop(_LOOP)
from services import response_library as _lib  # noqa: E402
from services import response_drafts as _rd  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_lib.db = _FRESH[_ENV["DB_NAME"]]
_rd.db = _FRESH[_ENV["DB_NAME"]]


def _rebind_loop():
    """Motor collections cache the event loop at first-await. When
    multiple pytest files share the `response_drafts` module, the module
    attribute may already point at a client bound to a previous loop —
    rebind before each test that touches the shared service."""
    _rd.db = _FRESH[_ENV["DB_NAME"]]
    _lib.db = _FRESH[_ENV["DB_NAME"]]


def _run(c):
    try: asyncio.set_event_loop(_LOOP)
    except Exception: pass
    _rebind_loop()
    return _LOOP.run_until_complete(c)


def _login(email):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    return r.json()["access_token"]


def _tid():
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


# ── 1. Auto-capture on status→posted writes a template ────────────
def test_auto_capture_on_posted():
    tid = f"tenant_p10d_{uuid.uuid4().hex[:6]}"
    _sync.response_draft_templates.delete_many({"tenant_id": tid})
    _sync.mention_response_drafts.delete_many({"tenant_id": tid})
    _sync.brand_mentions.delete_many({"tenant_id": tid})
    draft_id = f"drft_{uuid.uuid4().hex[:12]}"
    mention_id = f"m_{uuid.uuid4().hex[:8]}"
    _sync.mention_response_drafts.insert_one({
        "tenant_id": tid, "draft_id": draft_id,
        "mention_id": mention_id, "platform": "yelp", "tone": "empathetic",
        "draft_text": "Thank you for the feedback — please call us at 555-0100 so we can make this right.",
        "status": "draft", "drafted_at": "2026-07-30T10:00:00+00:00"})
    _sync.brand_mentions.insert_one({"tenant_id": tid, "mention_id": mention_id})

    r = _run(_rd.update_draft(tenant_id=tid, draft_id=draft_id,
                                  status="posted", user_id="u1"))
    assert r.get("status") == "posted"
    tpls = list(_sync.response_draft_templates.find({"tenant_id": tid}))
    assert len(tpls) == 1
    t = tpls[0]
    assert t["platform"] == "yelp"
    assert t["tone"] == "empathetic"
    assert "555-0100" in t["template_text"]
    assert t["use_count"] == 0
    _sync.response_draft_templates.delete_many({"tenant_id": tid})
    _sync.mention_response_drafts.delete_many({"tenant_id": tid})
    _sync.brand_mentions.delete_many({"tenant_id": tid})


# ── 2. Dedup on identical template_text + platform ────────────────
def test_dedup_identical_template_text():
    tid = f"tenant_p10d_dup_{uuid.uuid4().hex[:6]}"
    _sync.response_draft_templates.delete_many({"tenant_id": tid})
    text = "Sorry to hear this. We've already reached out to our team. Please call 555-0111."
    d1 = {"draft_id": "d1", "platform": "yelp", "tone": "empathetic",
           "draft_text": text}
    d2 = {"draft_id": "d2", "platform": "yelp", "tone": "professional",
           "draft_text": text}
    r1 = _run(_lib.capture_template_from_draft(tenant_id=tid, draft=d1))
    r2 = _run(_lib.capture_template_from_draft(tenant_id=tid, draft=d2))
    assert r1["template_id"] == r2["template_id"]
    assert _sync.response_draft_templates.count_documents({"tenant_id": tid}) == 1
    # Different platform → new row.
    d3 = {"draft_id": "d3", "platform": "google_reviews",
           "tone": "empathetic", "draft_text": text}
    _run(_lib.capture_template_from_draft(tenant_id=tid, draft=d3))
    assert _sync.response_draft_templates.count_documents({"tenant_id": tid}) == 2
    _sync.response_draft_templates.delete_many({"tenant_id": tid})


# ── 3. POST /use increments counters + rolling 30d ────────────────
def test_use_increments_counters_and_rolling_30d():
    tid = _tid()
    tok = _login("manager@aquaterra.com")
    # Seed a fresh template.
    tpl_id = f"tpl_{uuid.uuid4().hex[:12]}"
    _sync.response_draft_templates.insert_one({
        "tenant_id": tid, "template_id": tpl_id,
        "platform": "yelp", "tone": "empathetic",
        "template_text": "Sample template text for use test — thanks for the feedback.",
        "template_hash": f"h_{uuid.uuid4().hex[:20]}",
        "use_count": 3, "times_used_last_30d": 3,
        "last_used_at": "2026-07-30T09:00:00+00:00",
        "created_at": "2026-07-01T00:00:00+00:00"})
    r = requests.post(f"{API}/aeo/response/templates/{tpl_id}/use",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["use_count"] == 4
    assert d["times_used_last_30d"] == 4
    assert d["last_used_at"] > "2026-07-30T09:00:00+00:00"
    _sync.response_draft_templates.delete_one({"template_id": tpl_id})


# ── 4. Rolling 30d window reset when prior use is > 30d old ───────
def test_use_rolling_window_resets_over_30d():
    tid = f"tenant_p10d_win_{uuid.uuid4().hex[:6]}"
    _sync.response_draft_templates.delete_many({"tenant_id": tid})
    tpl_id = f"tpl_{uuid.uuid4().hex[:12]}"
    _sync.response_draft_templates.insert_one({
        "tenant_id": tid, "template_id": tpl_id,
        "platform": "yelp", "tone": "empathetic",
        "template_text": "old use — should roll",
        "template_hash": f"h_{uuid.uuid4().hex[:20]}",
        "use_count": 10, "times_used_last_30d": 10,
        "last_used_at": "2025-01-01T00:00:00+00:00",
        "created_at": "2024-12-31T00:00:00+00:00"})
    r = _run(_lib.use_template(tenant_id=tid, template_id=tpl_id))
    assert r["use_count"] == 11
    assert r["times_used_last_30d"] == 1  # window rolled
    _sync.response_draft_templates.delete_many({"tenant_id": tid})


# ── 5. Role guard × 3 template endpoints × 2 non-mod accounts ─────
def test_role_guard_all_template_endpoints():
    tpl_id = "tpl_probe"
    for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
        tok = _login(email)
        h = {"Authorization": f"Bearer {tok}"}
        assert requests.get(f"{API}/aeo/response/templates",
                             headers=h, timeout=10).status_code == 403
        assert requests.post(f"{API}/aeo/response/templates/{tpl_id}/use",
                              headers=h, timeout=10).status_code == 403
        assert requests.delete(f"{API}/aeo/response/templates/{tpl_id}",
                                headers=h, timeout=10).status_code == 403


# ── 6. Soft-delete excludes from listing ──────────────────────────
def test_soft_delete_excludes_from_list():
    tid = _tid()
    tok = _login("manager@aquaterra.com")
    tpl_id = f"tpl_{uuid.uuid4().hex[:12]}"
    _sync.response_draft_templates.insert_one({
        "tenant_id": tid, "template_id": tpl_id,
        "platform": "yelp", "tone": "empathetic",
        "template_text": "Soft-delete probe.", "template_hash": f"h_{tpl_id}",
        "use_count": 0, "times_used_last_30d": 0,
        "created_at": "2026-07-30T00:00:00+00:00"})
    r = requests.delete(f"{API}/aeo/response/templates/{tpl_id}",
                         headers={"Authorization": f"Bearer {tok}"},
                         timeout=10)
    assert r.status_code == 200 and r.json()["deleted"] is True
    r = requests.get(f"{API}/aeo/response/templates?platform=yelp",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200
    ids = [t["template_id"] for t in r.json()["items"]]
    assert tpl_id not in ids
    _sync.response_draft_templates.delete_one({"template_id": tpl_id})


# ── 7. Prompt few-shot rendering assembles examples ───────────────
def test_render_examples_appends_prior_replies():
    ex = [{"template_text": "Text A · thanks for feedback.",
            "platform": "yelp", "tone": "empathetic"},
           {"template_text": "Text B · sorry for the inconvenience.",
            "platform": "yelp", "tone": "empathetic"}]
    out = _lib.render_examples_for_prompt(ex)
    assert "Examples of prior public replies" in out
    assert "Text A" in out and "Text B" in out
    assert _lib.render_examples_for_prompt([]) == ""
