"""One-shot verification script — Feb 2026.

Runs VERIFY-1 (Stripe webhook signature + idempotency) and
VERIFY-2 (Stripe key health alert rehearsal) sequentially against the
running local backend. NOT part of the pytest suite — invoked ad-hoc
via ``python /tmp/verify_stripe_and_alert.py``.

Prints a structured report to stdout. Cleans up any test-only
marketing_deliveries rows it created but leaves the audit trail
(stripe_events_processed row) in place per the ops brief.
"""
from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

API = "http://localhost:8001/api"
WEBHOOK_URL = "http://localhost:8001/api/webhooks/stripe"
WHSEC = os.environ["STRIPE_WEBHOOK_SECRET"]
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "aquaterra")

BEC = "\n" + "═" * 78 + "\n"


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _sign(payload_bytes: bytes, ts: int, secret: str) -> str:
    signed = f"{ts}.".encode("utf-8") + payload_bytes
    v1 = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


# ═══════════════════════════ VERIFY-1 ══════════════════════════════════
async def verify_1():
    print(BEC + "VERIFY-1 — Stripe webhook signature + idempotency" + BEC)
    epoch = int(time.time())
    event_id = f"evt_selftest_{epoch}"
    pi_id = f"pi_selftest_{epoch}"
    # Real Brian Beckman invoice id per the ops brief.
    invoice_id = "2aee9222-4480-40b8-a8f8-38fc25eae676"
    event = {
        "id": event_id,
        "object": "event",
        "type": "payment_intent.succeeded",
        "api_version": "2022-11-15",
        "created": epoch,
        "livemode": True,
        "data": {
            "object": {
                "id": pi_id,
                "object": "payment_intent",
                "amount": 50,
                "currency": "usd",
                "status": "succeeded",
                "metadata": {"invoice_id": invoice_id},
                "created": epoch,
            }
        },
    }
    payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
    ts = int(time.time())
    good_sig = _sign(payload, ts, WHSEC)

    # (1) Valid signature — first POST.
    r1 = requests.post(
        WEBHOOK_URL, data=payload,
        headers={"Content-Type": "application/json", "stripe-signature": good_sig},
        timeout=15,
    )
    print(f"[1] Valid POST         → status={r1.status_code}")
    print(f"    body: {r1.text}")

    # (2) Valid signature — SAME event.id → dedupe expected.
    ts2 = int(time.time())
    good_sig2 = _sign(payload, ts2, WHSEC)
    r2 = requests.post(
        WEBHOOK_URL, data=payload,
        headers={"Content-Type": "application/json", "stripe-signature": good_sig2},
        timeout=15,
    )
    print(f"[2] Valid replay POST  → status={r2.status_code}")
    print(f"    body: {r2.text}")

    # (3) Bad signature (flip a hex char in v1).
    bad_v1 = good_sig.split(",v1=")[1]
    flipped = ("0" if bad_v1[0] != "0" else "1") + bad_v1[1:]
    bad_sig = f"t={ts},v1={flipped}"
    r3 = requests.post(
        WEBHOOK_URL, data=payload,
        headers={"Content-Type": "application/json", "stripe-signature": bad_sig},
        timeout=15,
    )
    print(f"[3] Bad-sig POST       → status={r3.status_code}")
    print(f"    body: {r3.text}")

    # DB inspection.
    db = _db()
    rows = await db.stripe_events_processed.find(
        {"event_id": event_id}, {"_id": 0},
    ).to_list(10)
    print(f"\nstripe_events_processed rows for {event_id}: {len(rows)}")
    for r in rows:
        print(f"  {r}")

    # marketing_deliveries — payment-triggered receipts.
    deliveries = await db.marketing_deliveries.find(
        {"trigger_entity.kind": "payment",
         "trigger_entity.id": pi_id},
        {"_id": 0},
    ).to_list(10)
    if not deliveries:
        # Some downstream handlers key by invoice_id — check that too.
        deliveries = await db.marketing_deliveries.find(
            {"trigger_entity.kind": "payment",
             "trigger_entity.id": invoice_id},
            {"_id": 0},
        ).to_list(10)
    print(f"marketing_deliveries rows with trigger_entity.kind=payment (pi/inv): "
           f"{len(deliveries)}")
    for d in deliveries:
        short = {k: d.get(k) for k in
                 ("id", "channel", "recipient_email", "recipient_phone",
                  "subject_rendered", "provider", "provider_response_id",
                  "trigger_entity")}
        print(f"  {short}")

    # Optional cleanup of test-created marketing_deliveries rows.
    if deliveries:
        ids = [d["id"] for d in deliveries]
        res = await db.marketing_deliveries.delete_many({"id": {"$in": ids}})
        print(f"  cleanup: deleted {res.deleted_count} marketing_deliveries row(s)")

    print(f"\nExpected: [1]=200, [2]=200 idempotent, [3]=400, rows=1")
    print(f"Observed: [1]={r1.status_code}, [2]={r2.status_code}, [3]={r3.status_code}, rows={len(rows)}")


# ═══════════════════════════ VERIFY-2 ══════════════════════════════════
async def verify_2():
    print(BEC + "VERIFY-2 — Stripe key health alert rehearsal" + BEC)
    tok = _login("admin@aquaterra.com")
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    db = _db()

    # 0. Ensure sms_escalation_recipients is populated for aquaterra
    #    using the tenant's own support_phone_number (no invented data).
    aqua = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    if not aqua.get("sms_escalation_recipients"):
        support = aqua.get("support_phone_number")
        if support:
            print(f"[pre] Seeding aquaterra.sms_escalation_recipients from "
                    f"tenant.support_phone_number = {support}")
            await db.tenants.update_one(
                {"id": aqua["id"]},
                {"$set": {"sms_escalation_recipients": [support]}},
            )
        else:
            print("[pre] WARN: aquaterra has neither sms_escalation_recipients nor support_phone_number")
    # Clear any prior cooldown for aquaterra so the alert is not suppressed.
    del_res = await db.ops_alerts_state.delete_many({"kind": "stripe_key_alert"})
    print(f"[pre] cleared ops_alerts_state.stripe_key_alert rows: {del_res.deleted_count}")

    # 1. Stub the stripe SDK first (replaces stripe.Account.retrieve
    #    with the in-process stub), then flip the "raise" flag.
    r_stub = requests.post(f"{API}/dev/_phase4b_stub_stripe",
                            headers=hdr, timeout=10)
    print(f"[1a] stub_stripe        → {r_stub.status_code} {r_stub.text}")
    r_raise = requests.post(f"{API}/dev/_phase4b_stub_account_raise",
                             headers=hdr, timeout=10)
    print(f"[1b] stub_account_raise → {r_raise.status_code} {r_raise.text}")

    # 2. Trigger the health run.
    r_run = requests.post(f"{API}/dev/stripe-key-health-run",
                           headers=hdr, timeout=30)
    print(f"[2] stripe-key-health-run → {r_run.status_code}")
    try:
        body = r_run.json()
    except Exception:
        body = r_run.text
    print(f"    body: {json.dumps(body, indent=2, default=str)}")

    # 3. Query marketing_deliveries.
    since = datetime.now(timezone.utc) - timedelta(seconds=90)
    since_iso = since.isoformat()
    rows = await db.marketing_deliveries.find(
        {"trigger_entity.kind": "stripe_key_alert",
         "sent_at": {"$gte": since_iso}},
        {"_id": 0},
    ).sort("sent_at", -1).to_list(50)
    email_rows = [r for r in rows if r.get("channel") == "email"]
    sms_rows = [r for r in rows if r.get("channel") == "sms"]
    print(f"[3] deliveries in last 90s → total={len(rows)} "
           f"email={len(email_rows)} sms={len(sms_rows)}")
    for r in email_rows:
        print(f"  EMAIL id={r.get('id')} to={r.get('recipient_email')} "
                f"provider={r.get('provider')} "
                f"provider_response_id={r.get('provider_response_id')} "
                f"provider_status={r.get('provider_status')} mock={r.get('mock')}")
    for r in sms_rows:
        print(f"  SMS   id={r.get('id')} to={r.get('recipient_phone')} "
                f"provider={r.get('provider')} "
                f"provider_response_id={r.get('provider_response_id')} "
                f"provider_status={r.get('provider_status')} mock={r.get('mock')}")
    if email_rows:
        print(f"\n[3] Sample email body (first 900 chars):")
        print(email_rows[0].get("body_rendered", "")[:900])

    # 4. Reset stub + verify.
    print()
    time.sleep(2)  # tiny pause; not strictly required
    r_ok = requests.post(f"{API}/dev/_phase4b_stub_account_ok",
                          headers=hdr, timeout=10)
    print(f"[5a] stub_account_ok    → {r_ok.status_code} {r_ok.text}")
    r_unstub = requests.post(f"{API}/dev/_phase4b_unstub_stripe",
                              headers=hdr, timeout=10)
    print(f"[5b] unstub_stripe      → {r_unstub.status_code} {r_unstub.text}")
    r_ping = requests.post(f"{API}/dev/stripe-live-ping",
                            headers=hdr, timeout=30)
    print(f"[6] stripe-live-ping   → {r_ping.status_code}")
    try:
        pbody = r_ping.json()
    except Exception:
        pbody = r_ping.text
    print(f"    body: {json.dumps(pbody, indent=2, default=str)}")


async def main():
    await verify_1()
    await verify_2()


if __name__ == "__main__":
    asyncio.run(main())
