"""Phase I1.7.d · Feb-2026 — Tenant Payments BYO providers.

Public API mirrors ``services.ai`` / ``services.maps`` / ``services.calendars``
so ``routers.tenant_integrations`` can dispatch on ``kind == "payments_byo"``
identically to the other BYO families.
"""
from __future__ import annotations

from .models import (
    ChargeResult,
    ConnectionHealth,
    InvalidPaymentsProviderConfig,
    PaymentsProviderUsage,
    PaymentsUsageResponse,
    RefundResult,
    TenantPaymentsNotConnected,
    TenantPaymentsUsageCapExceeded,
    UnknownPaymentsProvider,
    WebhookEvent,
    WebhookSignatureInvalid,
)
from .registry import (
    get_payments_byo_provider,
    get_payments_byo_provider_by_short_name,
    get_provider_field_schemas,
    list_registered_payments_byo_provider_keys,
    list_short_names,
    register_payments_byo_provider,
    reset_cache_for_tests,
    short_name_for,
)
from .tenant_base import PaymentsByoProvider

__all__ = [
    "ChargeResult", "ConnectionHealth", "InvalidPaymentsProviderConfig",
    "PaymentsProviderUsage", "PaymentsUsageResponse", "RefundResult",
    "TenantPaymentsNotConnected", "TenantPaymentsUsageCapExceeded",
    "UnknownPaymentsProvider", "WebhookEvent", "WebhookSignatureInvalid",
    "PaymentsByoProvider",
    "get_payments_byo_provider",
    "get_payments_byo_provider_by_short_name",
    "get_provider_field_schemas",
    "list_registered_payments_byo_provider_keys",
    "list_short_names",
    "register_payments_byo_provider",
    "reset_cache_for_tests",
    "short_name_for",
]
