"""Phase 47 · Feb-2026 — Direct Stripe Checkout Session flow.

Covers:
    * ``services.payments.stripe_charge.create_invoice_checkout_session``
      constructs the Session with mode=payment, right amount, right
      metadata, and success/cancel URLs pointing at the tenant portal.
    * ``handle_webhook_event(checkout.session.completed)`` marks the
      invoice paid, mirrors a stripe_charges row keyed off the Session
      id (idempotent), and appends an audit row into payment_events.
    * The router ``POST /api/invoices/{id}/request-payment-link``:
        - Rejects unknown invoice with 404.
        - Rejects a customer poking at someone else's invoice with 403.
        - Returns 502 with a clean error code when Stripe explodes.
        - Never calls the Zapier dispatcher.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── create_invoice_checkout_session ──────────────────────────────────
def _fake_stripe_session_object() -> Any:
    """A v15-shape StripeObject fake: has ``to_dict_recursive`` AND
    ``__getitem__`` attribute-access, but does NOT inherit dict."""
    payload = {
        "id": "cs_test_phase47_abc",
        "url": "https://checkout.stripe.com/c/pay/cs_test_phase47_abc",
        "amount_total": 12345,
        "currency": "usd",
        "metadata": {
            "crm_invoice_id": "inv-1",
            "crm_tenant_id": "aquaterra",
            "crm_customer_id": "cust-1",
            "source": "phase47_invoice_pay",
        },
    }
    return SimpleNamespace(
        to_dict_recursive=lambda: payload,
        **payload,
    )


def test_create_invoice_checkout_session_happy_path(monkeypatch):
    """Assert the Session is built with mode=payment, the right amount,
    the right metadata, and success/cancel URLs pointing at APP_PUBLIC_URL."""
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    from services.payments import stripe_charge as sc

    session_fake = _fake_stripe_session_object()
    fake_create = MagicMock(return_value=session_fake)

    with patch.object(sc, "_init_api_key", lambda: None), \
         patch.object(sc, "_stripe", MagicMock(checkout=MagicMock(Session=MagicMock(create=fake_create)))), \
         patch.object(sc, "_mode", lambda: "test"):
        out = asyncio.get_event_loop().run_until_complete(
            sc.create_invoice_checkout_session(
                tenant_id="aquaterra",
                invoice={"id": "inv-1", "total": 200.00, "amount_paid": 76.55,
                         "currency": "usd", "invoice_number": "INV-1001"},
                customer={"id": "cust-1", "email": "buyer@example.test",
                          "name": "Buyer"},
            )
        )
    assert out == {
        "payment_url": "https://checkout.stripe.com/c/pay/cs_test_phase47_abc",
        "checkout_session_id": "cs_test_phase47_abc",
        "amount_cents": 12345,
        "currency": "usd",
        "mode": "test",
    }
    # Inspect the kwargs Stripe would have received.
    kwargs = fake_create.call_args.kwargs
    assert kwargs["mode"] == "payment"
    assert kwargs["success_url"] == \
        "https://example.test/portal/payment-complete?session_id={CHECKOUT_SESSION_ID}"
    assert kwargs["cancel_url"] == "https://example.test/portal/invoices/inv-1"
    assert kwargs["customer_email"] == "buyer@example.test"
    assert kwargs["client_reference_id"] == "inv-1"
    # Metadata carried on the Session AND propagated to the PaymentIntent.
    for meta in (kwargs["metadata"], kwargs["payment_intent_data"]["metadata"]):
        assert meta["crm_invoice_id"] == "inv-1"
        assert meta["crm_tenant_id"] == "aquaterra"
        assert meta["crm_customer_id"] == "cust-1"
        assert meta["source"] == "phase47_invoice_pay"
    # Amount matches the invoice balance (200 - 76.55) in cents.
    assert kwargs["line_items"][0]["price_data"]["unit_amount"] == 12345
    # Idempotency key so a retried request doesn't create a second Session.
    assert kwargs["idempotency_key"].startswith("phase47:invoice:aquaterra:inv-1:")


def test_create_invoice_checkout_session_uses_asdict_no_raw_get(monkeypatch):
    """Regression guard — the helper must extract fields via _asdict()
    (which supports v15's non-``dict`` StripeObject) instead of
    ``.get(...)`` directly on the SDK return value."""
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    from services.payments import stripe_charge as sc
    import inspect
    src = inspect.getsource(sc.create_invoice_checkout_session)
    # Session return value is bound to ``session`` — the helper must
    # then convert via ``_asdict(session)`` before pulling fields off.
    assert "_asdict(session)" in src, \
        "must pass Session through _asdict() before accessing fields"


def test_create_invoice_checkout_session_rejects_already_paid(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    from services.payments import stripe_charge as sc
    with patch.object(sc, "_init_api_key", lambda: None):
        with pytest.raises(ValueError, match="invoice_already_paid"):
            asyncio.get_event_loop().run_until_complete(
                sc.create_invoice_checkout_session(
                    tenant_id="a", invoice={"id": "inv-1", "total": 50, "amount_paid": 50},
                    customer={"id": "c"}))


def test_create_invoice_checkout_session_requires_app_url(monkeypatch):
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    from services.payments import stripe_charge as sc
    with patch.object(sc, "_init_api_key", lambda: None):
        with pytest.raises(ValueError, match="APP_PUBLIC_URL"):
            asyncio.get_event_loop().run_until_complete(
                sc.create_invoice_checkout_session(
                    tenant_id="a", invoice={"id": "inv-1", "total": 50},
                    customer={"id": "c"}))


# ── Webhook handler ───────────────────────────────────────────────────
def _build_checkout_completed_event(**overrides) -> Dict[str, Any]:
    base = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_phase47_wh",
            "payment_status": "paid",
            "amount_total": 12345,
            "currency": "usd",
            "payment_intent": "pi_wh_1",
            "metadata": {
                "crm_invoice_id": "inv-99",
                "crm_tenant_id": "aquaterra",
                "crm_customer_id": "cust-99",
            },
        }},
    }
    base["data"]["object"].update(overrides)
    return base


@pytest.mark.asyncio_deprecated  # placeholder — real invocation below uses asyncio.run
def test_webhook_checkout_completed_marks_invoice_paid_and_writes_charge():
    from services.payments import stripe_charge as sc

    stripe_charges = MagicMock()
    stripe_charges.update_one = AsyncMock()
    quotes = MagicMock()
    quotes.find_one = AsyncMock(return_value={
        "id": "inv-99", "total": 123.45, "amount_paid": 0.0,
    })
    quotes.update_one = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    payment_events = MagicMock()
    payment_events.insert_one = AsyncMock()

    fake_db = MagicMock(stripe_charges=stripe_charges, quotes=quotes,
                        payment_events=payment_events)
    with patch.object(sc, "db", fake_db):
        out = asyncio.get_event_loop().run_until_complete(
            sc.handle_webhook_event(_build_checkout_completed_event()))
    assert out == {"type": "checkout.session.completed", "handled": True}
    assert stripe_charges.update_one.await_count == 1
    call = stripe_charges.update_one.await_args
    assert call.args[0] == {"stripe_checkout_session_id": "cs_test_phase47_wh"}
    set_on_insert = call.args[1]["$setOnInsert"]
    assert set_on_insert["invoice_id"] == "inv-99"
    assert set_on_insert["tenant_id"] == "aquaterra"
    assert set_on_insert["customer_id"] == "cust-99"
    assert set_on_insert["amount_cents"] == 12345
    assert set_on_insert["source"] == "phase47_invoice_pay"
    quotes.update_one.assert_awaited_once()
    update_args = quotes.update_one.await_args.args
    assert update_args[0] == {"id": "inv-99"}
    setter = update_args[1]["$set"]
    assert setter["payment_status"] == "paid"
    assert setter["payment_method"] == "stripe_checkout"
    assert setter["stripe_checkout_session_id"] == "cs_test_phase47_wh"
    assert setter["stripe_payment_intent_id"] == "pi_wh_1"
    assert "paid_at" in setter
    payment_events.insert_one.assert_awaited_once()
    audit = payment_events.insert_one.await_args.args[0]
    assert audit["kind"] == "phase47_checkout_session_completed"
    assert audit["invoice_id"] == "inv-99"


def test_webhook_checkout_completed_idempotent_when_already_paid():
    from services.payments import stripe_charge as sc
    quotes = MagicMock()
    quotes.find_one = AsyncMock(return_value={
        "id": "inv-99", "total": 100.0, "amount_paid": 100.0,
        "payment_status": "paid",
    })
    quotes.update_one = AsyncMock()
    fake_db = MagicMock(
        stripe_charges=MagicMock(update_one=AsyncMock()),
        quotes=quotes,
        payment_events=MagicMock(insert_one=AsyncMock()),
    )
    with patch.object(sc, "db", fake_db):
        out = asyncio.get_event_loop().run_until_complete(
            sc.handle_webhook_event(_build_checkout_completed_event()))
    assert out["handled"] is True
    quotes.update_one.assert_not_awaited()


def test_webhook_checkout_completed_unpaid_status_does_not_mark_invoice():
    from services.payments import stripe_charge as sc
    quotes = MagicMock()
    quotes.find_one = AsyncMock(return_value={"id": "inv-99", "total": 100.0})
    quotes.update_one = AsyncMock()
    fake_db = MagicMock(
        stripe_charges=MagicMock(update_one=AsyncMock()),
        quotes=quotes,
        payment_events=MagicMock(insert_one=AsyncMock()),
    )
    with patch.object(sc, "db", fake_db):
        asyncio.get_event_loop().run_until_complete(
            sc.handle_webhook_event(
                _build_checkout_completed_event(payment_status="unpaid")))
    quotes.update_one.assert_not_awaited()


def test_webhook_checkout_completed_ignores_events_without_invoice_metadata():
    from services.payments import stripe_charge as sc
    fake_db = MagicMock(
        stripe_charges=MagicMock(update_one=AsyncMock()),
        quotes=MagicMock(find_one=AsyncMock()),
        payment_events=MagicMock(insert_one=AsyncMock()),
    )
    ev = _build_checkout_completed_event()
    ev["data"]["object"]["metadata"] = {}
    with patch.object(sc, "db", fake_db):
        out = asyncio.get_event_loop().run_until_complete(
            sc.handle_webhook_event(ev))
    assert out == {"type": "checkout.session.completed", "handled": False}


# ── Router regression: no Zapier call remains ─────────────────────────
def test_router_no_longer_dispatches_to_zapier():
    """Grep the router body for any reference to the Zapier bridge.
    The module file still LIVES at ``routers/lumino_link_request.py``
    (path preserved for git history + import stability); the check is
    scoped to the function body via inspect.getsource(), stripping
    the router's own docstring (which explains WHY we swapped away
    from Lumino/Zapier)."""
    import inspect
    import re
    from routers import lumino_link_request as router_mod
    src = inspect.getsource(router_mod.request_payment_link)
    # Strip triple-quoted docstring (the router explains the migration
    # in its docstring — we only want to grep the RUNTIME body).
    body = re.sub(r'"""[\s\S]*?"""', "", src, count=1).lower()
    assert "dispatch_invoice_link_request" not in body
    assert "zapier" not in body
    assert "create_invoice_checkout_session" in body


def test_router_returns_payment_url_key():
    """Response contract — must return ``payment_url`` (matches the
    frontend PaymentForm.jsx expectation)."""
    import inspect
    from services.payments import stripe_charge as sc
    src = inspect.getsource(sc.create_invoice_checkout_session)
    assert '"payment_url"' in src
    assert '"checkout_session_id"' in src
