"""Phase I1.7.d · Feb-2026 — Payments-BYO provider ABC.

Every concrete provider (Square, PayPal, Authorize.Net, Lumino)
subclasses ``PaymentsByoProvider``. Payment-provider *SDKs* are not
force-installed — adapters call REST endpoints via httpx (mirror of
the AI/Maps BYO pattern).

Distinct from ``services.payments.tenant_base.TenantPaymentProvider``
which handles the platform-managed Stripe Connect flow (I1.7.a).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .models import ChargeResult, ConnectionHealth, RefundResult, WebhookEvent


class PaymentsByoProvider(ABC):
    """Tenant-scoped BYO payments provider contract."""

    provider_key: str = "abstract_payments_byo"
    #: Short name in ``tenant_payments_usage.provider`` + /usage response.
    short_name: str = "abstract"

    config_fields: Dict[str, Dict[str, Any]] = {}
    primary_secret_field: Optional[str] = None

    #: Header name a provider signs its webhook payload with (used
    #: only by the shared verify_webhook helper for test-mode mocks;
    #: real adapters override ``verify_webhook`` outright).
    webhook_signature_header: str = "x-webhook-signature"

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
    async def verify_webhook(
        self, *, tenant_id: str, payload: bytes, headers: Dict[str, str],
    ) -> WebhookEvent:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(
        self, *, tenant_id: str,
    ) -> ConnectionHealth:
        raise NotImplementedError
