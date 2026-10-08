"""Feb-2026 · MARCO-AI-CHAT Phase B — Safe-action tool tests.

Covers:
  (a) Role-gate widening (B4-b): admin + manager can hit the chat
      endpoints; technician gets 403; approve endpoint stays
      admin-only (manager → 403, technician → 403).
  (b) ``send_invoice_email`` dry-run returns {dry_run, action_id,
      recipient_masked, invoice_number, total} AND persists a
      ``marco_inline_confirm`` row.
  (c) ``send_estimate_email`` dry-run same shape with quote_number.
  (d) ``bulk_sms_scheduled`` dry-run returns customer_count + masked
      phones; the row is persisted.
  (e) ``approve_action`` on a ``marco_inline_confirm`` row
      re-dispatches the tool with the confirm_token and flips the
      status to ``executed`` (or ``failed`` when the primitive is
      not configured).
  (f) Tenant isolation — the approve endpoint 404s when the action
      row belongs to another tenant (admin cannot approve across
      tenants).
"""
import asyncio
import os
import uuid

import pytest
import requests

from tests._shared_mongo import shared_db
from tests._phase34_asyncio import batch_safe_run as _run_coro


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def manager_headers():
    try:
        tok = _login("manager@aquaterra.com")
    except AssertionError:
        pytest.skip("manager@aquaterra.com not seeded in this pod")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tech_headers():
    try:
        tok = _login("mike@aquaterra.com")
    except AssertionError:
        try:
            tok = _login("landscaper@aquaterra.com")
        except AssertionError:
            pytest.skip("no technician seed available in this pod")
    return {"Authorization": f"Bearer {tok}"}


def _marco(headers):
    r = requests.get(f"{API}/ai-employees", headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    marco = next((e for e in rows if e.get("key") == "marco_executive"),
                   None)
    assert marco, "MARCO persona not seeded on this pod"
    return marco


def _marco_db():
    """Return (marco_doc, tenant_id) looked up directly from Mongo."""
    db = shared_db()
    row = db.ai_employees.find_one({"key": "marco_executive"})
    assert row, "MARCO not in db.ai_employees"
    return row, row["tenant_id"]


# ══════════════════════════════════════════════════════════════════
# (a) ROLE GATE — B4-b
# ══════════════════════════════════════════════════════════════════
def test_manager_can_list_conversations(manager_headers):
    """Manager (B4-b) now reads Marco conversations."""
    marco = _marco(manager_headers)
    r = requests.get(f"{API}/ai-employees/{marco['id']}/conversations",
                     headers=manager_headers, timeout=15)
    assert r.status_code == 200, r.text


def test_manager_can_create_conversation(manager_headers):
    """Manager (B4-b) can start a Marco conversation.  Accepts 201
    (feature enabled on this tenant) OR 402 (``require_feature(
    'ai_copilot')`` rejection) — both prove the role gate let the
    manager through to the feature-marketplace check.  Only a 403
    from this endpoint would indicate the role gate bounced the
    manager, which is the regression we're guarding against."""
    marco = _marco(manager_headers)
    r = requests.post(f"{API}/ai-employees/{marco['id']}/conversations",
                      headers=manager_headers,
                      json={"title": "TEST_MARCO manager-chat"}, timeout=15)
    assert r.status_code in (201, 402), r.text
    # Explicit anti-regression: never 403 from the role gate.
    assert r.status_code != 403, r.text


def test_technician_forbidden_on_chat_endpoints(tech_headers):
    """Technicians still 403 on every chat endpoint."""
    # list_employees itself is admin-gated; use it as the smoke test.
    r = requests.get(f"{API}/ai-employees",
                     headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_manager_cannot_approve_action(manager_headers):
    """B4-b: approve endpoint stays admin-only. Insert a Marco
    inline-confirm row directly, verify manager gets 403 on approve."""
    db = shared_db()
    marco_row, tenant_id = _marco_db()
    aid = f"TEST_MARCO_{uuid.uuid4().hex[:10]}"
    db.ai_employee_actions.insert_one({
        "id": aid, "tenant_id": tenant_id,
        "employee_id": marco_row["id"],
        "employee_key": "marco_executive",
        "conversation_id": "conv-test-manager",
        "action": "marco.send_invoice_email",
        "params": {"invoice_id": "DUMMY"},
        "draft": {"recipient_masked": "***@example.com"},
        "title": "TEST manager-approve denial",
        "summary": "", "status": "pending",
        "kind": "marco_inline_confirm",
        "requested_by": "test", "decided_by": None,
        "decision_note": None, "executed_at": None, "result": None,
        "moderation_flags": [], "requires_human_approval": True,
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    })
    try:
        r = requests.post(
            f"{API}/ai-employees/actions/{aid}/approve",
            headers=manager_headers, json={}, timeout=15,
        )
        assert r.status_code in (401, 403), r.text
    finally:
        db.ai_employee_actions.delete_one({"id": aid})


# ══════════════════════════════════════════════════════════════════
# (b)(c)(d) DRY-RUN handlers persist marco_inline_confirm rows.
# ══════════════════════════════════════════════════════════════════
def _run(coro):
    """Run a coroutine from a sync test. Reuses the persistent
    session loop + Motor rebuild shim in ``tests._phase34_asyncio``
    so our handler tests tolerate the full-batch loop churn."""
    return _run_coro(coro)


def test_send_invoice_email_dry_run():
    """(b) Dry-run returns payload + persists marco_inline_confirm row."""
    db = shared_db()
    marco_row, tenant_id = _marco_db()
    cust_id = f"TEST_CUST_{uuid.uuid4().hex[:8]}"
    inv_id = f"TEST_INV_{uuid.uuid4().hex[:8]}"
    db.customers.insert_one({
        "id": cust_id, "tenant_id": tenant_id, "name": "TEST Customer",
        "email": "testinv@example.com", "phone": "+14805550101",
    })
    db.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id, "doc_type": "invoice",
        "customer_id": cust_id, "invoice_number": "INV-TEST-DRY-1",
        "total": 450.00, "amount_paid": 0,
    })
    try:
        from services.ai_employee_tools import _t_send_invoice_email
        result = _run(_t_send_invoice_email(
            tenant_id, invoice_id=inv_id,
            conversation_context={
                "conversation_id": "test-conv-dry-1",
                "tenant_id": tenant_id,
                "invoker_persona": marco_row,
                "user": {"id": "test-user"},
            },
        ))
        assert result.get("dry_run") is True, result
        assert result.get("action_id"), result
        assert result.get("invoice_number") == "INV-TEST-DRY-1"
        # Masked recipient: starts with 't' (local part first char).
        assert result.get("recipient_masked", "").startswith("t")
        # Row persisted with the right kind + action.
        row = db.ai_employee_actions.find_one(
            {"id": result["action_id"]})
        assert row is not None
        assert row["kind"] == "marco_inline_confirm"
        assert row["status"] == "pending"
        assert row["action"] == "marco.send_invoice_email"
        assert row["employee_key"] == "marco_executive"
    finally:
        db.customers.delete_one({"id": cust_id})
        db.quotes.delete_one({"id": inv_id})
        db.ai_employee_actions.delete_many(
            {"action": "marco.send_invoice_email",
             "params.invoice_id": inv_id})


def test_send_estimate_email_dry_run():
    """(c) Dry-run returns quote_number + persists row."""
    db = shared_db()
    marco_row, tenant_id = _marco_db()
    cust_id = f"TEST_CUST_{uuid.uuid4().hex[:8]}"
    quote_id = f"TEST_Q_{uuid.uuid4().hex[:8]}"
    db.customers.insert_one({
        "id": cust_id, "tenant_id": tenant_id, "name": "C",
        "email": "testq@example.com",
    })
    db.quotes.insert_one({
        "id": quote_id, "tenant_id": tenant_id, "doc_type": "quote",
        "customer_id": cust_id, "quote_number": "Q-TEST-DRY-1",
        "total": 999.00,
    })
    try:
        from services.ai_employee_tools import _t_send_estimate_email
        result = _run(_t_send_estimate_email(
            tenant_id, quote_id=quote_id,
            conversation_context={
                "conversation_id": "test-conv-dry-2",
                "tenant_id": tenant_id,
                "invoker_persona": marco_row,
                "user": {"id": "test-user"},
            },
        ))
        assert result.get("dry_run") is True, result
        assert result.get("quote_number") == "Q-TEST-DRY-1"
        row = db.ai_employee_actions.find_one(
            {"id": result["action_id"]})
        assert row["action"] == "marco.send_estimate_email"
        assert row["kind"] == "marco_inline_confirm"
    finally:
        db.customers.delete_one({"id": cust_id})
        db.quotes.delete_one({"id": quote_id})
        db.ai_employee_actions.delete_many(
            {"action": "marco.send_estimate_email",
             "params.quote_id": quote_id})


def test_bulk_sms_scheduled_dry_run_masks_phones():
    """(d) Dry-run returns customer_count + masked phones."""
    from datetime import datetime as _dt, timezone as _tz
    db = shared_db()
    marco_row, tenant_id = _marco_db()
    today_iso = _dt.now(_tz.utc).date().isoformat()
    cust_id = f"TEST_CUST_{uuid.uuid4().hex[:8]}"
    job_id = f"TEST_JOB_{uuid.uuid4().hex[:8]}"
    db.customers.insert_one({
        "id": cust_id, "tenant_id": tenant_id, "name": "Scheduled Cust",
        "phone": "+14805550199", "sms_opt_in": True,
    })
    db.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id, "customer_id": cust_id,
        "status": "scheduled", "scheduled_date": today_iso,
    })
    try:
        from services.ai_employee_tools import _t_bulk_sms_scheduled
        result = _run(_t_bulk_sms_scheduled(
            tenant_id, when="today", message="TEST bulk sms msg",
            conversation_context={
                "conversation_id": "test-conv-dry-3",
                "tenant_id": tenant_id,
                "invoker_persona": marco_row,
                "user": {"id": "test-user"},
            },
        ))
        assert result.get("dry_run") is True, result
        assert result.get("customer_count", 0) >= 1
        assert isinstance(result.get("phones_masked"), list)
        # Last 4 digits must appear in at least one masked phone.
        assert any("0199" in p for p in result["phones_masked"]), result
        # No unmasked phone leaks into the payload.
        assert not any("14805550199" in p for p in result["phones_masked"])
        row = db.ai_employee_actions.find_one(
            {"id": result["action_id"]})
        assert row["action"] == "marco.bulk_sms_scheduled"
        assert row["kind"] == "marco_inline_confirm"
    finally:
        db.customers.delete_one({"id": cust_id})
        db.jobs.delete_one({"id": job_id})
        db.ai_employee_actions.delete_many(
            {"action": "marco.bulk_sms_scheduled",
             "conversation_id": "test-conv-dry-3"})


# ══════════════════════════════════════════════════════════════════
# (e) Approve path re-dispatches the tool.
# ══════════════════════════════════════════════════════════════════
def test_approve_marco_inline_confirm_re_dispatches(admin_headers):
    """Admin approve on a marco_inline_confirm row re-dispatches the
    stored tool with ``_confirm_token`` and flips status to
    executed/failed."""
    db = shared_db()
    marco_row, tenant_id = _marco_db()
    cust_id = f"TEST_CUST_{uuid.uuid4().hex[:8]}"
    inv_id = f"TEST_INV_{uuid.uuid4().hex[:8]}"
    aid = f"TEST_MARCO_{uuid.uuid4().hex[:10]}"
    db.customers.insert_one({
        "id": cust_id, "tenant_id": tenant_id, "name": "ApproveCust",
        "email": "approve@example.com",
    })
    db.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id, "doc_type": "invoice",
        "customer_id": cust_id, "invoice_number": "INV-APPROVE-1",
        "total": 200.00,
    })
    db.ai_employee_actions.insert_one({
        "id": aid, "tenant_id": tenant_id,
        "employee_id": marco_row["id"],
        "employee_key": "marco_executive",
        "conversation_id": "conv-approve-test",
        "action": "marco.send_invoice_email",
        "params": {"invoice_id": inv_id},
        "draft": {"recipient_masked": "a***e@example.com"},
        "title": "TEST approve re-dispatch", "summary": "",
        "status": "pending", "kind": "marco_inline_confirm",
        "requested_by": "test-u", "decided_by": None,
        "decision_note": None, "executed_at": None, "result": None,
        "moderation_flags": [], "requires_human_approval": True,
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    })
    try:
        r = requests.post(
            f"{API}/ai-employees/actions/{aid}/approve",
            headers=admin_headers, json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] in ("executed", "failed"), body
        kind = (body.get("result") or {}).get("kind") or ""
        assert kind.startswith("marco_action_"), body
    finally:
        db.customers.delete_one({"id": cust_id})
        db.quotes.delete_one({"id": inv_id})
        db.ai_employee_actions.delete_one({"id": aid})


# ══════════════════════════════════════════════════════════════════
# (f) Tenant isolation.
# ══════════════════════════════════════════════════════════════════
def test_approve_tenant_isolation(admin_headers):
    """A row in another tenant must 404 on approve."""
    db = shared_db()
    marco_row, _tenant_id = _marco_db()
    aid = f"TEST_X_TENANT_{uuid.uuid4().hex[:10]}"
    other_tenant = f"test-other-tenant-{uuid.uuid4().hex[:6]}"
    db.ai_employee_actions.insert_one({
        "id": aid, "tenant_id": other_tenant,
        "employee_id": marco_row["id"],
        "employee_key": "marco_executive",
        "conversation_id": "x-tenant",
        "action": "marco.send_invoice_email",
        "params": {"invoice_id": "nope"},
        "draft": {}, "title": "X-TENANT",
        "summary": "", "status": "pending",
        "kind": "marco_inline_confirm",
        "requested_by": "x", "decided_by": None,
        "decision_note": None, "executed_at": None, "result": None,
        "moderation_flags": [], "requires_human_approval": True,
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    })
    try:
        r = requests.post(
            f"{API}/ai-employees/actions/{aid}/approve",
            headers=admin_headers, json={}, timeout=15,
        )
        assert r.status_code == 404, r.text
    finally:
        db.ai_employee_actions.delete_one({"id": aid})
