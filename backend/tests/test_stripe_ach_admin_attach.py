"""Phase B1 · Feb-2026 — Admin ACH parity backend tests.

Locking specs:

  1. ``POST /payments/stripe/setup-intent`` accepts a
     ``payment_method_types`` field and threads it through to
     :func:`services.payments.stripe_charge.create_setup_intent`.
  2. ``attach_payment_method`` correctly extracts ``us_bank_account``
     fields (``type``, ``bank_name``, ``account_holder_type``,
     ``verification_status``, ``last4``) into the ``db.payment_methods``
     mirror row when the retrieved PM is an ACH bank account.
  3. Card PMs continue to write the historical card fields with
     ``type="card"`` and empty ACH fields — regression guard for
     the existing card capture flow.
  4. ``list_payment_methods`` returns both card and ACH mirror rows
     unchanged (each carries a ``type`` discriminator the CRM UI
     uses to render card-chrome vs bank-chrome).
  5. ``detach_payment_method`` handles ACH removals identically to
     card removals — Stripe SDK detach + local mirror delete.

Stripe SDK + Motor DB are both monkey-patched — no external I/O.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List

import pytest


class _FakeCol:
    """Minimal Motor-lookalike (see sibling ACH tests for the
    original)."""

    def __init__(self, docs: Dict[str, Dict[str, Any]] | None = None):
        self._docs = docs or {}
        self._by_pm: Dict[str, Dict[str, Any]] = {}

    async def find_one(self, q, projection=None):  # noqa: ARG002
        cid = (q or {}).get("id")
        if cid and cid in self._docs:
            doc = self._docs.get(cid)
            # Respect tenant_id filter if the caller supplied one —
            # matches Mongo semantics + is essential for the
            # cross-tenant isolation regression guard.
            filter_tid = (q or {}).get("tenant_id")
            if filter_tid and doc.get("tenant_id") != filter_tid:
                return None
            return doc
        pmid = (q or {}).get("provider_payment_method_id")
        if pmid and pmid in self._by_pm:
            return self._by_pm.get(pmid)
        return None

    async def update_one(self, q, update, upsert=False):  # noqa: ARG002
        cid = (q or {}).get("id")
        if cid:
            self._docs.setdefault(cid, {}).update(update.get("$set", {}))
            return None
        pmid = (q or {}).get("provider_payment_method_id")
        if pmid:
            self._by_pm.setdefault(pmid, {}).update(
                update.get("$set", {}))
        return None

    async def update_many(self, q, update):  # noqa: ARG002
        return None

    async def insert_one(self, doc):
        pmid = doc.get("provider_payment_method_id")
        if pmid:
            self._by_pm[pmid] = doc
        return None

    async def delete_one(self, q):
        pmid = (q or {}).get("provider_payment_method_id")
        if pmid:
            self._by_pm.pop(pmid, None)
        return None

    async def count_documents(self, q):  # noqa: ARG002
        return len(self._by_pm)

    def find(self, q, projection=None):  # noqa: ARG002
        # Async iterator over stored PMs.
        docs = list(self._by_pm.values())

        class _Cursor:
            def __init__(self, rows):
                self._rows = rows

            def sort(self, *_a, **_k):
                return self

            def __aiter__(self):
                self._it = iter(self._rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:  # pragma: no cover
                    raise StopAsyncIteration
        return _Cursor(docs)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture()
def stripe_shim(monkeypatch):
    """Monkey-patch the Stripe SDK boundary + Motor collections."""
    from services.payments import stripe_charge as sc

    calls: Dict[str, List[Dict[str, Any]]] = {
        "attach": [], "retrieve": [], "detach": [],
        "setup_intent": [],
    }

    # PMs the shim can hand back via ``PaymentMethod.retrieve``.
    pms: Dict[str, Dict[str, Any]] = {}

    def _fake_attach(pm_id, **kw):
        calls["attach"].append({"pm_id": pm_id, **kw})
        return {"id": pm_id, "attached": True}

    def _fake_retrieve(pm_id, **kw):
        calls["retrieve"].append({"pm_id": pm_id, **kw})
        return pms[pm_id]

    def _fake_detach(pm_id, **kw):
        calls["detach"].append({"pm_id": pm_id, **kw})
        return {"id": pm_id, "detached": True}

    def _fake_setup_intent_create(**kw):
        calls["setup_intent"].append(kw)
        return {
            "id": f"seti_TEST_{uuid.uuid4().hex[:12]}",
            "client_secret": f"seti_TEST_{uuid.uuid4().hex[:8]}_secret",
        }

    monkeypatch.setattr(sc._stripe.PaymentMethod, "attach", _fake_attach)
    monkeypatch.setattr(
        sc._stripe.PaymentMethod, "retrieve", _fake_retrieve)
    monkeypatch.setattr(sc._stripe.PaymentMethod, "detach", _fake_detach)
    monkeypatch.setattr(
        sc._stripe.SetupIntent, "create", _fake_setup_intent_create)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)

    tid = f"TEST_b1_tenant_{uuid.uuid4().hex[:8]}"
    cid = f"TEST_b1_cust_{uuid.uuid4().hex[:8]}"
    stripe_cust_id = f"cus_TEST_{uuid.uuid4().hex[:12]}"
    customers = _FakeCol({
        cid: {"id": cid, "tenant_id": tid,
                "stripe_customer_id": stripe_cust_id,
                "name": "B1 Cust", "email": "b1@example.com"},
    })
    payment_methods = _FakeCol()
    monkeypatch.setattr(sc.db, "customers", customers)
    monkeypatch.setattr(sc.db, "payment_methods", payment_methods)

    return {
        "calls": calls, "pms": pms,
        "tid": tid, "cid": cid,
        "stripe_customer_id": stripe_cust_id,
        "col_customers": customers,
        "col_payment_methods": payment_methods,
    }


# ═════════════════════════════════════════════════════════════════════
# 1 · SetupIntent accepts payment_method_types + threads to Stripe
# ═════════════════════════════════════════════════════════════════════
def test_setup_intent_admin_ach_flow(stripe_shim):
    from services.payments import stripe_charge as sc
    out = _run(sc.create_setup_intent(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        actor_user_id="admin-u",
        payment_method_types=["us_bank_account"],
    ))
    assert out["client_secret"].startswith("seti_TEST_")
    kws = stripe_shim["calls"]["setup_intent"]
    assert len(kws) == 1
    assert kws[0]["payment_method_types"] == ["us_bank_account"]


# ═════════════════════════════════════════════════════════════════════
# 2 · attach_payment_method extracts ACH fields into the mirror row
# ═════════════════════════════════════════════════════════════════════
def test_attach_ach_pm_writes_full_bank_mirror(stripe_shim):
    from services.payments import stripe_charge as sc
    pm_id = f"pm_TEST_{uuid.uuid4().hex[:10]}"
    # Stripe response Stripe would give us on retrieve.
    stripe_shim["pms"][pm_id] = {
        "id": pm_id, "type": "us_bank_account",
        "us_bank_account": {
            "bank_name": "Test Bank",
            "last4": "6789",
            "account_holder_type": "individual",
            "verifications": {"status": "unverified"},
        },
        # No ``card`` sub-object.
    }
    out = _run(sc.attach_payment_method(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        payment_method_id=pm_id,
        set_default=False,
    ))
    assert out["type"] == "us_bank_account"
    assert out["bank_name"] == "Test Bank"
    assert out["last4"] == "6789"
    assert out["account_holder_type"] == "individual"
    assert out["verification_status"] == "unverified"
    assert out["brand"] == ""            # empty for ACH
    assert out["exp_month"] is None
    assert out["exp_year"] is None
    assert out["is_default"] is False


# ═════════════════════════════════════════════════════════════════════
# 3 · Card attach still works (regression guard)
# ═════════════════════════════════════════════════════════════════════
def test_attach_card_pm_still_writes_card_mirror(stripe_shim):
    from services.payments import stripe_charge as sc
    pm_id = f"pm_TEST_{uuid.uuid4().hex[:10]}"
    stripe_shim["pms"][pm_id] = {
        "id": pm_id, "type": "card",
        "card": {"brand": "visa", "last4": "4242",
                    "exp_month": 12, "exp_year": 2030},
    }
    out = _run(sc.attach_payment_method(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        payment_method_id=pm_id,
        set_default=True,
    ))
    assert out["type"] == "card"
    assert out["brand"] == "visa"
    assert out["last4"] == "4242"
    assert out["exp_month"] == 12
    assert out["exp_year"] == 2030
    # ACH fields present but empty.
    assert out["bank_name"] == ""
    assert out["account_holder_type"] == ""
    assert out["verification_status"] is None
    assert out["is_default"] is True


# ═════════════════════════════════════════════════════════════════════
# 4 · list_payment_methods returns card + ACH rows with type discriminator
# ═════════════════════════════════════════════════════════════════════
def test_list_returns_card_and_ach_rows(stripe_shim):
    from services.payments import stripe_charge as sc
    # Seed one card + one ACH via attach.
    card_pm = f"pm_TEST_{uuid.uuid4().hex[:10]}"
    ach_pm = f"pm_TEST_{uuid.uuid4().hex[:10]}"
    stripe_shim["pms"][card_pm] = {
        "id": card_pm, "type": "card",
        "card": {"brand": "visa", "last4": "4242",
                    "exp_month": 6, "exp_year": 2029},
    }
    stripe_shim["pms"][ach_pm] = {
        "id": ach_pm, "type": "us_bank_account",
        "us_bank_account": {"bank_name": "Chase", "last4": "0001",
                                 "account_holder_type": "individual",
                                 "verifications": {"status": "pending"}},
    }
    _run(sc.attach_payment_method(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        payment_method_id=card_pm, set_default=True,
    ))
    _run(sc.attach_payment_method(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        payment_method_id=ach_pm, set_default=False,
    ))
    rows = _run(sc.list_payment_methods(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
    ))
    types = {r.get("type") for r in rows}
    assert types == {"card", "us_bank_account"}
    ach_row = next(r for r in rows if r["type"] == "us_bank_account")
    assert ach_row["bank_name"] == "Chase"
    assert ach_row["verification_status"] == "pending"


# ═════════════════════════════════════════════════════════════════════
# 5 · detach_payment_method removes ACH mirror + calls Stripe detach
# ═════════════════════════════════════════════════════════════════════
def test_detach_ach_pm_removes_mirror(stripe_shim):
    from services.payments import stripe_charge as sc
    ach_pm = f"pm_TEST_{uuid.uuid4().hex[:10]}"
    stripe_shim["pms"][ach_pm] = {
        "id": ach_pm, "type": "us_bank_account",
        "us_bank_account": {"bank_name": "Wells Fargo",
                                 "last4": "9999",
                                 "verifications": {"status": "verified"}},
    }
    _run(sc.attach_payment_method(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
        payment_method_id=ach_pm, set_default=False,
    ))
    out = _run(sc.detach_payment_method(
        tenant_id=stripe_shim["tid"],
        payment_method_id=ach_pm,
    ))
    assert out["ok"] is True
    assert stripe_shim["calls"]["detach"][0]["pm_id"] == ach_pm
    # Mirror row gone.
    still = _run(sc.list_payment_methods(
        tenant_id=stripe_shim["tid"],
        customer_id=stripe_shim["cid"],
    ))
    assert all(r.get("provider_payment_method_id") != ach_pm
                  for r in still)


# ═════════════════════════════════════════════════════════════════════
# 6 · SetupIntentBody accepts payment_method_types (pydantic schema)
# ═════════════════════════════════════════════════════════════════════
def test_setup_intent_body_schema_accepts_payment_method_types():
    from routers.stripe_router import SetupIntentBody
    body = SetupIntentBody(customer_id="c-1",
                                 payment_method_types=["us_bank_account"])
    assert body.payment_method_types == ["us_bank_account"]
    # Default (unset) stays None so the historical card-only flow
    # continues to bypass the kwarg down to the service.
    body_default = SetupIntentBody(customer_id="c-1")
    assert body_default.payment_method_types is None


# ═════════════════════════════════════════════════════════════════════
# 7 · Tenant isolation — customer belongs to a different tenant → 404
# ═════════════════════════════════════════════════════════════════════
def test_attach_rejects_cross_tenant_customer(stripe_shim):
    from services.payments import stripe_charge as sc
    other_tid = f"TEST_other_tenant_{uuid.uuid4().hex[:8]}"
    pm_id = f"pm_TEST_{uuid.uuid4().hex[:10]}"
    stripe_shim["pms"][pm_id] = {
        "id": pm_id, "type": "us_bank_account",
        "us_bank_account": {"bank_name": "X", "last4": "0000",
                                 "verifications": {"status": "unverified"}},
    }
    with pytest.raises(ValueError, match="customer not found"):
        _run(sc.attach_payment_method(
            tenant_id=other_tid,
            customer_id=stripe_shim["cid"],
            payment_method_id=pm_id,
        ))
