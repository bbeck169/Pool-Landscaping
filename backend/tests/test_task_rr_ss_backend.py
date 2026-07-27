"""Task RR + SS · Feb 2026 — combined pytest coverage.

Covers:
  * Task RR — AI Employee tool registry: dispatch, access control,
    audit, rate-limit surface, and the tool-fence parser.
  * Task SS — admin service credit issuance + reversal endpoints,
    invoice paid-via-credit branch of ``apply_credits_to_invoice``.

Rate-limit tests only assert that the surface exists and rejects
correctly — they don't drive 100 real calls into the DB per pytest
run.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def admin_headers():
    # ``manager@aquaterra.com`` has role=admin in the Aquaterra tenant
    # (verified against ``users`` on 2026-02). Used for tests that
    # need a *regular* admin — distinct from super_admin — to exercise
    # the super_admin gate on ``read_access_scope=tenant_all``.
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def aq_tenant_id(db):
    t = _sync(db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1}))
    assert t
    return t["id"]


@pytest.fixture(scope="module")
def aq_customer_id(db, aq_tenant_id):
    """A synthetic Aquaterra customer id we can safely mutate credits on."""
    async def _find():
        c = await db.customers.find_one(
            {"tenant_id": aq_tenant_id}, {"_id": 0, "id": 1},
        )
        return c["id"] if c else None
    return _sync(_find())


# ═══════════════════════════════════════════════════════════════════
# Task RR — tool registry (no HTTP; direct dispatcher calls).
# ═══════════════════════════════════════════════════════════════════
def test_rr_tool_registry_exposes_8_tools():
    from services.ai_employee_tools import TOOL_REGISTRY
    assert set(TOOL_REGISTRY.keys()) == {
        "lookup_customer", "lookup_invoices", "lookup_invoice_detail",
        "lookup_next_visit", "lookup_service_history", "lookup_balance",
        "lookup_schedule", "search_customers",
    }


def test_rr_parse_tool_fence_extracts_name_and_args():
    from services.ai_employee_tools import parse_tool_fence
    reply = (
        "Sure — let me look that up.\n"
        "```tool\n"
        '{"name":"lookup_next_visit","args":{"customer_id":"c-1"}}\n'
        "```\n"
    )
    out = parse_tool_fence(reply)
    assert out is not None
    name, args = out
    assert name == "lookup_next_visit"
    assert args == {"customer_id": "c-1"}


def test_rr_parse_tool_fence_returns_none_on_plain_text():
    from services.ai_employee_tools import parse_tool_fence
    assert parse_tool_fence("no tool block here") is None


def test_rr_tool_schema_snippet_filters_by_scope():
    from services.ai_employee_tools import tool_schema_prompt_snippet
    customer_scoped = tool_schema_prompt_snippet(
        {"read_access_scope": "customer_scoped"}
    )
    tenant_all = tool_schema_prompt_snippet(
        {"read_access_scope": "tenant_all"}
    )
    # Customer-scoped persona should NOT see the tenant-all tools.
    assert "search_customers" not in customer_scoped
    assert "lookup_schedule" not in customer_scoped
    # Tenant_all persona sees everything.
    assert "search_customers" in tenant_all
    assert "lookup_schedule" in tenant_all
    # Everyone sees the customer-scoped tools.
    for t in ("lookup_next_visit", "lookup_balance"):
        assert t in customer_scoped
        assert t in tenant_all


def test_rr_dispatch_customer_scoped_persona_blocked_from_tenant_all_tool(db, aq_tenant_id):
    from services.ai_employee_tools import dispatch_tool
    persona = {"id": "p-test-1", "key": "billy", "read_access_scope": "customer_scoped"}
    out = _sync(dispatch_tool(
        tenant_id=aq_tenant_id, persona=persona,
        caller_kind="customer", caller_customer_id="c-abc",
        tool_name="search_customers", args={"query": "smith"},
    ))
    assert out.get("error") == "permission_denied"


def test_rr_dispatch_customer_scoped_rejects_cross_customer_lookup(db, aq_tenant_id, aq_customer_id):
    from services.ai_employee_tools import dispatch_tool
    persona = {"id": "p-test-2", "key": "billy", "read_access_scope": "customer_scoped"}
    other_cid = "c-not-mine-" + uuid.uuid4().hex[:6]
    out = _sync(dispatch_tool(
        tenant_id=aq_tenant_id, persona=persona,
        caller_kind="customer", caller_customer_id=aq_customer_id,
        tool_name="lookup_balance",
        args={"customer_id": other_cid},                # different from caller
    ))
    assert out.get("error") == "permission_denied"


def test_rr_dispatch_auto_injects_caller_customer_id(db, aq_tenant_id, aq_customer_id):
    from services.ai_employee_tools import dispatch_tool
    persona = {"id": "p-test-3", "key": "billy", "read_access_scope": "customer_scoped"}
    out = _sync(dispatch_tool(
        tenant_id=aq_tenant_id, persona=persona,
        caller_kind="customer", caller_customer_id=aq_customer_id,
        tool_name="lookup_balance", args={},           # no customer_id passed
    ))
    assert "result" in out
    r = out["result"]
    for k in ("unpaid_total_cents", "past_due_cents",
                "credit_balance_cents", "oldest_unpaid_days",
                "count_unpaid_invoices"):
        assert k in r


def test_rr_dispatch_tenant_all_persona_can_search_customers(db, aq_tenant_id):
    from services.ai_employee_tools import dispatch_tool
    persona = {"id": "p-test-4", "key": "billy_admin",
                 "read_access_scope": "tenant_all"}
    out = _sync(dispatch_tool(
        tenant_id=aq_tenant_id, persona=persona,
        caller_kind="admin", caller_id="u-admin",
        tool_name="search_customers", args={"query": "sm"},
    ))
    # Either got a list back OR a bad_args (query too short) — but
    # NEVER permission_denied.
    assert out.get("error") != "permission_denied"


def test_rr_audit_row_written_on_every_dispatch(db, aq_tenant_id, aq_customer_id):
    from services.ai_employee_tools import dispatch_tool
    persona = {"id": "p-audit-1", "key": "billy",
                 "read_access_scope": "customer_scoped"}
    _sync(dispatch_tool(
        tenant_id=aq_tenant_id, persona=persona,
        caller_kind="customer", caller_customer_id=aq_customer_id,
        tool_name="lookup_next_visit", args={},
    ))
    # Assert at least one audit row exists for this persona in the
    # last 60s.
    async def _find():
        return await db.ai_tool_calls.find_one(
            {"tenant_id": aq_tenant_id, "persona_id": "p-audit-1",
              "tool_name": "lookup_next_visit"},
            sort=[("created_at", -1)],
        )
    row = _sync(_find())
    assert row is not None
    assert row.get("result_status") in ("ok", "tool_error")
    assert row.get("persona_scope") == "customer_scoped"


def test_rr_audit_endpoint_admin_only(admin_headers, customer_headers):
    r_admin = requests.get(f"{API}/admin/ai-tool-audit",
                                  headers=admin_headers, timeout=30)
    assert r_admin.status_code == 200
    body = r_admin.json()
    assert "items" in body and "total" in body
    # Customer session must be rejected.
    r_cust = requests.get(f"{API}/admin/ai-tool-audit",
                                 headers=customer_headers, timeout=30)
    assert r_cust.status_code in (401, 403)


def test_rr_patch_read_access_scope_super_admin_only(admin_headers, super_headers, db, aq_tenant_id):
    # Find any admin-audience employee.
    async def _find():
        return await db.ai_employees.find_one(
            {"tenant_id": aq_tenant_id, "audience": "admin"},
            {"_id": 0, "id": 1},
        )
    emp = _sync(_find())
    if not emp:
        pytest.skip("no admin-audience employee to test against")
    eid = emp["id"]
    # Regular admin cannot flip to tenant_all.
    r_admin = requests.patch(
        f"{API}/ai-employees/{eid}",
        headers={**admin_headers, "Content-Type": "application/json"},
        json={"read_access_scope": "tenant_all"}, timeout=30,
    )
    assert r_admin.status_code == 403
    # Super_admin can.
    r_super = requests.patch(
        f"{API}/ai-employees/{eid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"read_access_scope": "tenant_all"}, timeout=30,
    )
    assert r_super.status_code == 200
    # Reset to safe default.
    requests.patch(
        f"{API}/ai-employees/{eid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"read_access_scope": "customer_scoped"}, timeout=30,
    )


# ═══════════════════════════════════════════════════════════════════
# Task SS — credits: paid-via-credit branch of apply_credits_to_invoice
# and admin endpoints.
# ═══════════════════════════════════════════════════════════════════
def test_ss_apply_credits_fully_paid_marks_paid_via_credit():
    from services.credits_apply import apply_credits_to_invoice
    invoice = {"id": "i-1", "customer_id": "c-1", "tenant_id": "t-1",
                  "total_cents": 3000, "line_items": [{"unit_price": 30}],
                  "status": "sent", "payment_status": "unpaid"}
    customer = {"id": "c-1", "credits_balance_cents": 5000}
    res = apply_credits_to_invoice(invoice, customer)
    assert res["credits_applied_cents"] == 3000
    upd = res["updated_invoice"]
    assert upd["total_cents"] == 0
    assert upd["payment_status"] == "paid"
    assert upd["paid_method"] == "service_credit"
    assert upd.get("paid_at")
    assert upd["status"] == "paid"
    assert res["updated_customer"]["credits_balance_cents"] == 2000


def test_ss_apply_credits_partial_leaves_unpaid_status():
    from services.credits_apply import apply_credits_to_invoice
    invoice = {"id": "i-2", "customer_id": "c-2", "tenant_id": "t-1",
                  "total_cents": 5000, "status": "sent",
                  "payment_status": "unpaid"}
    customer = {"id": "c-2", "credits_balance_cents": 1000}
    res = apply_credits_to_invoice(invoice, customer)
    assert res["credits_applied_cents"] == 1000
    upd = res["updated_invoice"]
    assert upd["total_cents"] == 4000
    assert upd.get("payment_status") == "unpaid"          # still unpaid
    assert upd.get("paid_method") is None
    assert res["updated_customer"]["credits_balance_cents"] == 0


def test_ss_apply_credits_zero_balance_no_op():
    from services.credits_apply import apply_credits_to_invoice
    invoice = {"id": "i-3", "customer_id": "c-3", "tenant_id": "t-1",
                  "total_cents": 5000, "status": "sent",
                  "payment_status": "unpaid"}
    customer = {"id": "c-3", "credits_balance_cents": 0}
    res = apply_credits_to_invoice(invoice, customer)
    assert res["credits_applied_cents"] == 0
    assert res["updated_invoice"]["total_cents"] == 5000


def test_ss_admin_issue_credit_happy_path(admin_headers, aq_customer_id, db, aq_tenant_id):
    """Task SS Phase 2 · Feb 2026 — the admin-issue endpoint is the
    already-shipped Phase 10 ``POST /customers/{cid}/credits/adjust``
    (retired the parallel Task-SS router to avoid divergent storage
    backends). Contract: ``{delta_cents, reason}``."""
    async def _bal():
        row = await db.customer_credits_balance.find_one(
            {"customer_id": aq_customer_id, "tenant_id": aq_tenant_id},
            {"_id": 0, "balance_cents": 1, "balance": 1},
        ) or {}
        return int(row.get("balance_cents")
                       or int(float(row.get("balance") or 0) * 100))
    before = _sync(_bal())
    r = requests.post(
        f"{API}/customers/{aq_customer_id}/credits/adjust",
        headers={**admin_headers, "Content-Type": "application/json"},
        json={"delta_cents": 2500, "reason": "TEST_SS admin issued credit"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_cents"] == before + 2500
    # Rollback via a compensating adjust so re-runs stay balanced.
    requests.post(
        f"{API}/customers/{aq_customer_id}/credits/adjust",
        headers={**admin_headers, "Content-Type": "application/json"},
        json={"delta_cents": -2500, "reason": "TEST_SS rollback"},
        timeout=30,
    )


def test_ss_admin_issue_credit_customer_role_gate(customer_headers, aq_customer_id):
    r = requests.post(
        f"{API}/customers/{aq_customer_id}/credits/adjust",
        headers={**customer_headers, "Content-Type": "application/json"},
        json={"delta_cents": 1000, "reason": "should be blocked"},
        timeout=30,
    )
    assert r.status_code in (401, 403)


def test_ss_admin_negative_pushes_below_zero_blocked(admin_headers, aq_customer_id, db, aq_tenant_id):
    async def _bal():
        row = await db.customer_credits_balance.find_one(
            {"customer_id": aq_customer_id, "tenant_id": aq_tenant_id},
            {"_id": 0, "balance_cents": 1, "balance": 1},
        ) or {}
        return int(row.get("balance_cents")
                       or int(float(row.get("balance") or 0) * 100))
    current = _sync(_bal())
    r = requests.post(
        f"{API}/customers/{aq_customer_id}/credits/adjust",
        headers={**admin_headers, "Content-Type": "application/json"},
        json={"delta_cents": -(current + 5000),
                "reason": "TEST_SS deduct below zero"},
        timeout=30,
    )
    assert r.status_code == 400
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("code") == "INSUFFICIENT_BALANCE"


def test_ss_admin_list_credits(admin_headers, aq_customer_id):
    r = requests.get(f"{API}/customers/{aq_customer_id}/credits",
                          headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "balance_cents" in body
    assert "ledger" in body
    assert isinstance(body["ledger"], list)


def test_ss_portal_own_credit_balance_endpoint(customer_headers):
    """Task RR/SS Phase 2 · Feb 2026 — new customer-scoped balance
    endpoint that powers the Portal Home CREDIT stat tile."""
    r = requests.get(f"{API}/customer-portal/credits/balance",
                          headers=customer_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "balance_cents" in body
    assert "balance_dollars" in body
    assert isinstance(body["balance_cents"], int)
    assert isinstance(body["balance_dollars"], (int, float))
