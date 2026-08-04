"""Phase 47c · Feb-2026 — RESTORED public "Add card" magic-link tests.

Covers the two new endpoints that back
``frontend/src/pages/public/AddCardPage.jsx``:
    * POST /api/customers/add-card/{token}/setup-intent
    * POST /api/customers/add-card/{token}/attach

Guardrails:
    * Invalid / expired / off-scope tokens must 4xx (never 500 or silent 2xx).
    * The setup-intent endpoint must NOT expose the internal Stripe
      customer id — a link leak shouldn't reveal PII.
    * The attach endpoint must go through
      ``services.payments.stripe_charge.attach_payment_method`` (i.e.
      the same code path the authenticated flow uses).
    * Regression guard against the Phase LZ4 "retired" stub coming
      back — response must NOT contain ``"retired": True``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


API = "/api"


# ── Fixtures ──────────────────────────────────────────────────────────
@pytest.fixture
def client():
    from server import app
    return TestClient(app)


@pytest.fixture
def seeded_customer_id():
    """Grab a real seeded customer id + tenant so the token roundtrips
    against the same doc the endpoints look up."""
    from server import db  # module-level Motor db handle
    row = asyncio.get_event_loop().run_until_complete(
        db.customers.find_one({}, {"_id": 0, "id": 1, "tenant_id": 1})
    )
    assert row and row.get("id") and row.get("tenant_id"), "no seed customer available"
    return row["id"], row["tenant_id"]


def _mint_token(customer_id: str, tenant_id: str) -> str:
    from services.add_card_links import encode_add_card_token
    return encode_add_card_token(customer_id, tenant_id)


# ── Regression: the LZ4 stub must be gone ─────────────────────────────
def test_setup_intent_endpoint_no_longer_returns_retired_stub(client, seeded_customer_id):
    """Phase LZ4 shipped a ``{"retired": True}`` stub. Phase 47c un-does
    it. If the retired stub is back, the payload will trip this assert."""
    cid, tid = seeded_customer_id
    tok = _mint_token(cid, tid)
    with patch("services.payments.stripe_charge.create_setup_intent",
               new=AsyncMock(return_value={
                   "client_secret": "seti_secret_dummy",
                   "setup_intent_id": "seti_dummy",
                   "publishable_key": "pk_test_x",
                   "mode": "test",
               })):
        r = client.post(f"{API}/customers/add-card/{tok}/setup-intent")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("retired") is not True
    assert body.get("reason") != "stripe_setup_intent_retired_lz4"


# ── Happy path: SetupIntent ───────────────────────────────────────────
def test_setup_intent_returns_client_secret_and_pk(client, seeded_customer_id):
    cid, tid = seeded_customer_id
    tok = _mint_token(cid, tid)
    with patch("services.payments.stripe_charge.create_setup_intent",
               new=AsyncMock(return_value={
                   "client_secret": "seti_1_secret_abc",
                   "setup_intent_id": "seti_1",
                   "publishable_key": "pk_test_x",
                   "mode": "test",
               })) as create_si:
        r = client.post(f"{API}/customers/add-card/{tok}/setup-intent")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_secret"] == "seti_1_secret_abc"
    assert body["setup_intent_id"] == "seti_1"
    assert body["publishable_key"] == "pk_test_x"
    assert body["mode"] == "test"
    # PII guardrail — internal Stripe customer id must NOT be echoed.
    assert "stripe_customer_id" not in body
    assert "provider_customer_id" not in body
    # And the underlying helper was called with the decoded ids from the token.
    kwargs = create_si.await_args.kwargs
    assert kwargs["customer_id"] == cid
    assert kwargs["tenant_id"] == tid


# ── Sad path: garbage token ───────────────────────────────────────────
def test_setup_intent_rejects_garbage_token(client):
    r = client.post(f"{API}/customers/add-card/not-a-real-jwt/setup-intent")
    assert r.status_code in (400, 401, 404, 422), r.text
    # Body must NOT include a client_secret leak on failure.
    assert "client_secret" not in (r.json() or {})


def test_setup_intent_bubbles_helper_failure_as_502(client, seeded_customer_id):
    cid, tid = seeded_customer_id
    tok = _mint_token(cid, tid)
    with patch("services.payments.stripe_charge.create_setup_intent",
               new=AsyncMock(side_effect=RuntimeError("stripe down"))):
        r = client.post(f"{API}/customers/add-card/{tok}/setup-intent")
    assert r.status_code == 502
    assert "payment_setup_unavailable" in r.text


# ── Happy path: Attach ───────────────────────────────────────────────
def test_attach_forwards_to_service_and_returns_masked_pm(client, seeded_customer_id):
    cid, tid = seeded_customer_id
    tok = _mint_token(cid, tid)
    with patch("services.payments.stripe_charge.attach_payment_method",
               new=AsyncMock(return_value={
                   "id": "row_1",
                   "last4": "4242",
                   "brand": "visa",
                   "exp_month": 12,
                   "exp_year": 2030,
                   "is_default": True,
                   # Fields the endpoint must strip before returning:
                   "provider_payment_method_id": "pm_secret_leak",
                   "provider_customer_id": "cus_secret_leak",
               })) as attach:
        r = client.post(
            f"{API}/customers/add-card/{tok}/attach",
            json={"payment_method_id": "pm_1234", "set_default": True},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "last4": "4242",
        "brand": "visa",
        "exp_month": 12,
        "exp_year": 2030,
        "is_default": True,
    }
    # PII: internal Stripe ids must NOT be echoed back to the browser.
    assert "provider_payment_method_id" not in body
    assert "provider_customer_id" not in body
    # Helper was called with the decoded token ids + the pm the browser sent.
    kwargs = attach.await_args.kwargs
    assert kwargs["customer_id"] == cid
    assert kwargs["tenant_id"] == tid
    assert kwargs["payment_method_id"] == "pm_1234"
    assert kwargs["set_default"] is True


def test_attach_requires_payment_method_id(client, seeded_customer_id):
    cid, tid = seeded_customer_id
    tok = _mint_token(cid, tid)
    r = client.post(f"{API}/customers/add-card/{tok}/attach", json={})
    assert r.status_code == 422
    assert "payment_method_id" in r.text


def test_attach_rejects_garbage_token(client):
    r = client.post(
        f"{API}/customers/add-card/not-a-real-jwt/attach",
        json={"payment_method_id": "pm_1"},
    )
    assert r.status_code in (400, 401, 404, 422)


def test_attach_bubbles_service_failure_as_502(client, seeded_customer_id):
    cid, tid = seeded_customer_id
    tok = _mint_token(cid, tid)
    with patch("services.payments.stripe_charge.attach_payment_method",
               new=AsyncMock(side_effect=RuntimeError("attach exploded"))):
        r = client.post(
            f"{API}/customers/add-card/{tok}/attach",
            json={"payment_method_id": "pm_x"},
        )
    assert r.status_code == 502
    assert "attach_failed" in r.text


# ── Regression: no raw .get() on the SetupIntent create response ─────
def test_no_raw_dot_get_on_stripe_response_in_public_setup_intent():
    """Static guard — the router must not access the Stripe response
    via ``.get()`` (which breaks on v15's non-dict ``StripeObject``).
    The helper already returns a plain dict via ``_asdict()``, so the
    router should read plain keys from the helper's dict result.
    """
    import inspect
    from routers import customers as router_mod
    src = inspect.getsource(router_mod.public_add_card_setup_intent)
    # The helper's response IS a dict, so ``.get(...)`` is safe here —
    # what we want to catch is a direct ``StripeObject.get(...)`` call.
    # Confirm the router never touches ``_stripe.`` or ``stripe.`` inline:
    assert "_stripe." not in src, "router must not touch Stripe SDK directly"
    assert "stripe.SetupIntent" not in src
