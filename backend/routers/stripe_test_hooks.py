"""Phase 47c-hooks · Feb-2026 — Stripe test-hook endpoints.

Restores the ``_phase4b_*`` in-process SDK stubs + a compact
``/stripe/health`` endpoint that the legacy Phase 4b / Phase 5a test
suites depend on. Registered by ``server.py`` **only** when the
pod-wide ``ALLOW_TEST_HOOKS=1`` env flag is set (mirroring the pattern
used by ``routers.workforce``, ``routers.dunning``,
``routers.ringcentral_jwt`` and ``routers.quickbooks_cleanup``).

Endpoints
---------
* ``POST /api/dev/_phase4b_stub_stripe``          — swaps the module-
  level ``services.payments.stripe_charge._stripe`` reference for the
  in-process ``_FakeStripe`` singleton (via ``set_stripe_client``).
  Returns ``{"ok": true, "installed": true, "mode": "<current>"}``.
* ``POST /api/dev/_phase4b_unstub_stripe``        — restores the real
  ``stripe`` SDK. Returns ``{"ok": true, "installed": false}``.
* ``POST /api/dev/_phase4b_stub_account_ok``      — flips the fake
  into "ok" mode (``Account.retrieve()`` returns a healthy account).
* ``POST /api/dev/_phase4b_stub_account_raise``   — flips the fake
  into "raise" mode (``Account.retrieve()`` raises
  ``stripe.error.AuthenticationError`` with a masked message).
* ``POST /api/dev/_phase4b_env_set`` (body: ``{key, value}``) — sets
  ``os.environ[key]=value`` inside the backend process. Used by
  tests that need to toggle ``STRIPE_MODE`` mid-suite.
* ``GET  /api/stripe/health``                     — returns
  ``{ok, mode, checked_at}``. Intentionally minimal per the Phase 47c
  guardrail ("do not touch runtime Stripe code beyond the two hook
  endpoints"). The richer legacy shape used by decommissioned
  ``test_phase53_stripe.py`` is NOT restored — those tests move to
  Phase 47c-B for deletion.

Security posture
----------------
* Router is **only imported + mounted** when ``ALLOW_TEST_HOOKS=1``.
  ``server.py``'s Phase 3-2 hotfix already forces the flag to ``0``
  when ``APP_ENV=production``, so production builds never expose any
  of these endpoints even if the .env slips.
* Endpoints do NOT accept any Stripe secret in the body; they only
  toggle the in-process stub. Nothing sensitive leaves the pod.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from services.payments import stripe_charge as _stripe_svc

router = APIRouter(tags=["stripe-test-hooks"])


# ═══════════════════════════════════════════════════════════════════
# In-process fake Stripe SDK
# ═══════════════════════════════════════════════════════════════════
class _FakeAuthError(Exception):
    """Mimic ``stripe.error.AuthenticationError`` — kept minimal so
    the runtime import of the real ``stripe`` SDK is not required
    inside the hooks router. The v15 SDK exposes the class at
    ``stripe.error.AuthenticationError`` (str subclass isn't needed —
    the ``live-ping`` handler inspects ``type(exc).__name__``)."""

    pass


class _FakeErrorNamespace:
    """``stripe.error`` shim so ``except stripe.error.AuthenticationError``
    keeps working when the fake is installed."""

    AuthenticationError = _FakeAuthError
    StripeError = Exception


class _FakeAccount:
    """``stripe.Account.retrieve()`` shim. Toggled between "ok" and
    "raise" modes by the ``_phase4b_stub_account_*`` endpoints."""

    _mode: str = "ok"  # "ok" | "raise"

    @classmethod
    def retrieve(cls, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        if cls._mode == "raise":
            # Mask the sk_live_ prefix per the Phase 5a live-ping
            # test — the assertion checks that neither the response
            # body nor the error message echoes secret prefixes.
            raise _FakeAuthError("Invalid API Key provided: (masked)")
        return {
            "id": "acct_test_phase4b_ok",
            "country": "US",
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
            "default_currency": "usd",
        }


class _FakePaymentIntent:
    _outer: Any = None

    @classmethod
    def create(cls, **kwargs: Any) -> Dict[str, Any]:
        import uuid as _uuid
        return {
            "id": f"pi_test_{_uuid.uuid4().hex[:10]}",
            "client_secret": f"pi_test_{_uuid.uuid4().hex[:10]}_secret_x",
            "status": kwargs.get("status", "requires_payment_method"),
            "amount": kwargs.get("amount"),
            "currency": kwargs.get("currency"),
        }


class _FakeRefund:
    @classmethod
    def create(cls, **kwargs: Any) -> Dict[str, Any]:
        import uuid as _uuid
        return {
            "id": f"re_test_{_uuid.uuid4().hex[:10]}",
            "amount": kwargs.get("amount"),
            "status": "succeeded",
            "payment_intent": kwargs.get("payment_intent"),
        }


class _FakeWebhook:
    @classmethod
    def construct_event(cls, payload: bytes, sig: str, secret: str) -> Dict[str, Any]:
        # Signature policy: accept "GOODSIG", reject anything else so
        # the legacy Phase 4b webhook tests can assert both branches
        # (bad-sig 400, missing-sig 400, good-sig 200).
        if sig != "GOODSIG":
            raise _FakeAuthError("Invalid signature")
        import json as _json
        try:
            return _json.loads(payload.decode() if isinstance(payload, (bytes, bytearray)) else payload)
        except Exception as exc:
            raise _FakeAuthError(f"malformed payload: {exc}") from exc


# Feb-2026 · Stripe reconcile-endpoint hardening — the new
# ``POST /payments/stripe/session/{sid}/reconcile`` handler calls
# ``stripe.checkout.Session.retrieve``. To exercise it end-to-end
# without a live Stripe API key, we queue a next-payload dict here
# and return it on the next ``retrieve()`` call. Tests that don't
# queue anything get ``ValueError`` — that surfaces the misconfig
# instead of a silent None.
class _FakeCheckoutSession:
    _next_payload: Any = None            # dict or None
    _retrieve_calls: list = []           # for idempotency assertions

    @classmethod
    def retrieve(cls, session_id: str, expand=None, **kwargs):
        cls._retrieve_calls.append(
            {"session_id": session_id, "expand": expand},
        )
        if cls._next_payload is None:
            raise _FakeAuthError(
                "no next session payload queued — call "
                "POST /dev/_stub_checkout_session_next first",
            )
        # Deep-copy so a test can't accidentally mutate the queued
        # dict via a prior call's return value.
        import copy as _copy
        return _copy.deepcopy(cls._next_payload)


class _FakeCheckout:
    Session = _FakeCheckoutSession


class _FakeStripe:
    """Aggregate fake exposing the surface the Phase 4b tests probe
    (``Account``, ``PaymentIntent``, ``Refund``, ``Webhook``, ``error``)
    plus, since Feb-2026, ``checkout.Session`` for the reconcile ship.

    The instance is stateless besides the module-level ``_FakeAccount._mode``
    toggle + ``_FakeCheckoutSession._next_payload`` queue; each
    classmethod builds a fresh dict per call."""

    api_key: str = ""
    error = _FakeErrorNamespace
    Account = _FakeAccount
    PaymentIntent = _FakePaymentIntent
    Refund = _FakeRefund
    Webhook = _FakeWebhook
    checkout = _FakeCheckout


_FAKE_SINGLETON = _FakeStripe()


# ═══════════════════════════════════════════════════════════════════
# Guard — every endpoint below is only reachable when the router is
# mounted (server.py checks ``ALLOW_TEST_HOOKS=1``). A second, cheap
# runtime guard is kept in case a stale process retains the router
# after the env flips.
# ═══════════════════════════════════════════════════════════════════
def _require_flag() -> None:
    if os.environ.get("ALLOW_TEST_HOOKS") != "1":
        raise HTTPException(status_code=404, detail={"error": "not_found"})


# ═══════════════════════════════════════════════════════════════════
# 1. /api/dev/_phase4b_stub_stripe (+ un-stub)
# ═══════════════════════════════════════════════════════════════════
@router.post("/dev/_phase4b_stub_stripe")
async def phase4b_stub_stripe() -> Dict[str, Any]:
    _require_flag()
    _FakeAccount._mode = "ok"
    _stripe_svc.set_stripe_client(_FAKE_SINGLETON)
    return {"ok": True, "installed": True, "mode": _FakeAccount._mode}


@router.post("/dev/_phase4b_unstub_stripe")
async def phase4b_unstub_stripe() -> Dict[str, Any]:
    _require_flag()
    _stripe_svc.set_stripe_client(None)
    _FakeAccount._mode = "ok"
    # Feb-2026 · Also clear the session-queue so a stale payload
    # doesn't leak into a subsequent stubbed test-run.
    _FakeCheckoutSession._next_payload = None
    _FakeCheckoutSession._retrieve_calls = []
    return {"ok": True, "installed": False}


# ═══════════════════════════════════════════════════════════════════
# 1b. /api/dev/_stub_checkout_session_next  (Feb-2026)
#      Queue the next payload that ``checkout.Session.retrieve`` will
#      return. Body is the raw Session dict — must include ``id``,
#      ``payment_status``, ``amount_total``, ``metadata``, and
#      ``payment_intent`` for the reconcile endpoint to succeed.
# ═══════════════════════════════════════════════════════════════════
@router.post("/dev/_stub_checkout_session_next")
async def stub_checkout_session_next(
    body: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    _require_flag()
    if not body or not body.get("id"):
        raise HTTPException(422, {"error": "missing_session_id"})
    _FakeCheckoutSession._next_payload = body
    return {"ok": True, "queued_session_id": body["id"]}


@router.post("/dev/_stub_checkout_session_reset")
async def stub_checkout_session_reset() -> Dict[str, Any]:
    _require_flag()
    calls = list(_FakeCheckoutSession._retrieve_calls)
    _FakeCheckoutSession._next_payload = None
    _FakeCheckoutSession._retrieve_calls = []
    return {"ok": True, "retrieve_calls": calls}


# ═══════════════════════════════════════════════════════════════════
# 2. /api/dev/_phase4b_stub_account_{ok,raise}
# ═══════════════════════════════════════════════════════════════════
@router.post("/dev/_phase4b_stub_account_ok")
async def phase4b_stub_account_ok() -> Dict[str, Any]:
    _require_flag()
    _FakeAccount._mode = "ok"
    return {"ok": True, "account_mode": "ok"}


@router.post("/dev/_phase4b_stub_account_raise")
async def phase4b_stub_account_raise() -> Dict[str, Any]:
    _require_flag()
    _FakeAccount._mode = "raise"
    return {"ok": True, "account_mode": "raise"}


# ═══════════════════════════════════════════════════════════════════
# 3. /api/dev/_phase4b_env_set
# ═══════════════════════════════════════════════════════════════════
@router.post("/dev/_phase4b_env_set")
async def phase4b_env_set(
    body: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    _require_flag()
    key = (body.get("key") or "").strip()
    if not key:
        raise HTTPException(422, {"error": "missing_key"})
    val = body.get("value")
    if val is None:
        os.environ.pop(key, None)
        return {"ok": True, "key": key, "cleared": True}
    os.environ[key] = str(val)
    return {"ok": True, "key": key, "value": str(val)}


# ═══════════════════════════════════════════════════════════════════
# 4. GET /api/stripe/health
# ═══════════════════════════════════════════════════════════════════
@router.get("/stripe/health")
async def stripe_health() -> Dict[str, Any]:
    """Compact Stripe health probe. Returns the minimum surface the
    Phase 47c brief asked for — ``{ok, mode, checked_at}``. The
    richer legacy shape (``configured``, ``key_authenticates``, ...)
    used by decommissioned test suites is intentionally NOT restored.

    Gated by ``ALLOW_TEST_HOOKS=1`` at both mount time (server.py) and
    at request time (belt-and-braces)."""
    _require_flag()
    mode = "live" if (
        (os.environ.get("STRIPE_MODE") or "").strip().lower() == "live"
    ) else "test"
    return {
        "ok": True,
        "mode": mode,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
