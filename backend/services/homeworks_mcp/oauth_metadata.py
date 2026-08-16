"""Feb-2026 · Homeworks Authorization-Server metadata (RFC 8414).

Fetches ``.well-known/oauth-authorization-server`` once per process and
memoises the result. All URLs used elsewhere in the flow
(``authorization_endpoint``, ``token_endpoint``, ``registration_endpoint``,
``scopes_supported``) come from here — nothing else in the codebase may
hard-code an ``api.home.works/oauth/*`` URL.

Metadata is refreshed if the cache is older than ``_METADATA_TTL_SECS``
(24 h). The metadata URL itself is configured via
``HOMEWORKS_OAUTH_METADATA_URL`` so a future env swap doesn't need a
code change.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("homeworks_mcp.oauth_metadata")

_METADATA_TTL_SECS = 60 * 60 * 24  # 24 h — matches spec ("refresh daily").
_HTTP_TIMEOUT = 15.0

_DEFAULT_METADATA_URL = (
    "https://api.home.works/.well-known/oauth-authorization-server"
)

_cache: Dict[str, Any] = {"data": None, "fetched_at": 0.0}


def metadata_url() -> str:
    return (
        os.environ.get("HOMEWORKS_OAUTH_METADATA_URL")
        or _DEFAULT_METADATA_URL
    ).strip()


def _cache_is_fresh(now: float) -> bool:
    return (
        _cache["data"] is not None
        and (now - _cache["fetched_at"]) < _METADATA_TTL_SECS
    )


async def fetch_metadata(force: bool = False) -> Dict[str, Any]:
    """Return the parsed AS metadata dict.

    Raises :class:`RuntimeError` on any transport / parsing failure — the
    caller is expected to convert this into a user-visible 502 or fail
    the connect attempt outright. We deliberately do NOT fall back to
    hardcoded URLs; the whole point of RFC 8414 is that the AS is the
    source of truth.
    """
    now = time.time()
    if not force and _cache_is_fresh(now):
        return _cache["data"]

    url = metadata_url()
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"homeworks_oauth_metadata_transport_failed:{exc}"
        ) from exc

    if r.status_code >= 400:
        raise RuntimeError(
            f"homeworks_oauth_metadata_http_{r.status_code}"
        )

    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError(
            f"homeworks_oauth_metadata_invalid_json:{exc}"
        ) from exc

    _required = (
        "authorization_endpoint",
        "token_endpoint",
        "code_challenge_methods_supported",
    )
    missing = [k for k in _required if not data.get(k)]
    if missing:
        raise RuntimeError(
            f"homeworks_oauth_metadata_missing_fields:{','.join(missing)}"
        )

    if "S256" not in (data.get("code_challenge_methods_supported") or []):
        # We only implement S256; refuse to proceed on any surprise.
        raise RuntimeError(
            "homeworks_oauth_metadata_no_s256_support"
        )

    _cache["data"] = data
    _cache["fetched_at"] = now
    logger.info(
        "[homeworks_oauth] metadata cached · issuer=%s · scopes=%s",
        data.get("issuer"), data.get("scopes_supported"),
    )
    return data


def reset_cache() -> None:
    """Test hook. Clears the in-memory cache."""
    _cache["data"] = None
    _cache["fetched_at"] = 0.0


def cached_metadata() -> Optional[Dict[str, Any]]:
    """Return the current cached metadata if any (no fetch)."""
    return _cache["data"]
