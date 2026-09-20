"""Phase 14a · Feb-2026 — Stripe card-on-file service + router tests.

Stripe SDK is fully stubbed via ``services.payments.stripe_charge.set_stripe_client``
so no live Stripe HTTP is ever issued. Every test cleans up the docs it
inserts so re-runs stay idempotent.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
from services.payments import stripe_charge as svc  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
svc.db = _FRESH[_ENV["DB_NAME"]]


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    return _LOOP.run_until_complete(coro)


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login", json={"email": email, "password": password}, timeout=10
    )
    if r.status_code != 200:
        raise RuntimeError(f"login failed for {email}: {r.status_code} {r.text}")
    return r.json()["access_token"]


def _tid() -> str:
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


# ── Fake Stripe SDK ───────────────────────────────────────────────────
class _FakeStripe:
    """In-memory replacement for the stripe module. Only the surface the
    service uses is stubbed. Tests can inspect ``calls`` and set
    ``next_error`` to force a raise."""

    def __init__(self):
        self.calls = []
        self.next_error = None
        self.next_intent_status = "succeeded"
        self._pm_store = {}

    # error class shim used by service imports (not needed here but keeps
    # attribute access safe if the service accidentally imports it).
    class error:  # noqa: N801 - mimic stripe.error
        class StripeError(Exception):
            pass

    class Customer:  # noqa: N801
        _outer = None

        @classmethod
        def create(cls, **kwargs):
            cls._outer.calls.append(("Customer.create", kwargs))
            if cls._outer.next_error:
                exc, cls._outer.next_error = cls._outer.next_error, None
                raise exc
            return {"id": f"cus_test_{uuid.uuid4().hex[:8]}", **kwargs}

    class PaymentMethod:  # noqa: N801
        _outer = None

        @classmethod
        def attach(cls, pm_id, **kwargs):
            cls._outer.calls.append(("PaymentMethod.attach", pm_id, kwargs))
            if cls._outer.next_error:
                exc, cls._outer.next_error = cls._outer.next_error, None
                raise exc
            cls._outer._pm_store[pm_id] = kwargs.get("customer")
            return {"id": pm_id, "customer": kwargs.get("customer")}

        @classmethod
        def retrieve(cls, pm_id, **kwargs):
            cls._outer.calls.append(("PaymentMethod.retrieve", pm_id))
            return {
                "id": pm_id,
                "customer": cls._outer._pm_store.get(pm_id),
                "card": {
                    "brand": "visa",
                    "last4": "4242",
                    "exp_month": 12,
                    "exp_year": 2032,
                },
            }

        @classmethod
        def detach(cls, pm_id, **kwargs):
            cls._outer.calls.append(("PaymentMethod.detach", pm_id))
            if cls._outer.next_error:
                exc, cls._outer.next_error = cls._outer.next_error, None
                raise exc
            cls._outer._pm_store.pop(pm_id, None)
            return {"id": pm_id, "customer": None}

    class SetupIntent:  # noqa: N801
        _outer = None

        @classmethod
        def create(cls, **kwargs):
            cls._outer.calls.append(("SetupIntent.create", kwargs))
            return {
                "id": f"seti_test_{uuid.uuid4().hex[:8]}",
                "client_secret": f"seti_test_{uuid.uuid4().hex[:8]}_secret_x",
                "customer": kwargs.get("customer"),
            }

    class PaymentIntent:  # noqa: N801
        _outer = None

        @classmethod
        def create(cls, **kwargs):
            cls._outer.calls.append(("PaymentIntent.create", kwargs))
            if cls._outer.next_error:
                exc, cls._outer.next_error = cls._outer.next_error, None
                raise exc
            return {
                "id": f"pi_test_{uuid.uuid4().hex[:8]}",
                "status": cls._outer.next_intent_status,
                "amount": kwargs.get("amount"),
                "currency": kwargs.get("currency"),
            }

    class Webhook:  # noqa: N801
        _outer = None

        @classmethod
        def construct_event(cls, payload, sig, secret):
            cls._outer.calls.append(("Webhook.construct_event", secret))
            if cls._outer.next_error:
                exc, cls._outer.next_error = cls._outer.next_error, None
                raise exc
            import json
            return json.loads(payload)

    api_key = ""


def _fake_stripe() -> _FakeStripe:
    fake = _FakeStripe()
    for cls_name in (
        "Customer", "PaymentMethod", "SetupIntent", "PaymentIntent", "Webhook",
    ):
        getattr(fake, cls_name)._outer = fake
    return fake


@pytest.fixture
def stub():
    fake = _fake_stripe()
    svc.set_stripe_client(fake)
    yield fake
    svc.set_stripe_client(None)


# ── Test customer helper ─────────────────────────────────────────────
def _make_test_customer(tenant_id: str) -> str:
    cid = f"TEST_stripe14a_{uuid.uuid4().hex[:10]}"
    _sync.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": f"TEST_stripe14a {cid[-6:]}",
        "email": f"TEST_stripe14a_{cid[-6:]}@example.com",
        "phone": "+15550100000",
        "created_at": "2026-02-01T00:00:00Z",
    })
    return cid


def _cleanup(cid: str, tenant_id: str) -> None:
    _sync.customers.delete_one({"id": cid, "tenant_id": tenant_id})
    _sync.payment_methods.delete_many({"customer_id": cid, "tenant_id": tenant_id})
    _sync.stripe_charges.delete_many({"customer_id": cid, "tenant_id": tenant_id})


# ═════════════════════════════════════════════════════════════════════
# Service-level tests (async)
# ═════════════════════════════════════════════════════════════════════
def test_setup_intent_creates_customer_and_intent(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        out = _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        assert out["client_secret"].startswith("seti_test_")
        assert out["setup_intent_id"].startswith("seti_test_")
        assert out["stripe_customer_id"].startswith("cus_test_")
        # customer doc got the stripe_customer_id stamped
        fresh = _sync.customers.find_one({"id": cid, "tenant_id": tid})
        assert fresh["stripe_customer_id"] == out["stripe_customer_id"]
        # second call must NOT create a fresh Stripe customer
        stub.calls.clear()
        out2 = _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        assert out2["stripe_customer_id"] == out["stripe_customer_id"]
        assert not any(c[0] == "Customer.create" for c in stub.calls)
    finally:
        _cleanup(cid, tid)


def test_setup_intent_missing_customer_raises(stub):
    with pytest.raises(ValueError):
        _run(svc.create_setup_intent(tenant_id=_tid(), customer_id="nonexistent-xyz"))


def test_attach_mirrors_card_metadata_and_sets_default(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        out = _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_A"
        ))
        assert out["provider"] == "stripe"
        assert out["brand"] == "visa"
        assert out["last4"] == "4242"
        assert out["is_default"] is True
        mirror = _sync.payment_methods.find_one(
            {"provider_payment_method_id": "pm_test_A", "tenant_id": tid}
        )
        assert mirror is not None
        assert mirror["customer_id"] == cid
        # customer default pointer + count updated
        cust = _sync.customers.find_one({"id": cid, "tenant_id": tid})
        assert cust["stripe_default_payment_method_id"] == "pm_test_A"
        assert cust["saved_payment_methods_count"] == 1
    finally:
        _cleanup(cid, tid)


def test_attach_second_card_reassigns_default(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_1"
        ))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_2"
        ))
        rows = _run(svc.list_payment_methods(tenant_id=tid, customer_id=cid))
        assert len(rows) == 2
        default = [r for r in rows if r["is_default"]]
        assert len(default) == 1
        assert default[0]["provider_payment_method_id"] == "pm_test_2"
        cust = _sync.customers.find_one({"id": cid, "tenant_id": tid})
        assert cust["saved_payment_methods_count"] == 2
    finally:
        _cleanup(cid, tid)


def test_detach_removes_mirror_and_clears_default(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_D"
        ))
        out = _run(svc.detach_payment_method(
            tenant_id=tid, payment_method_id="pm_test_D"
        ))
        assert out["ok"] is True
        assert _sync.payment_methods.find_one(
            {"provider_payment_method_id": "pm_test_D", "tenant_id": tid}
        ) is None
        cust = _sync.customers.find_one({"id": cid, "tenant_id": tid})
        assert cust["stripe_default_payment_method_id"] is None
        assert cust["saved_payment_methods_count"] == 0
    finally:
        _cleanup(cid, tid)


def test_charge_success_logs_stripe_charges_row(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_C"
        ))
        stub.next_intent_status = "succeeded"
        res = _run(svc.charge_card_on_file(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_C",
            amount_cents=1250, currency="usd", invoice_id="inv_TEST",
        ))
        assert res["ok"] is True
        assert res["status"] == "succeeded"
        row = _sync.stripe_charges.find_one({"id": res["charge_row_id"]})
        assert row is not None
        assert row["amount_cents"] == 1250
        assert row["status"] == "succeeded"
        assert row["error"] is None
        assert row["invoice_id"] == "inv_TEST"
        assert row["stripe_payment_intent_id"] == res["payment_intent_id"]
    finally:
        _cleanup(cid, tid)


def test_charge_failure_logs_error_row_and_reraises(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_F"
        ))
        stub.next_error = RuntimeError("Your card was declined.")
        with pytest.raises(RuntimeError):
            _run(svc.charge_card_on_file(
                tenant_id=tid, customer_id=cid, payment_method_id="pm_test_F",
                amount_cents=999, currency="usd", invoice_id=None,
            ))
        row = _sync.stripe_charges.find_one(
            {"customer_id": cid, "provider_payment_method_id": "pm_test_F"}
        )
        assert row is not None
        assert row["status"] == "failed"
        assert "declined" in (row["error"] or "").lower()
        assert row["stripe_payment_intent_id"] is None
    finally:
        _cleanup(cid, tid)


def test_charge_rejects_invalid_amount(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_test_Z"
        ))
        with pytest.raises(ValueError):
            _run(svc.charge_card_on_file(
                tenant_id=tid, customer_id=cid, payment_method_id="pm_test_Z",
                amount_cents=0, currency="usd", invoice_id=None,
            ))
    finally:
        _cleanup(cid, tid)


def test_charge_rejects_unknown_payment_method(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        with pytest.raises(ValueError):
            _run(svc.charge_card_on_file(
                tenant_id=tid, customer_id=cid, payment_method_id="pm_unknown",
                amount_cents=100, currency="usd", invoice_id=None,
            ))
    finally:
        _cleanup(cid, tid)


def test_webhook_signature_verification_uses_mode_secret(stub, monkeypatch):
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test_abc123")
    import json
    body = json.dumps({"type": "payment_method.attached", "data": {"object": {"id": "pm_wh"}}}).encode()
    event = svc.verify_and_parse_webhook(payload=body, sig_header="sig_test")
    assert event["type"] == "payment_method.attached"
    assert any(c[0] == "Webhook.construct_event" and c[1] == "whsec_test_abc123"
               for c in stub.calls)


def test_webhook_missing_secret_raises(stub, monkeypatch):
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET_TEST", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValueError):
        svc.verify_and_parse_webhook(payload=b"{}", sig_header="x")


def test_webhook_payment_method_attached_mirrors_row(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    stripe_cust_id = f"cus_wh_{uuid.uuid4().hex[:8]}"
    _sync.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {"stripe_customer_id": stripe_cust_id}},
    )
    event = {
        "type": "payment_method.attached",
        "data": {"object": {
            "id": "pm_wh_test",
            "customer": stripe_cust_id,
            "card": {"brand": "mc", "last4": "1111", "exp_month": 6, "exp_year": 2030},
        }},
    }
    try:
        out = _run(svc.handle_webhook_event(event))
        assert out["handled"] is True
        row = _sync.payment_methods.find_one({"provider_payment_method_id": "pm_wh_test"})
        assert row is not None
        assert row["customer_id"] == cid
        assert row["brand"] == "mc"
    finally:
        _cleanup(cid, tid)


def test_webhook_payment_intent_succeeded_upserts_charge_row(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        event = {
            "type": "payment_intent.succeeded",
            "data": {"object": {
                "id": "pi_wh_success",
                "amount": 5000,
                "currency": "usd",
                "payment_method": "pm_wh_ok",
                "metadata": {"crm_tenant_id": tid, "crm_customer_id": cid,
                              "crm_invoice_id": "inv_WH"},
            }},
        }
        out = _run(svc.handle_webhook_event(event))
        assert out["handled"] is True
        row = _sync.stripe_charges.find_one({"stripe_payment_intent_id": "pi_wh_success"})
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["invoice_id"] == "inv_WH"
    finally:
        _cleanup(cid, tid)


# ═════════════════════════════════════════════════════════════════════
# Router-level tests (HTTP)
# ═════════════════════════════════════════════════════════════════════
def _admin_token():
    return _login("admin@aquaterra.com")


def _customer_login():
    """Return (token, customer_id, tenant_id) for a demo customer login.

    The pool preview seeds ``demo@customer.com`` (mapped to Chris Wilson).
    """
    from tests.conftest import demo_pw
    cust_email = "demo@customer.com"
    r = requests.post(f"{API}/auth/login",
                       json={"email": cust_email, "password": demo_pw(cust_email)},
                       timeout=10)
    if r.status_code != 200:
        pytest.skip(f"no customer demo login available: {r.status_code}")
    tok = r.json()["access_token"]
    me = requests.get(f"{API}/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    if me.status_code == 200:
        return tok, me.json().get("customer_id"), me.json().get("tenant_id")
    # Fall back to sync-DB lookup for customer_id.
    urow = _sync.users.find_one({"email": cust_email})
    return tok, urow.get("customer_id"), urow.get("tenant_id")


def test_router_setup_intent_admin_flow(stub):
    """Skipped unless a real Stripe test key is wired via env — the backend
    runs in a separate process (supervisor), so the in-process ``stub``
    fixture can't reach it. Auth + validation router tests below still cover
    the router-side surface without needing Stripe."""
    if not (os.environ.get("STRIPE_SECRET_KEY_TEST") or "").startswith("sk_test_"):
        pytest.skip("no real STRIPE_SECRET_KEY_TEST wired — router happy-path skipped")
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        tok = _admin_token()
        r = requests.post(
            f"{API}/payments/stripe/setup-intent",
            json={"customer_id": cid},
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["client_secret"].startswith("seti_test_")
        assert body["mode"] == "test"
    finally:
        _cleanup(cid, tid)


def test_router_setup_intent_admin_missing_customer_id_422(stub):
    tok = _admin_token()
    r = requests.post(
        f"{API}/payments/stripe/setup-intent",
        json={},
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 422, r.text


def test_router_charge_blocks_technician(stub):
    # Technician login (seeded).
    from tests.conftest import demo_pw
    email = "mike@aquaterra.com"
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": demo_pw(email)},
                       timeout=10)
    if r.status_code != 200:
        pytest.skip("technician demo login unavailable")
    tok = r.json()["access_token"]
    resp = requests.post(
        f"{API}/payments/stripe/charge",
        json={
            "customer_id": "any", "payment_method_id": "pm_any",
            "amount_cents": 100, "currency": "usd",
        },
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert resp.status_code == 403, resp.text


def test_router_payment_methods_admin_ok(stub):
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_rt_1",
        ))
        tok = _admin_token()
        r = requests.get(
            f"{API}/payments/stripe/payment-methods/{cid}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["customer_id"] == cid
        assert len(body["payment_methods"]) >= 1
        assert body["payment_methods"][0]["provider"] == "stripe"
    finally:
        _cleanup(cid, tid)


def test_router_charge_admin_success_returns_intent(stub):
    """Skipped unless a real Stripe test key is wired via env (see reasoning
    on ``test_router_setup_intent_admin_flow``)."""
    if not (os.environ.get("STRIPE_SECRET_KEY_TEST") or "").startswith("sk_test_"):
        pytest.skip("no real STRIPE_SECRET_KEY_TEST wired — router happy-path skipped")
    tid = _tid()
    cid = _make_test_customer(tid)
    try:
        _run(svc.create_setup_intent(tenant_id=tid, customer_id=cid))
        _run(svc.attach_payment_method(
            tenant_id=tid, customer_id=cid, payment_method_id="pm_rt_charge",
        ))
        tok = _admin_token()
        r = requests.post(
            f"{API}/payments/stripe/charge",
            json={
                "customer_id": cid,
                "payment_method_id": "pm_rt_charge",
                "amount_cents": 2500,
                "currency": "usd",
                "invoice_id": "inv_router_TEST",
            },
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["payment_intent_id"].startswith("pi_test_")
    finally:
        _cleanup(cid, tid)
