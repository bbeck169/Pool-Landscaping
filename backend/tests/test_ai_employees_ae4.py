"""AE4 — Soshie + Scouty + Commet — Feb-2026 ship."""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


def _emp_id(admin_headers, key: str) -> str:
    rows = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15).json()
    return next(e["id"] for e in rows if e["key"] == key)


def _new_conv(admin_headers, eid):
    r = requests.post(f"{API}/ai-employees/{eid}/conversations",
                        headers=admin_headers, json={"title": "AE4"}, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


def _balance(admin_headers):
    return requests.get(f"{API}/ai-credits/balance",
                          headers=admin_headers, timeout=15).json()["balance"]


def _send(admin_headers, eid, cid, text, action=None, action_params=None):
    body = {"text": text}
    if action:
        body["action"] = action
    if action_params is not None:
        body["action_params"] = action_params
    return requests.post(f"{API}/ai-employees/{eid}/conversations/{cid}/messages",
                            headers=admin_headers, json=body, timeout=60)


# ─── Discovery ─────────────────────────────────────────────────────────

def test_ae4_trio_seeded_and_active(admin_headers):
    rows = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15).json()
    got = {e["key"] for e in rows}
    assert {"soshie", "scouty", "commet"} <= got
    for k in ("soshie", "scouty", "commet"):
        emp = next(e for e in rows if e["key"] == k)
        assert emp["active"] is True


# ─── Chat baseline (1c debit per employee) ────────────────────────────

@pytest.mark.parametrize("key", ["soshie", "scouty", "commet"])
def test_ae4_chat_debits_one_credit(admin_headers, key):
    eid = _emp_id(admin_headers, key)
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "hello")
    assert r.status_code == 201, r.text
    after = _balance(admin_headers)
    assert before - after == 1


# ─── Soshie ────────────────────────────────────────────────────────────

def test_soshie_draft_post_is_approve_gated(admin_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "spring pool",
                action="soshie.draft_post",
                action_params={"platform": "instagram",
                                 "topic": "Spring pool openings",
                                 "tone": "friendly"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"]["status"] == "pending"
    assert body["action"]["employee_key"] == "soshie"
    after = _balance(admin_headers)
    assert before - after == 6


def test_soshie_hashtag_research_is_readonly(admin_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "hashtags",
                action="soshie.hashtag_research",
                action_params={"topic": "backyard pool remodel"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    assert body["assistant_message"]["text"]
    after = _balance(admin_headers)
    assert before - after == 1


def test_soshie_content_calendar_is_readonly(admin_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "calendar",
                action="soshie.suggest_content_calendar",
                action_params={"days": 7,
                                 "service_types": ["Pool", "Landscape"]})
    assert r.status_code == 201, r.text
    assert r.json()["action"] is None
    assert r.json()["assistant_message"]["text"]


def test_soshie_analyze_engagement_handles_empty_data(admin_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "engagement",
                action="soshie.analyze_engagement",
                action_params={"days": 30})
    assert r.status_code == 201
    assert r.json()["action"] is None
    assert r.json()["assistant_message"]["text"]


def test_soshie_schedule_post_pending_action(admin_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "schedule",
                action="soshie.schedule_post",
                action_params={"platform": "facebook",
                                 "scheduled_at": "2026-05-01T10:00Z",
                                 "caption": "Book your spring opening today."})
    assert r.status_code == 201
    body = r.json()
    assert body["action"]["status"] == "pending"
    assert body["action"]["action"] == "soshie.schedule_post"


def test_soshie_schedule_post_missing_caption_returns_hint(admin_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "",
                action="soshie.schedule_post",
                action_params={"platform": "instagram"})
    # Empty text triggers pydantic 422; retry with non-empty text but empty caption
    if r.status_code == 422:
        r = _send(admin_headers, eid, c["id"], "schedule",
                    action="soshie.schedule_post",
                    action_params={"platform": "instagram", "caption": ""})
    assert r.status_code == 201
    assert r.json()["action"] is None
    assert "caption" in r.json()["assistant_message"]["text"].lower()


def test_soshie_approve_flips_to_executed(admin_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "post",
                action="soshie.draft_post",
                action_params={"platform": "linkedin",
                                 "topic": "Team spotlight"})
    aid = r.json()["action"]["id"]
    r = requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed"
    assert r.json()["result"]["kind"] == "soshie_draft_ready"


# ─── Scouty ────────────────────────────────────────────────────────────

def test_scouty_draft_job_posting_is_approve_gated(admin_headers):
    eid = _emp_id(admin_headers, "scouty")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "job",
                action="scouty.draft_job_posting",
                action_params={"role": "Pool Technician",
                                 "location": "Peoria, AZ",
                                 "pay_range": "$22-28/hr"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"]["status"] == "pending"
    assert body["action"]["employee_key"] == "scouty"
    after = _balance(admin_headers)
    assert before - after == 6


def test_scouty_screen_resume_returns_scored_analysis(admin_headers):
    eid = _emp_id(admin_headers, "scouty")
    c = _new_conv(admin_headers, eid)
    resume_text = (
        "10 years pool tech experience, CPO certified, own transportation, "
        "clean driving record, strong customer service, bilingual English/Spanish. "
        "Prior role: Aqua Pros 2016-2024, Route Supervisor."
    )
    r = _send(admin_headers, eid, c["id"], "screen",
                action="scouty.screen_resume",
                action_params={"resume_text": resume_text,
                                 "role": "Pool Technician"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    assert body["assistant_message"]["text"]


def test_scouty_screen_resume_missing_text_returns_hint(admin_headers):
    eid = _emp_id(admin_headers, "scouty")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "short",
                action="scouty.screen_resume",
                action_params={"resume_text": "too short"})
    assert r.status_code == 201
    assert "resume_text" in r.json()["assistant_message"]["text"].lower()


def test_scouty_interview_questions_readonly(admin_headers):
    eid = _emp_id(admin_headers, "scouty")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "questions",
                action="scouty.suggest_interview_questions",
                action_params={"role": "Route Manager", "count": 6})
    assert r.status_code == 201, r.text
    assert r.json()["action"] is None
    after = _balance(admin_headers)
    assert before - after == 1


def test_scouty_offer_letter_is_approve_gated(admin_headers):
    eid = _emp_id(admin_headers, "scouty")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "offer",
                action="scouty.generate_offer_letter",
                action_params={"candidate_name": "Jamie Rivera",
                                 "role": "Pool Technician",
                                 "salary": "$52,000/year",
                                 "start_date": "2026-03-15"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"]["status"] == "pending"
    assert body["action"]["action"] == "scouty.generate_offer_letter"
    after = _balance(admin_headers)
    assert before - after == 6


def test_scouty_pipeline_summary_readonly(admin_headers):
    eid = _emp_id(admin_headers, "scouty")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "summary",
                action="scouty.pipeline_summary")
    assert r.status_code == 201
    assert r.json()["action"] is None


# ─── Commet ────────────────────────────────────────────────────────────

def test_commet_draft_funnel_copy_is_approve_gated(admin_headers):
    eid = _emp_id(admin_headers, "commet")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "funnel",
                action="commet.draft_funnel_copy",
                action_params={"goal": "Increase InstaQuote submissions",
                                 "audience": "in-ground pool owners"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"]["status"] == "pending"
    assert body["action"]["employee_key"] == "commet"
    after = _balance(admin_headers)
    assert before - after == 6


def test_commet_analyze_conversion_readonly(admin_headers):
    eid = _emp_id(admin_headers, "commet")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "analyze",
                action="commet.analyze_conversion",
                action_params={"days": 60})
    assert r.status_code == 201
    assert r.json()["action"] is None
    assert r.json()["assistant_message"]["text"]


def test_commet_ab_variants_returns_three_and_is_approve_gated(admin_headers):
    eid = _emp_id(admin_headers, "commet")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "ab",
                action="commet.suggest_ab_variants",
                action_params={"element": "headline",
                                 "current_copy": "Book your pool cleaning today"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"]["status"] == "pending"
    assert len(body["action"]["draft"]["variants"]) == 3


def test_commet_ab_variants_missing_copy_returns_hint(admin_headers):
    eid = _emp_id(admin_headers, "commet")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "empty",
                action="commet.suggest_ab_variants",
                action_params={"element": "cta"})
    assert r.status_code == 201
    assert r.json()["action"] is None
    assert "current_copy" in r.json()["assistant_message"]["text"].lower()


def test_commet_recommend_cta_changes_readonly(admin_headers):
    eid = _emp_id(admin_headers, "commet")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "cta",
                action="commet.recommend_cta_changes",
                action_params={"current_cta": "Get a Quote"})
    assert r.status_code == 201, r.text
    assert r.json()["action"] is None
    after = _balance(admin_headers)
    assert before - after == 1


def test_commet_funnel_stage_report_readonly(admin_headers):
    eid = _emp_id(admin_headers, "commet")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "report",
                action="commet.funnel_stage_report")
    assert r.status_code == 201
    assert r.json()["action"] is None


def test_commet_approve_flips_to_executed(admin_headers):
    eid = _emp_id(admin_headers, "commet")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "draft",
                action="commet.draft_funnel_copy",
                action_params={"goal": "get quotes",
                                 "audience": "homeowners"})
    aid = r.json()["action"]["id"]
    r = requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "executed"
    assert r.json()["result"]["kind"] == "commet_draft_ready"


# ─── RBAC + cross-employee stub ───────────────────────────────────────

def test_ae4_approve_tech_forbidden(admin_headers, tech_headers):
    eid = _emp_id(admin_headers, "soshie")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "post",
                action="soshie.draft_post",
                action_params={"platform": "twitter",
                                 "topic": "test"})
    aid = r.json()["action"]["id"]
    r = requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                        headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_cross_employee_action_returns_stub(admin_headers):
    """soshie.* action sent to Scouty must return the polite stub."""
    eid = _emp_id(admin_headers, "scouty")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "x",
                action="soshie.draft_post",
                action_params={"platform": "instagram", "topic": "x"})
    assert r.status_code == 201
    body = r.json()
    assert body["action"] is None
    assert "isn't wired" in body["assistant_message"]["text"] \
        or "aren't wired" in body["assistant_message"]["text"]
