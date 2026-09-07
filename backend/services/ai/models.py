"""Phase I1.7.c.1 · Feb-2026 — Shared AI-BYO models.

Mirrors ``services.messaging.models`` so callers never switch on
``provider_key``. Everything here is JSON-serialisable and MUST
NOT contain any secret material.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AICompletionResult(BaseModel):
    """Normalized completion return-shape from every AI provider."""

    content: str
    provider_key: str            # "openai" | "anthropic" | "gemini" | "emergent"
    provider_used: str           # "tenant:openai" | "platform:emergent" | ...
    model: str
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class AIProviderUsage(BaseModel):
    """One row in the ``/usage`` response."""

    provider: str                # "openai" | "anthropic" | "gemini"
    period_yyyymm: str           # e.g. "202602"
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    monthly_token_cap: Optional[int] = None    # None = unlimited
    default_model: Optional[str] = None
    connected: bool = False
    pct_used: Optional[float] = None           # None when cap is None
    status: str = "ok"                          # "ok" | "warn" | "blocked"


class AIUsageResponse(BaseModel):
    tenant_id: str
    period_yyyymm: str
    providers: List[AIProviderUsage]


# ── Health ───────────────────────────────────────────────────────
class ConnectionHealth(BaseModel):
    """Same shape as messaging.ConnectionHealth (kept separate to
    avoid inter-package import cycles)."""
    provider_key: str
    tenant_id: str
    ok: bool
    connected_account_id_masked: Optional[str] = None
    message: str = ""
    checked_at: str


# ── Errors ───────────────────────────────────────────────────────
class AIError(Exception):
    """Base error class raised by any AI provider. Public error
    messages must NEVER echo plaintext api keys or user payloads."""


class TenantAINotConnected(AIError):
    """No BYO row + platform fallback disabled."""


class UnknownAIProvider(AIError):
    """Provider key not registered."""


class InvalidAIProviderConfig(AIError):
    """Missing / blank required config field at save-time."""


class TenantAIUsageCapExceeded(AIError):
    """Tenant's monthly token cap has been reached — MUST be surfaced
    as HTTP 429 with NO platform fallback (per problem statement)."""

    def __init__(self, provider: str, cap: int, used: int) -> None:
        super().__init__(
            f"tenant AI usage cap reached for provider={provider}: "
            f"used={used}/{cap} tokens this month"
        )
        self.provider = provider
        self.cap = cap
        self.used = used
