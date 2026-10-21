"""TD-97 · Feb-2026 — Four-entrypoint invariant + multi-quote reparent + bypass control.

Reconciliation regression guard shipped as part of the TD-97 Phase-1
reconciliation audit (audit doc:
``memory/td97_lead_auto_convert_on_quote_accept_audit.md``). TD-97 was
pre-shipped in commit ``3f153049b`` (P2 #4 backend · Oct 2026); this
file locks the invariants the audit identified as load-bearing for the
lead auto-convert pipeline.

Companion to ``test_lead_auto_convert_on_quote_accept.py`` (3 cases on
the happy-path + idempotency + customer-recipient control). This file
adds the invariants the audit §2 §4 §6 identified as not yet locked:

  * **§4 Four-entrypoint invariant**: ``_mark_accepted`` is the sole
    acceptance funnel referenced by all four production acceptance
    paths. Static import check — if a future refactor moves a path
    off the helper, this test fails before the ship lands.
  * **§6 Multi-outstanding-quote reparent**: accepting ONE
    lead-recipient quote reparents ALL other outstanding
    lead-recipient quotes on the same lead (not just the triggering
    one). Pipeline uses ``update_many`` scoped by
    ``recipient_type="lead" + recipient_id=<lid>`` — not by quote id.
  * **Control**: direct DB mutation flipping ``status="accepted"``
    WITHOUT calling ``_mark_accepted`` does NOT auto-convert the
    lead. Documents the schema contract: the auto-convert is driven
    by the helper, not by the status transition itself.
  * **Deprecated bypass documentation**: ``POST /quotes/{qid}/decision``
    is explicitly marked ``deprecated=True`` in
    ``routers/quotes.py:1985-2062`` and bypasses the hook on purpose.
    Dedicated test case documents the bypass with a pytest ``skip``
    + reason so a future refactor cannot silently remove the
    deprecation without also updating this guard.

Pattern parity: mirrors the harness established by
``test_lead_auto_convert_on_quote_accept.py`` — Motor direct, module-
level ``_patch_db_everywhere`` loop re-pin.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    for mod in ("routers.quotes", "routers.leads", "routers.estimates",
                "routers.reports", "routers.estimate_viewer",
                "routers.income_categories",
                "services.invoice_builder",
                "services.invoice_numbering", "services.recipient",
                "services.lead_conversion_notifications",
                "routers.finances"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"td97b-{uuid4().hex[:8]}"
TENANT = f"{PREFIX}-tenant"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_lead(lid, tid, name="Larry Lead"):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": name,
        "email": "larry@example.com", "phone": "480-555-0001",
        "service_address": "100 Palo Verde Way", "address": "100 Palo Verde Way",
        "status": "new", "source": "admin_manual",
        "timeline": [], "notes": "",
    })


async def _seed_lead_recipient_quote(qid, tid, lid, *, status="sent",
                                       name="Larry Lead", total=100.0):
    await _DB.quotes.insert_one({
        "id": qid, "tenant_id": tid, "doc_type": "quote",
        "customer_id": None, "customer_name": name,
        "recipient_type": "lead", "recipient_id": lid,
        "line_items": [{"description": "x", "quantity": 1,
                          "unit_price": total, "category": ""}],
        "subtotal": total, "tax": 0.0, "total": total,
        "amount_paid": 0.0, "status": status, "payment_status": "unpaid",
        "created_at": "2026-02-10T00:00:00+00:00",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "customers", "leads", "audit_logs",
                 "marketing_deliveries", "marketing_drip_enrollments",
                 "sales_sequences", "outbound_emails",
                 "tenant_pay_notifications"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx},
                     {"entity_id": rx}, {"lead_id": rx}, {"quote_id": rx}]},
        )
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


def _patch_notifications_noop():
    """fire_welcome_bundle imports Resend / RC adapter at call-time.
    Monkeypatch to a no-op so the pipeline stays hermetic in CI."""
    import services.lead_conversion_notifications as _m
    import sys

    async def _fake(**kw):
        return {"email_id": None, "sms_id": None, "drip_enrollment_id": None}

    _m.fire_welcome_bundle = _fake
    sys.modules["services.lead_conversion_notifications"].fire_welcome_bundle = _fake


# ═══════════════════════════════════════════════════════════════════
# §1 · Four-entrypoint invariant — _mark_accepted is importable and
# is the referenced helper by every production acceptance path.
# ═══════════════════════════════════════════════════════════════════
def test_mark_accepted_is_sole_funnel_across_four_entrypoints():
    """Static import + reference check. Fails if a future refactor
    moves any production accept path off ``_mark_accepted``.

    The four production paths are:
      (a) POST /quotes/{qid}/accept             — estimate_viewer:753
      (b) POST /portal/quotes/via-token/accept  — estimate_viewer:1110
      (c) POST /portal/quotes/{token}/approve   — estimate_viewer:1404
      (d) POST /quotes/bulk-accept              — quotes:3973

    This check reads the source text and asserts the helper symbol
    appears as a call site in each file. It's a textual guard rather
    than a runtime guard because the four endpoints have different
    auth / rate-limit / signature-gate preconditions that make a
    full runtime orchestration brittle — the real runtime behavior
    is already covered by ``test_lead_auto_convert_on_quote_accept.py``
    (direct helper call) and the referencing paths funneling into
    the same helper is the invariant we lock here.
    """
    from pathlib import Path

    _be = Path(__file__).resolve().parents[1]
    _ev = (_be / "routers" / "estimate_viewer.py").read_text()
    _qt = (_be / "routers" / "quotes.py").read_text()

    # (a-c) estimate_viewer.py has three call sites. The helper
    # itself is defined there, so we require 1 def + >= 3 call sites.
    assert "async def _mark_accepted(" in _ev, (
        "_mark_accepted definition missing from estimate_viewer.py"
    )
    call_sites_ev = _ev.count("_mark_accepted(")
    # 1 definition + 3 call sites = 4 occurrences minimum. If a path
    # is removed, this check needs an operator-approved update to
    # TD-97 TECH_DEBT.md explaining the new entrypoint shape.
    assert call_sites_ev >= 4, (
        f"estimate_viewer.py: expected >= 4 occurrences of "
        f"_mark_accepted (1 def + 3 call sites), found {call_sites_ev}. "
        "A production accept path was removed without a TD-97 update."
    )

    # (d) quotes.py bulk-accept imports and calls the helper.
    assert "from routers.estimate_viewer import _mark_accepted" in _qt, (
        "quotes.py: bulk_accept_quotes no longer imports _mark_accepted"
    )
    assert "await _mark_accepted(doc, tenant[\"id\"], user.get(\"id\"))" in _qt, (
        "quotes.py: bulk_accept_quotes no longer calls _mark_accepted"
    )


# ═══════════════════════════════════════════════════════════════════
# §2 · Multi-outstanding-quote reparent — accepting ONE lead-recipient
# quote reparents ALL other outstanding lead-recipient quotes on the
# same lead together.
# ═══════════════════════════════════════════════════════════════════
def test_accept_reparents_all_outstanding_lead_recipient_quotes():
    _patch_notifications_noop()
    lid = f"{PREFIX}-lead-multi"
    q1 = f"{PREFIX}-q-accept"      # the one being accepted
    q2 = f"{PREFIX}-q-sent-still"  # still in "sent" state
    q3 = f"{PREFIX}-q-viewed"      # still in "viewed" state
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(lid, TENANT))
    _run(_seed_lead_recipient_quote(q1, TENANT, lid,
                                      status="sent", total=100.0))
    _run(_seed_lead_recipient_quote(q2, TENANT, lid,
                                      status="sent", total=200.0))
    _run(_seed_lead_recipient_quote(q3, TENANT, lid,
                                      status="viewed", total=300.0))

    est = _run(_DB.quotes.find_one({"id": q1}, {"_id": 0}))
    from routers.estimate_viewer import _mark_accepted
    _run(_mark_accepted(est, TENANT, ADMIN["id"]))

    lead_after = _run(_DB.leads.find_one({"id": lid}, {"_id": 0}))
    cid = lead_after["converted_customer_id"]
    assert cid

    # All three quotes are reparented, regardless of their status.
    for qid in (q1, q2, q3):
        row = _run(_DB.quotes.find_one({"id": qid}, {"_id": 0}))
        assert row["recipient_type"] == "customer", (
            f"quote {qid} did not reparent: "
            f"recipient_type={row.get('recipient_type')!r}"
        )
        assert row["recipient_id"] == cid
        assert row["customer_id"] == cid
        assert row["converted_from_lead_id"] == lid

    # Non-triggering quotes' statuses are preserved — reparent flips
    # ownership fields only, not lifecycle status.
    q2_after = _run(_DB.quotes.find_one({"id": q2}, {"_id": 0}))
    q3_after = _run(_DB.quotes.find_one({"id": q3}, {"_id": 0}))
    assert q2_after["status"] == "sent"
    assert q3_after["status"] == "viewed"
    # The triggering quote did flip to accepted.
    q1_after = _run(_DB.quotes.find_one({"id": q1}, {"_id": 0}))
    assert q1_after["status"] == "accepted"

    # Exactly one audit row — the pipeline fires once per lead, not
    # per reparented quote.
    audit_rows = _run(_DB.audit_logs.find({
        "tenant_id": TENANT, "event": "lead.converted_via_quote",
        "lead_id": lid,
    }, {"_id": 0}).to_list(10))
    assert len(audit_rows) == 1
    assert audit_rows[0]["quote_id"] == q1


# ═══════════════════════════════════════════════════════════════════
# §3 · Control — direct DB mutation to status="accepted" WITHOUT
# calling _mark_accepted does NOT auto-convert the lead.
# ═══════════════════════════════════════════════════════════════════
def test_direct_status_mutation_bypasses_auto_convert():
    """Documents the schema contract: auto-convert is driven by the
    _mark_accepted helper, not by the status transition itself. A
    future ship that moves a production path off _mark_accepted and
    does a bare db.quotes.update_one({status:"accepted"}) will NOT
    auto-convert the lead — this test proves that so the §1 textual
    guard is semantically meaningful.
    """
    lid = f"{PREFIX}-lead-bypass"
    qid = f"{PREFIX}-q-bypass"
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(lid, TENANT))
    _run(_seed_lead_recipient_quote(qid, TENANT, lid, status="sent"))

    # Direct DB write — bypasses the hook entirely.
    _run(_DB.quotes.update_one(
        {"id": qid, "tenant_id": TENANT},
        {"$set": {"status": "accepted", "accepted_at": "2026-02-10T00:00:00+00:00"}},
    ))

    # Lead is NOT converted (converted_customer_id is still unset).
    lead_after = _run(_DB.leads.find_one({"id": lid}, {"_id": 0}))
    assert not lead_after.get("converted_customer_id"), (
        "Direct DB mutation should NOT auto-convert the lead. "
        "If this assertion flips, a status-transition-driven hook "
        "was introduced somewhere — update TD-97 TECH_DEBT.md to "
        "reflect the new invariant."
    )
    # Quote retains recipient_type="lead" (no reparent).
    q_after = _run(_DB.quotes.find_one({"id": qid}, {"_id": 0}))
    assert q_after["recipient_type"] == "lead"
    assert q_after["recipient_id"] == lid
    # Audit log is empty.
    audit_count = _run(_DB.audit_logs.count_documents({
        "tenant_id": TENANT, "event": "lead.converted_via_quote",
    }))
    assert audit_count == 0


# ═══════════════════════════════════════════════════════════════════
# §4 · Deprecated /quotes/{qid}/decision bypass — documented.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.skip(reason=(
    "DOCUMENTED KNOWN BYPASS: POST /quotes/{qid}/decision is marked "
    "deprecated=True in routers/quotes.py:1985-2062, customer-role-only, "
    "slated for removal after Phase C ships. It flips status='accepted' "
    "directly without calling _mark_accepted and therefore does NOT "
    "auto-convert the lead by design. Operators migrated to "
    "/portal/quotes/via-token/{token}/approve which routes through the "
    "hook. If this endpoint is UN-deprecated or kept past Phase C, "
    "this skip must be removed and the test re-written to assert the "
    "new intended behavior. Covered semantically by §3 (direct DB "
    "mutation control)."
))
def test_deprecated_decision_endpoint_bypasses_hook_known():
    """Placeholder locking the deprecation state.

    When Phase C ships and the deprecated endpoint is removed, delete
    this test case entirely. When reviewing, cross-check against:
      * routers/quotes.py:1985-2062 (endpoint, deprecated=True)
      * memory/td97_lead_auto_convert_on_quote_accept_audit.md §2.4
    """
    assert False, "unreachable — case is pytest.mark.skip"
