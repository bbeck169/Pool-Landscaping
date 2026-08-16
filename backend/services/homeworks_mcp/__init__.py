"""Feb-2026 · Homeworks MCP OAuth integration (``https://api.home.works/mcp``).

Phase 1a scope: OAuth 2.1 Authorization-Code + PKCE (S256) against the
Homeworks Authorization Server, at-rest Fernet encryption of tokens,
automatic refresh with a 60 s skew.

Distinct package from ``services.homeworks`` (Phase 55 Copilot-CRM
importer) — that one is one-shot ETL, this one is a live OAuth
integration. Kept separate to avoid semantic overload.

Public API used by ``routers.integrations_homeworks_oauth``::

    from services.homeworks_mcp import (
        pkce, state_store, token_store, token_refresh, oauth_metadata,
    )

MCP tools/list + tools/call intentionally NOT part of Phase 1a. Ships in
Phase 1b once we've verified the token exchange end-to-end.
"""
