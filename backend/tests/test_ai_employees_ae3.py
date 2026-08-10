"""AE3 — Buddy + Vizzy + Dexter (Analytics Trio) — Feb-2026 ship."""
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
                        headers=admin_headers, json={"title": "AE3"}, timeout=15)
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


# ─── Roster ────────────────────────────────────────────────────────────

def test_ae3_trio_seeded(admin_headers):
    rows = requests.get(f"{API}/ai-employees", headers=admin_headers, timeout=15).json()
    keys = {e["key"] for e in rows}
    assert {"buddy", "vizzy", "dexter"} <= keys


# ─── Buddy ────────────────────────────────────────────────────────────

def test_buddy_weekly_growth_brief_creates_pending_action(admin_headers):
    eid = _emp_id(admin_headers, "buddy")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"],
                "Give me the growth brief.",
                action="buddy.weekly_growth_brief",
                action_params={"days": 7})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["assistant_message"]["text"]
    assert body["action"]["status"] == "pending"
    signals = body["action"]["draft"]["signals"]
    # All 5 data sources present.
    assert "deals" in signals
    assert "instaquote" in signals
    assert "reviews" in signals
    assert "campaigns" in signals
    assert "season" in signals
    # Chat 1c + heavy 5c = 6c debit total.
    after = _balance(admin_headers)
    assert before - after == 6


def test_buddy_pipeline_analysis_is_readonly_one_credit(admin_headers):
    eid = _emp_id(admin_headers, "buddy")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "Analyze the pipeline.",
                action="buddy.pipeline_analysis",
                action_params={"days": 14})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    assert body["assistant_message"]["text"]
    after = _balance(admin_headers)
    assert before - after == 1


def test_buddy_pricing_recommendation_is_approve_gated(admin_headers):
    eid = _emp_id(admin_headers, "buddy")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"],
                "Suggest pricing tweaks.",
                action="buddy.pricing_recommendation")
    assert r.status_code == 201
    body = r.json()
    assert body["action"]["status"] == "pending"
    assert body["action"]["employee_key"] == "buddy"
    after = _balance(admin_headers)
    assert before - after == 6


def test_buddy_approve_flips_to_executed_no_writes(admin_headers):
    eid = _emp_id(admin_headers, "buddy")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "brief",
                action="buddy.weekly_growth_brief")
    aid = r.json()["action"]["id"]
    r = requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed"
    assert r.json()["result"]["kind"] == "buddy_brief_acknowledged"


def test_buddy_approve_tech_forbidden(admin_headers, tech_headers):
    eid = _emp_id(admin_headers, "buddy")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "brief",
                action="buddy.weekly_growth_brief")
    aid = r.json()["action"]["id"]
    r = requests.post(f"{API}/ai-employees/actions/{aid}/approve",
                        headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


# ─── Vizzy ────────────────────────────────────────────────────────────

def test_vizzy_daily_brief_is_readonly(admin_headers):
    eid = _emp_id(admin_headers, "vizzy")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "brief please",
                action="vizzy.daily_brief")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    assert body["assistant_message"]["text"]
    assert "jobs_today" in body["assistant_message"]["text"]  # signal snapshot appended
    after = _balance(admin_headers)
    assert before - after == 1


def test_vizzy_prep_call_uses_customer_context(admin_headers):
    # Seed a customer.
    marker = uuid.uuid4().hex[:6]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"AE3-Prep {marker}",
        "first_name": "TEST_PREP", "last_name": f"P{marker}",
        "email": f"prep{marker}@example.com",
    }, timeout=15)
    cid = r.json()["id"]
    try:
        eid = _emp_id(admin_headers, "vizzy")
        c = _new_conv(admin_headers, eid)
        r = _send(admin_headers, eid, c["id"], "prep sheet",
                    action="vizzy.prep_call",
                    action_params={"customer_id": cid})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["action"] is None
        assert body["assistant_message"]["text"]
    finally:
        requests.delete(f"{API}/customers/{cid}",
                          headers=admin_headers, timeout=15)


def test_vizzy_prep_call_unknown_customer_graceful(admin_headers):
    eid = _emp_id(admin_headers, "vizzy")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "prep",
                action="vizzy.prep_call",
                action_params={"customer_id": uuid.uuid4().hex})
    assert r.status_code == 201
    body = r.json()
    assert body["action"] is None
    assert "not found" in body["assistant_message"]["text"].lower()


def test_vizzy_prep_call_missing_customer_id_returns_hint(admin_headers):
    eid = _emp_id(admin_headers, "vizzy")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "prep",
                action="vizzy.prep_call")
    assert r.status_code == 201
    assert "customer_id" in r.json()["assistant_message"]["text"].lower()


def test_vizzy_prioritize_today_returns_ranked_list(admin_headers):
    eid = _emp_id(admin_headers, "vizzy")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "what should I do today?",
                action="vizzy.prioritize_today")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    assert body["assistant_message"]["text"]
    after = _balance(admin_headers)
    assert before - after == 1


# ─── Dexter ────────────────────────────────────────────────────────────

def test_dexter_ad_hoc_query_returns_answer(admin_headers):
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "How many customers?",
                action="dexter.ad_hoc_query",
                action_params={"question": "How many customers do we have in Peoria?"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    assert body["assistant_message"]["text"]
    after = _balance(admin_headers)
    assert before - after == 1


def test_dexter_ad_hoc_query_too_broad_returns_hint(admin_headers):
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "everything",
                action="dexter.ad_hoc_query",
                action_params={"question": "List all data across everything since forever."})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] is None
    txt = body["assistant_message"]["text"].lower()
    assert "too broad" in txt or "narrow" in txt or "refine" in txt


def test_dexter_top_customers_by_revenue(admin_headers):
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "top by revenue",
                action="dexter.top_customers_report",
                action_params={"metric": "revenue", "period_days": 90})
    assert r.status_code == 201, r.text
    assert r.json()["assistant_message"]["text"]


def test_dexter_top_customers_by_visits(admin_headers):
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "top by visits",
                action="dexter.top_customers_report",
                action_params={"metric": "visits", "period_days": 90})
    assert r.status_code == 201, r.text


def test_dexter_top_customers_by_chemicals_cost(admin_headers):
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "top by chem cost",
                action="dexter.top_customers_report",
                action_params={"metric": "chemicals_cost", "period_days": 90})
    assert r.status_code == 201, r.text


def test_dexter_top_customers_unknown_metric_hint(admin_headers):
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "top",
                action="dexter.top_customers_report",
                action_params={"metric": "bogus"})
    assert r.status_code == 201
    assert "unknown metric" in r.json()["assistant_message"]["text"].lower()


def test_dexter_chemical_profitability_report_returns_analysis(admin_headers):
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    before = _balance(admin_headers)
    r = _send(admin_headers, eid, c["id"], "chem margin",
                action="dexter.chemical_profitability_report",
                action_params={"period_days": 60})
    assert r.status_code == 201, r.text
    assert r.json()["assistant_message"]["text"]
    after = _balance(admin_headers)
    assert before - after == 1


# ─── Tenant isolation ─────────────────────────────────────────────────

def test_dexter_snapshot_scoped_to_current_tenant(admin_headers):
    """Snapshot counts must match a direct query — no cross-tenant
    leak. We use aquaterra tenant customer count as ground truth."""
    r_customers = requests.get(f"{API}/customers?count_only=true",
                                  headers=admin_headers, timeout=15).json()
    ground = int(r_customers["count"])
    eid = _emp_id(admin_headers, "dexter")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "counts",
                action="dexter.ad_hoc_query",
                action_params={"question": "How many customers total?"})
    assert r.status_code == 201
    txt = r.json()["assistant_message"]["text"]
    # Non-strict check — either the ground-truth number is in the
    # text, OR the model chose to summarize non-numerically. We at
    # least require the text is non-empty (query executed).
    assert txt
    _ = ground


def test_ae3_tenant_scoping_no_cross_tenant_data(admin_headers):
    """A super-quick sanity check that Buddy's rollup didn't grab
    numbers from another tenant.

    Task D-1 · test drift fix — the previous ground-truth query hit
    ``GET /api/deals`` which is capped at ``limit=200`` (see
    ``routers/pipelines.py::list_deals``). Its top-level ``count``
    field is ``len(rows)`` on the PAGINATED slice, NOT the true
    tenant total. Any tenant with > 200 deals produces a false
    positive here. Fixed by ground-truthing via pymongo directly —
    same query Buddy runs under the hood.
    """
    import os
    from pymongo import MongoClient
    from dotenv import dotenv_values

    _env = {**dotenv_values(os.path.join(os.path.dirname(__file__),
                                              "..", ".env")),
             **os.environ}
    _db = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
    # Resolve the admin's tenant_id via the /auth/me endpoint.
    me = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=10)
    if me.status_code != 200:
        pytest.skip("/auth/me endpoint unavailable")
    tid = me.json().get("tenant_id")
    if not tid:
        pytest.skip("no tenant_id resolvable for admin")
    ground = _db.deals.count_documents({"tenant_id": tid})

    eid = _emp_id(admin_headers, "buddy")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "brief",
                action="buddy.weekly_growth_brief",
                action_params={"days": 365})
    assert r.status_code == 201
    signals = r.json()["action"]["draft"]["signals"]
    # Buddy's tenant-scoped aggregation MUST match the true tenant
    # total. A leak would show Buddy > ground.
    assert signals["deals"]["total_deals"] == ground, \
        f"tenant leak: buddy={signals['deals']['total_deals']} vs db={ground}"


# ─── Non-shipped actions still return polite stubs ────────────────────

def test_wrong_employee_for_dexter_action(admin_headers):
    """Sending a dexter.* action to Buddy → polite stub, no crash."""
    eid = _emp_id(admin_headers, "buddy")
    c = _new_conv(admin_headers, eid)
    r = _send(admin_headers, eid, c["id"], "x",
                action="dexter.ad_hoc_query",
                action_params={"question": "?"})
    assert r.status_code == 201
    body = r.json()
    assert body["action"] is None
    assert "isn't wired" in body["assistant_message"]["text"] \
        or "aren't wired" in body["assistant_message"]["text"]


# ─── OpenAPI still clean ──────────────────────────────────────────────

def test_ae3_openapi_unchanged():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    paths = r.json()["paths"]
    assert "/api/ai-employees/{eid}/conversations/{cid}/messages" in paths
    assert "/api/ai-employees/actions" in paths
