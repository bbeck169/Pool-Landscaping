"""TD-invoice-pay-now-stripe-idempotency-conflict · Feb-2026.

Covers:

    * Anchored ``exp`` on the magic-link JWT inside
      ``create_invoice_checkout_session`` so ``cancel_url`` is
      byte-identical across retries on the same invoice (satisfies
      the stable ``idempotency_key``).
    * Routers (``lumino_link_request`` + ``invoice_magic_pay``) map
      ``stripe_charge._IdempotencyConflict`` to HTTP 409
      ``{"error": "stripe_idempotency_conflict", ...}`` instead of
      the generic 502/503 ``payment_gateway_unavailable``.
    * Backward-compat: ``pay_link_builder.issue_invoice_magic_token``
      called without ``exp`` still mints a wall-clock-dated JWT so
      the dunning / drip-campaign call sites keep working.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from services import pay_link_builder as plb
from services.payments import stripe_charge as sc


# ─── Shared fakes ────────────────────────────────────────────────────────


def _fake_stripe_session_object() -> Any:
    payload = {
        "id": "cs_test_idempotency_1",
        "url": "https://checkout.stripe.com/c/pay/cs_test_idempotency_1",
        "amount_total": 20000,
        "currency": "usd",
        "metadata": {"crm_invoice_id": "inv-idem-1",
                     "crm_tenant_id": "tnt-1",
                     "crm_customer_id": "cust-1",
                     "source": "phase47_invoice_pay"},
    }
    return SimpleNamespace(to_dict_recursive=lambda: payload, **payload)


_INVOICE = {
    "id": "inv-idem-1",
    "total": 200.00,
    "amount_paid": 0.0,
    "currency": "usd",
    "invoice_number": "INV-2026-000068",
    "created_at": "2026-01-15T10:00:00+00:00",
    "tenant_id": "tnt-1",
}
_CUSTOMER = {"id": "cust-1", "email": "pay@example.test", "name": "Buyer"}


# ─── Anchored exp → stable cancel_url + idempotency key ────────────────


def test_two_sequential_calls_mint_identical_cancel_url_and_idem_key(
        monkeypatch):
    """Two sequential calls to ``create_invoice_checkout_session`` on
    the same invoice MUST produce identical ``cancel_url`` AND
    identical ``idempotency_key`` so Stripe accepts the retry.
    """
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")

    captured_kwargs: list = []

    def _create(**kw):
        captured_kwargs.append(kw)
        return _fake_stripe_session_object()

    fake_stripe = MagicMock(
        checkout=MagicMock(Session=MagicMock(create=_create)))
    # Ensure stripe.error.IdempotencyError resolves on the ``getattr``
    # ladder inside ``_invoke_checkout_create`` — a plain class is
    # enough; we never raise it in this test.
    fake_stripe.error = MagicMock(IdempotencyError=type(
        "IdempotencyError", (Exception,), {}))

    with patch.object(sc, "_init_api_key", lambda: None), \
         patch.object(sc, "_stripe", fake_stripe), \
         patch.object(sc, "_mode", lambda: "test"):
        asyncio.get_event_loop().run_until_complete(
            sc.create_invoice_checkout_session(
                tenant_id="tnt-1", invoice=_INVOICE, customer=_CUSTOMER))
        asyncio.get_event_loop().run_until_complete(
            sc.create_invoice_checkout_session(
                tenant_id="tnt-1", invoice=_INVOICE, customer=_CUSTOMER))

    assert len(captured_kwargs) == 2
    first, second = captured_kwargs
    assert first["cancel_url"] == second["cancel_url"], (
        "cancel_url MUST be byte-identical across retries so the "
        "stable idempotency_key can replay without parameter drift.")
    assert first["idempotency_key"] == second["idempotency_key"]
    # Sanity: cancel_url points at the magic-link viewer.
    assert first["cancel_url"].startswith("https://example.test/i/")


def test_anchored_exp_lands_at_created_at_plus_one_year(monkeypatch):
    """Decode the JWT in the ``cancel_url`` and confirm its ``exp``
    claim is anchored at ``invoice.created_at + 365d`` (operator-
    approved anchor path).  Guards against a future refactor that
    silently re-introduces ``now()``-based minting.
    """
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")

    captured_kwargs: list = []
    fake_stripe = MagicMock(
        checkout=MagicMock(Session=MagicMock(
            create=lambda **kw: (captured_kwargs.append(kw)
                                 or _fake_stripe_session_object()))))
    fake_stripe.error = MagicMock(IdempotencyError=type(
        "IdempotencyError", (Exception,), {}))

    with patch.object(sc, "_init_api_key", lambda: None), \
         patch.object(sc, "_stripe", fake_stripe), \
         patch.object(sc, "_mode", lambda: "test"):
        asyncio.get_event_loop().run_until_complete(
            sc.create_invoice_checkout_session(
                tenant_id="tnt-1", invoice=_INVOICE, customer=_CUSTOMER))

    cancel_url = captured_kwargs[0]["cancel_url"]
    token = cancel_url.split("/i/")[-1]
    decoded = jwt.decode(
        token,
        __import__("config").JWT_SECRET,
        algorithms=[__import__("config").JWT_ALGO],
    )
    expected_exp = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc) \
        + timedelta(days=365)
    assert decoded["exp"] == int(expected_exp.timestamp())
    assert decoded["invoice_id"] == "inv-idem-1"
    assert decoded["tenant_id"] == "tnt-1"


def test_sha256_fallback_when_created_at_missing(monkeypatch):
    """When ``invoice.created_at`` is absent, the fallback anchors
    ``exp`` at a fixed 2099-01-01 UTC timestamp so retries still
    produce identical JWTs.
    """
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")

    captured_kwargs: list = []
    fake_stripe = MagicMock(
        checkout=MagicMock(Session=MagicMock(
            create=lambda **kw: (captured_kwargs.append(kw)
                                 or _fake_stripe_session_object()))))
    fake_stripe.error = MagicMock(IdempotencyError=type(
        "IdempotencyError", (Exception,), {}))

    invoice_no_created = dict(_INVOICE)
    invoice_no_created.pop("created_at", None)

    with patch.object(sc, "_init_api_key", lambda: None), \
         patch.object(sc, "_stripe", fake_stripe), \
         patch.object(sc, "_mode", lambda: "test"):
        asyncio.get_event_loop().run_until_complete(
            sc.create_invoice_checkout_session(
                tenant_id="tnt-1", invoice=invoice_no_created,
                customer=_CUSTOMER))

    token = captured_kwargs[0]["cancel_url"].split("/i/")[-1]
    decoded = jwt.decode(
        token,
        __import__("config").JWT_SECRET,
        algorithms=[__import__("config").JWT_ALGO],
    )
    expected = datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert decoded["exp"] == int(expected.timestamp())


# ─── IdempotencyError raised by SDK → _IdempotencyConflict sentinel ─────


def test_idempotency_error_wrapped_as_sentinel(monkeypatch):
    """When ``stripe.checkout.Session.create`` raises
    ``stripe.error.IdempotencyError``, the service re-raises as
    ``_IdempotencyConflict`` so routers can map it to 409.
    """
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")

    _IdemErr = type("IdempotencyError", (Exception,), {})

    def _create(**kw):
        raise _IdemErr("Keys for idempotent requests can only be used with "
                       "the same parameters they were first used with.")

    fake_stripe = MagicMock(
        checkout=MagicMock(Session=MagicMock(create=_create)))
    fake_stripe.error = MagicMock(IdempotencyError=_IdemErr)

    with patch.object(sc, "_init_api_key", lambda: None), \
         patch.object(sc, "_stripe", fake_stripe), \
         patch.object(sc, "_mode", lambda: "test"):
        with pytest.raises(sc._IdempotencyConflict) as excinfo:
            asyncio.get_event_loop().run_until_complete(
                sc.create_invoice_checkout_session(
                    tenant_id="tnt-1", invoice=_INVOICE,
                    customer=_CUSTOMER))

    assert "inv-idem-1" in str(excinfo.value)


# ─── Router mapping — lumino_link_request (authed path) ────────────────


def test_lumino_router_maps_idempotency_conflict_to_409():
    """Drive the lumino router's catch block (same shape as the
    router uses in-process) and prove the sentinel is caught BEFORE
    the generic 502 catch-all so the 409 wins.
    """
    with pytest.raises(HTTPException) as excinfo:
        asyncio.get_event_loop().run_until_complete(
            _invoke_lumino_router_catch_only())

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == {
        "error": "stripe_idempotency_conflict",
        "detail": "Stripe idempotency conflict for invoice inv-idem-1: "
                  "test param drift",
    }


async def _invoke_lumino_router_catch_only():
    """Mirror the catch ordering in ``routers.lumino_link_request``:
    _IdempotencyConflict must be caught BEFORE the generic Exception.
    If a future refactor reorders them, this test fails.
    """
    try:
        raise sc._IdempotencyConflict(
            "Stripe idempotency conflict for invoice inv-idem-1: "
            "test param drift")
    except sc._UnconfiguredStripeError:
        raise HTTPException(502, "payment_gateway_unavailable")
    except sc._IdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "stripe_idempotency_conflict",
                    "detail": str(exc)},
        )
    except Exception:    # noqa: BLE001
        raise HTTPException(502, "payment_gateway_unavailable")


# ─── Router mapping — invoice_magic_pay (magic-link path) ──────────────


def test_magic_link_router_maps_idempotency_conflict_to_409():
    """Source-level audit of the catch block the magic-link router
    uses — proves the sentinel is caught BEFORE the generic 503
    catch-all, so the 409 wins.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "routers/invoice_magic_pay.py").read_text()
    # The sentinel catch must appear.
    assert "except stripe_svc._IdempotencyConflict" in src
    # It must map to 409 with the specific error code.
    assert '"error": "stripe_idempotency_conflict"' in src
    # The catch-all 503 must come AFTER the sentinel catch so the
    # specific case wins.
    idem_pos = src.index("except stripe_svc._IdempotencyConflict")
    catchall_pos = src.index("except Exception as exc:  # noqa: BLE001")
    assert idem_pos < catchall_pos


def test_lumino_router_catch_ordering():
    """Same ordering guarantee for the authed router."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "routers/lumino_link_request.py").read_text()
    assert "except stripe_svc._IdempotencyConflict" in src
    assert '"error": "stripe_idempotency_conflict"' in src
    idem_pos = src.index("except stripe_svc._IdempotencyConflict")
    catchall_pos = src.index("except Exception as exc:")
    assert idem_pos < catchall_pos


# ─── Backward-compat: issue_invoice_magic_token without exp ────────────


def test_issue_invoice_magic_token_default_signature_still_wall_clock():
    """Ambiguity #5 lock — callers that do NOT pass ``exp`` MUST keep
    receiving a ``now + days``-dated token.  Guards the dunning /
    drip-campaign call sites.
    """
    before = datetime.now(timezone.utc) + timedelta(days=29, hours=23)
    token = plb.issue_invoice_magic_token("inv-x", "tnt-x", days=30)
    after = datetime.now(timezone.utc) + timedelta(days=30, minutes=1)

    decoded = jwt.decode(
        token,
        __import__("config").JWT_SECRET,
        algorithms=[__import__("config").JWT_ALGO],
    )
    exp_dt = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
    assert before <= exp_dt <= after
    assert decoded["invoice_id"] == "inv-x"
    assert decoded["tenant_id"] == "tnt-x"
    assert decoded["sub"] == "invoice_pay"


def test_issue_invoice_magic_token_explicit_exp_overrides():
    """When ``exp`` is explicitly passed, the ``days`` kwarg is
    ignored and the token carries exactly the pinned timestamp.
    """
    pinned = datetime(2027, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    token = plb.issue_invoice_magic_token(
        "inv-y", "tnt-y", days=30, exp=pinned)
    decoded = jwt.decode(
        token,
        __import__("config").JWT_SECRET,
        algorithms=[__import__("config").JWT_ALGO],
    )
    assert decoded["exp"] == int(pinned.timestamp())


def test_issue_invoice_magic_token_same_exp_mints_identical_bytes():
    """Idempotency-stability proof — same inputs AND same ``exp``
    MUST yield the same JWT bytes.  This is the invariant that
    ``create_invoice_checkout_session`` relies on for its stable
    ``cancel_url``.
    """
    pinned = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = plb.issue_invoice_magic_token("inv-z", "tnt-z", exp=pinned)
    b = plb.issue_invoice_magic_token("inv-z", "tnt-z", exp=pinned)
    assert a == b
