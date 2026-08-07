"""Phase P1-Hotfix-#3 · Feb 2026 — Stripe webhook route + handler regression.

Stripe Dashboard was configured to POST webhooks to
``/api/stripe/webhook`` (a historical short path) but the main router
lives at ``/api/payments/stripe/webhook``. That mismatch produced a
constant stream of 404s to Stripe, which the SaaS retries endlessly
and eventually surfaces as ``Webhook delivery failing`` emails to the
operator.

This module locks the fix in place. Tests:

1. ``/api/stripe/webhook`` (the historical short URL) is mounted and
   returns a 4xx signature-error envelope for a bogus payload — NOT
   404 (which is what Stripe's dashboard was seeing before).
2. ``/api/payments/stripe/webhook`` (the primary URL) still works.
3. Both URLs share the same handler — verified by asserting the
   identical response envelope.
4. The handler accepts each of the common event types the app cares
   about (``payment_intent.succeeded``, ``checkout.session.completed``,
   ``invoice.paid``, ``charge.refunded``) with a valid mocked signature
   and returns 2xx. Unhandled event types also return 2xx so Stripe
   doesn't retry.

The signature-verification path is mocked at the ``stripe.Webhook``
level (mirroring the existing Phase 14a test rig) so tests are
hermetic and don't require live Stripe credentials.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server import app


client = TestClient(app)


# ── Route existence guardrails ────────────────────────────────────────
def test_alias_route_returns_signature_error_not_404():
    """Historical short URL must be mounted. Bogus payload without a
    valid Stripe-Signature header should surface as 400 (invalid
    signature), not 404 (route missing) — which was the bug that
    caused Stripe Dashboard's failing-webhook emails."""
    r = client.post(
        "/api/stripe/webhook",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code != 404, (
        "P1-Hotfix-#3 regression: the /api/stripe/webhook legacy alias "
        "route is not mounted. Stripe Dashboard is configured to POST "
        "here and will retry indefinitely with 404 responses."
    )
    assert r.status_code == 400
    body = r.json()
    assert "invalid signature" in body.get("detail", "").lower()


def test_primary_route_returns_signature_error_not_404():
    """The primary URL (``/api/payments/stripe/webhook``) must also
    accept POSTs and produce a signature-error envelope."""
    r = client.post(
        "/api/payments/stripe/webhook",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    body = r.json()
    assert "invalid signature" in body.get("detail", "").lower()


def test_both_routes_share_the_same_handler():
    """Both URLs must produce byte-identical responses for the same
    bogus payload — proving the alias forwards to the same handler."""
    r1 = client.post(
        "/api/stripe/webhook",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    r2 = client.post(
        "/api/payments/stripe/webhook",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert r1.status_code == r2.status_code == 400
    assert r1.json() == r2.json()


# ── Handler accepts common event types (mocked signature) ─────────────
class _FakeWebhook:
    """Stand-in for ``stripe.Webhook`` that skips signature verification
    and returns the parsed JSON as-is."""

    @staticmethod
    def construct_event(payload, sig_header, secret):  # noqa: ARG004
        return json.loads(payload)


@pytest.fixture
def _mock_stripe_webhook(monkeypatch):
    """Patch ``stripe.Webhook`` so the handler accepts any payload
    without a real Stripe HMAC signature. The test-mode webhook
    secret is still required to be present so we set a sentinel."""
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test_dummy_regression_only")
    import stripe
    monkeypatch.setattr(stripe, "Webhook", _FakeWebhook)


@pytest.mark.parametrize("event_type,event_object", [
    ("payment_intent.succeeded",
     {"id": "pi_test_regr_1", "amount_received": 1500, "customer": "cus_test"}),
    ("checkout.session.completed",
     {"id": "cs_test_regr_1", "customer": "cus_test", "payment_intent": "pi_test_regr_1"}),
    ("invoice.paid",
     {"id": "in_test_regr_1", "customer": "cus_test", "amount_paid": 1500}),
    ("charge.refunded",
     {"id": "ch_test_regr_1", "customer": "cus_test", "amount_refunded": 500}),
])
def test_common_event_types_return_2xx(_mock_stripe_webhook, event_type, event_object):
    """Each of the common event types the handler processes must
    return 2xx so Stripe doesn't retry them. Payload verification is
    mocked so we exercise only the routing + dispatch logic."""
    payload = json.dumps({
        "id": f"evt_{event_type.replace('.', '_')}",
        "type": event_type,
        "data": {"object": event_object},
    }).encode()
    r = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": "test-sig"},
    )
    assert 200 <= r.status_code < 300, (
        f"Handler returned {r.status_code} for event type {event_type!r}. "
        f"Stripe will retry non-2xx responses forever. Body: {r.text[:300]}"
    )
    body = r.json()
    assert body.get("ok") is True


def test_unhandled_event_type_still_returns_2xx(_mock_stripe_webhook):
    """The handler must return 2xx for event types it doesn't know
    about — otherwise Stripe retries indefinitely for every unknown
    event. A gracefully-ignored event is still a successful
    delivery from Stripe's perspective."""
    payload = json.dumps({
        "id": "evt_unhandled_test",
        "type": "some.new.event.type.stripe.invented",
        "data": {"object": {"id": "obj_test"}},
    }).encode()
    r = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": "test-sig"},
    )
    assert 200 <= r.status_code < 300, (
        f"Handler returned {r.status_code} for an unknown event type. "
        f"This will cause Stripe to retry indefinitely."
    )
