"""Stripe TEST 4 — real test-mode partial refund end-to-end.

Flow:
  1. Reuse existing customer for tenant 3814833a-... (cus_UxeVbgBEs6P9iU).
  2. Attach Stripe's built-in test PM `pm_card_visa` to that customer.
  3. Create a $0.50 invoice + charge it (test mode).
  4. Partial refund $0.25 via stripe.Refund.create.
  5. Replay the signed charge.refunded webhook.
  6. Assert partial state.
  7. Replay again → assert idempotent.
"""
from __future__ import annotations
import asyncio, os, sys, time, json, hmac, hashlib
sys.path.insert(0, "/app/backend")

import stripe
import requests
from uuid import uuid4

stripe.api_key = os.environ["STRIPE_SECRET_KEY_TEST"]
WH_SECRET = os.environ["STRIPE_WEBHOOK_SECRET_TEST"]
BACKEND = "https://poolscape-audit.preview.emergentagent.com"

from services.payments import stripe_charge as sc

TENANT = "3814833a-dd0d-4bd9-90ea-351c24924649"
CUSTOMER_ID = "f6685ef7-6b86-450d-93ef-3376b5dd85f0"
STRIPE_CUS = "cus_UxeVbgBEs6P9iU"


def sign_and_post(event: dict) -> tuple[int, str]:
    """Sign a Stripe webhook event dict and POST to backend."""
    payload = json.dumps(event, separators=(",", ":")).encode()
    ts = int(time.time())
    signed = f"{ts}.".encode() + payload
    sig = hmac.new(WH_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    hdr = f"t={ts},v1={sig}"
    r = requests.post(
        f"{BACKEND}/api/payments/stripe/webhook",
        data=payload,
        headers={"Stripe-Signature": hdr, "Content-Type": "application/json"},
        timeout=30,
    )
    return r.status_code, r.text[:200]


async def main():
    # Step 1: create a FRESH test-mode Stripe customer + attach a
    # test card. The existing CRM customer's `stripe_customer_id`
    # is a live-mode value; we can't reuse it under the test key.
    print(f"\n== TEST 4 · partial-refund e2e (real Stripe test mode) ==\n")
    stripe_cust = stripe.Customer.create(
        email="test4@aquaterra.local",
        name="Test-4 partial-refund customer",
        metadata={"source": "test4_script", "crm_tenant_id": TENANT},
    )
    stripe_cus_id = stripe_cust.id
    print(f"1. Created test Stripe customer: {stripe_cus_id}")
    pm = stripe.PaymentMethod.create(
        type="card",
        card={"token": "tok_visa"},  # Stripe test token → yields a real PM.
    )
    print(f"   Created test PM: {pm.id}")
    stripe.PaymentMethod.attach(pm.id, customer=stripe_cus_id)
    print(f"   Attached PM to customer {stripe_cus_id}")

    # Mirror into db.payment_methods so the service's attach guard clears.
    now = "2026-02-15T00:00:00+00:00"
    await sc.db.payment_methods.insert_one({
        "id": str(uuid4()),
        "tenant_id": TENANT, "customer_id": CUSTOMER_ID,
        "provider": "stripe", "provider_customer_id": stripe_cus_id,
        "provider_payment_method_id": pm.id,
        "brand": pm.card.brand, "last4": pm.card.last4,
        "exp_month": pm.card.exp_month, "exp_year": pm.card.exp_year,
        "is_default": False, "stripe_mode": "test",
        "created_at": now, "updated_at": now,
    })
    print("   Mirrored into db.payment_methods")

    # Step 2: create a fresh $0.50 invoice.
    inv_id = str(uuid4())
    await sc.db.quotes.insert_one({
        "id": inv_id, "tenant_id": TENANT, "doc_type": "invoice",
        "total": 0.50, "amount_paid": 0.0, "payment_status": "unpaid",
        "customer_id": CUSTOMER_ID, "currency": "usd",
        "created_at": now,
    })
    print(f"\n2. Created invoice {inv_id} · total=$0.50")

    # Step 3: charge $0.50 via the service.
    result = await sc.charge_card_on_file(
        tenant_id=TENANT, customer_id=CUSTOMER_ID,
        payment_method_id=pm.id, amount_cents=50,
        invoice_id=inv_id,
    )
    print(f"\n3. Charge result:")
    print(f"   status={result['status']}  pi={result['payment_intent_id']}")
    assert result["status"] == "succeeded", f"charge failed: {result}"
    pi_id = result["payment_intent_id"]

    inv = await sc.db.quotes.find_one({"id": inv_id})
    print(f"   invoice.amount_paid=${inv['amount_paid']}  payment_status={inv['payment_status']}")
    assert abs(inv["amount_paid"] - 0.50) < 0.01
    assert inv["payment_status"] == "paid"

    # Step 4: partial refund $0.25 via real Stripe API.
    refund = stripe.Refund.create(payment_intent=pi_id, amount=25)
    print(f"\n4. Created partial refund: {refund.id} · amount=$0.25")

    # Step 5: replay the signed charge.refunded webhook payload.
    ch = stripe.PaymentIntent.retrieve(pi_id, expand=["latest_charge"]).latest_charge
    if isinstance(ch, str):
        ch = stripe.Charge.retrieve(ch)
    ch_data = json.loads(str(ch))
    ch_data["amount_refunded"] = 25
    ch_data["refunded"] = False
    ch_data["payment_intent"] = pi_id

    event = {
        "id": f"evt_test4_{int(time.time()*1000)}",
        "object": "event", "api_version": "2020-08-27",
        "created": int(time.time()),
        "type": "charge.refunded", "livemode": False,
        "pending_webhooks": 1,
        "request": {"id": None, "idempotency_key": None},
        "data": {"object": ch_data},
    }
    status, body = sign_and_post(event)
    print(f"\n5. Webhook replay #1: HTTP {status}  body={body[:120]}")
    assert status == 200

    inv = await sc.db.quotes.find_one({"id": inv_id})
    print(f"   after replay #1: amount_paid=${inv['amount_paid']}  status={inv['payment_status']}")
    print(f"                    refunded_from_intents={inv.get('refunded_from_intents')}")
    assert abs(inv["amount_paid"] - 0.25) < 0.01, f"expected $0.25, got ${inv['amount_paid']}"
    assert inv["payment_status"] == "partially_refunded"
    assert len(inv.get("refunded_from_intents", [])) == 1

    # Step 6: replay the SAME payload → expect no drift.
    status, body = sign_and_post(event)
    print(f"\n6. Webhook replay #2 (same payload): HTTP {status}  body={body[:120]}")
    inv2 = await sc.db.quotes.find_one({"id": inv_id})
    print(f"   after replay #2: amount_paid=${inv2['amount_paid']}  status={inv2['payment_status']}")
    print(f"                    refunded_from_intents={inv2.get('refunded_from_intents')}")
    assert abs(inv2["amount_paid"] - 0.25) < 0.01, "double-subtract regression!"
    assert inv2["payment_status"] == "partially_refunded"
    assert inv2.get("refunded_from_intents") == inv.get("refunded_from_intents"), "set drift on replay"

    print("\n== TEST 4 · PASS ==\n")


if __name__ == "__main__":
    asyncio.run(main())
