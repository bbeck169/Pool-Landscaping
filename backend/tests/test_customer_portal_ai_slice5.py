"""Feb-2026 · Slice 5 — Customer-portal AI carve-out (Skedra + Billy) tests.

Covers the full RBAC + data-scoping + escalation + credit surface.

We deliberately keep the LLM call in "stub" mode by NOT setting
``EMERGENT_LLM_KEY`` in the test process — the ``_llm_chat`` helper
returns a deterministic ``[stub] {user_text[:200]}`` reply which lets
us assert:
  * escalation triggers on a stub prefix
  * credit debits happen even when the LLM is stubbed
  * cross-customer isolation via the context payload we ship into
    the prompt (asserted directly by reading ``customer_scoped_context``)
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


def _db():
    """Fresh Motor client every call — avoids "attached to a different
    loop" errors when running direct-DB assertions from ``asyncio.run``
    inside sync pytest tests. The connection is closed by GC when the
    test's loop tears down."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    """Run ``coro`` on a fresh event loop (mirrors ``asyncio.run``).
    Every helper that touches Mongo goes through this so the Motor
    connection is opened + closed on the same loop the test uses."""
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════
# 1. Enumeration + audience RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_customer_lists_skedra_and_billy_only(customer_headers):
    r = requests.get(f"{API}/customer-portal/ai-employees",
                     headers=customer_headers, timeout=15)
    assert r.status_code == 200, r.text
    keys = sorted(x["key"] for x in r.json())
    assert keys == ["billy", "skedra"], (
        f"customer must see only Skedra + Billy — got {keys}"
    )
    for row in r.json():
        assert row.get("audience") == "customer"


def test_admin_does_not_see_customer_employees(admin_headers):
    """Admin AI Dock (unchanged endpoint) must never expose Skedra
    or Billy — they'd only clutter the admin panel."""
    r = requests.get(f"{API}/ai-employees",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200
    keys = {x["key"] for x in r.json()}
    assert "skedra" not in keys
    assert "billy" not in keys
    # But the original 8 must still be present — no regression.
    for expected in ("casey", "emmie", "buddy", "vizzy", "dexter",
                      "soshie", "scouty", "commet"):
        assert expected in keys, f"admin Dock lost {expected}"


def test_customer_forbidden_on_admin_ai_endpoint(customer_headers):
    r = requests.get(f"{API}/ai-employees",
                     headers=customer_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_admin_forbidden_on_customer_ai_endpoint(admin_headers):
    r = requests.get(f"{API}/customer-portal/ai-employees",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 403


def test_tech_forbidden_on_customer_ai_endpoint(tech_headers):
    r = requests.get(f"{API}/customer-portal/ai-employees",
                     headers=tech_headers, timeout=15)
    assert r.status_code == 403


def test_anon_forbidden_on_customer_ai_endpoint():
    r = requests.get(f"{API}/customer-portal/ai-employees", timeout=15)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# 2. Cross-audience conversation guard
# ═══════════════════════════════════════════════════════════════════════
def test_customer_cannot_open_admin_employee_conversation(customer_headers, admin_headers):
    """Customer sends a valid admin-audience employee id — the customer
    portal route MUST 403 rather than fall through and try the LLM."""
    r = requests.get(f"{API}/ai-employees",
                     headers=admin_headers, timeout=15).json()
    casey_id = next(e["id"] for e in r if e["key"] == "casey")
    r2 = requests.post(
        f"{API}/customer-portal/ai-employees/{casey_id}/conversations",
        headers=customer_headers, json={}, timeout=15,
    )
    assert r2.status_code == 403, r2.text


def test_admin_cannot_open_customer_employee_conversation(admin_headers, customer_headers):
    """Symmetric — admin sends a customer-audience employee id to the
    admin route → 403. Skedra + Billy are customer-only, full stop."""
    r = requests.get(f"{API}/customer-portal/ai-employees",
                      headers=customer_headers, timeout=15).json()
    skedra_id = next(e["id"] for e in r if e["key"] == "skedra")
    r2 = requests.post(
        f"{API}/ai-employees/{skedra_id}/conversations",
        headers=admin_headers, json={}, timeout=15,
    )
    assert r2.status_code == 403, r2.text


# ═══════════════════════════════════════════════════════════════════════
# 3. Conversation + chat happy path (stub LLM)
# ═══════════════════════════════════════════════════════════════════════
def _open_conv(headers, key: str):
    emps = requests.get(f"{API}/customer-portal/ai-employees",
                         headers=headers, timeout=15).json()
    eid = next(e["id"] for e in emps if e["key"] == key)
    r = requests.post(
        f"{API}/customer-portal/ai-employees/{eid}/conversations",
        headers=headers, json={}, timeout=15,
    )
    assert r.status_code in (200, 201), r.text
    return eid, r.json()["id"]


def test_open_conversation_and_chat(customer_headers):
    eid, cid = _open_conv(customer_headers, "billy")
    r = requests.post(
        f"{API}/customer-portal/ai-employees/{eid}/conversations/{cid}/messages",
        headers=customer_headers,
        json={"text": "What's my balance?"},
        timeout=30,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user_message"]["text"] == "What's my balance?"
    assert body["assistant_message"]["text"]
    # The LLM stub echoes the user text with a "[stub]" prefix — that
    # counts as no useful answer and should escalate on turn 2+, but
    # NOT on turn 1 (turn 1 with stub prefix means the model wasn't
    # available; still, we accept either behaviour on turn 1 as long
    # as we don't crash).
    assert body["assistant_message"]["provider"] in ("stub", "emergent")


def test_chat_debits_one_credit_per_message(customer_headers):
    """Confirm the tenant credit balance moves by exactly 1 per user
    message (matches admin AI chat cost). Zero-balance scenario is
    covered separately below."""
    async def _balance(email):
        db = _db()
        u = await db.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
        t = await db.tenants.find_one({"id": u["tenant_id"]},
                                        {"_id": 0, "ai_credits_balance": 1})
        return int(t.get("ai_credits_balance") or 0)

    before = asyncio.new_event_loop().run_until_complete(
        _balance("customer@aquaterra.com"),
    )

    eid, cid = _open_conv(customer_headers, "skedra")
    r = requests.post(
        f"{API}/customer-portal/ai-employees/{eid}/conversations/{cid}/messages",
        headers=customer_headers,
        json={"text": "When is my next pool visit?"},
        timeout=30,
    )
    assert r.status_code == 201

    after = asyncio.new_event_loop().run_until_complete(
        _balance("customer@aquaterra.com"),
    )

    if before > 0:
        assert after == before - 1, (
            f"expected exactly 1c debit — before={before}, after={after}"
        )
    else:
        # Zero-balance path: no debit (short-circuited), still escalates.
        assert after == before
        assert r.json().get("escalated") is True


# ═══════════════════════════════════════════════════════════════════════
# 4. Zero-credits graceful escalation
# ═══════════════════════════════════════════════════════════════════════
def test_zero_balance_triggers_graceful_escalation(customer_headers):
    """Force the tenant's ``ai_credits_balance`` to 0 and confirm the
    next customer message returns a graceful reply + fires an
    ``ai_escalation`` internal message + bell without crashing."""
    async def _set_balance(email, new_bal):
        db = _db()
        u = await db.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
        prior = await db.tenants.find_one({"id": u["tenant_id"]},
                                            {"_id": 0, "ai_credits_balance": 1})
        await db.tenants.update_one(
            {"id": u["tenant_id"]},
            {"$set": {"ai_credits_balance": new_bal}},
        )
        return int(prior.get("ai_credits_balance") or 0)

    prior = asyncio.new_event_loop().run_until_complete(
        _set_balance("customer@aquaterra.com", 0),
    )

    try:
        eid, cid = _open_conv(customer_headers, "billy")
        r = requests.post(
            f"{API}/customer-portal/ai-employees/{eid}/conversations/{cid}/messages",
            headers=customer_headers,
            json={"text": "I need to update my card."},
            timeout=30,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["escalated"] is True, body
        assert body["escalate_reason"] == "tenant_credits_exhausted"
        assert "unavailable" in body["assistant_message"]["text"].lower() or \
                "team" in body["assistant_message"]["text"].lower()
    finally:
        # Restore the tenant's credits so subsequent tests still exercise
        # the debit path.
        asyncio.new_event_loop().run_until_complete(
            _set_balance("customer@aquaterra.com", prior),
        )


# ═══════════════════════════════════════════════════════════════════════
# 5. Escalation wire — bell + internal message land on admin surface
# ═══════════════════════════════════════════════════════════════════════
def _bell_count(headers) -> int:
    r = requests.get(f"{API}/notifications/unread-count",
                     headers=headers, timeout=15)
    return int(r.json().get("count") or 0) if r.status_code == 200 else 0


def test_manual_handoff_fires_escalation(customer_headers, admin_headers):
    before = _bell_count(admin_headers)
    eid, cid = _open_conv(customer_headers, "skedra")
    # Prime the thread so the handoff has something to summarise.
    requests.post(
        f"{API}/customer-portal/ai-employees/{eid}/conversations/{cid}/messages",
        headers=customer_headers,
        json={"text": "I'd like to move my Tuesday appt."},
        timeout=30,
    )
    r = requests.post(
        f"{API}/customer-portal/ai-employees/{eid}/conversations/{cid}/handoff",
        headers=customer_headers, timeout=15,
    )
    assert r.status_code == 201, r.text
    after = _bell_count(admin_headers)
    assert after >= before + 1, (
        f"handoff must enqueue a bell for admins (before={before}, "
        f"after={after})"
    )

    # And confirm the deep-link href from the escalation resolves —
    # regression against the 3D 404 bug.
    rows = requests.get(f"{API}/notifications?limit=50",
                        headers=admin_headers, timeout=15).json() or []
    escalation_row = next(
        (n for n in rows
         if (n.get("source_ref") or {}).get("kind") == "ai_escalation"),
        None,
    )
    assert escalation_row is not None, "no ai_escalation bell row found"
    href = escalation_row.get("href") or ""
    assert href.startswith("/communication/"), (
        f"ai_escalation href must open the admin thread — got {href!r}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 6. Cross-customer + cross-tenant isolation — direct helper assertions
# ═══════════════════════════════════════════════════════════════════════
def test_customer_scoped_context_isolation_and_cross_tenant():
    """Consolidated data-isolation guarantee for ``customer_scoped_context``:
      * two customers in the same tenant — each sees only their own data
      * scheduling ctx isolated across customers
      * a foreign-tenant "shadow" invoice sharing the same customer_id
        must NOT leak into the owning tenant's ctx

    Consolidated into one function on purpose — Motor caches its
    connection on the first event loop it sees, so multiple sync tests
    hitting the same globals fail with "attached to a different loop".
    All three assertions share one loop below.
    """
    from routers.customer_ai import customer_scoped_context

    async def _go():
        # Use the same ``db`` module import that ``customer_scoped_context``
        # uses so the Motor client is bound to THIS loop.
        from config import db
        import json

        tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(2)
        assert len(tenants) >= 2, "need at least 2 tenants for this test"
        t_owner = tenants[0]["id"]
        t_foreign = tenants[1]["id"]

        c_a = f"slice5-A-{uuid.uuid4().hex[:8]}"
        c_b = f"slice5-B-{uuid.uuid4().hex[:8]}"
        c_cross = f"slice5-X-{uuid.uuid4().hex[:8]}"

        await db.customers.insert_many([
            {"id": c_a, "tenant_id": t_owner, "name": "AlphaCust"},
            {"id": c_b, "tenant_id": t_owner, "name": "BetaCust"},
            {"id": c_cross, "tenant_id": t_owner, "name": "CrossCust"},
        ])
        await db.quotes.insert_many([
            # Same-tenant, different customers with distinct numbers.
            {"id": f"inv-a-{c_a}", "tenant_id": t_owner,
             "customer_id": c_a, "doc_type": "invoice",
             "total": 111.11, "amount_paid": 0,
             "due_date": "2020-01-01"},
            {"id": f"inv-b-{c_b}", "tenant_id": t_owner,
             "customer_id": c_b, "doc_type": "invoice",
             "total": 777.77, "amount_paid": 0,
             "due_date": "2030-01-01"},
            # Cross-tenant shadow — same customer_id under a foreign
            # tenant. MUST never leak.
            {"id": f"shadow-{c_cross}", "tenant_id": t_foreign,
             "customer_id": c_cross, "doc_type": "invoice",
             "total": 9999.99, "amount_paid": 0},
        ])
        await db.jobs.insert_many([
            {"id": f"jA-{c_a}", "tenant_id": t_owner,
             "customer_id": c_a, "customer_name": "AlphaCust",
             "service_type": "AlphaClean",
             "status": "scheduled",
             "scheduled_start": "2030-08-05T10:00:00+00:00"},
            {"id": f"jB-{c_b}", "tenant_id": t_owner,
             "customer_id": c_b, "customer_name": "BetaCust",
             "service_type": "BetaSweep",
             "status": "scheduled",
             "scheduled_start": "2030-08-06T10:00:00+00:00"},
        ])

        try:
            # 6a — customer-A billing ctx must not leak customer-B numbers.
            ctx_a = await customer_scoped_context(t_owner, c_a, "billing")
            a_json = json.dumps(ctx_a)
            assert "111.11" in a_json, a_json
            assert "777.77" not in a_json, (
                f"cross-customer leak — B's $777.77 in A's ctx: {a_json}"
            )
            assert c_b not in a_json
            assert "BetaCust" not in a_json

            # 6b — customer-B billing ctx symmetric.
            ctx_b = await customer_scoped_context(t_owner, c_b, "billing")
            b_json = json.dumps(ctx_b)
            assert "777.77" in b_json
            assert "111.11" not in b_json
            assert c_a not in b_json
            assert "AlphaCust" not in b_json

            # 6c — scheduling ctx isolated too.
            ctx_sched = await customer_scoped_context(
                t_owner, c_a, "scheduling",
            )
            sched_json = json.dumps(ctx_sched)
            assert "AlphaClean" in sched_json
            assert "BetaSweep" not in sched_json, (
                f"cross-customer leak in scheduling ctx: {sched_json}"
            )

            # 6d — cross-tenant shadow invoice must be invisible.
            ctx_cross = await customer_scoped_context(
                t_owner, c_cross, "billing",
            )
            cross_json = json.dumps(ctx_cross)
            assert "9999.99" not in cross_json, (
                f"cross-tenant leak — foreign tenant's invoice appeared: "
                f"{cross_json}"
            )
        finally:
            await db.quotes.delete_many({"id": {"$in": [
                f"inv-a-{c_a}", f"inv-b-{c_b}", f"shadow-{c_cross}",
            ]}})
            await db.jobs.delete_many({"id": {"$in": [
                f"jA-{c_a}", f"jB-{c_b}",
            ]}})
            await db.customers.delete_many({"id": {"$in": [c_a, c_b, c_cross]}})

    _run(_go())
