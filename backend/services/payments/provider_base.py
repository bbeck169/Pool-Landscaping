"""Task QQ · Feb 2026 — payment-provider abstraction.

Shared exceptions + abstract base class every concrete provider
(Stripe, Lumino, …) implements. Callers (routers, services, cron
jobs) should ONLY depend on `PaymentProvider` and the concrete
provider is selected by `provider_factory.get_payment_provider()`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class PaymentProviderError(Exception):
    """Base class for all provider errors."""


class PaymentProviderNotConfigured(PaymentProviderError):
    """Raised when a provider is instantiated but its required env
    (api url / token / webhook secret) is not populated. Callers
    should catch this and surface a friendly "payment provider not
    configured" error to the operator."""


class PaymentProviderDryRun(PaymentProviderError):
    """Signals that a call short-circuited into dry-run mode because
    the destination customer is not on the preview allow-list. NOT
    an error — the caller can inspect ``payload`` for the synthetic
    response the adapter fabricated."""

    def __init__(self, payload: Dict[str, Any]):
        super().__init__("payment call short-circuited to dry-run")
        self.payload = payload


class PaymentTestScopeViolation(PaymentProviderError):
    """Raised when a non-production call targets a customer that
    isn't a synthetic test fixture (Aquaterra / PLOFV / explicit
    allow-list). Prevents accidental Lumino/Stripe API calls against
    live customer data during preview or Jest/pytest runs.

    User directive · Feb 2026: NO LIVE CUSTOMERS in any test flow.
    """


class PaymentProvider(ABC):
    """Abstract payment provider. Concrete providers implement each
    method with idempotency-key support (accept optional
    ``idempotency_key`` kwarg and forward to the underlying API)."""

    name: str = "abstract"

    # ── Customer lifecycle ────────────────────────────────────────
    @abstractmethod
    async def create_customer(self, *, email: str, name: Optional[str] = None,
                                    metadata: Optional[Dict[str, Any]] = None,
                                    idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    # ── Vaulting (Add-a-Card) ─────────────────────────────────────
    @abstractmethod
    async def create_setup_session(self, *, customer_ref: str,
                                        return_url: str,
                                        idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def list_vaulted_methods(self, *, customer_ref: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    # ── Payment / Checkout ────────────────────────────────────────
    @abstractmethod
    async def create_payment_session(self, *, customer_ref: str,
                                          amount_cents: int, currency: str,
                                          description: Optional[str] = None,
                                          metadata: Optional[Dict[str, Any]] = None,
                                          off_session: bool = False,
                                          method_ref: Optional[str] = None,
                                          idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    # ── Subscriptions (Autobilling) ───────────────────────────────
    @abstractmethod
    async def create_subscription(self, *, customer_ref: str, plan_ref: str,
                                        metadata: Optional[Dict[str, Any]] = None,
                                        idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def cancel_subscription(self, *, subscription_ref: str,
                                        idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    # ── Refunds ───────────────────────────────────────────────────
    @abstractmethod
    async def create_refund(self, *, transaction_ref: str,
                                 amount_cents: Optional[int] = None,
                                 reason: Optional[str] = None,
                                 idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    # ── Webhook verification ──────────────────────────────────────
    @abstractmethod
    def verify_webhook(self, *, raw_body: bytes, signature_header: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse_webhook_event(self, *, raw_body: bytes) -> Dict[str, Any]:
        raise NotImplementedError

    async def get_payment_status(self, *, session_id: str) -> Dict[str, Any]:
        """Task QQ Phase 2 · Feb 2026 — payment status probe used by
        the return-URL endpoint + nightly reconciler. Default
        implementation raises; providers that support it override."""
        raise NotImplementedError
