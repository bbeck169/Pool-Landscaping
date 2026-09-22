"""Phase P30 · Feb-2026 — Stripe ``checkout.session.completed`` webhook
strict-routing tests for the ``card_add_setup`` branch.

Covers the P30 addendum hardening:

1. Happy path — all metadata correct, ``session.customer`` matches
   the internal customer's ``stripe_customer_id`` → attach fires,
   customer flagged ``has_card_on_file=True``, audit row minted.
2. Metadata missing ``crm_tenant_id`` → NO attach, ERROR logged.
3. Metadata missing ``crm_customer_id`` → NO attach, ERROR logged.
4. Customer id points at a customer in a DIFFERENT tenant than
   ``crm_tenant_id`` → tenant-scoped lookup misses, NO attach,
   ERROR logged.
5. ``session.customer`` (Stripe cust) does NOT match the internal
   customer's ``stripe_customer_id`` → NO attach, CRITICAL logged.
6. Idempotency — a re-delivery of the same ``session_id`` returns
   ``{idempotent: true}`` and never double-writes the audit row.
7. Non-P30 checkout.session.completed events (metadata.source unset
   or set to a Phase-47 invoice pay marker) do NOT enter the branch.

All tests use the F7 loop-bound Mongo so the strict routing exercises
the same ``db.customers``/``db.payment_events`` collections the
production webhook writes to.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════════
# Stub Stripe SDK — the webhook retrieves SetupIntents + attaches
# PaymentMethods via ``_stripe.SetupIntent.retrieve`` /
# ``_stripe.PaymentMethod.attach`` / ``_stripe.Customer.modify``. Every
# test swaps in a fresh stub via ``set_stripe_client`` so the webhook
# never hits the network.
# ═════════════════════════════════════════════════════════════════════
class _StubStripe:
    def __init__(self, *, pm_id: str = "pm_stub_abc"):
        self.SetupIntent = MagicMock()
        # Stripe SDK returns an object exposing ``.payment_method`` OR
        # a dict — `_asdict` normalizes.  Use dict for simplicity.
        self.SetupIntent.retrieve = MagicMock(return_value={
            "id": "seti_stub", "payment_method": pm_id,
        })
        self.PaymentMethod = MagicMock()
        self.PaymentMethod.attach = MagicMock(return_value={"id": pm_id})
        self.Customer = MagicMock()
        self.Customer.modify = MagicMock(return_value={"id": "cus_stub"})
        # Init-key hooks.
        self.api_key = None
        self.api_version = None


@pytest.fixture(autouse=True)
def _stripe_stub():
    from services.payments import stripe_charge
    stub = _StubStripe()
    stripe_charge.set_stripe_client(stub)
    yield stub
    stripe_charge.set_stripe_client(None)


def _mk_event(
    *,
    session_id: str,
    stripe_cust: Optional[str] = "cus_matching",
    setup_intent: Optional[str] = "seti_stub",
    source: str = "card_add_setup",
    crm_tenant_id: Optional[str] = None,
    crm_customer_id: Optional[str] = None,
    include_tenant: bool = True,
    include_customer: bool = True,
) -> Dict[str, Any]:
    """Build a ``checkout.session.completed`` event envelope."""
    metadata: Dict[str, Any] = {"source": source, "flow": "card_add_setup"}
    if include_tenant and crm_tenant_id is not None:
        metadata["crm_tenant_id"] = crm_tenant_id
    if include_customer and crm_customer_id is not None:
        metadata["crm_customer_id"] = crm_customer_id
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "customer": stripe_cust,
            "setup_intent": setup_intent,
            "metadata": metadata,
        }},
    }


async def _seed_customer(db, *, tenant_id, cid, stripe_cust_id):
    await db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id, "name": "P30 Webhook Test",
        "email": "webhook@p30.test",
        "stripe_customer_id": stripe_cust_id,
        "has_card_on_file": False,
    })


async def _cleanup(db, *, cid, session_id):
    await db.customers.delete_one({"id": cid})
    await db.payment_events.delete_many({"session_id": session_id})


# ═════════════════════════════════════════════════════════════════════
# 1. Happy path — attach fires, customer flagged, audit row minted.
# ═════════════════════════════════════════════════════════════════════
def test_p30_webhook_happy_path_attaches_and_stamps_customer(
    _stripe_stub,
):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-p30w-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
        await _seed_customer(
            db, tenant_id=tid, cid=cid, stripe_cust_id="cus_happy",
        )
        try:
            evt = _mk_event(
                session_id=session_id, stripe_cust="cus_happy",
                crm_tenant_id=tid, crm_customer_id=cid,
            )
            out = await handle_webhook_event(evt)
            assert out["handled"] is True
            assert out["source"] == "card_add_setup"
            assert out["payment_method_id"] == "pm_stub_abc"

            # SetupIntent retrieved, PM attached, default set.
            assert _stripe_stub.SetupIntent.retrieve.call_count == 1
            assert _stripe_stub.PaymentMethod.attach.call_count == 1
            _stripe_stub.PaymentMethod.attach.assert_called_with(
                "pm_stub_abc", customer="cus_happy",
            )
            assert _stripe_stub.Customer.modify.call_count == 1

            # Customer row flagged.
            row = await db.customers.find_one(
                {"id": cid, "tenant_id": tid},
                {"_id": 0, "has_card_on_file": 1,
                    "stripe_default_payment_method": 1,
                    "card_added_via": 1},
            )
            assert row["has_card_on_file"] is True
            assert row["stripe_default_payment_method"] == "pm_stub_abc"
            assert row["card_added_via"] == "setup_link"

            # Audit row present.
            audit = await db.payment_events.find_one(
                {"session_id": session_id,
                    "kind": "p30_card_add_setup_completed"},
                {"_id": 0},
            )
            assert audit is not None
            assert audit["tenant_id"] == tid
            assert audit["customer_id"] == cid
            assert audit["payment_method_id"] == "pm_stub_abc"
        finally:
            await _cleanup(db, cid=cid, session_id=session_id)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 2. Missing ``crm_tenant_id`` → no attach, ERROR logged.
# ═════════════════════════════════════════════════════════════════════
def test_p30_webhook_missing_tenant_metadata_rejects(_stripe_stub, caplog):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-p30w-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        session_id = f"cs_missing_t_{uuid.uuid4().hex[:10]}"
        await _seed_customer(
            db, tenant_id=tid, cid=cid, stripe_cust_id="cus_x",
        )
        try:
            evt = _mk_event(
                session_id=session_id, stripe_cust="cus_x",
                include_tenant=False,
                crm_customer_id=cid,
            )
            with caplog.at_level(logging.ERROR):
                out = await handle_webhook_event(evt)
            # Not handled (returns without attaching).
            assert out.get("handled") is not True
            # No Stripe SDK call.
            assert _stripe_stub.PaymentMethod.attach.call_count == 0
            # Customer row untouched.
            row = await db.customers.find_one(
                {"id": cid}, {"_id": 0, "has_card_on_file": 1},
            )
            assert row["has_card_on_file"] is False
            # No audit row.
            audit = await db.payment_events.find_one(
                {"session_id": session_id}, {"_id": 0},
            )
            assert audit is None
            # ERROR log fired.
            assert any(
                "card_add_setup rejected" in rec.message
                and "crm_tenant_id" in rec.message
                for rec in caplog.records
                if rec.levelno == logging.ERROR
            )
        finally:
            await _cleanup(db, cid=cid, session_id=session_id)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 3. Missing ``crm_customer_id`` → no attach, ERROR logged.
# ═════════════════════════════════════════════════════════════════════
def test_p30_webhook_missing_customer_metadata_rejects(
    _stripe_stub, caplog,
):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-p30w-{uuid.uuid4().hex[:6]}"
        session_id = f"cs_missing_c_{uuid.uuid4().hex[:10]}"
        evt = _mk_event(
            session_id=session_id, stripe_cust="cus_x",
            crm_tenant_id=tid,
            include_customer=False,
        )
        with caplog.at_level(logging.ERROR):
            out = await handle_webhook_event(evt)
        assert out.get("handled") is not True
        assert _stripe_stub.PaymentMethod.attach.call_count == 0
        assert any(
            "card_add_setup rejected" in rec.message
            and "crm_customer_id" in rec.message
            for rec in caplog.records
            if rec.levelno == logging.ERROR
        )
        await db.payment_events.delete_many({"session_id": session_id})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 4. Cross-tenant metadata mismatch — customer belongs to tenant A,
#    metadata says tenant B. Tenant-scoped lookup misses.
# ═════════════════════════════════════════════════════════════════════
def test_p30_webhook_cross_tenant_customer_rejects(_stripe_stub, caplog):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid_a = f"t-a-{uuid.uuid4().hex[:6]}"
        tid_b = f"t-b-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        session_id = f"cs_xt_{uuid.uuid4().hex[:10]}"
        # Customer belongs to tenant A.
        await _seed_customer(
            db, tenant_id=tid_a, cid=cid, stripe_cust_id="cus_x",
        )
        try:
            # But the metadata claims tenant B.
            evt = _mk_event(
                session_id=session_id, stripe_cust="cus_x",
                crm_tenant_id=tid_b, crm_customer_id=cid,
            )
            with caplog.at_level(logging.ERROR):
                out = await handle_webhook_event(evt)
            assert out.get("handled") is not True
            assert _stripe_stub.PaymentMethod.attach.call_count == 0
            # Customer row (in tenant A) MUST NOT be flagged.
            row = await db.customers.find_one(
                {"id": cid, "tenant_id": tid_a},
                {"_id": 0, "has_card_on_file": 1},
            )
            assert row["has_card_on_file"] is False
            assert any(
                "customer=" in rec.message and "not found" in rec.message
                for rec in caplog.records
                if rec.levelno == logging.ERROR
            )
        finally:
            await _cleanup(db, cid=cid, session_id=session_id)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 5. Stripe-customer parity mismatch → CRITICAL logged, no attach.
# ═════════════════════════════════════════════════════════════════════
def test_p30_webhook_stripe_customer_parity_mismatch_rejects(
    _stripe_stub, caplog,
):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-p30w-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        session_id = f"cs_parity_{uuid.uuid4().hex[:10]}"
        # Internal row says stripe_customer_id=cus_internal.
        await _seed_customer(
            db, tenant_id=tid, cid=cid, stripe_cust_id="cus_internal",
        )
        try:
            # Session's Stripe customer is DIFFERENT — either tampered
            # or the internal row went stale.
            evt = _mk_event(
                session_id=session_id, stripe_cust="cus_TAMPERED",
                crm_tenant_id=tid, crm_customer_id=cid,
            )
            with caplog.at_level(logging.CRITICAL):
                out = await handle_webhook_event(evt)
            assert out.get("handled") is not True
            assert _stripe_stub.PaymentMethod.attach.call_count == 0
            row = await db.customers.find_one(
                {"id": cid}, {"_id": 0, "has_card_on_file": 1},
            )
            assert row["has_card_on_file"] is False
            # CRITICAL log fired with the parity-mismatch message.
            crit_records = [
                rec for rec in caplog.records
                if rec.levelno == logging.CRITICAL
                and "parity mismatch" in rec.message
            ]
            assert crit_records, (
                "expected CRITICAL parity-mismatch log; got: "
                + repr([r.message for r in caplog.records])
            )
        finally:
            await _cleanup(db, cid=cid, session_id=session_id)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 6. Idempotency — redelivery of same session_id → no double-write.
# ═════════════════════════════════════════════════════════════════════
def test_p30_webhook_redelivery_is_idempotent(_stripe_stub):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-p30w-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        session_id = f"cs_idem_{uuid.uuid4().hex[:10]}"
        await _seed_customer(
            db, tenant_id=tid, cid=cid, stripe_cust_id="cus_idem",
        )
        try:
            evt = _mk_event(
                session_id=session_id, stripe_cust="cus_idem",
                crm_tenant_id=tid, crm_customer_id=cid,
            )
            out1 = await handle_webhook_event(evt)
            assert out1["handled"] is True
            assert _stripe_stub.PaymentMethod.attach.call_count == 1

            out2 = await handle_webhook_event(evt)
            assert out2.get("idempotent") is True
            # Second delivery does NOT invoke the Stripe SDK again.
            assert _stripe_stub.PaymentMethod.attach.call_count == 1

            # Audit row count == 1.
            audit_count = await db.payment_events.count_documents(
                {"session_id": session_id,
                    "kind": "p30_card_add_setup_completed"},
            )
            assert audit_count == 1
        finally:
            await _cleanup(db, cid=cid, session_id=session_id)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 7. Non-P30 checkout.session.completed events NEVER enter the branch.
#    Guards against a Phase-47 invoice-pay session being mis-routed
#    when it shares the event type.
# ═════════════════════════════════════════════════════════════════════
def test_p30_webhook_unrelated_source_does_not_enter_card_branch(
    _stripe_stub,
):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        # Randomize the session + PI ids so this test never collides
        # with a leaked ``stripe_charges`` row from a prior run —
        # the collection has a unique index on
        # ``stripe_payment_intent_id``.
        session_id = f"cs_unrelated_{uuid.uuid4().hex[:10]}"
        pi_id = f"pi_p47_{uuid.uuid4().hex[:10]}"
        inv_id = f"inv-{uuid.uuid4().hex[:6]}"
        tid = f"t-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:6]}"
        evt = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": session_id,
                "customer": "cus_p47",
                "setup_intent": None,
                "payment_intent": pi_id,
                "payment_status": "unpaid",
                "amount_total": 5000,
                "currency": "usd",
                "metadata": {
                    "source": "phase47_invoice_pay",
                    "crm_tenant_id": tid,
                    "crm_customer_id": cid,
                    "crm_invoice_id": inv_id,
                },
            }},
        }
        try:
            await handle_webhook_event(evt)
            # The card-add branch was NEVER entered — no SetupIntent
            # retrieve, no PM attach.
            assert _stripe_stub.SetupIntent.retrieve.call_count == 0
            assert _stripe_stub.PaymentMethod.attach.call_count == 0
        finally:
            # Clean up any ``stripe_charges`` row inserted by the
            # P47 branch so re-runs don't collide on the unique
            # index.
            await db.stripe_charges.delete_many(
                {"stripe_checkout_session_id": session_id},
            )
            await db.stripe_charges.delete_many(
                {"stripe_payment_intent_id": pi_id},
            )

    run_test(_go)
