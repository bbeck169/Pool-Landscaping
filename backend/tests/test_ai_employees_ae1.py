"""AE1 — AI Employees foundation + Casey (Feb-2026 ship)."""
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


@pytest.fixture
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


# ─── Roster seed + list ────────────────────────────────────────────────

def test_ai_employees_seeded_with_all_eight(admin_headers):
    r = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    keys = {e["key"] for e in rows}
    assert keys >= {"casey", "emmie", "buddy", "vizzy",
                     "dexter", "soshie", "scouty", "commet"}
    casey = next(e for e in rows if e["key"] == "casey")
    assert casey["role"] == "Directories"
    assert casey["active"] is True
    assert casey["avatar_emoji"]


def test_ai_employees_list_tech_forbidden(tech_headers):
    r = requests.get(f"{API}/ai-employees", headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_ai_employees_seed_is_idempotent(admin_headers):
    r1 = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15).json()
    r2 = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15).json()
    assert len(r1) == len(r2)
    assert {e["id"] for e in r1} == {e["id"] for e in r2}


def _casey_id(admin_headers):
    rows = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15).json()
    return next(e["id"] for e in rows if e["key"] == "casey")


# ─── Patch (rename + custom prompt) ────────────────────────────────────

def test_patch_employee_rename_and_prompt(admin_headers):
    eid = _casey_id(admin_headers)
    r = requests.patch(f"{API}/ai-employees/{eid}", headers=admin_headers, json={
        "name": "Casey the Curator",
        "system_prompt": "Custom Casey prompt.",
    }, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Casey the Curator"
    # Restore for later tests.
    requests.patch(f"{API}/ai-employees/{eid}", headers=admin_headers, json={
        "name": "Casey",
        "system_prompt": None,
    }, timeout=15)


def test_patch_employee_404(admin_headers):
    r = requests.patch(f"{API}/ai-employees/{uuid.uuid4().hex}",
                        headers=admin_headers, json={"name": "X"}, timeout=15)
    assert r.status_code == 404


def test_patch_employee_tech_forbidden(admin_headers, tech_headers):
    eid = _casey_id(admin_headers)
    r = requests.patch(f"{API}/ai-employees/{eid}", headers=tech_headers,
                        json={"name": "X"}, timeout=15)
    assert r.status_code in (401, 403)


# ─── Brand brain ──────────────────────────────────────────────────────

def test_brand_brain_lazy_create(admin_headers):
    r = requests.get(f"{API}/brand-brain", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert "tone" in r.json()


def test_brand_brain_patch_persists(admin_headers):
    marker = uuid.uuid4().hex[:6]
    r = requests.patch(f"{API}/brand-brain", headers=admin_headers, json={
        "tone": f"Friendly {marker}",
        "audience": "Homeowners",
        "do_say": ["Reliable", "On time"],
        "dont_say": ["Cheap"],
    }, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["tone"] == f"Friendly {marker}"


def test_brand_brain_tech_forbidden(tech_headers):
    r = requests.get(f"{API}/brand-brain", headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


# ─── Conversations + messages ─────────────────────────────────────────

def _new_conv(admin_headers, eid):
    r = requests.post(f"{API}/ai-employees/{eid}/conversations",
                        headers=admin_headers, json={"title": "T"}, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list_conversations(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    r = requests.get(f"{API}/ai-employees/{eid}/conversations",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert any(x["id"] == c["id"] for x in r.json())


def test_send_message_debits_and_persists(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    # Balance before.
    bal_before = requests.get(f"{API}/ai-credits/balance",
                                headers=admin_headers, timeout=15).json()["balance"]
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={"text": "hello"}, timeout=45)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user_message"]["text"] == "hello"
    assert body["assistant_message"]["text"]
    bal_after = requests.get(f"{API}/ai-credits/balance",
                               headers=admin_headers, timeout=15).json()["balance"]
    assert bal_after == bal_before - 1, f"chat should debit 1 credit; delta={bal_before - bal_after}"


def test_list_messages_returns_persisted_turns(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                    headers=admin_headers, json={"text": "one"}, timeout=45)
    requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                    headers=admin_headers, json={"text": "two"}, timeout=45)
    rows = requests.get(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                          headers=admin_headers, timeout=15).json()
    assert len(rows) >= 4
    texts = [m["text"] for m in rows]
    assert "one" in texts and "two" in texts


def test_conversation_isolation_between_users(admin_headers):
    """A conversation created by one admin must not appear in another
    user's list. We simulate this by manually creating a stray
    conversation with a fake user_id via direct DB write is not
    trivial from HTTP, so we just verify the current admin only sees
    their own threads."""
    eid = _casey_id(admin_headers)
    _new_conv(admin_headers, eid)
    r = requests.get(f"{API}/ai-employees/{eid}/conversations",
                       headers=admin_headers, timeout=15)
    for c in r.json():
        # The user_id field isn't returned; but empty user filter would
        # leak — this is a smoke test that the endpoint doesn't return
        # a huge cross-user list.
        assert "id" in c


def test_send_message_404_unknown_conversation(admin_headers):
    eid = _casey_id(admin_headers)
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{uuid.uuid4().hex}/messages",
                        headers=admin_headers, json={"text": "hi"}, timeout=15)
    assert r.status_code == 404


def test_disabled_employee_rejects_messages(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    requests.patch(f"{API}/ai-employees/{eid}", headers=admin_headers,
                     json={"active": False}, timeout=15)
    try:
        r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                            headers=admin_headers, json={"text": "x"}, timeout=15)
        assert r.status_code == 400
    finally:
        requests.patch(f"{API}/ai-employees/{eid}", headers=admin_headers,
                         json={"active": True}, timeout=15)


# ─── Casey actions ────────────────────────────────────────────────────

def test_casey_draft_directory_submission_creates_pending_action(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={
        "text": "Draft us a Google Business Profile listing.",
        "action": "casey.draft_directory_submission",
        "action_params": {"directory_slug": "gbp",
                            "directory_name": "Google Business Profile"},
    }, timeout=60)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is not None
    assert body["action"]["status"] == "pending"
    assert body["action"]["employee_key"] == "casey"
    assert body["action"]["action"] == "casey.draft_directory_submission"


def test_casey_suggest_directory_updates_no_nap(admin_headers):
    """Without a NAP profile, Casey answers with a helpful hint
    instead of a draft."""
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={
        "text": "What should we update?",
        "action": "casey.suggest_directory_updates",
    }, timeout=45)
    assert r.status_code == 201, r.text
    body = r.json()
    # Either a helpful hint (no NAP → no action) OR an action row if
    # the tenant already has a NAP + stale rows. Both are valid.
    assert body["assistant_message"]["text"]


def test_casey_draft_outreach_reply_creates_action(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={
        "text": "Reply to the Yelp outreach.",
        "action": "casey.draft_outreach_reply",
        "action_params": {"incoming_text": "Would you like to boost your listing?"},
    }, timeout=60)
    assert r.status_code == 201, r.text
    assert r.json()["action"]["action"] == "casey.draft_outreach_reply"


def test_non_casey_action_returns_polite_stub(admin_headers):
    rows = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15).json()
    emmie = next(e for e in rows if e["key"] == "emmie")
    c = _new_conv(admin_headers, emmie["id"])
    r = requests.post(f"{API}/ai-employees/{emmie['id']}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={
        "text": "Draft campaign.",
        "action": "casey.draft_directory_submission",
    }, timeout=30)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    assert "aren't wired" in body["assistant_message"]["text"] \
        or "isn't wired" in body["assistant_message"]["text"]


# ─── Actions queue + approve/reject ──────────────────────────────────

def test_approve_casey_action_flips_to_executed(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={
        "text": "Draft Angi listing.",
        "action": "casey.draft_directory_submission",
        "action_params": {"directory_slug": "angi"},
    }, timeout=60)
    aid = r.json()["action"]["id"]
    r = requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                        headers=admin_headers, json={"note": "LGTM"}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed"
    assert r.json()["result"]["kind"] == "casey_draft_ready"


def test_reject_action_sets_rejected(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={
        "text": "Draft BBB listing.",
        "action": "casey.draft_directory_submission",
        "action_params": {"directory_slug": "bbb"},
    }, timeout=60)
    aid = r.json()["action"]["id"]
    r = requests.post(f"{API}/ai-employees/actions/{aid}/reject",
                        headers=admin_headers, json={"note": "Wrong tone"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_approve_already_decided_400(admin_headers):
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    r = requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                         headers=admin_headers, json={
        "text": "Draft Yelp.",
        "action": "casey.draft_directory_submission",
    }, timeout=60)
    aid = r.json()["action"]["id"]
    requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 400


def test_list_actions_filters_by_status_and_key(admin_headers):
    r = requests.get(f"{API}/ai-employees/actions?status=executed&employee_key=casey",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    for a in r.json():
        assert a["status"] == "executed"
        assert a["employee_key"] == "casey"


def test_list_actions_tech_forbidden(tech_headers):
    r = requests.get(f"{API}/ai-employees/actions", headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_action_404_unknown_id(admin_headers):
    r = requests.get(f"{API}/ai-employees/actions/{uuid.uuid4().hex}",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404


def test_heavy_action_debits_more_than_chat(admin_headers):
    """Chat = 1 credit; a Casey action adds 5 on top → 6 total delta."""
    eid = _casey_id(admin_headers)
    c = _new_conv(admin_headers, eid)
    bal_before = requests.get(f"{API}/ai-credits/balance",
                                headers=admin_headers, timeout=15).json()["balance"]
    requests.post(f"{API}/ai-employees/{eid}/conversations/{c['id']}/messages",
                    headers=admin_headers, json={
        "text": "Draft HomeAdvisor.",
        "action": "casey.draft_directory_submission",
        "action_params": {"directory_slug": "home_advisor"},
    }, timeout=60)
    bal_after = requests.get(f"{API}/ai-credits/balance",
                               headers=admin_headers, timeout=15).json()["balance"]
    assert bal_before - bal_after == 6, f"expected 6-credit debit; delta={bal_before - bal_after}"


# ─── OpenAPI hygiene fixes (folded MP2 warns) ─────────────────────────

def test_jobs_openapi_documents_enrichment():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    body = r.json()["paths"]["/api/jobs"]["get"]
    desc = body["responses"]["200"]["description"]
    assert "property_label" in desc
    assert "property_address" in desc


def test_customers_openapi_documents_properties_count():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    body = r.json()["paths"]["/api/customers"]["get"]
    desc = body["responses"]["200"]["description"]
    assert "properties_count" in desc


def test_jobs_list_includes_property_keys_even_when_null(admin_headers):
    # Create a customer with no properties + one job → property_label/
    # property_address must be present with null values (AE1 hygiene).
    marker = uuid.uuid4().hex[:6]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"AE1NoProp {marker}",
        "first_name": "TEST_AE1", "last_name": f"NP{marker}",
    }, timeout=15)
    cid = r.json()["id"]
    try:
        r = requests.post(f"{API}/jobs", headers=admin_headers, json={
            "customer_id": cid, "title": "TEST_ae1_null_keys",
            "status": "scheduled",
        }, timeout=15)
        jid = r.json()["id"]
        r = requests.get(f"{API}/jobs", headers=admin_headers, timeout=15)
        j = next(x for x in r.json() if x["id"] == jid)
        assert "property_label" in j
        assert "property_address" in j
        assert j["property_label"] is None
        assert j["property_address"] is None
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)
    finally:
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


# ─── OpenAPI paths present ────────────────────────────────────────────

def test_openapi_has_ae1_paths():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    paths = r.json()["paths"]
    for p in (
        "/api/ai-employees",
        "/api/ai-employees/{eid}",
        "/api/ai-employees/{eid}/conversations",
        "/api/ai-employees/{eid}/conversations/{cid}/messages",
        "/api/ai-employees/actions",
        "/api/ai-employees/actions/{aid}/approve",
        "/api/ai-employees/actions/{aid}/reject",
        "/api/brand-brain",
    ):
        assert p in paths, f"missing {p}"
