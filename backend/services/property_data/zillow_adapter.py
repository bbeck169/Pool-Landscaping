"""Task TT · Feb 2026 — RapidAPI-Zillow adapter (dry-scaffold).

Design
------
* Env is read on **each call** (not module import) so a supervisor
  restart after populating ``RAPIDAPI_KEY`` / ``RAPIDAPI_ZILLOW_HOST``
  in ``.env`` immediately flips the adapter from *keys_missing → live*
  without a code change.
* Cache-first: every method inspects the ``zillow_rapidapi_cache``
  Mongo collection regardless of whether the RapidAPI env is
  populated. A cache hit returns immediately with ``cached: True``.
* Missing keys → **never** raise, **never** log per-call. Every
  method returns ``{"unavailable": True, "reason": "keys_not_configured"}``.
  The one-time boot banner in ``server.py`` announces the armed
  state; per-call chatter is suppressed to keep logs clean.
* Test-scope guardrail — when ``APP_ENV`` is not ``production`` the
  adapter refuses live calls unless (a) the normalized address
  contains ``aquaterra`` (synthetic seed data) or (b) the
  ``ZILLOW_TEST_ALLOWLIST_ADDRESSES`` env lists it (comma-separated,
  case-insensitive substring match). Refusals return
  ``{"unavailable": True, "reason": "test_scope_refused"}``.
* 429 throttle memo — a 5-minute in-process cool-down per RapidAPI
  host. When the throttle is armed, every method short-circuits to
  ``{"unavailable": True, "reason": "quota_exhausted"}`` **before**
  hitting the network. Logged at WARN level once per arm.
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

import httpx

from config import db, logger

# ─── constants ────────────────────────────────────────────────────────
CACHE_COLL = "zillow_rapidapi_cache"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
THROTTLE_COOLDOWN_SECONDS = 5 * 60  # 5 minutes
DEFAULT_TIMEOUT_S = 10.0
SYNTHETIC_TOKEN = "aquaterra"  # test-scope allowlist marker

REASON_KEYS_NOT_CONFIGURED = "keys_not_configured"
REASON_QUOTA_EXHAUSTED = "quota_exhausted"
REASON_TEST_SCOPE_REFUSED = "test_scope_refused"
REASON_PROVIDER_ERROR = "provider_error"
REASON_NOT_FOUND = "not_found"

# ─── module-level throttle state ──────────────────────────────────────
# Keyed by RapidAPI host string. Value is the epoch-seconds until
# which the host is considered rate-limited. In-process only — a
# supervisor restart clears it, which is intentional (allows a manual
# retry cycle without waiting the full 5 minutes).
_throttle_until: Dict[str, float] = {}
_throttle_lock = asyncio.Lock()

# Prevents ensure_indexes from running twice within a single process.
_indexes_ready = False


# ─── env helpers (read-each-call so restart-live-refresh works) ──────
def _rapidapi_key() -> Optional[str]:
    v = os.environ.get("RAPIDAPI_KEY", "").strip()
    return v or None


def _rapidapi_host() -> Optional[str]:
    v = os.environ.get("RAPIDAPI_ZILLOW_HOST", "").strip()
    return v or None


def keys_configured() -> bool:
    return bool(_rapidapi_key() and _rapidapi_host())


def _app_env() -> str:
    return os.environ.get("APP_ENV", "preview").lower()


def _test_allowlist() -> list[str]:
    raw = os.environ.get("ZILLOW_TEST_ALLOWLIST_ADDRESSES", "")
    return [tok.strip().lower() for tok in raw.split(",") if tok.strip()]


def startup_log_line() -> str:
    return f"[ZILLOW] adapter armed · keys_configured={keys_configured()}"


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
    """Idempotent — creates TTL on expires_at + unique cache_key.

    Silent-recovers if the index already exists with a different spec
    (e.g. re-ordered fields) — the underlying collection stays usable.
    """
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db[CACHE_COLL].create_index("cache_key", unique=True)
        await db[CACHE_COLL].create_index(
            "expires_at", expireAfterSeconds=0,
        )
        _indexes_ready = True
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"[ZILLOW] ensure_indexes: {e}")


async def _cache_get(cache_key: str) -> Optional[Dict[str, Any]]:
    await _ensure_indexes()
    doc = await db[CACHE_COLL].find_one({"cache_key": cache_key})
    if not doc:
        return None
    # Defensive: the Mongo TTL sweeper runs every ~60s, so an expired
    # doc may still be visible for a minute. Manual expiry check.
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
    """Return True iff the host is currently in cool-down."""
    async with _throttle_lock:
        until = _throttle_until.get(host, 0.0)
        return until > time.time()


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
    """Test-only helper to clear the in-process throttle memo."""
    _throttle_until.clear()


# ─── test-scope guard ────────────────────────────────────────────────
def _test_scope_allows(ident: str) -> bool:
    """When APP_ENV != production, block live calls unless the address
    is synthetic (contains ``aquaterra``) or matches the allowlist env.
    """
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
    """Thin RapidAPI-Zillow wrapper with cache + guardrails.

    Every method returns a dict shaped like one of::

        {"unavailable": False, "data": {...}, "cached": bool}
        {"unavailable": True,  "reason": "<REASON_*>"}

    The endpoint router flattens this into a JSON body the frontend
    can render with a single ``if (r.unavailable)`` check.
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        # ``http_client`` is injectable for tests. Production callers
        # let the client build a per-call short-lived AsyncClient so
        # timeouts are enforced and no long-lived socket sits idle.
        self._http = http_client

    # ── search_by_address ──────────────────────────────────────────
    async def search_by_address(
        self, address: str, tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._call(
            method="search_by_address",
            ident=address,
            path="/propertyExtendedSearch",
            params={"location": address},
            tenant_id=tenant_id,
        )

    # ── property_detail ────────────────────────────────────────────
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

    # ── zestimate ─────────────────────────────────────────────────
    async def zestimate(
        self, zpid: str, tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._call(
            method="zestimate",
            ident=str(zpid),
            path="/zestimateHistory",
            params={"zpid": str(zpid)},
            tenant_id=tenant_id,
        )

    # ── internal ──────────────────────────────────────────────────
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
        key = _rapidapi_key()
        host = _rapidapi_host()
        if not key or not host:
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

        # 4. Throttle memo — refuse live call if host is in cool-down.
        if await _throttle_check(host):
            return {
                "unavailable": True,
                "reason": REASON_QUOTA_EXHAUSTED,
            }

        # 5. Live call.
        url = f"https://{host}{path}"
        headers = {
            "x-rapidapi-key": key,
            "x-rapidapi-host": host,
        }
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
            await _throttle_arm(host)
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
