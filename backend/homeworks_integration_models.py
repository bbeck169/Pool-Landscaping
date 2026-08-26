"""Phase 0 POC · Feb-2026 — Homeworks (home.works MCP) BYO-creds integration.

Pydantic models for the per-tenant integration document stored in
``db.homeworks_byo_integrations``.

Deviation from Phase 0 spec (intentional, documented):
    The spec asked for ``backend/models/homeworks_integration.py`` but
    the backend already ships ``backend/models.py`` as a flat module
    (imported everywhere via ``from models import X``). Creating a
    ``models/`` package would shadow that module and break every
    existing route. Model lives at this flat-module path instead;
    router + tests reference it accordingly.

Schema
------
Per-tenant config for OAuth 2.0 + MCP handshake. Secrets (client
secret, access token, refresh token) are Fernet-encrypted at rest by
``services.homeworks_mcp_client``; this module only defines the shape.

Fields marked ``…_encrypted`` are strings containing the Fernet
ciphertext (URL-safe base64), NEVER plaintext. GET responses returned
to the frontend redact those fields and set boolean has_* flags in
their place — see ``services.homeworks_mcp_client.redact_config``.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


DEFAULT_MCP_SERVER_URL = "https://www.home.works/connect/mcp"
CONNECTION_STATUSES = ("disconnected", "connected", "error")


class HomeworksIntegrationConfig(BaseModel):
    """Persisted per-tenant Homeworks OAuth + MCP configuration."""

    tenant_id: str

    # OAuth 2.0 client credentials (user-provided).
    client_id: str = ""
    client_secret_encrypted: Optional[str] = None

    # OAuth endpoints (user-editable; home.works docs are behind their
    # connect page so we don't hard-code guesses).
    authorize_url: str = ""
    token_url: str = ""
    redirect_uri: str = ""
    scopes: List[str] = Field(default_factory=list)

    # MCP server URL (defaults to the home.works published endpoint).
    mcp_server_url: str = DEFAULT_MCP_SERVER_URL

    # OAuth tokens (populated after successful handshake).
    access_token_encrypted: Optional[str] = None
    refresh_token_encrypted: Optional[str] = None
    token_expires_at: Optional[datetime] = None

    # Connection health.
    connection_status: str = "disconnected"  # one of CONNECTION_STATUSES
    last_error: Optional[str] = None
    last_connected_at: Optional[datetime] = None

    # Audit.
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class HomeworksIntegrationCredsInput(BaseModel):
    """Body for ``PUT /api/admin/integrations/homeworks``.

    All fields optional so partial updates work (e.g. rotate secret
    without re-typing client_id). Empty-string client_secret means
    "keep existing"; explicit ``null`` (JSON null) means "clear".
    """

    client_id: Optional[str] = None
    client_secret: Optional[str] = None  # plaintext; encrypted before persist
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    redirect_uri: Optional[str] = None
    scopes: Optional[List[str]] = None
    mcp_server_url: Optional[str] = None


class HomeworksIntegrationRedactedView(BaseModel):
    """Response shape for GET / PUT. Secrets are redacted."""

    tenant_id: str
    client_id: str
    has_client_secret: bool
    authorize_url: str
    token_url: str
    redirect_uri: str
    scopes: List[str]
    mcp_server_url: str
    connection_status: str
    last_error: Optional[str] = None
    last_connected_at: Optional[str] = None  # ISO string
    token_expires_at: Optional[str] = None
    has_access_token: bool
    has_refresh_token: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
