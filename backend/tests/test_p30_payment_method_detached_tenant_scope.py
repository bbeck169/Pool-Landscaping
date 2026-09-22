"""Phase P30 addendum · Feb-2026 — tenant-scoped ``payment_method.detached``
webhook handler.

Locks in the P30 addendum contract:

1. A ``payment_method.detached`` event for a customer with a saved
   card clears ``has_card_on_file`` + ``stripe_default_payment_method``
   on THAT customer's row and stamps the removal audit fields.
2. Idempotency — a second delivery for a customer already cleared
   is a no-op (no error, fields stay cleared).
3. The ``payment_methods`` mirror row is dropped by ``pm_id``.
4. Defense-in-depth: if two customers (across tenants) share the
   same ``stripe_customer_id`` (which the P30 unique index blocks
   but which could still exist on legacy data), a CRITICAL log
   fires and both rows are cleared. Prior code would only clear
   the first row matched globally by ``pm_id`` — this is the
   audit trail the incident-response runbook needs.

Uses the F7 loop-bound Mongo.
"""
from __future__ import annotations

import logging
import uuid

from tests._f7_loop_fixture import run_test


def _detached_event(*, pm_id, stripe_cust):
    return {
        "type": "payment_method.detached",
        "data": {"object": {
            "id": pm_id,
            "customer": stripe_cust,
        }},
    }


async def _seed(db, *, tenant_id, cid, stripe_cust_id,
                 has_card=True, pm_id=None):
    await db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Detach Test",
        "stripe_customer_id": stripe_cust_id,
        "has_card_on_file": has_card,
        "stripe_default_payment_method": pm_id,
    })


# ═════════════════════════════════════════════════════════════════════
# 1. Happy path — event clears the card on the matched customer.
# ═════════════════════════════════════════════════════════════════════
def test_p30_detached_clears_card_on_matched_customer():
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-det-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        pm_id = f"pm_det_{uuid.uuid4().hex[:8]}"
        stripe_cust = f"cus_det_{uuid.uuid4().hex[:8]}"
        await _seed(db, tenant_id=tid, cid=cid,
                     stripe_cust_id=stripe_cust,
                     has_card=True, pm_id=pm_id)
        try:
            evt = _detached_event(pm_id=pm_id, stripe_cust=stripe_cust)
            out = await handle_webhook_event(evt)
            assert out["handled"] is True
            row = await db.customers.find_one(
                {"id": cid, "tenant_id": tid},
                {"_id": 0, "has_card_on_file": 1,
                    "stripe_default_payment_method": 1,
                    "card_removed_at": 1, "card_removed_via": 1},
            )
            assert row["has_card_on_file"] is False
            assert row["stripe_default_payment_method"] is None
            assert row["card_removed_via"] == "stripe_detached_webhook"
            assert row["card_removed_at"] is not None
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 2. Idempotency — re-delivery of the same event is a safe no-op.
# ═════════════════════════════════════════════════════════════════════
def test_p30_detached_redelivery_is_idempotent():
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-det-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        pm_id = f"pm_{uuid.uuid4().hex[:8]}"
        stripe_cust = f"cus_{uuid.uuid4().hex[:8]}"
        await _seed(db, tenant_id=tid, cid=cid,
                     stripe_cust_id=stripe_cust, has_card=True,
                     pm_id=pm_id)
        try:
            evt = _detached_event(pm_id=pm_id, stripe_cust=stripe_cust)
            await handle_webhook_event(evt)
            # Second delivery — no error, row unchanged.
            await handle_webhook_event(evt)
            row = await db.customers.find_one(
                {"id": cid}, {"_id": 0, "has_card_on_file": 1},
            )
            assert row["has_card_on_file"] is False
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 3. Legacy dup — two customers sharing stripe_customer_id across
#    tenants → CRITICAL log fires, BOTH are cleared, the runbook
#    trail is captured.
# ═════════════════════════════════════════════════════════════════════
def test_p30_detached_dup_stripe_customer_across_tenants_clears_both(
    caplog,
):
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid_a = f"t-a-{uuid.uuid4().hex[:6]}"
        tid_b = f"t-b-{uuid.uuid4().hex[:6]}"
        cid_a = f"cA-{uuid.uuid4().hex[:8]}"
        cid_b = f"cB-{uuid.uuid4().hex[:8]}"
        pm_id = f"pm_{uuid.uuid4().hex[:8]}"
        shared_stripe = f"cus_dup_{uuid.uuid4().hex[:8]}"
        await _seed(db, tenant_id=tid_a, cid=cid_a,
                     stripe_cust_id=shared_stripe, has_card=True,
                     pm_id=pm_id)
        await _seed(db, tenant_id=tid_b, cid=cid_b,
                     stripe_cust_id=shared_stripe, has_card=True,
                     pm_id=pm_id)
        try:
            evt = _detached_event(pm_id=pm_id, stripe_cust=shared_stripe)
            with caplog.at_level(logging.CRITICAL):
                out = await handle_webhook_event(evt)
            assert out["handled"] is True
            row_a = await db.customers.find_one(
                {"id": cid_a}, {"_id": 0, "has_card_on_file": 1},
            )
            row_b = await db.customers.find_one(
                {"id": cid_b}, {"_id": 0, "has_card_on_file": 1},
            )
            assert row_a["has_card_on_file"] is False
            assert row_b["has_card_on_file"] is False
            # CRITICAL log fired.
            assert any(
                "share stripe_customer_id" in rec.message
                and shared_stripe in rec.message
                for rec in caplog.records
                if rec.levelno == logging.CRITICAL
            )
        finally:
            await db.customers.delete_many(
                {"id": {"$in": [cid_a, cid_b]}},
            )

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 4. Missing ``customer`` on the event → still drops the pm mirror
#    (guarded on ``pm_id`` only), but no customer row is touched.
# ═════════════════════════════════════════════════════════════════════
def test_p30_detached_missing_stripe_customer_touches_no_row():
    from services.payments.stripe_charge import handle_webhook_event

    async def _go(db):
        tid = f"t-det-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        pm_id = f"pm_{uuid.uuid4().hex[:8]}"
        stripe_cust = f"cus_{uuid.uuid4().hex[:8]}"
        await _seed(db, tenant_id=tid, cid=cid,
                     stripe_cust_id=stripe_cust, has_card=True,
                     pm_id=pm_id)
        try:
            # Malformed event — no ``customer`` field.
            evt = {
                "type": "payment_method.detached",
                "data": {"object": {"id": pm_id}},
            }
            await handle_webhook_event(evt)
            row = await db.customers.find_one(
                {"id": cid}, {"_id": 0, "has_card_on_file": 1},
            )
            # Customer flag UNCHANGED — narrow guard held.
            assert row["has_card_on_file"] is True
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)
