"""Hotfix #3 · Feb-2026 — Zillow property enrichment for D2D prospects.

Thin wrapper over the existing ``services.property_data.zillow_adapter``
(OpenWebNinja Zillow provider). Adds three things the raw adapter
doesn't have:

  1. Normalised return shape matching the D2D UI contract
     (``zpid``, ``address_formatted``, ``estimated_value``, …).
  2. ``ZILLOW_TESTMODE_MOCK=true`` short-circuit that returns
     deterministic fixture data (SHA-1 of the address seeds the
     numbers, so the same address always produces the same fixture).
  3. Per-tenant rate limit (100 req/hour) to guard against runaway
     provider spend. Implemented in Mongo so it's shared across
     backend pods.

The follow-up plan (I1.7.f — Data Enrichment BYO providers) will
retire the env-var-based key in favour of per-tenant BYO integration
cards, at which point this module gets a ``registry`` parallel to
``services.payments_byo.registry``.

**Provider choice note.** The brief suggested RapidAPI. The codebase
already ships an OpenWebNinja Zillow adapter with per-address cache,
30-day TTL, admin budget guard, and a mature test surface. Rather
than duplicate that surface with a parallel RapidAPI adapter, we
reuse OpenWebNinja and map its response into the requested shape.
Switching to RapidAPI (or any other Zillow provider) is now a single
``ZillowClient.search_by_address`` swap.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# Phase P1.1 · Feb 2026 — canonical import surface for the adapter.
# Kept at module-top so an accidental drift on the export side of
# the contract fails fast at BOOT (the router refuses to import the
# whole module) instead of masking itself as a 502 at first call.
from services.property_data.zillow_adapter import (
    get_zillow_client,
    ZillowError,
    REASON_KEYS_NOT_CONFIGURED,
    REASON_QUOTA_EXHAUSTED,
    REASON_NOT_FOUND,
    REASON_PROVIDER_ERROR,
    REASON_TEST_SCOPE_REFUSED,
)


# ── Constants ────────────────────────────────────────────────────
CACHE_COLLECTION = "zillow_cache"              # existing collection
RATE_LIMIT_COLLECTION = "zillow_enrich_rate"   # per-tenant hourly counter
CACHE_TTL_HOURS = 24
RATE_LIMIT_PER_HOUR = 100


# ── Return shape ─────────────────────────────────────────────────
class ZillowProperty(BaseModel):
    zpid: Optional[str] = None
    address_formatted: str
    estimated_value: Optional[int] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    bed_count: Optional[float] = None
    bath_count: Optional[float] = None
    year_built: Optional[int] = None
    image_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_fetched_at: str
    raw: Dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    mock: bool = False


class ZillowNotConfigured(Exception):
    """Raised when neither the provider key nor ``TESTMODE_MOCK`` is set."""


class ZillowRateLimited(Exception):
    """Raised when the per-tenant 100/hr cap is hit."""


# ── Helpers ──────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _testmode_mock() -> bool:
    return os.environ.get("ZILLOW_TESTMODE_MOCK", "").strip().lower() in ("1", "true", "yes")


def _provider_configured() -> bool:
    # ``services.property_data.zillow_adapter`` uses OpenWebNinja as
    # the concrete backend, but we honour the brief's spelling
    # (``ZILLOW_RAPIDAPI_KEY``) as an alias so ops can flip either
    # variable in prod. Either one being present means "configured".
    for name in ("ZILLOW_RAPIDAPI_KEY", "OPENWEB_NINJA_API_KEY", "OWN_API_KEY"):
        v = os.environ.get(name)
        if v and v.strip():
            return True
    return False


def _normalise_address(address: str) -> str:
    return " ".join((address or "").strip().split()).lower()


def _address_hash(address: str) -> str:
    return hashlib.sha256(_normalise_address(address).encode("utf-8")).hexdigest()


def _default_db():
    from config import db
    return db


# ── Mock fixture ─────────────────────────────────────────────────
def _mock_property(address: str) -> ZillowProperty:
    """Deterministic fixture — SHA-1 of the address seeds every numeric.

    Same address in, same fixture out — indefinitely.
    """
    seed = hashlib.sha1(_normalise_address(address).encode("utf-8")).hexdigest()
    def _int_from(hex_slice: str, lo: int, hi: int) -> int:
        n = int(hex_slice, 16)
        return lo + (n % (hi - lo + 1))
    return ZillowProperty(
        zpid=f"mock-{seed[:10]}",
        address_formatted=address.strip() or "Unknown address",
        estimated_value=_int_from(seed[0:6], 250_000, 950_000),
        sqft=_int_from(seed[6:10], 900, 4500),
        lot_size_sqft=_int_from(seed[10:14], 3000, 20000),
        bed_count=float(_int_from(seed[14:16], 2, 6)),
        bath_count=float(_int_from(seed[16:18], 1, 4)),
        year_built=_int_from(seed[18:22], 1955, 2024),
        image_url=None,
        latitude=None, longitude=None,
        last_fetched_at=_now_iso(),
        raw={"mock": True, "seed": seed},
        cached=False,
        mock=True,
    )


# ── Response normalisation (real provider → ZillowProperty) ─────
def _extract_first_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """OpenWebNinja returns ``{results: [...]}`` for search-by-address."""
    if not isinstance(raw, dict):
        return {}
    for k in ("results", "properties", "data"):
        v = raw.get(k)
        if isinstance(v, list) and v:
            return v[0] if isinstance(v[0], dict) else {}
    return raw


def _map_provider_response(address: str, raw: Dict[str, Any]) -> ZillowProperty:
    first = _extract_first_result(raw)
    def _as_int(v) -> Optional[int]:
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    def _as_float(v) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    return ZillowProperty(
        zpid=str(first.get("zpid") or first.get("zpid_id") or "") or None,
        address_formatted=str(
            first.get("address")
            or first.get("streetAddress")
            or address
        ),
        estimated_value=_as_int(
            first.get("zestimate")
            or first.get("estimated_value")
            or first.get("price")
        ),
        sqft=_as_int(first.get("livingArea") or first.get("sqft")),
        lot_size_sqft=_as_int(first.get("lotAreaValue") or first.get("lot_size_sqft")),
        bed_count=_as_float(first.get("bedrooms") or first.get("beds")),
        bath_count=_as_float(first.get("bathrooms") or first.get("baths")),
        year_built=_as_int(first.get("yearBuilt") or first.get("year_built")),
        image_url=first.get("imgSrc") or first.get("image") or None,
        latitude=_as_float(first.get("latitude") or first.get("lat")),
        longitude=_as_float(first.get("longitude") or first.get("lng")),
        last_fetched_at=_now_iso(),
        raw=raw or {},
        cached=False,
        mock=False,
    )


# ── Rate limit (100 req/hr/tenant) ───────────────────────────────
async def _enforce_rate_limit(tenant_id: str, *, db=None) -> None:
    if db is None:
        db = _default_db()
    now = datetime.now(timezone.utc)
    hour_key = now.strftime("%Y-%m-%dT%H")
    # Atomic increment — get the new count back and enforce.
    res = await db[RATE_LIMIT_COLLECTION].find_one_and_update(
        {"tenant_id": tenant_id, "hour_key": hour_key},
        {"$inc": {"count": 1},
         "$set": {"updated_at": now.isoformat()},
         "$setOnInsert": {"created_at": now.isoformat()}},
        upsert=True, return_document=True,
    )
    # PyMongo drivers return the doc after the update when
    # ``return_document=True``; older motor versions return the
    # pre-update doc. Handle both defensively.
    if not res:
        return
    count = int(res.get("count") or 0)
    # ``find_one_and_update`` with default ``ReturnDocument.BEFORE``
    # yields the *previous* count; we want post-increment.
    if count < RATE_LIMIT_PER_HOUR + 1:
        # Read the post-update count explicitly.
        after = await db[RATE_LIMIT_COLLECTION].find_one(
            {"tenant_id": tenant_id, "hour_key": hour_key},
            {"_id": 0, "count": 1},
        )
        count = int((after or {}).get("count") or 0)
    if count > RATE_LIMIT_PER_HOUR:
        raise ZillowRateLimited(
            f"tenant {tenant_id} hit Zillow-enrich rate limit "
            f"({count}/{RATE_LIMIT_PER_HOUR} per hour)"
        )


async def get_rate_limit_state(tenant_id: str, *, db=None) -> Dict[str, Any]:
    if db is None:
        db = _default_db()
    hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    row = await db[RATE_LIMIT_COLLECTION].find_one(
        {"tenant_id": tenant_id, "hour_key": hour_key}, {"_id": 0},
    )
    return {
        "hour_key": hour_key,
        "used": int((row or {}).get("count") or 0),
        "cap": RATE_LIMIT_PER_HOUR,
    }


# ── Cache read/write (24h TTL) ───────────────────────────────────
async def _read_cache(address: str, *, db=None) -> Optional[ZillowProperty]:
    if db is None:
        db = _default_db()
    row = await db[CACHE_COLLECTION].find_one(
        {"address_hash": _address_hash(address)}, {"_id": 0},
    )
    if not row:
        return None
    fetched_at = row.get("last_fetched_at")
    try:
        dt = datetime.fromisoformat(fetched_at)
        if datetime.now(timezone.utc) - dt > timedelta(hours=CACHE_TTL_HOURS):
            return None
    except Exception:
        return None
    payload = row.get("payload") or {}
    payload["cached"] = True
    try:
        return ZillowProperty(**payload)
    except Exception:
        return None


async def _write_cache(prop: ZillowProperty, address: str, *, db=None) -> None:
    if db is None:
        db = _default_db()
    payload = prop.model_dump()
    payload["cached"] = False   # cached-flag is set on read, not stored
    await db[CACHE_COLLECTION].update_one(
        {"address_hash": _address_hash(address)},
        {"$set": {
            "address_hash": _address_hash(address),
            "address": address,
            "payload": payload,
            "last_fetched_at": prop.last_fetched_at,
        }},
        upsert=True,
    )


# ── Public API ───────────────────────────────────────────────────
async def fetch_zillow_property(
    address: str, *, tenant_id: str, force_refresh: bool = False, db=None,
) -> ZillowProperty:
    """Fetch (or cache-hit) Zillow data for ``address``.

    Raises:
        ZillowNotConfigured: neither provider key nor ``TESTMODE_MOCK``.
        ZillowRateLimited:   tenant hit the 100/hr cap.
    """
    if db is None:
        db = _default_db()
    address = (address or "").strip()
    if not address:
        raise ValueError("address is required")

    # Cache hit (24h TTL) — cheap and skips both rate-limit and
    # provider spend.
    if not force_refresh:
        cached = await _read_cache(address, db=db)
        if cached is not None:
            return cached

    mock_mode = _testmode_mock()
    if not mock_mode and not _provider_configured():
        raise ZillowNotConfigured(
            "Set ZILLOW_RAPIDAPI_KEY env var or enable "
            "ZILLOW_TESTMODE_MOCK=true for preview."
        )

    # Rate limit only counts live (non-cached) fetches — cache hits
    # are essentially free.
    await _enforce_rate_limit(tenant_id, db=db)

    if mock_mode:
        prop = _mock_property(address)
    else:
        # Reuse the mature adapter — the singleton factory in
        # ``zillow_adapter`` raises ``ZillowError(503,
        # "zillow_not_configured")`` when the provider key is
        # missing. We translate that to the historical
        # ``ZillowNotConfigured`` exception the router already
        # catches, so downstream contracts stay unchanged.
        try:
            client = get_zillow_client()
        except ZillowError as ze:
            if ze.status_code == 503 and ze.detail == "zillow_not_configured":
                raise ZillowNotConfigured(str(ze))
            # Any other structured error surfaces as-is — the router
            # catch-branch maps ``.status_code`` to HTTPException.
            raise
        # ``ZillowClient._call`` returns
        #   { unavailable: False, data: {...}, cached: bool }   OR
        #   { unavailable: True,  reason: "<REASON_*>" }
        # so we bridge the dict-return contract into the same
        # structured exception surface the rest of enrichment uses.
        result = await client.search_by_address(
            address, tenant_id=tenant_id,
        )
        if result.get("unavailable"):
            reason = result.get("reason") or REASON_PROVIDER_ERROR
            if reason == REASON_KEYS_NOT_CONFIGURED:
                raise ZillowNotConfigured(
                    "Zillow adapter reported keys_not_configured at call time."
                )
            if reason == REASON_QUOTA_EXHAUSTED:
                raise ZillowRateLimited(
                    "Zillow provider is in cool-down (429 quota memo).",
                )
            if reason == REASON_NOT_FOUND:
                raise ZillowError(
                    status_code=404,
                    detail="zillow_address_not_found",
                    message=f"Zillow has no record for address {address!r}.",
                )
            if reason == REASON_TEST_SCOPE_REFUSED:
                # Preview-pod hitting a real address that isn't in
                # the allow-list — surface as 403 so ops can spot
                # misconfigured preview env vs a real provider
                # outage in the logs.
                raise ZillowError(
                    status_code=403,
                    detail="zillow_test_scope_refused",
                    message=(
                        "Live Zillow calls are refused for this "
                        "address on non-production pods."
                    ),
                )
            # Genuine upstream failure — network timeout, non-JSON
            # response, 5xx status. THIS is the only path that
            # should ever surface as a 502 upstream.
            raise ZillowError(
                status_code=502,
                detail="zillow_upstream_error",
                message="Upstream Zillow provider failed the request.",
            )
        raw = result.get("data") or {}
        prop = _map_provider_response(address, raw)

    await _write_cache(prop, address, db=db)
    return prop


async def ensure_indexes(db=None) -> None:
    if db is None:
        db = _default_db()
    await db[RATE_LIMIT_COLLECTION].create_index(
        [("tenant_id", 1), ("hour_key", 1)], unique=True,
    )
