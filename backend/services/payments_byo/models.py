"""Phase I1.7.d · Feb-2026 — Shared Payments-BYO models.

Mirrors ``services.ai.models`` / ``services.maps.models`` — every
provider maps its own response into these shapes so downstream
callers never switch on ``provider_key``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Result shapes ────────────────────────────────────────────────
class ChargeResult(BaseModel):
    """Normalized create_charge return shape."""
    id: str                     # provider-issued charge/transaction id
    status: str                 # succeeded | pending | failed
    amount_cents: int
    currency: str
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class RefundResult(BaseModel):
    id: str
    charge_id: str
    status: str
    amount_cents: int
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class WebhookEvent(BaseModel):
    """Normalized verify_webhook output — used by /webhook receivers."""
    id: str
    event_type: str
    provider_key: str
    tenant_id: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class ConnectionHealth(BaseModel):
    """Result of test_connection (shape parity with ai/maps)."""
    provider_key: str
    tenant_id: str
    ok: bool
    connected_account_id_masked: Optional[str] = None
    message: str = ""
    checked_at: str


# ── Usage response shape ─────────────────────────────────────────
class PaymentsProviderUsage(BaseModel):
    """One row in the /payments/usage response."""
    provider: str                              # "square" | "paypal" | ...
    period_yyyymm: str
    charge_count: int = 0
    refund_count: int = 0
    ops_total: int = 0                          # charge + refund
    monthly_request_cap: Optional[int] = None   # None = unlimited
    connected: bool = False
    pct_used: Optional[float] = None
    status: str = "ok"                          # ok | warn | blocked


class PaymentsUsageResponse(BaseModel):
    tenant_id: str
    period_yyyymm: str
    providers: List[PaymentsProviderUsage]


# ── Errors ───────────────────────────────────────────────────────
class PaymentsByoError(Exception):
    """Base error — public message MUST NEVER echo plaintext secrets."""


class TenantPaymentsNotConnected(PaymentsByoError):
    """Called ``create_charge`` for a tenant with no saved config."""


class UnknownPaymentsProvider(PaymentsByoError):
    """Unregistered provider key."""


class InvalidPaymentsProviderConfig(PaymentsByoError):
    """Missing / blank required config field at save-time."""


class WebhookSignatureInvalid(PaymentsByoError):
    """Signature verification on a /webhook payload failed."""


class TenantPaymentsUsageCapExceeded(PaymentsByoError):
    """Tenant's monthly request cap hit — surfaced as HTTP 429."""

    def __init__(self, provider: str, cap: int, used: int) -> None:
        super().__init__(
            f"tenant payments usage cap reached for provider={provider}: "
            f"used={used}/{cap} ops this month"
        )
        self.provider = provider
        self.cap = cap
        self.used = used
