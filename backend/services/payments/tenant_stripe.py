"""Phase I1.7.a · Feb-2026 — Stripe Connect Standard provider.

Implements ``TenantPaymentProvider`` on top of Stripe Connect
*Standard* OAuth:

* Each tenant connects their own Stripe account via OAuth. The
  platform never sees the tenant's Stripe secret key — Stripe
  issues an access-token scoped to that account which the tenant
  can revoke at any time.
* All charge / refund / intent calls include the tenant's
  ``stripe_account`` (their connected account ``acct_...``) so
  the money lands in *their* Stripe balance, not the platform's.
* Webhooks are verified with the platform's webhook secret; the
  ``account`` field of the event body is what identifies the
  tenant.

Fallback
--------
When the tenant has no stored Connect account, the provider MAY
fall back to the platform Stripe key (existing pre-I1.7.a
behavior) — this preserves backward compat during the transition
period. Every fallback is written to the
``platform_stripe_fallback_log`` collection for auditing. Toggle
via ``STRIPE_PLATFORM_FALLBACK_ENABLED`` env var (default
``true`` — flip to ``false`` after every legacy customer is
migrated).

Test-mode mock
--------------
When ``STRIPE_TESTMODE_MOCK_CONNECT=true``, the connect-link /
callback flow short-circuits: clicking Connect stores a fake
``acct_test123`` on the tenant so the frontend flow can be
tested without leaving the pod. Charge / refund calls still hit
Stripe *test-mode* real API (with a mock account id, which will
fail loudly if used) — set ``STRIPE_MOCK_CHARGES=true`` to also
stub the charge side to a synthetic ``ch_test_...`` id.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import stripe as _stripe_module

from services.secrets import get_secret
from services.secrets.models import ConnectionType

from .tenant_base import (
    ChargeResult,
    ConnectionHealth,
    PaymentIntent,
    RefundResult,
    TenantNotConnected,
    TenantPaymentError,
    TenantPaymentProvider,
    WebhookEvent,
)


log = logging.getLogger("payments.tenant_stripe")


PROVIDER_KEY = "stripe"
FALLBACK_LOG_COLLECTION = "platform_stripe_fallback_log"


def _platform_secret_key() -> Optional[str]:
    mode = (os.environ.get("STRIPE_MODE") or "test").strip().lower()
    if mode == "live":
        return os.environ.get("STRIPE_SECRET_KEY_LIVE") or None
    return os.environ.get("STRIPE_SECRET_KEY_TEST") or None


def _platform_webhook_secret() -> Optional[str]:
    mode = (os.environ.get("STRIPE_MODE") or "test").strip().lower()
    if mode == "live":
        return os.environ.get("STRIPE_WEBHOOK_SECRET_LIVE") or None
    return os.environ.get("STRIPE_WEBHOOK_SECRET_TEST") or None


def _connect_client_id() -> Optional[str]:
    return os.environ.get("STRIPE_CONNECT_CLIENT_ID") or None


def _fallback_enabled() -> bool:
    return os.environ.get("STRIPE_PLATFORM_FALLBACK_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def _testmode_mock_connect() -> bool:
    return os.environ.get("STRIPE_TESTMODE_MOCK_CONNECT", "").strip().lower() in ("1", "true", "yes")


def _mock_charges() -> bool:
    return os.environ.get("STRIPE_MOCK_CHARGES", "").strip().lower() in ("1", "true", "yes")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_connect_link(state: str, redirect_uri: str) -> str:
    """Build a Stripe Connect Standard OAuth URL. Missing client id
    surfaces as an explicit ``TenantPaymentError`` so the frontend
    can render a "Stripe not yet configured" panel instead of a
    dead redirect."""
    client_id = _connect_client_id()
    if not client_id:
        raise TenantPaymentError(
            "STRIPE_CONNECT_CLIENT_ID is not set — Stripe Connect "
            "is not enabled on this deployment yet."
        )
    query = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "state": state,
        "redirect_uri": redirect_uri,
        "stripe_landing": "login",
    })
    return f"https://connect.stripe.com/oauth/authorize?{query}"


class StripeConnectProvider(TenantPaymentProvider):
    """Concrete tenant provider for Stripe Connect Standard.

    The class is stateless; each call re-reads the tenant's stored
    access token (which is what Stripe's SDK expects as the
    ``api_key`` on Connect-account calls) via ``services.secrets``.
    """

    provider_key = PROVIDER_KEY

    def __init__(self, stripe_client: Any = None, db=None) -> None:
        # Injectable client for tests.
        self._stripe = stripe_client or _stripe_module
        self._db = db  # None → resolve at call time via config.db

    # ── Helpers ──────────────────────────────────────────────────
    def _db_now(self, db=None):
        if db is not None:
            return db
        if self._db is not None:
            return self._db
        from config import db as _db
        return _db

    async def _tenant_access_token(self, tenant_id: str, *, db=None) -> Optional[str]:
        """Return the tenant's Connect access token, or None."""
        # ``get_secret`` returns plaintext — plaintext stays inside
        # this method and is passed as ``api_key=`` to Stripe.
        # NOTE: use explicit ``is not None`` — Motor ``Database``
        # objects raise on ``bool()`` so ``db or self._db`` blows up.
        effective_db = db if db is not None else self._db
        return await get_secret(tenant_id, PROVIDER_KEY, db=effective_db)

    async def _log_fallback(self, *, tenant_id: str, op: str, db=None) -> None:
        try:
            await self._db_now(db)[FALLBACK_LOG_COLLECTION].insert_one({
                "id": uuid.uuid4().hex,
                "tenant_id": tenant_id,
                "op": op,
                "at": _now_iso(),
            })
        except Exception:  # pragma: no cover
            pass

    async def _resolve_auth(self, tenant_id: str, op: str, *, db=None) -> str:
        """Pick the api_key to use: tenant's Connect token if
        available, else the platform key when fallback is
        enabled."""
        tok = await self._tenant_access_token(tenant_id, db=db)
        if tok:
            return tok
        if _fallback_enabled():
            pk = _platform_secret_key()
            if not pk:
                raise TenantPaymentError(
                    "Stripe platform secret key is not configured."
                )
            await self._log_fallback(tenant_id=tenant_id, op=op, db=db)
            return pk
        raise TenantNotConnected(
            f"Tenant {tenant_id} has no Stripe connection and "
            "platform fallback is disabled."
        )

    def _blocking(self, fn, *args, **kwargs):
        """Run a blocking Stripe SDK call off the event loop."""
        return asyncio.to_thread(fn, *args, **kwargs)

    # ── TenantPaymentProvider methods ────────────────────────────
    async def create_charge(
        self, *, tenant_id: str, amount_cents: int, currency: str,
        customer_id: Optional[str] = None,
        payment_method_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> ChargeResult:
        if _mock_charges():
            return ChargeResult(
                id=f"ch_mock_{uuid.uuid4().hex[:12]}",
                status="succeeded",
                amount_cents=amount_cents,
                currency=currency,
                provider_key=PROVIDER_KEY,
                tenant_id=tenant_id,
                raw={"mock": True},
            )
        api_key = await self._resolve_auth(tenant_id, "create_charge")
        kwargs: Dict[str, Any] = {
            "amount": amount_cents,
            "currency": currency,
            "api_key": api_key,
            "confirm": True,
            "off_session": True,
        }
        if customer_id:
            kwargs["customer"] = customer_id
        if payment_method_id:
            kwargs["payment_method"] = payment_method_id
        if description:
            kwargs["description"] = description
        if metadata:
            kwargs["metadata"] = metadata
        if idempotency_key:
            kwargs["idempotency_key"] = idempotency_key
        try:
            resp = await self._blocking(self._stripe.PaymentIntent.create, **kwargs)
            data = resp if isinstance(resp, dict) else resp.to_dict()
            return ChargeResult(
                id=data.get("id", ""),
                status=data.get("status", "unknown"),
                amount_cents=int(data.get("amount", amount_cents)),
                currency=data.get("currency", currency),
                provider_key=PROVIDER_KEY,
                tenant_id=tenant_id,
                raw=data,
            )
        except Exception as e:  # public error message must NOT echo api_key
            log.warning("stripe create_charge failed for tenant=%s: %s",
                         tenant_id, type(e).__name__)
            raise TenantPaymentError(f"create_charge failed: {type(e).__name__}") from e

    async def refund_charge(
        self, *, tenant_id: str, charge_id: str,
        amount_cents: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> RefundResult:
        api_key = await self._resolve_auth(tenant_id, "refund_charge")
        kwargs: Dict[str, Any] = {
            "charge": charge_id,
            "api_key": api_key,
        }
        if amount_cents is not None:
            kwargs["amount"] = amount_cents
        if reason:
            kwargs["reason"] = reason
        if idempotency_key:
            kwargs["idempotency_key"] = idempotency_key
        try:
            resp = await self._blocking(self._stripe.Refund.create, **kwargs)
            data = resp if isinstance(resp, dict) else resp.to_dict()
            return RefundResult(
                id=data.get("id", ""),
                charge_id=charge_id,
                status=data.get("status", "unknown"),
                amount_cents=int(data.get("amount", amount_cents or 0)),
                provider_key=PROVIDER_KEY,
                tenant_id=tenant_id,
                raw=data,
            )
        except Exception as e:
            log.warning("stripe refund_charge failed for tenant=%s: %s",
                         tenant_id, type(e).__name__)
            raise TenantPaymentError(f"refund_charge failed: {type(e).__name__}") from e

    async def get_charge(self, *, tenant_id: str, charge_id: str) -> ChargeResult:
        api_key = await self._resolve_auth(tenant_id, "get_charge")
        try:
            resp = await self._blocking(self._stripe.PaymentIntent.retrieve, charge_id, api_key=api_key)
            data = resp if isinstance(resp, dict) else resp.to_dict()
            return ChargeResult(
                id=data.get("id", charge_id),
                status=data.get("status", "unknown"),
                amount_cents=int(data.get("amount", 0)),
                currency=data.get("currency", ""),
                provider_key=PROVIDER_KEY,
                tenant_id=tenant_id,
                raw=data,
            )
        except Exception as e:
            log.warning("stripe get_charge failed for tenant=%s: %s",
                         tenant_id, type(e).__name__)
            raise TenantPaymentError(f"get_charge failed: {type(e).__name__}") from e

    async def create_payment_intent(
        self, *, tenant_id: str, amount_cents: int, currency: str,
        customer_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentIntent:
        api_key = await self._resolve_auth(tenant_id, "create_payment_intent")
        kwargs: Dict[str, Any] = {
            "amount": amount_cents,
            "currency": currency,
            "api_key": api_key,
            "automatic_payment_methods": {"enabled": True},
        }
        if customer_id:
            kwargs["customer"] = customer_id
        if description:
            kwargs["description"] = description
        if metadata:
            kwargs["metadata"] = metadata
        if idempotency_key:
            kwargs["idempotency_key"] = idempotency_key
        try:
            resp = await self._blocking(self._stripe.PaymentIntent.create, **kwargs)
            data = resp if isinstance(resp, dict) else resp.to_dict()
            return PaymentIntent(
                id=data.get("id", ""),
                client_secret=data.get("client_secret", ""),
                status=data.get("status", "unknown"),
                amount_cents=int(data.get("amount", amount_cents)),
                currency=data.get("currency", currency),
                provider_key=PROVIDER_KEY,
                tenant_id=tenant_id,
                raw=data,
            )
        except Exception as e:
            log.warning("stripe create_payment_intent failed for tenant=%s: %s",
                         tenant_id, type(e).__name__)
            raise TenantPaymentError(
                f"create_payment_intent failed: {type(e).__name__}"
            ) from e

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> WebhookEvent:
        secret = _platform_webhook_secret()
        if not secret:
            raise TenantPaymentError("Stripe webhook secret is not configured.")
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature") or ""
        if not sig:
            raise TenantPaymentError("Missing Stripe-Signature header.")
        try:
            event = self._stripe.Webhook.construct_event(payload, sig, secret)
        except Exception as e:
            log.warning(
                "stripe webhook verify failed: %s (payload_len=%d, sig_head=%s)",
                type(e).__name__, len(payload), sig[:40]
            )
            raise TenantPaymentError(f"webhook verify failed: {type(e).__name__}") from e
        data = event if isinstance(event, dict) else event.to_dict()
        return WebhookEvent(
            id=data.get("id", ""),
            event_type=data.get("type", ""),
            provider_key=PROVIDER_KEY,
            tenant_id=None,  # tenant resolution is a router-layer concern
            raw=data,
        )

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        tok = await self._tenant_access_token(tenant_id)
        if not tok:
            return ConnectionHealth(
                provider_key=PROVIDER_KEY, tenant_id=tenant_id,
                ok=False, connected_account_id_masked=None,
                message="No Stripe connection configured for this tenant.",
                checked_at=_now_iso(),
            )
        try:
            # Cheapest Stripe API probe — Account.retrieve (returns
            # the connected account object; also validates the token
            # hasn't been revoked).
            resp = await self._blocking(self._stripe.Account.retrieve, api_key=tok)
            data = resp if isinstance(resp, dict) else resp.to_dict()
            acct = data.get("id")
            return ConnectionHealth(
                provider_key=PROVIDER_KEY, tenant_id=tenant_id,
                ok=True,
                connected_account_id_masked=(f"{acct[:5]}…{acct[-4:]}" if acct and len(acct) > 8 else acct),
                message="Stripe Account.retrieve returned OK.",
                checked_at=_now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=PROVIDER_KEY, tenant_id=tenant_id,
                ok=False, connected_account_id_masked=None,
                message=f"Stripe probe failed: {type(e).__name__}",
                checked_at=_now_iso(),
            )

    # ── OAuth callback (used by the router) ──────────────────────
    async def exchange_oauth_code(self, *, code: str) -> Dict[str, Any]:
        """Exchange the code Stripe returns on the callback for the
        connected account's ``stripe_user_id`` + ``access_token``.
        Returns the raw provider payload — router persists it via
        ``services.secrets.put_secret``.
        """
        platform_key = _platform_secret_key()
        if not platform_key:
            raise TenantPaymentError("Stripe platform secret key is not configured.")
        try:
            resp = await self._blocking(
                self._stripe.OAuth.token,
                grant_type="authorization_code",
                code=code,
                api_key=platform_key,
            )
            data = resp if isinstance(resp, dict) else resp.to_dict()
            return data
        except Exception as e:
            log.warning("stripe OAuth.token failed: %s", type(e).__name__)
            raise TenantPaymentError(
                f"stripe oauth exchange failed: {type(e).__name__}"
            ) from e
