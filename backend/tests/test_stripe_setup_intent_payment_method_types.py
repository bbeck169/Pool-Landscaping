"""Feb 2026 · P0 Stripe ACH SetupIntent + payment_method_types kwarg.

Locking specs for the Feb-2026 fix:

  1. ``create_setup_intent`` accepts a ``payment_method_types`` kwarg
     and threads it through to the Stripe SDK call. Regression guard
     for the P0 that had the customer-portal ACH endpoint blowing up
     with a ``TypeError`` on every "Connect Bank Account" click.

  2. Default behaviour (no kwarg / empty / bad value) still resolves
     to ``["card"]`` so the historical card capture path is bit-for-
     bit preserved.

Both the Stripe SDK boundary AND the Motor DB boundary are monkey-
patched — the specs assert kwarg propagation and nothing else, so a
100% in-memory test rig avoids Motor's "different loop" pain when
the module was previously bound to Motor's own event loop.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List

import pytest


class _FakeCustomersCol:
    """Minimal Motor-lookalike so ``sc.db.customers.find_one`` /
    ``.update_one`` are awaitable and return sane shapes without
    touching Mongo (which lives on a different event loop)."""

    def __init__(self, docs: Dict[str, Dict[str, Any]]):
        self._docs = docs
        self.update_calls: List[Dict[str, Any]] = []

    async def find_one(self, q, projection=None):  # noqa: ARG002
        cid = (q or {}).get("id")
        return self._docs.get(cid)

    async def update_one(self, q, update):
        self.update_calls.append({"q": q, "update": update})
        cid = (q or {}).get("id")
        if cid in self._docs and "$set" in update:
            self._docs[cid].update(update["$set"])
        return None


@pytest.fixture()
def stripe_shim(monkeypatch):
    """Monkey-patch the Stripe SDK boundary + Motor customers
    collection so we can drive ``create_setup_intent`` without any
    external I/O."""
    from services.payments import stripe_charge as sc

    calls: Dict[str, List[Dict[str, Any]]] = {
        "setup_intent": [], "customer": [],
    }

    def _fake_customer_create(**kw):
        calls["customer"].append(kw)
        return {"id": f"cus_TEST_{uuid.uuid4().hex[:12]}"}

    def _fake_setup_intent_create(**kw):
        calls["setup_intent"].append(kw)
        return {
            "id": f"seti_TEST_{uuid.uuid4().hex[:12]}",
            "client_secret": f"seti_TEST_{uuid.uuid4().hex[:8]}_secret",
        }

    monkeypatch.setattr(sc._stripe.Customer, "create", _fake_customer_create)
    monkeypatch.setattr(sc._stripe.SetupIntent, "create", _fake_setup_intent_create)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)

    # In-memory customer store; each test loads a canonical fixture.
    tid = f"TEST_stripe_pmt_tenant_{uuid.uuid4().hex[:8]}"
    cid = f"TEST_stripe_cust_{uuid.uuid4().hex[:8]}"
    store: Dict[str, Dict[str, Any]] = {
        cid: {
            "id": cid, "tenant_id": tid,
            "name": "Stripe PMT Customer",
            "email": "stripe-pmt@example.com",
            "stripe_customer_id": f"cus_TEST_{uuid.uuid4().hex[:12]}",
        },
    }
    fake_col = _FakeCustomersCol(store)
    monkeypatch.setattr(sc.db, "customers", fake_col)

    return {"calls": calls, "tid": tid, "cid": cid, "col": fake_col}


def _run(coro):
    """Fresh loop per test — the DB boundary is now in-memory so
    there's no shared-state that survives loop teardown."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_create_setup_intent_default_card_only(stripe_shim):
    from services.payments import stripe_charge as sc
    out = _run(sc.create_setup_intent(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        actor_user_id="u",
    ))
    assert out["client_secret"].startswith("seti_TEST_")
    kws = stripe_shim["calls"]["setup_intent"]
    assert len(kws) == 1
    assert kws[0]["payment_method_types"] == ["card"]


def test_create_setup_intent_ach_flavor(stripe_shim):
    """P0 fix — ACH flavour must propagate through to Stripe."""
    from services.payments import stripe_charge as sc
    out = _run(sc.create_setup_intent(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        actor_user_id="u",
        payment_method_types=["us_bank_account"],
    ))
    assert out["client_secret"].startswith("seti_TEST_")
    kws = stripe_shim["calls"]["setup_intent"]
    assert kws[0]["payment_method_types"] == ["us_bank_account"]


def test_create_setup_intent_mixed_types(stripe_shim):
    """Multi-flavour SetupIntent (card + ACH tabs on <PaymentElement>)."""
    from services.payments import stripe_charge as sc
    _run(sc.create_setup_intent(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        actor_user_id="u",
        payment_method_types=["card", "us_bank_account"],
    ))
    kws = stripe_shim["calls"]["setup_intent"]
    assert kws[0]["payment_method_types"] == ["card", "us_bank_account"]


def test_create_setup_intent_bad_input_falls_back_to_card(stripe_shim):
    """Empty list / None / non-list inputs coerce to ``["card"]``."""
    from services.payments import stripe_charge as sc
    for bad in (None, [], "us_bank_account"):
        stripe_shim["calls"]["setup_intent"].clear()
        _run(sc.create_setup_intent(
            tenant_id=stripe_shim["tid"],
            customer_id=stripe_shim["cid"],
            actor_user_id="u",
            payment_method_types=bad,
        ))
        kws = stripe_shim["calls"]["setup_intent"]
        assert kws[0]["payment_method_types"] == ["card"], (
            f"bad input {bad!r} did not fall back to card"
        )


def test_idempotency_key_differs_between_card_and_ach(stripe_shim):
    """Regression guard — two clicks on the same day for DIFFERENT
    flavours must NOT dedupe back to the same SetupIntent. The
    fix bakes the sorted PM-types list into the idempotency key.
    """
    from services.payments import stripe_charge as sc
    _run(sc.create_setup_intent(
        tenant_id=stripe_shim["tid"], customer_id=stripe_shim["cid"],
        payment_method_types=["card"],
    ))
    _run(sc.create_setup_intent(
        tenant_id=stripe_shim["tid"], customer_id=stripe_shim["cid"],
        payment_method_types=["us_bank_account"],
    ))
    kws = stripe_shim["calls"]["setup_intent"]
    assert len(kws) == 2
    # ``stripe`` SDK's Python client forwards ``idempotency_key`` via
    # kwarg. Our shim captures it verbatim.
    keys = [k.get("idempotency_key") for k in kws]
    assert keys[0] != keys[1], (
        "Idempotency keys collided between card + ACH flavours — "
        "second SetupIntent will silently dedupe back to the first."
    )


def test_customer_portal_ach_endpoint_no_longer_raises_typeerror():
    """Import-time smoke — the router call site now matches the
    signature. Before the fix, the module import succeeded but the
    first call blew up with ``TypeError: create_setup_intent()
    got an unexpected keyword argument 'payment_method_types'``.
    Now the kwarg is accepted, so the call site is contract-clean.
    """
    from services.payments import stripe_charge as sc
    import inspect
    sig = inspect.signature(sc.create_setup_intent)
    assert "payment_method_types" in sig.parameters, (
        "create_setup_intent must accept payment_method_types "
        "kwarg — the customer-portal ACH endpoint passes it."
    )
    p = sig.parameters["payment_method_types"]
    assert p.default is None
