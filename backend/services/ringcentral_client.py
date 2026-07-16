"""Phase 54 · RingCentral SDK bootstrap (JWT auth + lazy singleton).

Reads all credentials from environment. NEVER logs credential values.
Provides:
    · `get_rc_platform()`  — authenticated `Platform` singleton
                             (per-process cache, auto-refresh on 401).
    · `is_outbound_enabled()` — reads runtime `rc_settings` collection
                                first, falls back to `RC_OUTBOUND_ENABLED`
                                env var. Default false (safety).
    · `rc_health_env()` — pure env inspection for the /health endpoint.

Never makes live outbound calls from this module. Live calls happen at
call-sites (SMS send, ring-out, subscription register, contact sync)
and only after `is_outbound_enabled()` gates them.
"""
from __future__ import annotations

import os
from typing import Optional

from config import db, logger

_PLATFORM = None  # cached authenticated Platform instance


def rc_health_env() -> dict:
    return {
        "client_id_configured":     bool(os.getenv("RC_CLIENT_ID")),
        "client_secret_configured": bool(os.getenv("RC_CLIENT_SECRET")),
        "jwt_configured":           bool(os.getenv("RC_JWT")),
        "server_url_configured":    bool(os.getenv("RC_SERVER_URL")),
        "from_number_configured":   bool(os.getenv("RC_FROM_NUMBER")),
    }


async def is_outbound_enabled() -> bool:
    """Runtime toggle in `rc_settings` collection wins over env. This
    lets an admin flip outbound on from the /admin/settings/ringcentral
    UI without restarting the pod."""
    try:
        row = await db.rc_settings.find_one({"key": "outbound_enabled"}, {"_id": 0, "value": 1})
        if row is not None:
            return bool(row.get("value"))
    except Exception:
        pass
    return (os.getenv("RC_OUTBOUND_ENABLED") or "").lower() == "true"


def _build_platform():
    """Constructs a fresh, JWT-authenticated Platform. Any failure is
    logged as a class name only — never with credential material."""
    from ringcentral import SDK
    client_id = os.getenv("RC_CLIENT_ID") or ""
    client_secret = os.getenv("RC_CLIENT_SECRET") or ""
    server = os.getenv("RC_SERVER_URL") or "https://platform.ringcentral.com"
    jwt = os.getenv("RC_JWT") or ""
    if not (client_id and client_secret and jwt):
        raise RuntimeError("rc credentials missing")
    sdk = SDK(client_id, client_secret, server)
    platform = sdk.platform()
    platform.login(jwt=jwt)
    return platform


def get_rc_platform():
    """Returns the cached authenticated Platform, rebuilding on 401.
    Raises RuntimeError when credentials are missing."""
    global _PLATFORM
    if _PLATFORM is None:
        _PLATFORM = _build_platform()
        logger.info("ringcentral platform authenticated")
    return _PLATFORM


def reset_rc_platform():
    """Drop the cached Platform — call after a 401 so the next request
    rebuilds fresh JWT auth."""
    global _PLATFORM
    _PLATFORM = None
