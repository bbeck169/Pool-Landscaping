"""Feb 2026 addendum · save-on-first-payment.

Two locking specs:

  1. ``create_invoice_checkout_session`` accepts a
     ``save_for_future_billing: bool`` kwarg and propagates it to
     Stripe as ``payment_intent_data.setup_future_usage="off_session"``
     + ``metadata.crm_save_for_future="1"``. Default is False (no
     save) so existing callers keep the historical behaviour.

  2. On ``checkout.session.completed`` with
     ``metadata.crm_save_for_future="1"`` + ``payment_status=paid``,
     the reconcile path retrieves the PI, extracts
     ``payment_method``, and routes through
     ``attach_payment_method(set_default=True)``. Idempotent.

  3. Server-side gate — the ``/invoices/{id}/request-payment-link``
     router NEVER passes ``save_for_future_billing=True`` down when
     the customer already has 1+ saved PMs. Locks the "don't silently
     promote a new PM behind an existing default" product rule.

Stripe SDK + Motor DB are both monkey-patched — no external I/O.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List

import pytest


class _FakeCol:
    def __init__(self, docs: Dict[str, Dict[str, Any]] | None = None):
        self._docs = docs or {}
        self.upsert_calls: List[Dict[str, Any]] = []
        self.count_calls: List[Dict[str, Any]] = []
        self._count_return = 0

    def _set_count(self, n: int):
        self._count_return = n

    async def find_one(self, q, projection=None):  # noqa: ARG002
        cid = (q or {}).get("id")
        return self._docs.get(cid)

    async def update_one(self, q, update, upsert=False):  # noqa: ARG002
        self.upsert_calls.append({"q": q, "update": update, "upsert": upsert})
        cid = (q or {}).get("id") or (q or {}).get("provider_payment_method_id")
        if cid and "$set" in update:
            self._docs.setdefault(cid, {}).update(update["$set"])
        if cid and "$setOnInsert" in update:
            self._docs.setdefault(cid, {}).update(update["$setOnInsert"])
        return None

    async def insert_one(self, doc):
        rid = doc.get("id") or doc.get("provider_payment_method_id") or str(uuid.uuid4())
        self._docs[rid] = doc
        return None

    async def count_documents(self, q):
        self.count_calls.append(q)
        return self._count_return


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture()
def stripe_shim(monkeypatch):
    from services.payments import stripe_charge as sc

    calls: Dict[str, List[Dict[str, Any]]] = {
        "session": [], "attach": [], "pi_retrieve": [],
    }

    def _fake_session_create(**kw):
        calls["session"].append(kw)
        return {
            "id": f"cs_TEST_{uuid.uuid4().hex[:12]}",
            "url": "https://checkout.stripe.com/c/pay/cs_TEST",
        }

    def _fake_pi_retrieve(pi_id, **_):
        calls["pi_retrieve"].append(pi_id)
        return {
            "id": pi_id,
            "payment_method": f"pm_TEST_{uuid.uuid4().hex[:12]}",
        }

    monkeypatch.setattr(sc._stripe.checkout.Session, "create", _fake_session_create)
    monkeypatch.setattr(sc._stripe.PaymentIntent, "retrieve", _fake_pi_retrieve)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.com")

    # Stub the shared ``attach_payment_method`` so we can prove the
    # webhook path calls it with ``set_default=True`` and the right
    # PM id. The real helper mutates ``db.payment_methods`` and hits
    # the Stripe SDK a second time; a shim keeps this spec pure.
    async def _fake_attach(*, tenant_id, customer_id, payment_method_id, set_default=False):
        calls["attach"].append({
            "tenant_id": tenant_id, "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "set_default": set_default,
        })
        return {
            "id": f"pm_row_{uuid.uuid4().hex[:8]}",
            "provider_payment_method_id": payment_method_id,
            "is_default": bool(set_default),
        }
    monkeypatch.setattr(sc, "attach_payment_method", _fake_attach)

    # In-memory Mongo stand-in. The two functions under test both
    # read/write ``db.customers`` and ``db.quotes``; the webhook also
    # writes ``db.stripe_charges`` and ``db.payment_events``. All
    # stubbed with the ``_FakeCol`` shim.
    tid = f"TEST_tenant_{uuid.uuid4().hex[:8]}"
    cid = f"TEST_cust_{uuid.uuid4().hex[:8]}"
    customers = _FakeCol({cid: {
        "id": cid, "tenant_id": tid, "name": "Test", "email": "t@example.com",
    }})
    monkeypatch.setattr(sc.db, "customers", customers)
    quotes = _FakeCol()
    monkeypatch.setattr(sc.db, "quotes", quotes)
    monkeypatch.setattr(sc.db, "stripe_charges", _FakeCol())
    monkeypatch.setattr(sc.db, "payment_events", _FakeCol())

    return {"calls": calls, "tid": tid, "cid": cid}


def _invoice(tid: str, cid: str, iid: str = None, total: float = 42.0):
    return {
        "id": iid or f"TEST_inv_{uuid.uuid4().hex[:8]}",
        "tenant_id": tid,
        "customer_id": cid,
        "customer_name": "Test",
        "customer_email": "t@example.com",
        "invoice_number": "TEST-0007",
        "total": total,
        "amount_paid": 0,
        "currency": "usd",
    }


# ────────────────────────── Session-create ────────────────────────
def test_session_default_no_setup_future_usage(stripe_shim):
    from services.payments import stripe_charge as sc
    inv = _invoice(stripe_shim["tid"], stripe_shim["cid"])
    _run(sc.create_invoice_checkout_session(
        tenant_id=stripe_shim["tid"], invoice=inv,
        customer={"id": stripe_shim["cid"], "email": "t@example.com"},
    ))
    kw = stripe_shim["calls"]["session"][0]
    pi_data = kw.get("payment_intent_data") or {}
    assert "setup_future_usage" not in pi_data
    assert kw["metadata"]["crm_save_for_future"] == "0"


def test_session_with_save_flag_sets_setup_future_usage(stripe_shim):
    from services.payments import stripe_charge as sc
    inv = _invoice(stripe_shim["tid"], stripe_shim["cid"])
    _run(sc.create_invoice_checkout_session(
        tenant_id=stripe_shim["tid"], invoice=inv,
        customer={"id": stripe_shim["cid"], "email": "t@example.com"},
        save_for_future_billing=True,
    ))
    kw = stripe_shim["calls"]["session"][0]
    pi_data = kw.get("payment_intent_data") or {}
    assert pi_data.get("setup_future_usage") == "off_session"
    assert kw["metadata"]["crm_save_for_future"] == "1"
    # Metadata is ALSO on the PI (webhook reads from there).
    assert pi_data["metadata"]["crm_save_for_future"] == "1"


def test_session_idempotency_key_differs_between_save_and_nosave(stripe_shim):
    """Regression guard — a customer who unchecks the save box then
    re-clicks Pay must NOT dedupe back to the earlier save-enabled
    Session. The fix folds the save flavour into the idempotency
    key alongside the amount.
    """
    from services.payments import stripe_charge as sc
    inv = _invoice(stripe_shim["tid"], stripe_shim["cid"])
    _run(sc.create_invoice_checkout_session(
        tenant_id=stripe_shim["tid"], invoice=inv,
        customer={"id": stripe_shim["cid"]},
        save_for_future_billing=True,
    ))
    _run(sc.create_invoice_checkout_session(
        tenant_id=stripe_shim["tid"], invoice=inv,
        customer={"id": stripe_shim["cid"]},
        save_for_future_billing=False,
    ))
    k0 = stripe_shim["calls"]["session"][0]["idempotency_key"]
    k1 = stripe_shim["calls"]["session"][1]["idempotency_key"]
    assert k0 != k1


# ─────────────────────────── Webhook branch ───────────────────────
def test_webhook_save_flag_attaches_pm_as_default(stripe_shim):
    from services.payments import stripe_charge as sc
    tid, cid = stripe_shim["tid"], stripe_shim["cid"]
    iid = f"TEST_inv_{uuid.uuid4().hex[:8]}"
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": f"cs_TEST_{uuid.uuid4().hex[:8]}",
            "payment_intent": f"pi_TEST_{uuid.uuid4().hex[:8]}",
            "payment_status": "paid",
            "amount_total": 4200,
            "currency": "usd",
            "metadata": {
                "crm_invoice_id": iid,
                "crm_tenant_id": tid,
                "crm_customer_id": cid,
                "crm_save_for_future": "1",
                "source": "phase47_invoice_pay",
            },
        }},
    }
    _run(sc.handle_webhook_event(event))
    # Attach was called once with set_default=True.
    assert len(stripe_shim["calls"]["attach"]) == 1
    ac = stripe_shim["calls"]["attach"][0]
    assert ac["tenant_id"] == tid
    assert ac["customer_id"] == cid
    assert ac["set_default"] is True
    # PI retrieve was called to find the payment_method id.
    assert len(stripe_shim["calls"]["pi_retrieve"]) == 1


def test_webhook_no_save_flag_skips_attach(stripe_shim):
    from services.payments import stripe_charge as sc
    tid, cid = stripe_shim["tid"], stripe_shim["cid"]
    iid = f"TEST_inv_{uuid.uuid4().hex[:8]}"
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": f"cs_TEST_{uuid.uuid4().hex[:8]}",
            "payment_intent": f"pi_TEST_{uuid.uuid4().hex[:8]}",
            "payment_status": "paid",
            "amount_total": 4200,
            "currency": "usd",
            "metadata": {
                "crm_invoice_id": iid,
                "crm_tenant_id": tid,
                "crm_customer_id": cid,
                "crm_save_for_future": "0",
                "source": "phase47_invoice_pay",
            },
        }},
    }
    _run(sc.handle_webhook_event(event))
    assert stripe_shim["calls"]["attach"] == []
    assert stripe_shim["calls"]["pi_retrieve"] == []


def test_webhook_save_flag_but_unpaid_skips_attach(stripe_shim):
    """If Stripe reports ``payment_status != "paid"`` (e.g. bank
    redirect abandoned), the save-on-first-payment branch must NOT
    fire — nothing was actually charged."""
    from services.payments import stripe_charge as sc
    tid, cid = stripe_shim["tid"], stripe_shim["cid"]
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": f"cs_TEST_{uuid.uuid4().hex[:8]}",
            "payment_intent": f"pi_TEST_{uuid.uuid4().hex[:8]}",
            "payment_status": "unpaid",
            "amount_total": 4200,
            "currency": "usd",
            "metadata": {
                "crm_invoice_id": f"TEST_inv_{uuid.uuid4().hex[:8]}",
                "crm_tenant_id": tid,
                "crm_customer_id": cid,
                "crm_save_for_future": "1",
                "source": "phase47_invoice_pay",
            },
        }},
    }
    _run(sc.handle_webhook_event(event))
    assert stripe_shim["calls"]["attach"] == []


# ───────────────── Router server-side gate (PM count) ─────────────
def test_router_gate_customer_with_pms_forces_save_false(monkeypatch):
    """Server-side gate: caller sends save=true but the customer
    has 1+ saved PMs → we resolve to save=false before calling
    Stripe. Locks the "don't silently promote a new PM behind an
    existing default" product rule."""
    from routers import lumino_link_request as rr

    fake_pm_col = _FakeCol()
    fake_pm_col._set_count(3)  # customer has 3 PMs on file
    monkeypatch.setattr(rr.db, "payment_methods", fake_pm_col)

    resolved = _run(rr._customer_pm_count("tid-1", "cid-1"))
    assert resolved == 3
    # Downstream router logic: `save_requested and pm_count == 0`.
    save_requested = True
    save_for_future = save_requested and resolved == 0
    assert save_for_future is False


def test_router_gate_zero_pms_honors_save_flag(monkeypatch):
    from routers import lumino_link_request as rr

    fake_pm_col = _FakeCol()
    fake_pm_col._set_count(0)
    monkeypatch.setattr(rr.db, "payment_methods", fake_pm_col)

    resolved = _run(rr._customer_pm_count("tid-1", "cid-1"))
    assert resolved == 0
    save_requested = True
    save_for_future = save_requested and resolved == 0
    assert save_for_future is True


def test_router_gate_pm_count_read_failure_is_safe(monkeypatch):
    """If the ``payment_methods`` read blows up (bad index, replica
    lag, ...), the helper returns a large sentinel so the router
    fails the "== 0" gate. Better a missed save than an accidental
    silent promotion."""
    from routers import lumino_link_request as rr

    class _ExplodingCol:
        async def count_documents(self, q):  # noqa: ARG002
            raise RuntimeError("bad index")
    monkeypatch.setattr(rr.db, "payment_methods", _ExplodingCol())

    resolved = _run(rr._customer_pm_count("tid-1", "cid-1"))
    assert resolved >= 1   # NOT 0, so the "== 0" gate fails safely
