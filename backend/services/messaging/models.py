"""Phase I1.7.b · Feb-2026 — Shared messaging models.

Provider-agnostic return types mirror ``services.payments.tenant_base``
so downstream callers never switch on ``provider_key``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── SMS ──────────────────────────────────────────────────────────
class SmsResult(BaseModel):
    id: str                     # provider-issued message id
    status: str                 # normalized: queued | sent | failed | delivered | undelivered
    to: str
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class SmsStatus(BaseModel):
    id: str
    status: str
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class SmsInboundEvent(BaseModel):
    id: str                     # provider-issued inbound message id
    from_number: str
    to_number: str
    body: str
    provider_key: str
    tenant_id: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


# ── Email ────────────────────────────────────────────────────────
class EmailAttachment(BaseModel):
    filename: str
    content_b64: str            # base64-encoded bytes
    content_type: str = "application/octet-stream"


class EmailResult(BaseModel):
    id: str                     # provider-issued message id
    status: str                 # normalized: queued | sent | failed | delivered
    to: List[str]
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class EmailStatus(BaseModel):
    id: str
    status: str
    provider_key: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class EmailInboundEvent(BaseModel):
    """Delivery / bounce / complaint / open event posted by the provider."""
    id: str
    event_type: str             # normalized: delivered | bounced | complained | opened | clicked
    message_id: Optional[str] = None
    recipient: Optional[str] = None
    provider_key: str
    tenant_id: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


# ── Common ───────────────────────────────────────────────────────
class ConnectionHealth(BaseModel):
    """Result of ``test_connection``. Same shape as ``payments.ConnectionHealth``
    but named differently to avoid an import-order cycle when both
    packages import ``services.secrets``."""
    provider_key: str
    tenant_id: str
    ok: bool
    connected_account_id_masked: Optional[str] = None
    message: str = ""
    checked_at: str


# ── Errors ───────────────────────────────────────────────────────
class MessagingError(Exception):
    """Base error class raised by any messaging provider. Public error
    messages must NEVER echo the plaintext api-key / smtp-password /
    webhook payload."""


class TenantMessagingNotConnected(MessagingError):
    """Raised when the caller attempted a send for a tenant that has
    no messaging provider row AND platform fallback is disabled."""


class UnknownMessagingProvider(MessagingError):
    """Raised by the registry when the requested provider key isn't registered."""


class InvalidProviderConfig(MessagingError):
    """Raised at save-time when a provider config is missing a required
    field (e.g. Twilio without ``account_sid``, SMTP without ``host``).
    Message must NOT echo any secret field values."""
