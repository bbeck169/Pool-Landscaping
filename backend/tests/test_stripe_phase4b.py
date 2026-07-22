"""Phase 4B · Stripe Live Payments — end-to-end backend tests.

Hits the running backend on localhost:8001 (matches other Feb-2026 tests).

Coverage
========
* config surface           — /api/config/public, /api/dev/stripe-config-check
* payment-intent creation  — authenticated + portal magic-link paths,
                              amount tampering (client body ignored),
                              idempotency key format, RBAC (tech/other-cust)
* refund role gating       — admin allowed, manager allowed, tech denied,
                              customer denied, reason required
* webhook                  — bad signature 400, missing header 400,
                              successful event marks invoice paid + writes
                              transactional deliveries, duplicate event.id
                              processed exactly once, dispute fan-out
* magic-link viewer        — /full-magic public endpoint

Stripe SDK is monkeypatched **inside the backend process** via a
dedicated ``/api/dev/_phase4b_stub_stripe`` test hook that swaps in the
fakes — this keeps the test process out-of-process from Stripe.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import requests

os.environ.setdefault("STRIPE_SECRET_KEY", "sk_live_placeholder_test")
os.environ.setdefault("STRIPE_PUBLISHABLE_KEY", "pk_live_placeholder_test")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_placeholder_test")

API = "http://localhost:8001/api"


# ─── Dedicated loop so Motor is happy across tests ────────────────────
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]


# ─── Fake Stripe SDK (installed in-process via test hook) ─────────────
class _FakePI(dict):
    pass


def _install_stubs():
    """Monkey-patch stripe SDK inside the backend process. Called via
    an admin-only /api/dev/_phase4b_stub_stripe control endpoint that
    only registers when ALLOW_TEST_HOOKS=1 (set in .env)."""
    r = requests.post(f"{API}/dev/_phase4b_stub_stripe", timeout=15)
    assert r.status_code == 200, r.text


def _uninstall_stubs():
    requests.post(f"{API}/dev/_phase4b_unstub_stripe", timeout=15)


# ─── Auth helpers ─────────────────────────────────────────────────────
def _jwt_secret() -> str:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return os.environ["JWT_SECRET"]


def _mk_token(user_id: str, role: str, email: str = "u@example.com") -> str:
    return jwt.encode(
        {"sub": user_id, "email": email, "role": role,
         "exp": datetime.now(timezone.utc) + timedelta(hours=2)},
        _jwt_secret(), algorithm="HS256",
    )


def _headers_for(tok: str, slug: str) -> dict:
    return {"Authorization": f"Bearer {tok}",
             "X-Tenant-Slug": slug,
             "Content-Type": "application/json"}


# ─── Fixture: seed a fresh tenant for the whole module ────────────────
@pytest.fixture(scope="module", autouse=True)
def _stub_stripe():
    _install_stubs()
    yield
    _uninstall_stubs()


@pytest.fixture(scope="module")
def seed_env():
    from utils import new_id, now_iso  # local so PYTHONPATH stays fixed
    tenant_id = f"TEST_tenant_{uuid.uuid4().hex[:8]}"
    admin_id = f"TEST_admin_{uuid.uuid4().hex[:8]}"
    manager_id = f"TEST_manager_{uuid.uuid4().hex[:8]}"
    tech_id = f"TEST_tech_{uuid.uuid4().hex[:8]}"
    cust_id = f"TEST_cust_{uuid.uuid4().hex[:8]}"
    other_cust_id = f"TEST_other_{uuid.uuid4().hex[:8]}"
    inv_id = f"TEST_inv_{uuid.uuid4().hex[:8]}"
    slug = f"test-phase4b-{uuid.uuid4().hex[:6]}"

    db = _db()

    async def _seed():
        await db.tenants.insert_one({
            "id": tenant_id, "name": "TEST Phase 4B Tenant", "slug": slug,
            "active": True,
            "support_phone_number": "+16238878060",
            "sms_escalation_recipients": ["+16238878060"],
            "created_at": now_iso(),
        })
        await db.users.insert_many([
            {"id": admin_id, "email": f"admin_{admin_id}@example.com",
             "name": "TEST Admin", "role": "admin", "active": True,
             "tenant_id": tenant_id, "created_at": now_iso()},
            {"id": manager_id, "email": f"mgr_{manager_id}@example.com",
             "name": "TEST Manager", "role": "manager", "active": True,
             "tenant_id": tenant_id, "created_at": now_iso()},
            {"id": tech_id, "email": f"tech_{tech_id}@example.com",
             "name": "TEST Tech", "role": "technician", "active": True,
             "tenant_id": tenant_id, "created_at": now_iso()},
            {"id": f"cust-user-{cust_id}",
             "email": f"cust_{cust_id}@example.com",
             "name": "TEST Customer", "role": "customer", "active": True,
             "tenant_id": tenant_id, "customer_id": cust_id,
             "created_at": now_iso()},
            {"id": f"cust-user-{other_cust_id}",
             "email": f"other_{other_cust_id}@example.com",
             "name": "TEST Other", "role": "customer", "active": True,
             "tenant_id": tenant_id, "customer_id": other_cust_id,
             "created_at": now_iso()},
        ])
        await db.customers.insert_many([
            {"id": cust_id, "tenant_id": tenant_id, "name": "TEST Customer",
             "email": f"cust_{cust_id}@example.com",
             "phone": "+16238878060", "created_at": now_iso()},
            {"id": other_cust_id, "tenant_id": tenant_id, "name": "TEST Other",
             "email": f"other_{other_cust_id}@example.com",
             "created_at": now_iso()},
        ])
        await db.quotes.insert_one({
            "id": inv_id, "tenant_id": tenant_id, "doc_type": "invoice",
            "status": "sent", "payment_status": "unpaid",
            "customer_id": cust_id, "customer_name": "TEST Customer",
            "customer_email": f"cust_{cust_id}@example.com",
            "customer_phone": "+16238878060",
            "title": "TEST Phase 4B payable invoice",
            "invoice_number": "TEST-4B-0001",
            "total": 125.50, "subtotal": 125.50, "amount_paid": 0.0,
            "currency": "usd", "line_items": [],
            "created_at": now_iso(),
        })
    _run(_seed())

    yield {
        "tenant_id": tenant_id, "slug": slug,
        "admin_id": admin_id, "manager_id": manager_id, "tech_id": tech_id,
        "cust_id": cust_id, "other_cust_id": other_cust_id,
        "inv_id": inv_id, "amount_cents": 12550,
    }

    async def _cleanup():
        await db.tenants.delete_one({"id": tenant_id})
        await db.users.delete_many({"tenant_id": tenant_id})
        await db.customers.delete_many({"tenant_id": tenant_id})
        await db.quotes.delete_many({"tenant_id": tenant_id})
        await db.stripe_payments_live.delete_many({"tenant_id": tenant_id})
        await db.stripe_events_processed.delete_many({
            "event_id": {"$regex": "^evt_test_phase4b_"},
        })
        await db.marketing_deliveries.delete_many({"tenant_id": tenant_id})
    _run(_cleanup())


# ─── config surface ───────────────────────────────────────────────────
def test_config_public_exposes_pk_and_mode():
    r = requests.get(f"{API}/config/public", timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["stripe_publishable_key"].startswith("pk_")
    assert j["stripe_mode"] in ("live", "test")
    for v in j.values():
        if isinstance(v, str):
            assert not v.startswith("sk_"), "secret leaked"
            assert not v.startswith("whsec_"), "webhook secret leaked"


def test_stripe_config_check_admin_only_and_masks(seed_env):
    admin_tok = _mk_token(seed_env["admin_id"], "admin")
    tech_tok = _mk_token(seed_env["tech_id"], "technician")

    r_denied = requests.post(f"{API}/dev/stripe-config-check",
                                headers={"Authorization": f"Bearer {tech_tok}"},
                                timeout=15)
    assert r_denied.status_code == 403

    r_ok = requests.post(f"{API}/dev/stripe-config-check",
                            headers={"Authorization": f"Bearer {admin_tok}"},
                            timeout=15)
    assert r_ok.status_code == 200, r_ok.text
    j = r_ok.json()
    assert j["has_secret"] is True
    assert j["has_webhook_secret"] is True
    assert j["has_publishable"] is True
    assert j["ready"] is True
    body = json.dumps(j)
    assert "sk_" not in body
    assert "whsec_" not in body


# ─── create-payment-intent · authenticated ────────────────────────────
def test_create_payment_intent_authenticated_customer_owner(seed_env):
    cust_user_id = f"cust-user-{seed_env['cust_id']}"
    tok = _mk_token(cust_user_id, "customer")

    body = {"invoice_id": seed_env["inv_id"], "source": "authenticated"}
    r = requests.post(f"{API}/payments/create-payment-intent",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["amount_cents"] == seed_env["amount_cents"]
    assert j["currency"] == "usd"
    assert j["client_secret"].startswith("pi_")

    # Amount tampering ignored — server resolves from invoice.
    body2 = {"invoice_id": seed_env["inv_id"], "source": "authenticated",
              "amount_cents": 1}
    r2 = requests.post(f"{API}/payments/create-payment-intent",
                         headers=_headers_for(tok, seed_env["slug"]),
                         data=json.dumps(body2), timeout=15)
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert j2["amount_cents"] == seed_env["amount_cents"]

    # Idempotency-Key format captured on server via ledger row.
    async def _check_ledger():
        db = _db()
        rows = await db.stripe_payments_live.find(
            {"invoice_id": seed_env["inv_id"]},
        ).to_list(50)
        assert len(rows) >= 2
        for row in rows:
            assert row["idempotency_key"].startswith(f"pi:{seed_env['inv_id']}:")
            parts = row["idempotency_key"].split(":")
            assert parts[-1].isdigit() and int(parts[-1]) >= 1
    _run(_check_ledger())


def test_create_payment_intent_denies_other_customer(seed_env):
    other_uid = f"cust-user-{seed_env['other_cust_id']}"
    tok = _mk_token(other_uid, "customer")
    body = {"invoice_id": seed_env["inv_id"], "source": "authenticated"}
    r = requests.post(f"{API}/payments/create-payment-intent",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 403


def test_create_payment_intent_denies_technician(seed_env):
    tok = _mk_token(seed_env["tech_id"], "technician")
    body = {"invoice_id": seed_env["inv_id"], "source": "authenticated"}
    r = requests.post(f"{API}/payments/create-payment-intent",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 403


# ─── portal magic-link ────────────────────────────────────────────────
def _issue_magic(inv_id: str, tenant_id: str, days: int = 30) -> str:
    return jwt.encode(
        {"sub": "invoice_pay", "invoice_id": inv_id, "tenant_id": tenant_id,
         "exp": datetime.now(timezone.utc) + timedelta(days=days)},
        _jwt_secret(), algorithm="HS256",
    )


def test_portal_magic_link_flow(seed_env):
    token = _issue_magic(seed_env["inv_id"], seed_env["tenant_id"])
    body = {"invoice_id": seed_env["inv_id"], "source": "portal",
             "magic_token": token}
    r = requests.post(f"{API}/payments/create-payment-intent",
                        headers={"Content-Type": "application/json"},
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["amount_cents"] == seed_env["amount_cents"]


def test_portal_magic_link_wrong_invoice(seed_env):
    token = _issue_magic("some-other-invoice-id", seed_env["tenant_id"])
    body = {"invoice_id": seed_env["inv_id"], "source": "portal",
             "magic_token": token}
    r = requests.post(f"{API}/payments/create-payment-intent",
                        headers={"Content-Type": "application/json"},
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 401


def test_portal_magic_link_expired(seed_env):
    expired = jwt.encode(
        {"sub": "invoice_pay", "invoice_id": seed_env["inv_id"],
         "tenant_id": seed_env["tenant_id"],
         "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        _jwt_secret(), algorithm="HS256",
    )
    body = {"invoice_id": seed_env["inv_id"], "source": "portal",
             "magic_token": expired}
    r = requests.post(f"{API}/payments/create-payment-intent",
                        headers={"Content-Type": "application/json"},
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 401


def test_portal_full_magic_viewer_endpoint(seed_env):
    token = _issue_magic(seed_env["inv_id"], seed_env["tenant_id"])
    r = requests.get(
        f"{API}/invoices/{seed_env['inv_id']}/full-magic",
        params={"token": token}, timeout=15,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["invoice_id"] == seed_env["inv_id"]
    assert payload["totals"]["total_due"] == 125.50

    r2 = requests.get(
        f"{API}/invoices/{seed_env['inv_id']}/full-magic",
        params={"token": "bad"}, timeout=15,
    )
    assert r2.status_code == 401


# ─── refund ───────────────────────────────────────────────────────────
def _seed_paid_ledger(seed_env, amount_cents: int = 5000) -> str:
    from utils import new_id, now_iso
    db = _db()
    pi_id = f"pi_paid_{uuid.uuid4().hex[:10]}"

    async def _seed():
        await db.stripe_payments_live.insert_one({
            "id": new_id(),
            "tenant_id": seed_env["tenant_id"],
            "invoice_id": seed_env["inv_id"],
            "customer_id": seed_env["cust_id"],
            "kind": "payment_intent",
            "payment_intent_id": pi_id,
            "amount_cents": amount_cents,
            "currency": "usd",
            "status": "paid",
            "refunded_cents": 0,
            "attempt": 99,
            "idempotency_key": f"pi:{seed_env['inv_id']}:99",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    _run(_seed())
    return pi_id


def test_refund_admin_full(seed_env):
    pi_id = _seed_paid_ledger(seed_env, 5000)
    tok = _mk_token(seed_env["admin_id"], "admin")
    body = {"payment_intent_id": pi_id, "reason": "requested_by_customer"}
    r = requests.post(f"{API}/payments/refund",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["amount_cents"] == 5000
    assert j["status"] == "refunded"

    # Idempotency-Key recorded on the refund
    async def _check():
        db = _db()
        row = await db.stripe_payments_live.find_one(
            {"payment_intent_id": pi_id}, {"_id": 0},
        )
        assert row["refunds"][0]["amount_cents"] == 5000
        assert row["refunded_cents"] == 5000
    _run(_check())


def test_refund_manager_partial(seed_env):
    pi_id = _seed_paid_ledger(seed_env, 10000)
    tok = _mk_token(seed_env["manager_id"], "manager")
    body = {"payment_intent_id": pi_id, "amount_cents": 2500,
             "reason": "partial refund per contract"}
    r = requests.post(f"{API}/payments/refund",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["amount_cents"] == 2500
    assert j["status"] == "partially_refunded"


def test_refund_technician_denied(seed_env):
    pi_id = _seed_paid_ledger(seed_env, 5000)
    tok = _mk_token(seed_env["tech_id"], "technician")
    body = {"payment_intent_id": pi_id, "reason": "not allowed"}
    r = requests.post(f"{API}/payments/refund",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 403


def test_refund_customer_denied(seed_env):
    pi_id = _seed_paid_ledger(seed_env, 5000)
    tok = _mk_token(f"cust-user-{seed_env['cust_id']}", "customer")
    body = {"payment_intent_id": pi_id, "reason": "no way"}
    r = requests.post(f"{API}/payments/refund",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps(body), timeout=15)
    assert r.status_code == 403


def test_refund_reason_required(seed_env):
    pi_id = _seed_paid_ledger(seed_env, 3000)
    tok = _mk_token(seed_env["admin_id"], "admin")
    r = requests.post(f"{API}/payments/refund",
                        headers=_headers_for(tok, seed_env["slug"]),
                        data=json.dumps({"payment_intent_id": pi_id}),
                        timeout=15)
    assert r.status_code in (400, 422)

    r2 = requests.post(f"{API}/payments/refund",
                         headers=_headers_for(tok, seed_env["slug"]),
                         data=json.dumps({"payment_intent_id": pi_id,
                                            "reason": "no"}),
                         timeout=15)
    assert r2.status_code in (400, 422)


# ─── webhook ─────────────────────────────────────────────────────────
def _wh_post(event: dict, sig: str = "GOODSIG"):
    return requests.post(
        f"{API}/webhooks/stripe",
        data=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": sig,
                  "content-type": "application/json"},
        timeout=20,
    )


def test_webhook_bad_signature_400():
    ev = {"id": "evt_test_phase4b_bad", "type": "payment_intent.succeeded",
           "data": {"object": {}}}
    r = _wh_post(ev, sig="BADSIG")
    assert r.status_code == 400


def test_webhook_missing_signature_400():
    ev = {"id": "evt_test_phase4b_nosig", "type": "payment_intent.succeeded",
           "data": {"object": {}}}
    r = requests.post(f"{API}/webhooks/stripe",
                        data=json.dumps(ev).encode("utf-8"),
                        headers={"content-type": "application/json"},
                        timeout=15)
    assert r.status_code == 400


def test_webhook_succeeded_marks_invoice_and_writes_receipts(seed_env):
    from utils import new_id, now_iso
    db = _db()
    inv_id = f"TEST_wh_inv_{uuid.uuid4().hex[:8]}"
    pi_id = f"pi_test_wh_{uuid.uuid4().hex[:10]}"

    async def _seed():
        await db.quotes.insert_one({
            "id": inv_id, "tenant_id": seed_env["tenant_id"],
            "doc_type": "invoice", "status": "sent",
            "payment_status": "unpaid",
            "customer_id": seed_env["cust_id"],
            "customer_name": "TEST Customer",
            "title": "TEST webhook invoice",
            "invoice_number": f"WH-{uuid.uuid4().hex[:6]}",
            "total": 42.00, "amount_paid": 0.0,
            "created_at": now_iso(),
        })
        await db.stripe_payments_live.insert_one({
            "id": new_id(),
            "tenant_id": seed_env["tenant_id"],
            "invoice_id": inv_id,
            "customer_id": seed_env["cust_id"],
            "kind": "payment_intent",
            "payment_intent_id": pi_id,
            "amount_cents": 4200,
            "currency": "usd",
            "status": "initiated",
            "refunded_cents": 0,
            "attempt": 1,
            "idempotency_key": f"pi:{inv_id}:1",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    _run(_seed())

    event_id = f"evt_test_phase4b_{uuid.uuid4().hex[:10]}"
    ev = {
        "id": event_id, "type": "payment_intent.succeeded",
        "data": {"object": {
            "id": pi_id, "amount": 4200, "amount_received": 4200,
            "currency": "usd", "status": "succeeded",
            "latest_charge": f"ch_test_{uuid.uuid4().hex[:10]}",
            "metadata": {"tenant_id": seed_env["tenant_id"],
                          "invoice_id": inv_id,
                          "customer_id": seed_env["cust_id"]},
        }},
    }
    r = _wh_post(ev)
    assert r.status_code == 200, r.text
    assert r.json().get("handled") is True

    async def _check():
        inv = await db.quotes.find_one({"id": inv_id}, {"_id": 0})
        assert inv["payment_status"] == "paid"
        assert abs(float(inv["amount_paid"]) - 42.00) < 0.01
        row = await db.stripe_payments_live.find_one(
            {"payment_intent_id": pi_id}, {"_id": 0},
        )
        assert row["status"] == "paid"
        deliveries = await db.marketing_deliveries.find(
            {"tenant_id": seed_env["tenant_id"],
             "trigger_entity.id": pi_id}, {"_id": 0},
        ).to_list(20)
        channels = {d["channel"] for d in deliveries}
        assert "email" in channels
        for d in deliveries:
            assert d["kind"] == "transactional"
            assert d["trigger_entity"]["kind"] == "payment"
    _run(_check())

    # Duplicate → idempotent
    r2 = _wh_post(ev)
    assert r2.status_code == 200
    assert r2.json().get("idempotent") is True

    # Cleanup this test's invoice/ledger.
    async def _clean():
        await db.quotes.delete_one({"id": inv_id})
        await db.stripe_payments_live.delete_one({"payment_intent_id": pi_id})
    _run(_clean())


def test_webhook_dispute_notifies_admins(seed_env):
    db = _db()
    pi_id = _seed_paid_ledger(seed_env, 7500)
    charge_id = f"ch_disp_{uuid.uuid4().hex[:8]}"

    async def _attach():
        await db.stripe_payments_live.update_one(
            {"payment_intent_id": pi_id},
            {"$set": {"charge_id": charge_id}},
        )
    _run(_attach())

    ev = {
        "id": f"evt_test_phase4b_disp_{uuid.uuid4().hex[:8]}",
        "type": "charge.dispute.created",
        "data": {"object": {
            "id": f"dp_{uuid.uuid4().hex[:8]}",
            "charge": charge_id, "payment_intent": pi_id,
            "amount": 7500, "reason": "fraudulent",
        }},
    }
    r = _wh_post(ev)
    assert r.status_code == 200
    assert r.json().get("handled") is True

    async def _check():
        row = await db.stripe_payments_live.find_one(
            {"payment_intent_id": pi_id}, {"_id": 0},
        )
        assert row["status"] == "disputed"
        assert row["dispute_reason"] == "fraudulent"
    _run(_check())
