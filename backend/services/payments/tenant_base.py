"""Phase I1.7.a · Feb-2026 — Tenant-scoped payment provider ABC.

**Distinct from** ``services.payments.provider_base.PaymentProvider``
(Task QQ) which is platform-scoped and hosts the SetupIntent →
attach → off_session pipeline used by the customer portal.

The new ``TenantPaymentProvider`` is *tenant-aware* — every method
accepts ``tenant_id`` so the concrete provider can look up the
tenant's own connected account (Stripe Connect, Square OAuth,
PayPal partner referral, …). It is the foundation the I1.7.b/c/d
sub-phases build on:

    I1.7.a → Stripe Connect (this phase)
    I1.7.b → SMS + Email providers (BYO Twilio / SendGrid keys)
    I1.7.c → AI + Maps + Calendars BYO
    I1.7.d → Square, PayPal, Authorize.net, Lumino

Every concrete provider is registered in
``services.payments.tenant_registry`` and instantiated once per
process. Instances are stateless — per-request state (tenant id,
idempotency key) is passed as a method arg.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ── Return types ─────────────────────────────────────────────────
class ChargeResult(BaseModel):
    """Result of ``create_charge`` / ``get_charge``.

    Shape is intentionally provider-agnostic: every provider maps
    its own response into these fields so downstream callers
    (invoicing, receipts, refunds) never need to switch on
    ``provider_key``.
    """
    id: str                     # provider-issued charge id (e.g. "ch_...")
    status: str                 # normalized: succeeded | pending | failed
    amount_cents: int
    currency: str
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)  # provider's full payload for auditing
    error: Optional[str] = None


class RefundResult(BaseModel):
    id: str
    charge_id: str
    status: str                 # succeeded | pending | failed
    amount_cents: int
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class PaymentIntent(BaseModel):
    """Return shape for ``create_payment_intent`` — used by hosted-
    checkout flows where the client needs a client_secret to complete
    the payment in a browser SDK."""
    id: str                     # provider-issued intent id
    client_secret: str          # ⚠️ short-lived, safe to hand to the browser
    status: str
    amount_cents: int
    currency: str
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class WebhookEvent(BaseModel):
    id: str                     # provider event id (dedupe key)
    event_type: str             # normalized: charge.succeeded, refund.created, etc.
    provider_key: str
    tenant_id: Optional[str] = None  # None when the event is platform-level
    raw: Dict[str, Any] = Field(default_factory=dict)


class ConnectionHealth(BaseModel):
    """Result of ``test_connection``.

    P0e · Feb-2026 — Fields ``error_code`` / ``error_class`` /
    ``remediation`` / ``mode`` are OPTIONAL additions for distinct
    error-branch surfacing on the Stripe probe (see
    ``services.payments.tenant_stripe.StripeProvider.test_connection``).
    SMS / Email / AI / Maps providers that haven't adopted the
    distinct-branch pattern yet simply leave these ``None`` so the
    shared ``POST /tenants/me/integrations/{key}/test`` endpoint
    returns a uniform shape.
    """
    provider_key: str
    tenant_id: str
    ok: bool
    connected_account_id_masked: Optional[str] = None
    message: str = ""
    checked_at: str

    # P0e Stage 2 · Feb-2026 — distinct error-branch surface.
    error_code: Optional[str] = None     # ``stripe_key_invalid_or_revoked`` | …
    error_class: Optional[str] = None    # SDK exception class name
    remediation: Optional[str] = None    # one-line "what to do next"
    mode: Optional[str] = None           # ``live`` | ``test`` on success


# ── Errors ───────────────────────────────────────────────────────
class TenantPaymentError(Exception):
    """Base error class raised by any tenant-payment provider.
    Public error message must NEVER echo the plaintext access
    token / API key / webhook body."""


class TenantNotConnected(TenantPaymentError):
    """Raised when the caller attempted a charge / refund for a
    tenant that has no ``connection_type`` = OAUTH_STRIPE_CONNECT
    row (and platform fallback is disabled)."""


class UnknownProvider(TenantPaymentError):
    """Raised by the registry when ``get_provider(unknown_key)``."""


# ── ABC ──────────────────────────────────────────────────────────
class TenantPaymentProvider(ABC):
    provider_key: str = "abstract"

    @abstractmethod
    async def create_charge(
        self, *, tenant_id: str, amount_cents: int, currency: str,
        customer_id: Optional[str] = None,
        payment_method_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> ChargeResult:
        raise NotImplementedError

    @abstractmethod
    async def refund_charge(
        self, *, tenant_id: str, charge_id: str,
        amount_cents: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> RefundResult:
        raise NotImplementedError

    @abstractmethod
    async def get_charge(
        self, *, tenant_id: str, charge_id: str,
    ) -> ChargeResult:
        raise NotImplementedError

    @abstractmethod
    async def create_payment_intent(
        self, *, tenant_id: str, amount_cents: int, currency: str,
        customer_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentIntent:
        raise NotImplementedError

    @abstractmethod
    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> WebhookEvent:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(
        self, *, tenant_id: str,
    ) -> ConnectionHealth:
        raise NotImplementedError
