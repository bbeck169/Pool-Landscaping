"""Feb-2026 · Stripe reconcile endpoint — pytest.

Locks in ``POST /api/payments/stripe/session/{session_id}/reconcile``
added to ``backend/routers/stripe_router.py``. The endpoint closes the
design gap where the customer-portal invoice-pay flow relied 100% on
``checkout.session.completed`` webhook delivery to flip the invoice —
if the webhook mis-fired (Thin-payload rejection, transient blip,
Dashboard misconfig), the customer's payment orphaned.

Coverage:
  1. Happy path — session paid, invoice flipped to
     ``payment_status: paid`` with ``amount_paid`` = session total.
  2. Idempotency — firing reconcile twice on the same session
     results in ONE ``$set`` write; second call short-circuits inside
     ``_mark_invoice_paid_from_session`` via the
     ``payment_status == 'paid'`` guard.
  3. Cross-tenant guard — the session's invoice lives in tenant B
     but the JWT is scoped to tenant A → 403.
  4. Unpaid session — Stripe returns ``payment_status: 'unpaid'`` →
     200 ``{"reconciled": false, "reason": "unpaid"}``. The invoice
     doc is not touched.
  5. Webhook + reconcile race — webhook fires first (flipping the
     invoice to paid), then the browser lands on
     ``/portal/payment-complete`` and fires reconcile → second call
     is a safe no-op (``already_paid: true``, same amount_paid).
  6. Customer role scoping — a customer whose ``customer_id`` does
     not match the invoice's ``customer_id`` gets 403 even if the
     session id is otherwise valid in their tenant.
  7. Owner customer can reconcile their own invoice (positive path
     for the customer-role branch).

Uses ``fastapi.testclient.TestClient`` so ``set_stripe_client()``
takes effect in-process (the pod runs ``APP_ENV=production`` which
force-clears ``ALLOW_TEST_HOOKS=0`` at boot, disabling the
cross-process stub-install endpoints; TestClient sidesteps that by
running the FastAPI app inside the pytest process). Mirrors the
pattern in ``test_stripe_webhook_route_hotfix3.py``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from pymongo import MongoClient

os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


# Import the FastAPI app + set up an in-process client. TestClient
# used as a context manager ("with" form) keeps a single anyio event
# loop alive across the module so motor's cached ``AsyncIOMotorClient``
# doesn't crash with "Event loop is closed" on the 2nd request through
# an auth-dependent endpoint. Mirrors the fix Starlette recommends
# for TestClient + motor co-existence.
from server import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(user_id: str, email: str, role: str,
          tenant_id: str, customer_id: str | None = None) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ──────────────────────────────────────────────────────────────────────
# Stripe SDK stub — install the in-process fake via ``set_stripe_client``
# and queue the next Session payload via the ``_FakeCheckoutSession``
# class-level slot (added in this ship's extension of
# ``routers/stripe_test_hooks.py``).
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture()
def stripe_stub():
    from services.payments import stripe_charge as sc
    from routers.stripe_test_hooks import (
        _FakeStripe as FakeStripe,
        _FakeCheckoutSession as FakeSession,
    )

    fake = FakeStripe()
    sc.set_stripe_client(fake)
    FakeSession._retrieve_calls = []

    def _queue(session_payload: dict) -> None:
        FakeSession._next_payload = session_payload

    yield _queue

    # Teardown — restore the real SDK; wipe the session queue so a
    # subsequent test that ALSO installs the fake starts clean.
    sc.set_stripe_client(None)
    FakeSession._next_payload = None
    FakeSession._retrieve_calls = []


# ──────────────────────────────────────────────────────────────────────
# DB fixtures — one tenant + customer + invoice per test.
# ──────────────────────────────────────────────────────────────────────
PREFIX = f"srec-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def tenant_id():
    tid = f"{PREFIX}-{uuid.uuid4().hex[:6]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"SRec {tid}", "slug": tid,
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "customers", "quotes"):
        _sync[col].delete_many({"tenant_id": tid})


def _seed_customer(tenant_id: str) -> str:
    cid = f"cust-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "SRec Customer", "email": f"{cid}@srec.test",
    })
    return cid


def _seed_invoice(tenant_id: str, customer_id: str,
                    total: float = 250.00) -> str:
    iid = f"inv-{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id,
        "doc_type": "invoice",
        "customer_id": customer_id,
        "title": "Pool Repair",
        "total": total,
        "subtotal": total,
        "tax": 0.0,
        "amount_paid": 0.0,
        "payment_status": "unpaid",
        "status": "sent",
        "currency": "USD",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return iid


def _seed_user(tenant_id: str, role: str, *,
                customer_id: str | None = None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@srec.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"SRec {role}", "email": email,
        "customer_id": customer_id,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "token": _tok(uid, email, role, tenant_id, customer_id)}


@pytest.fixture()
def admin(tenant_id):
    return _seed_user(tenant_id, "admin")


@pytest.fixture()
def customer(tenant_id):
    cid = _seed_customer(tenant_id)
    return _seed_user(tenant_id, "customer", customer_id=cid)


def _auth(user: dict) -> dict:
    return {
        "Authorization": f"Bearer {user['token']}",
        "X-Tenant-Id": user["tenant_id"],
    }


def _paid_session(session_id: str, invoice_id: str,
                   tenant_id: str, customer_id: str,
                   amount_total_cents: int = 25000) -> dict:
    return {
        "id": session_id,
        "object": "checkout.session",
        "payment_status": "paid",
        "amount_total": amount_total_cents,
        "currency": "usd",
        "client_reference_id": invoice_id,
        "metadata": {
            "crm_invoice_id": invoice_id,
            "crm_tenant_id": tenant_id,
            "crm_customer_id": customer_id,
            "source": "phase47_invoice_pay",
        },
        "payment_intent": {"id": f"pi_{uuid.uuid4().hex[:16]}"},
    }


def _unpaid_session(session_id: str, invoice_id: str,
                     tenant_id: str, customer_id: str) -> dict:
    s = _paid_session(session_id, invoice_id, tenant_id, customer_id)
    s["payment_status"] = "unpaid"
    return s


def _reconcile(client, user: dict, session_id: str):
    return client.post(
        f"/api/payments/stripe/session/{session_id}/reconcile",
        headers=_auth(user), json={},
    )


# ══════════════════════════════════════════════════════════════════════
# 1 · Happy path — session paid → invoice flipped, amount_paid set.
# ══════════════════════════════════════════════════════════════════════
def test_reconcile_paid_session_flips_invoice(client, stripe_stub, admin, tenant_id):
    cust_id = _seed_customer(tenant_id)
    inv_id = _seed_invoice(tenant_id, cust_id, total=250.00)
    sid = f"cs_test_{uuid.uuid4().hex[:16]}"
    stripe_stub(_paid_session(sid, inv_id, tenant_id, cust_id))

    r = _reconcile(client, admin, sid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reconciled"] is True
    assert body["already_paid"] is False
    assert body["invoice_id"] == inv_id
    assert body["amount_paid"] == 250.00
    assert body["payment_status"] == "paid"

    # Invoice doc actually flipped.
    row = _sync.quotes.find_one({"id": inv_id},
                                  {"_id": 0, "payment_status": 1,
                                   "amount_paid": 1,
                                   "stripe_checkout_session_id": 1,
                                   "payment_method": 1})
    assert row["payment_status"] == "paid"
    assert row["amount_paid"] == 250.00
    assert row["stripe_checkout_session_id"] == sid
    assert row["payment_method"] == "stripe_checkout"


# ══════════════════════════════════════════════════════════════════════
# 2 · Idempotency — firing twice → one $set write; second call safe.
# ══════════════════════════════════════════════════════════════════════
def test_reconcile_is_idempotent_on_double_delivery(client, stripe_stub, admin, tenant_id):
    cust_id = _seed_customer(tenant_id)
    inv_id = _seed_invoice(tenant_id, cust_id, total=250.00)
    sid = f"cs_test_{uuid.uuid4().hex[:16]}"
    stripe_stub(_paid_session(sid, inv_id, tenant_id, cust_id))

    r1 = _reconcile(client, admin, sid)
    assert r1.status_code == 200, r1.text
    assert r1.json()["already_paid"] is False

    # Re-queue the same session — the fake consumes the payload but
    # the reconcile endpoint's idempotency comes from the invoice's
    # ``payment_status == 'paid'`` short-circuit, not from Stripe.
    stripe_stub(_paid_session(sid, inv_id, tenant_id, cust_id))
    r2 = _reconcile(client, admin, sid)
    assert r2.status_code == 200, r2.text
    # The invoice is already paid, so the helper's short-circuit
    # kicked in — reconciled: True (we did complete a reconcile
    # cycle), but already_paid: True (no fresh write).
    assert r2.json()["reconciled"] is True
    assert r2.json()["already_paid"] is True

    # And the persisted amount_paid did NOT double — no drift.
    row = _sync.quotes.find_one({"id": inv_id},
                                  {"_id": 0, "amount_paid": 1})
    assert row["amount_paid"] == 250.00, (
        "amount_paid must not double on second delivery; got "
        f"{row['amount_paid']}"
    )


# ══════════════════════════════════════════════════════════════════════
# 3 · Cross-tenant — session belongs to tenant B, JWT is tenant A → 403.
# ══════════════════════════════════════════════════════════════════════
def test_reconcile_cross_tenant_returns_403(client, stripe_stub, admin, tenant_id):
    # Admin's JWT is scoped to `tenant_id` (tenant A).  The invoice
    # + customer we seed here live in tenant B.
    other_tid = f"{PREFIX}-B-{uuid.uuid4().hex[:6]}"
    _sync.tenants.insert_one({
        "id": other_tid, "name": "SRec Tenant B", "slug": other_tid,
        "active": True, "widget_allowed_domains": [],
    })
    try:
        cust_id_B = _seed_customer(other_tid)
        inv_id_B = _seed_invoice(other_tid, cust_id_B, total=999.00)
        sid = f"cs_test_{uuid.uuid4().hex[:16]}"
        # The Stripe session's metadata correctly points at tenant B —
        # but the caller's JWT is tenant A.
        stripe_stub(_paid_session(sid, inv_id_B, other_tid, cust_id_B))

        r = _reconcile(client, admin, sid)
        assert r.status_code == 403, r.text

        # Invoice in tenant B remains untouched.
        row = _sync.quotes.find_one({"id": inv_id_B},
                                      {"_id": 0, "payment_status": 1,
                                       "amount_paid": 1})
        assert row["payment_status"] == "unpaid"
        assert row["amount_paid"] == 0.0
    finally:
        for col in ("tenants", "customers", "quotes"):
            _sync[col].delete_many({"tenant_id": other_tid})


# ══════════════════════════════════════════════════════════════════════
# 4 · Unpaid session — returns 200 with reconciled: false.
# ══════════════════════════════════════════════════════════════════════
def test_reconcile_unpaid_session_returns_reconciled_false(
    client, stripe_stub, admin, tenant_id,
):
    cust_id = _seed_customer(tenant_id)
    inv_id = _seed_invoice(tenant_id, cust_id, total=250.00)
    sid = f"cs_test_{uuid.uuid4().hex[:16]}"
    stripe_stub(_unpaid_session(sid, inv_id, tenant_id, cust_id))

    r = _reconcile(client, admin, sid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reconciled"] is False
    assert body["reason"] == "unpaid"
    assert body.get("payment_status") == "unpaid"

    # Invoice doc untouched.
    row = _sync.quotes.find_one({"id": inv_id},
                                  {"_id": 0, "payment_status": 1,
                                   "amount_paid": 1})
    assert row["payment_status"] == "unpaid"
    assert row["amount_paid"] == 0.0


# ══════════════════════════════════════════════════════════════════════
# 5 · Webhook + reconcile race — no double-write, no drift.
#      Simulated by pre-flipping the invoice (as the webhook would
#      have done) and then firing reconcile.
# ══════════════════════════════════════════════════════════════════════
def test_reconcile_after_webhook_is_safe_noop(client, stripe_stub, admin, tenant_id):
    cust_id = _seed_customer(tenant_id)
    inv_id = _seed_invoice(tenant_id, cust_id, total=250.00)
    sid = f"cs_test_{uuid.uuid4().hex[:16]}"

    # Simulate the webhook having already reconciled — same $set the
    # helper writes when the invoice was unpaid.
    _sync.quotes.update_one(
        {"id": inv_id},
        {"$set": {
            "amount_paid": 250.00,
            "payment_status": "paid",
            "payment_method": "stripe_checkout",
            "stripe_checkout_session_id": sid,
            "paid_at": datetime.now(timezone.utc).isoformat(),
            "status": "accepted",
        }},
    )
    stripe_stub(_paid_session(sid, inv_id, tenant_id, cust_id))

    r = _reconcile(client, admin, sid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reconciled"] is True
    assert body["already_paid"] is True, (
        "reconcile after webhook must short-circuit inside the "
        "helper; got fresh write"
    )
    assert body["amount_paid"] == 250.00

    # Still exactly one $250 payment on the invoice — no doubling.
    row = _sync.quotes.find_one({"id": inv_id},
                                  {"_id": 0, "amount_paid": 1})
    assert row["amount_paid"] == 250.00


# ══════════════════════════════════════════════════════════════════════
# 6 · Customer scoping — customer whose customer_id does NOT match
#      the invoice's customer_id → 403 even if same tenant.
# ══════════════════════════════════════════════════════════════════════
def test_customer_cannot_reconcile_another_customers_invoice(
    client, stripe_stub, tenant_id,
):
    owner_cid = _seed_customer(tenant_id)
    owner_inv = _seed_invoice(tenant_id, owner_cid, total=250.00)
    intruder = _seed_user(tenant_id, "customer",
                            customer_id=_seed_customer(tenant_id))
    sid = f"cs_test_{uuid.uuid4().hex[:16]}"
    stripe_stub(_paid_session(sid, owner_inv, tenant_id, owner_cid))

    r = _reconcile(client, intruder, sid)
    assert r.status_code == 403, r.text

    # Owner's invoice untouched.
    row = _sync.quotes.find_one({"id": owner_inv},
                                  {"_id": 0, "payment_status": 1,
                                   "amount_paid": 1})
    assert row["payment_status"] == "unpaid"
    assert row["amount_paid"] == 0.0


# ══════════════════════════════════════════════════════════════════════
# 7 · Owner customer can reconcile their own invoice.
# ══════════════════════════════════════════════════════════════════════
def test_owner_customer_can_reconcile_own_invoice(client, stripe_stub, customer, tenant_id):
    inv_id = _seed_invoice(tenant_id, customer["customer_id"], total=250.00)
    sid = f"cs_test_{uuid.uuid4().hex[:16]}"
    stripe_stub(_paid_session(sid, inv_id, tenant_id,
                                customer["customer_id"]))

    r = _reconcile(client, customer, sid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reconciled"] is True
    assert body["amount_paid"] == 250.00
    row = _sync.quotes.find_one({"id": inv_id},
                                  {"_id": 0, "payment_status": 1})
    assert row["payment_status"] == "paid"
