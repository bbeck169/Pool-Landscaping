"""Feb-2026 P0 · Belt-and-braces error mapping in
``POST /api/invoices/{invoice_id}/request-payment-link``.

The endpoint (``backend/routers/lumino_link_request.py``) used to
let ``_UnconfiguredStripeError`` bubble as a plain 500 and
``ValueError("APP_PUBLIC_URL not configured")`` bubble as a plain
400 with an unmapped detail — both showed up on the frontend as the
generic "Something went wrong preparing your payment link" copy.

Contract under test:
* Any config-time failure (missing Stripe key, missing
  APP_PUBLIC_URL) → HTTP 502 with ``detail=="payment_gateway_unavailable"``
  which ``PaymentForm.friendlyFor`` maps to the friendly gateway-
  outage message.
* ``invoice_already_paid`` still surfaces as 409 (unchanged).
* Happy path still returns ``payment_url``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _warm_backend() -> None:
    import time
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/config/public", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


_warm_backend()


def _login(email: str) -> str:
    for _ in range(4):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": demo_pw(email)},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["access_token"]
        except (requests.exceptions.ReadTimeout,
                 requests.exceptions.ConnectionError):
            pass
    raise AssertionError(f"login failed for {email}")


def test_happy_path_returns_payment_url():
    """Sanity — a real invoice + configured env returns a
    Stripe Checkout URL. Guards against a regression in the newly-
    added ``except`` branches accidentally swallowing the happy
    path."""
    tok = _login("super@aquaterra.com")
    # Pick any existing invoice via /quotes?doc_type=invoice.
    r = requests.get(f"{API}/quotes?doc_type=invoice&limit=1",
                      headers={"Authorization": f"Bearer {tok}"},
                      timeout=15)
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    assert items, "no invoices present to test against"
    inv = items[0]

    r2 = requests.post(
        f"{API}/invoices/{inv['id']}/request-payment-link",
        json={},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=30,
    )
    if r2.status_code == 409:
        # Invoice happened to be already paid — the mapped 409 is a
        # correct outcome for this contract; skip rather than fail.
        pytest.skip("first invoice was already paid — happy-path skipped")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["payment_url"].startswith("https://checkout.stripe.com/")
    assert body["mode"] in ("test", "live")


def test_unconfigured_stripe_error_maps_to_502_gateway_unavailable():
    """Patch ``stripe_charge.create_invoice_checkout_session`` to
    raise ``_UnconfiguredStripeError`` — endpoint MUST return
    HTTP 502 + ``payment_gateway_unavailable`` so the frontend
    renders the mapped friendly message instead of the generic one.

    We drive the endpoint function IN-PROCESS (no HTTP round-trip)
    because monkeypatching a running uvicorn is a hassle and the
    error-mapping contract lives entirely in the endpoint's local
    try/except."""
    from routers.lumino_link_request import request_payment_link
    from services.payments import stripe_charge

    # Stub the invoice lookup + customer lookup so we get past the
    # early return branches and land inside the try/except.
    fake_invoice = {"id": "inv-x", "tenant_id": "t-x",
                    "customer_id": "c-x", "total": 10.0,
                    "amount_paid": 0.0}
    fake_customer = {"id": "c-x", "email": "x@example.com"}

    async def _fake_lookup(_invoice_id):
        return fake_invoice

    async def _fake_find_one(*args, **kwargs):
        return fake_customer

    async def _raise_unconfigured(*_args, **_kwargs):
        raise stripe_charge._UnconfiguredStripeError(
            "No Stripe secret key configured.")

    user = {"id": "u-1", "role": "admin"}

    from fastapi import HTTPException

    with patch("routers.lumino_link_request._lookup_invoice", _fake_lookup):
        with patch("routers.lumino_link_request.db") as fake_db:
            fake_db.customers.find_one = _fake_find_one
            with patch.object(
                stripe_charge, "create_invoice_checkout_session",
                _raise_unconfigured,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    asyncio.get_event_loop().run_until_complete(
                        request_payment_link(
                            invoice_id=f"inv-x-{uuid.uuid4().hex[:6]}",
                            user=user,
                        )
                    )
                assert exc_info.value.status_code == 502
                assert exc_info.value.detail == "payment_gateway_unavailable"


def test_app_public_url_unset_maps_to_502_gateway_unavailable():
    """Same coverage but for the ``ValueError("APP_PUBLIC_URL not
    configured")`` branch: config-time failures collapse onto the
    single well-known ``payment_gateway_unavailable`` code."""
    from routers.lumino_link_request import request_payment_link
    from services.payments import stripe_charge

    fake_invoice = {"id": "inv-x", "tenant_id": "t-x",
                    "customer_id": "c-x", "total": 10.0}
    fake_customer = {"id": "c-x", "email": "x@example.com"}

    async def _fake_lookup(_invoice_id):
        return fake_invoice

    async def _fake_find_one(*args, **kwargs):
        return fake_customer

    async def _raise_no_url(*_args, **_kwargs):
        raise ValueError("APP_PUBLIC_URL not configured")

    from fastapi import HTTPException
    user = {"id": "u-1", "role": "admin"}

    with patch("routers.lumino_link_request._lookup_invoice", _fake_lookup):
        with patch("routers.lumino_link_request.db") as fake_db:
            fake_db.customers.find_one = _fake_find_one
            with patch.object(
                stripe_charge, "create_invoice_checkout_session",
                _raise_no_url,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    asyncio.get_event_loop().run_until_complete(
                        request_payment_link(
                            invoice_id=f"inv-x-{uuid.uuid4().hex[:6]}",
                            user=user,
                        )
                    )
                assert exc_info.value.status_code == 502
                assert exc_info.value.detail == "payment_gateway_unavailable"


def test_invoice_already_paid_still_maps_to_409():
    """Regression guard — the widened ValueError handler must NOT
    swallow the ``invoice_already_paid`` sub-case, which was and
    still is a mapped 409 (business logic, not gateway issue)."""
    from routers.lumino_link_request import request_payment_link
    from services.payments import stripe_charge

    fake_invoice = {"id": "inv-x", "tenant_id": "t-x",
                    "customer_id": "c-x", "total": 10.0,
                    "amount_paid": 10.0}
    fake_customer = {"id": "c-x", "email": "x@example.com"}

    async def _fake_lookup(_invoice_id):
        return fake_invoice

    async def _fake_find_one(*args, **kwargs):
        return fake_customer

    async def _raise_already_paid(*_args, **_kwargs):
        raise ValueError("invoice_already_paid")

    from fastapi import HTTPException
    user = {"id": "u-1", "role": "admin"}

    with patch("routers.lumino_link_request._lookup_invoice", _fake_lookup):
        with patch("routers.lumino_link_request.db") as fake_db:
            fake_db.customers.find_one = _fake_find_one
            with patch.object(
                stripe_charge, "create_invoice_checkout_session",
                _raise_already_paid,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    asyncio.get_event_loop().run_until_complete(
                        request_payment_link(
                            invoice_id=f"inv-x-{uuid.uuid4().hex[:6]}",
                            user=user,
                        )
                    )
                assert exc_info.value.status_code == 409
                assert exc_info.value.detail == "invoice_already_paid"
