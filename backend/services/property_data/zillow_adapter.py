"""Task TT / TT.5 · Feb 2026 — OpenWebNinja-Zillow adapter (dry-scaffold).

Provider
--------
User's Zillow provider is **OpenWebNinja direct** (not RapidAPI):
    https://api.openwebninja.com/realtime-zillow-data
    header: x-api-key: <OPENWEB_NINJA_API_KEY>

Task TT originally shipped a RapidAPI-style scaffold. TT.5 reconciles
the adapter to the real provider — same wrapper contract (cache-first,
test-scope guard, 5-min throttle memo, graceful ``{unavailable, reason}``
returns), swapped provider auth + endpoint paths.

Isolation from the legacy Phase 56.9b path
------------------------------------------
The existing ``routers/property.py`` + ``routers/d2d.py`` still own
their own cache (``zillow_cache`` — 30-day TTL, ``cached_at_dt``),
their tech/tenant rate-limit contract, and their audit trail. This
adapter uses a **separate** cache collection (``zillow_own_cache``,
7-day TTL, ``expires_at``) so both systems coexist without stepping
on each other. Both share the single ``OPENWEB_NINJA_API_KEY`` env
so provider rotation is one-shot.

Design invariants (unchanged from Task TT)
------------------------------------------
* Env is read on **each call** so a supervisor restart after the
  operator populates ``OPENWEB_NINJA_API_KEY`` in ``.env`` flips the
  adapter from *keys_missing → live* without a code change.
* Cache-first: every method inspects ``zillow_own_cache`` regardless
  of whether the API key env is populated. A cache hit returns
  immediately with ``cached: True``.
* Missing key → **never** raise, **never** log per-call. Every method
  returns ``{"unavailable": True, "reason": "keys_not_configured"}``.
  The one-time boot banner announces the armed state; per-call
  chatter is suppressed to keep logs clean.
* Test-scope guardrail — when ``APP_ENV`` is not ``production`` the
  adapter refuses live calls unless (a) the normalized address
  contains ``aquaterra`` (synthetic seed data) or (b) the
  ``ZILLOW_TEST_ALLOWLIST_ADDRESSES`` env lists it (comma-separated,
  case-insensitive substring match).
* 429 throttle memo — a 5-minute in-process cool-down per provider
  host. When the throttle is armed, every method short-circuits to
  ``{"unavailable": True, "reason": "quota_exhausted"}`` **before**
  hitting the network.
* Zero live network in pytest — every test monkey-patches
  ``httpx.AsyncClient`` and ``db``.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from config import db, logger

# ─── provider constants ──────────────────────────────────────────────
PROVIDER_NAME = "openwebninja"
PROVIDER_BASE_URL = "https://api.openwebninja.com/realtime-zillow-data"
PROVIDER_HOST = urlparse(PROVIDER_BASE_URL).hostname or "api.openwebninja.com"

# ─── cache + throttle constants ──────────────────────────────────────
CACHE_COLL = "zillow_own_cache"  # namespaced separately from legacy zillow_cache
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
THROTTLE_COOLDOWN_SECONDS = 5 * 60  # 5 minutes
DEFAULT_TIMEOUT_S = 10.0
SYNTHETIC_TOKEN = "aquaterra"  # test-scope allowlist marker

REASON_KEYS_NOT_CONFIGURED = "keys_not_configured"
REASON_QUOTA_EXHAUSTED = "quota_exhausted"
REASON_TEST_SCOPE_REFUSED = "test_scope_refused"
REASON_PROVIDER_ERROR = "provider_error"
REASON_NOT_FOUND = "not_found"

# ─── module-level throttle state ─────────────────────────────────────
_throttle_until: Dict[str, float] = {}
_throttle_lock = asyncio.Lock()

_indexes_ready = False


# Placeholder-detection guard (Task RR/SS Phase 2 follow-on · Feb 2026).
# The escape-hatch flow leaves literal ``REPLACE_ME_*`` strings in
# ``.env`` until the operator swaps them for real values. Those
# strings are non-empty, so a naive ``bool(env)`` check would report
# the adapter as armed even though every live call would 401 upstream.
# The guard short-circuits placeholder values to ``None`` so the
# banner reports ``keys_configured=False`` and every live call falls
# through to the graceful ``keys_not_configured`` return path.
_PLACEHOLDER_PREFIX = "REPLACE_ME_"
_placeholder_warned = False


def _looks_like_placeholder(value: str) -> bool:
    return bool(value) and value.startswith(_PLACEHOLDER_PREFIX)


def _reset_placeholder_warning_for_tests() -> None:
    """Test helper — clears the one-shot warning latch so multiple
    tests can each assert the WARN log line without one silencing
    the next."""
    global _placeholder_warned
    _placeholder_warned = False


# ─── env helpers (read-each-call so restart-live-refresh works) ─────
def _provider_api_key() -> Optional[str]:
    """Prefer ``OPENWEB_NINJA_ZILLOW_API_KEY``; fall back to
    ``OPENWEB_NINJA_API_KEY``. Matches the resolution order used in
    ``config.OPENWEB_NINJA_API_KEY`` so both legacy code and this
    adapter always agree on which key is authoritative.

    Placeholder-detection: if the resolved value starts with
    ``REPLACE_ME_`` (the escape-hatch marker), treat it as unset.
    A one-shot WARN log fires the first time this happens per
    process so the operator sees the guidance in the logs without
    per-call spam.
    """
    global _placeholder_warned
    v = (os.environ.get("OPENWEB_NINJA_ZILLOW_API_KEY", "").strip()
         or os.environ.get("OPENWEB_NINJA_API_KEY", "").strip())
    if not v:
        return None
    if _looks_like_placeholder(v):
        if not _placeholder_warned:
            logger.warning(
                "[ZILLOW] adapter env value looks like a placeholder — "
                "treating as not configured. Please replace REPLACE_ME_* "
                "in /app/backend/.env with the real key and restart.",
            )
            _placeholder_warned = True
        return None
    return v


def keys_configured() -> bool:
    return bool(_provider_api_key())


def _app_env() -> str:
    return os.environ.get("APP_ENV", "preview").lower()


def _test_allowlist() -> list[str]:
    raw = os.environ.get("ZILLOW_TEST_ALLOWLIST_ADDRESSES", "")
    return [tok.strip().lower() for tok in raw.split(",") if tok.strip()]


def startup_log_line() -> str:
    return (f"[ZILLOW] adapter armed · provider={PROVIDER_NAME}"
            f" · keys_configured={keys_configured()}")


# ─── normalization + cache primitives ────────────────────────────────
def _normalize(addr: str) -> str:
    if not addr:
        return ""
    s = re.sub(r"\s+", " ", addr.strip().lower())
    s = re.sub(r"[^\w\s,-]", "", s)
    return s


def _cache_key(method: str, ident: str) -> str:
    norm = _normalize(ident)
    raw = f"{method}::{norm}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db[CACHE_COLL].create_index("cache_key", unique=True)
        await db[CACHE_COLL].create_index("expires_at", expireAfterSeconds=0)
        _indexes_ready = True
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"[ZILLOW] ensure_indexes: {e}")


async def _cache_get(cache_key: str) -> Optional[Dict[str, Any]]:
    await _ensure_indexes()
    doc = await db[CACHE_COLL].find_one({"cache_key": cache_key})
    if not doc:
        return None
    exp = doc.get("expires_at")
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= _now_utc():
            return None
    return doc.get("response_json")


async def _cache_put(
    cache_key: str,
    method: str,
    ident_normalized: str,
    response_json: Dict[str, Any],
    tenant_id: Optional[str],
) -> None:
    await _ensure_indexes()
    now = _now_utc()
    doc = {
        "cache_key": cache_key,
        "method": method,
        "ident_normalized": ident_normalized,
        "tenant_id": tenant_id,
        "response_json": response_json,
        "cached_at": now,
        "expires_at": now + timedelta(seconds=CACHE_TTL_SECONDS),
    }
    await db[CACHE_COLL].update_one(
        {"cache_key": cache_key}, {"$set": doc}, upsert=True,
    )


# ─── throttle memo ───────────────────────────────────────────────────
async def _throttle_check(host: str) -> bool:
    async with _throttle_lock:
        return _throttle_until.get(host, 0.0) > time.time()


async def _throttle_arm(host: str) -> None:
    async with _throttle_lock:
        already = _throttle_until.get(host, 0.0)
        new_until = time.time() + THROTTLE_COOLDOWN_SECONDS
        if new_until > already:
            _throttle_until[host] = new_until
            logger.warning(
                f"[ZILLOW] 429 from {host} — throttle armed for "
                f"{THROTTLE_COOLDOWN_SECONDS}s",
            )


def _reset_throttle_for_tests() -> None:
    _throttle_until.clear()


# ─── test-scope guard ────────────────────────────────────────────────
def _test_scope_allows(ident: str) -> bool:
    if _app_env() == "production":
        return True
    n = _normalize(ident)
    if SYNTHETIC_TOKEN in n:
        return True
    for allowed in _test_allowlist():
        if allowed and allowed in n:
            return True
    return False


# ─── the client ──────────────────────────────────────────────────────
class ZillowClient:
    """Thin OpenWebNinja-Zillow wrapper with cache + guardrails.

    Every method returns a dict shaped like one of::

        {"unavailable": False, "data": {...}, "cached": bool}
        {"unavailable": True,  "reason": "<REASON_*>"}

    The endpoint router flattens this into a JSON body the frontend
    can render with a single ``if (r.unavailable)`` check.
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self._http = http_client

    async def search_by_address(
        self, address: str, tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._call(
            method="search_by_address",
            ident=address,
            path="/property-details-address",
            params={"address": address},
            tenant_id=tenant_id,
        )

    async def property_detail(
        self, zpid: str, tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._call(
            method="property_detail",
            ident=str(zpid),
            path="/property",
            params={"zpid": str(zpid)},
            tenant_id=tenant_id,
        )

    async def zestimate(
        self, zpid: str, tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # OpenWebNinja's realtime-zillow-data returns zestimate inside
        # /property; there is no discrete /zestimate endpoint. We keep
        # the method surface for callers, but reuse /property under
        # the hood so a single API call powers both facts + zestimate.
        return await self._call(
            method="zestimate",
            ident=str(zpid),
            path="/property",
            params={"zpid": str(zpid)},
            tenant_id=tenant_id,
        )

    async def _call(
        self,
        *,
        method: str,
        ident: str,
        path: str,
        params: Dict[str, Any],
        tenant_id: Optional[str],
    ) -> Dict[str, Any]:
        ident_norm = _normalize(ident)
        cache_key = _cache_key(method, ident)

        # 1. Cache first — regardless of keys-present state.
        try:
            cached = await _cache_get(cache_key)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"[ZILLOW] cache read failed: {e}")
            cached = None
        if cached is not None:
            return {"unavailable": False, "data": cached, "cached": True}

        # 2. Keys check (silent, per-call decision, no logging).
        key = _provider_api_key()
        if not key:
            return {
                "unavailable": True,
                "reason": REASON_KEYS_NOT_CONFIGURED,
            }

        # 3. Test-scope refusal (non-prod + non-synthetic + not allowlisted).
        if not _test_scope_allows(ident):
            return {
                "unavailable": True,
                "reason": REASON_TEST_SCOPE_REFUSED,
            }

        # 4. Throttle memo — refuse live call if provider is in cool-down.
        if await _throttle_check(PROVIDER_HOST):
            return {
                "unavailable": True,
                "reason": REASON_QUOTA_EXHAUSTED,
            }

        # 5. Live call.
        url = f"{PROVIDER_BASE_URL}{path}"
        headers = {"x-api-key": key}
        try:
            client = self._http
            owns_client = False
            if client is None:
                client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)
                owns_client = True
            try:
                resp = await client.get(url, params=params, headers=headers)
            finally:
                if owns_client:
                    await client.aclose()
        except (httpx.TimeoutException, httpx.RequestError) as e:
            logger.warning(f"[ZILLOW] {method} network error: {e}")
            return {"unavailable": True, "reason": REASON_PROVIDER_ERROR}
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"[ZILLOW] {method} unexpected error: {e}")
            return {"unavailable": True, "reason": REASON_PROVIDER_ERROR}

        # 6. Response handling.
        if resp.status_code == 429:
            await _throttle_arm(PROVIDER_HOST)
            return {"unavailable": True, "reason": REASON_QUOTA_EXHAUSTED}
        if resp.status_code == 404:
            return {"unavailable": True, "reason": REASON_NOT_FOUND}
        if resp.status_code >= 400:
            logger.warning(
                f"[ZILLOW] {method} provider error status="
                f"{resp.status_code} body={resp.text[:200]}",
            )
            return {"unavailable": True, "reason": REASON_PROVIDER_ERROR}

        try:
            payload = resp.json()
        except Exception as e:
            logger.warning(f"[ZILLOW] {method} non-JSON response: {e}")
            return {"unavailable": True, "reason": REASON_PROVIDER_ERROR}

        # OpenWebNinja wraps payloads under a top-level ``data`` key
        # (mirroring ``routers/property.py`` handling). Empty ``data``
        # is a not-found signal from this provider — surface it that
        # way so callers can render the "no record" copy variant.
        if isinstance(payload, dict) and "data" in payload:
            data_val = payload.get("data")
            if data_val in (None, [], {}):
                return {"unavailable": True, "reason": REASON_NOT_FOUND}

        # 7. Cache-write + return.
        try:
            await _cache_put(
                cache_key=cache_key,
                method=method,
                ident_normalized=ident_norm,
                response_json=payload,
                tenant_id=tenant_id,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"[ZILLOW] cache write failed: {e}")

        return {"unavailable": False, "data": payload, "cached": False}
