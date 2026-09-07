"""Phase I1.7.a · Feb-2026 — TenantSecret models + status enums.

Shape (Mongo ``tenant_secrets`` collection)::

    {
      id: "<uuid>",
      tenant_id: "<uuid>",
      provider_key: "stripe" | "square" | "twilio" | ...,
      connection_type: "oauth" | "api_key" | "oauth_stripe_connect",
      encrypted_blob: <base64 ciphertext>,
      iv:             <base64 12-byte GCM nonce>,
      auth_tag:       <base64 16-byte GCM auth tag>,
      dek_wrapped:    <base64 KEK-wrapped DEK> | None,   # None ⇒ direct KEK enc
      last_4:         <last 4 chars of plaintext>,       # never a scrap of the real key beyond this
      connected_status: "connected" | "disconnected" | "error" | "pending",
      connected_account_id: str | None,     # e.g. Stripe "acct_..."
      last_used_at: iso8601 | None,
      error_log: [
        { at: iso8601, code: str, message: str },
        ...
      ],
      created_at: iso8601,
      updated_at: iso8601,
    }

Unique index on ``(tenant_id, provider_key)`` (enforced by the
store on first write) so rotation is a simple upsert.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConnectionType(str, Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"
    OAUTH_STRIPE_CONNECT = "oauth_stripe_connect"


class ConnectionStatus(str, Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class ErrorLogEntry(BaseModel):
    at: str
    code: str
    message: str


class TenantSecret(BaseModel):
    """In-memory model of a persisted secret row. ``encrypted_blob`` /
    ``iv`` / ``auth_tag`` are opaque base64 strings — nothing outside
    ``services.secrets.crypto`` should try to inspect them."""

    id: str
    tenant_id: str
    provider_key: str
    connection_type: ConnectionType
    encrypted_blob: str
    iv: str
    auth_tag: str
    dek_wrapped: Optional[str] = None
    last_4: str = ""
    connected_status: ConnectionStatus = ConnectionStatus.CONNECTED
    connected_account_id: Optional[str] = None
    last_used_at: Optional[str] = None
    error_log: List[ErrorLogEntry] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ConnectionSummary(BaseModel):
    """Safe-to-serve summary that leaves the encryption boundary.

    NEVER includes the plaintext or any part of the ciphertext.
    """
    provider_key: str
    connection_type: ConnectionType
    connected: bool
    last_4: Optional[str] = None
    connected_account_id_masked: Optional[str] = None
    last_used_at: Optional[str] = None
    connected_status: ConnectionStatus
    error_log_count: int = 0
    last_error: Optional[Dict[str, Any]] = None
