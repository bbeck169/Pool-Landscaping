"""Feb-2026 · Homeworks OAuth token refresh helper.

Single entry point :func:`get_valid_access_token`. Callers hand in the
tenant id, we hand back a fresh plaintext ``access_token`` — refreshing
it via ``grant_type=refresh_token`` when we're within
``REFRESH_SKEW_SECONDS`` of expiry.

Returns ``None`` when:
* there is no stored connection for the tenant, OR
* the refresh call itself fails (401, network, non-JSON) — the token
  doc is left in place so the operator can retry / reconnect.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from services.homeworks_mcp import oauth_metadata, token_store

logger = logging.getLogger("homeworks_mcp.token_refresh")

REFRESH_SKEW_SECONDS = 60
_HTTP_TIMEOUT = 15.0


def _client_id() -> str:
    return (os.environ.get("HOMEWORKS_CLIENT_ID") or "").strip()


async def _refresh(tenant_id: str, refresh_token_plain: str) -> Optional[str]:
    """Perform the refresh call, update storage, return the new access
    token. Returns ``None`` on any failure."""
    md = await oauth_metadata.fetch_metadata()
    token_url = md["token_endpoint"]
    client_id = _client_id()
    if not client_id:
        logger.warning(
            "[homeworks_oauth] refresh aborted: HOMEWORKS_CLIENT_ID unset"
        )
        return None
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as http:
            r = await http.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token_plain,
                    "client_id": client_id,
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.warning("[homeworks_oauth] refresh transport failed: %s", exc)
        return None

    if r.status_code >= 400:
        logger.warning(
            "[homeworks_oauth] refresh_failed tenant=%s status=%s body=%s",
            tenant_id, r.status_code, r.text[:200],
        )
        return None

    try:
        payload = r.json()
    except ValueError:
        logger.warning("[homeworks_oauth] refresh returned non-JSON body")
        return None

    new_access = payload.get("access_token")
    if not new_access:
        logger.warning(
            "[homeworks_oauth] refresh payload missing access_token"
        )
        return None
    new_refresh = payload.get("refresh_token")  # may be None (no rotation)
    expires_in = int(payload.get("expires_in") or 3600)
    await token_store.update_after_refresh(
        tenant_id=tenant_id,
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in_secs=expires_in,
    )
    return new_access


async def get_valid_access_token(tenant_id: str) -> Optional[str]:
    """Return a plaintext access token that's guaranteed to be valid for
    at least ``REFRESH_SKEW_SECONDS`` seconds. ``None`` on any failure."""
    doc = await token_store.get_by_tenant(tenant_id)
    if not doc:
        return None
    try:
        access = token_store.decrypt(doc["encrypted_access_token"])
    except (KeyError, ValueError) as exc:
        logger.warning(
            "[homeworks_oauth] cached access_token unusable tenant=%s :: %s",
            tenant_id, exc,
        )
        return None

    exp = doc.get("expires_at")
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        remaining = (exp - datetime.now(timezone.utc)).total_seconds()
    else:
        remaining = 0.0

    if remaining > REFRESH_SKEW_SECONDS:
        return access

    # Need to refresh.
    try:
        refresh = token_store.decrypt(doc["encrypted_refresh_token"])
    except (KeyError, ValueError) as exc:
        logger.warning(
            "[homeworks_oauth] cached refresh_token unusable tenant=%s :: %s",
            tenant_id, exc,
        )
        return None
    return await _refresh(tenant_id, refresh)
