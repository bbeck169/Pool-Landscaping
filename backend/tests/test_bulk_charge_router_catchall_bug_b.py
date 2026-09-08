"""Bug B · Feb-2026 — Router-level catch-all wrapper for the bulk-charge
endpoints.

Pins the contract that when the ``execute_bulk_charge*`` core raises an
uncaught, non-``HTTPException`` exception (e.g. a Mongo timeout, a
downstream service crash, or a bare ``raise`` from the DuplicateKey
replay path), the router MUST convert it into a structured
``HTTPException(status_code=500, detail=<message>)`` so the FE sees a
usable ``{"detail": "..."}`` JSON body instead of Starlette's default
plaintext ``Internal Server Error``.

Without this wrapper the FE surfaced ``{}`` in the Bulk Charge modal
error card because ``res.json()`` failed on the plaintext body.  The FE
UX fix now falls back to raw text, but this backend guarantee is what
turns any subsequent unhandled failure into a diagnosable error string
for both the modal AND the ops logs (``logger.exception``).

Scope: NARROW.  These tests call the two router handler coroutines
DIRECTLY — no TestClient, no event-loop juggling — so they compose
cleanly with the sibling K38/14b/P0 suites that use their own
module-level loops.  They only prove the wrapper's shape.  They do NOT
touch Stripe capability config, ACH routing, retry logic, or webhook
behaviour.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from routers import invoices_bulk_charge as bulk_mod


def _run(coro):
    # Local, single-shot loop — no module-level state to pollute.
    return asyncio.new_event_loop().run_until_complete(coro)


def _body():
    return bulk_mod.BulkChargeBody(
        invoice_ids=["INV-2026-000010"],
        dry_run=True,
        idempotency_key="bugb-test-key-1",
    )


def _user():
    return {"id": "u-admin", "role": "admin", "email": "admin@x.com"}


def _tenant():
    return {"id": "t-bugb-1"}


# ─────────────────────────────────────────────────────────────────────
# ACH endpoint — downstream raise surfaces as structured 500
# ─────────────────────────────────────────────────────────────────────
def test_bulk_ach_wraps_runtime_error_as_structured_500(monkeypatch):
    async def _boom(*a, **kw):
        raise RuntimeError(
            "Stripe: us_bank_account_ach_payments capability inactive"
        )
    monkeypatch.setattr(bulk_mod, "execute_bulk_charge_ach", _boom)

    with pytest.raises(HTTPException) as ei:
        _run(bulk_mod.bulk_charge_ach_on_file(
            body=_body(), user=_user(), tenant=_tenant(),
        ))
    assert ei.value.status_code == 500
    # detail is a plain string — FastAPI serialises this as
    # ``{"detail": "..."}`` JSON, which is exactly what the FE needs.
    assert isinstance(ei.value.detail, str)
    assert "us_bank_account_ach_payments capability inactive" in ei.value.detail


def test_bulk_ach_wraps_mongo_timeout_as_structured_500(monkeypatch):
    class _MongoTimeoutError(Exception):
        pass

    async def _boom(*a, **kw):
        raise _MongoTimeoutError("operation timed out after 30000ms")
    monkeypatch.setattr(bulk_mod, "execute_bulk_charge_ach", _boom)

    with pytest.raises(HTTPException) as ei:
        _run(bulk_mod.bulk_charge_ach_on_file(
            body=_body(), user=_user(), tenant=_tenant(),
        ))
    assert ei.value.status_code == 500
    assert ei.value.detail == "operation timed out after 30000ms"


def test_bulk_ach_wraps_bare_exception_repr_when_str_empty(monkeypatch):
    """A bare ``Exception()`` with no message must still surface a
    non-empty detail (repr fallback) — never an empty string."""
    async def _boom(*a, **kw):
        raise Exception()
    monkeypatch.setattr(bulk_mod, "execute_bulk_charge_ach", _boom)

    with pytest.raises(HTTPException) as ei:
        _run(bulk_mod.bulk_charge_ach_on_file(
            body=_body(), user=_user(), tenant=_tenant(),
        ))
    assert ei.value.status_code == 500
    assert isinstance(ei.value.detail, str)
    assert ei.value.detail != ""
    assert ei.value.detail != "{}"


# ─────────────────────────────────────────────────────────────────────
# Card endpoint — parallel guarantee for the twin surface
# ─────────────────────────────────────────────────────────────────────
def test_bulk_card_wraps_runtime_error_as_structured_500(monkeypatch):
    async def _boom(*a, **kw):
        raise RuntimeError("stripe.error.APIConnectionError: timeout")
    monkeypatch.setattr(bulk_mod, "execute_bulk_charge", _boom)

    with pytest.raises(HTTPException) as ei:
        _run(bulk_mod.bulk_charge_card_on_file(
            body=_body(), user=_user(), tenant=_tenant(),
        ))
    assert ei.value.status_code == 500
    assert "stripe.error.APIConnectionError: timeout" in ei.value.detail


# ─────────────────────────────────────────────────────────────────────
# Regression guard — HTTPException from inside the core must pass
# through UNTOUCHED (preserving status codes like 403/404/409/422).
# ─────────────────────────────────────────────────────────────────────
def test_bulk_ach_httpexception_from_core_passes_through(monkeypatch):
    async def _boom(*a, **kw):
        raise HTTPException(status_code=409, detail="idempotency mismatch")
    monkeypatch.setattr(bulk_mod, "execute_bulk_charge_ach", _boom)

    with pytest.raises(HTTPException) as ei:
        _run(bulk_mod.bulk_charge_ach_on_file(
            body=_body(), user=_user(), tenant=_tenant(),
        ))
    # MUST NOT be re-wrapped to 500 — the original 409 + detail survives.
    assert ei.value.status_code == 409
    assert ei.value.detail == "idempotency mismatch"


def test_bulk_card_httpexception_from_core_passes_through(monkeypatch):
    async def _boom(*a, **kw):
        raise HTTPException(status_code=404, detail="run not found")
    monkeypatch.setattr(bulk_mod, "execute_bulk_charge", _boom)

    with pytest.raises(HTTPException) as ei:
        _run(bulk_mod.bulk_charge_card_on_file(
            body=_body(), user=_user(), tenant=_tenant(),
        ))
    assert ei.value.status_code == 404
    assert ei.value.detail == "run not found"
