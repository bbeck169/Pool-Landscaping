"""Phase 17 · Feb-2026 — Google Geocoding wrapper with 30-day cache.

Google's ToS forbids indefinite address→latlng caching but allows up
to 30 days, which is what we honor. Cache keyed by normalized address
in ``db.geocode_cache`` so every call is idempotent + bounded.

Phase I1.7.e Chunk 3 (Feb-2026) additions:
  * :func:`_platform_geocode_http` — raw-httpx-plus-parse helper.
    Isolated so :mod:`services.maps.dispatcher` can call it directly
    for the platform-fallback branch WITHOUT going through
    :func:`geocode_address` (which would create recursion once the
    ``MAPS_BYO_ENABLED`` flag is on).
  * :func:`geocode_address` now takes ``tenant_id`` + ``db`` kwargs.
    When ``MAPS_BYO_ENABLED=true`` AND ``tenant_id`` is supplied the
    call routes through :func:`services.maps.dispatcher.dispatch_maps_geocode`
    so per-tenant BYO keys + monthly caps fire. When the flag is off,
    OR ``tenant_id=None``, behavior is byte-for-byte identical to the
    pre-Chunk-3 implementation.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import httpx

from config import db, logger
from services.google_maps.geocode_trigger import (
    GeocodeOutcome,
    GeocodeTrigger,
    write_geocode_log,
)

_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
_CACHE_TTL_DAYS = 30
_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"


def _normalize(addr: str) -> str:
    return re.sub(r"\s+", " ", (addr or "").strip().lower())


def _flatten_addr(raw: Any) -> str:
    """Feb-2026 · P37b · Tolerantly collapse a ``service_address`` value
    to a single string. Legacy rows persist ``service_address`` as a
    structured dict (``{street, city, state, postal_code|zip}``) while
    newer rows persist a free-form string. Callers used to assume
    string; the dict shape blew up the P37 backfill with an
    ``AttributeError`` on ``.strip()``. This helper is the single
    read-side normalizer.
    """
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        return " ".join(filter(None, [
            (raw.get("street") or "").strip(),
            (raw.get("city") or "").strip(),
            (raw.get("state") or "").strip(),
            (raw.get("postal_code") or raw.get("zip") or "").strip(),
        ])).strip()
    return ""


# Feb-2026 · Fix — Re-geocode button falsely reported "no address"
# because the fallback chain read only ``service_address`` +
# structured legacy fields, missing customers whose only populated
# address field was ``address`` / ``street_address`` / ``mailing_
# address``. This helper is the single source of truth for the
# resolution order — every caller MUST use it so the display path
# (which uses ``address``) and the geocode path stay in lockstep.
#
# Order:
#   1. ``service_address``        — canonical (may be free-form or dict).
#   2. ``address``                — the field the display renderer reads.
#   3. ``street_address``         — legacy admin-side alias.
#   4. ``mailing_address``        — billing fallback (last resort).
#   5. Structured composite      — ``service_street/city/state/zip`` OR
#                                    the legacy ``street/city/state/zip``.
def resolve_customer_address(customer: Dict[str, Any]) -> str:
    """Return the first non-empty address on ``customer`` (trimmed).

    Reads every field the various customer-writing paths have used
    over time. Returns empty string when NONE of them yield a
    non-empty value — that's the ``no_address`` signal callers
    should honor.
    """
    if not customer:
        return ""
    # Free-form / dict fields first (in priority order).
    for _k in ("service_address", "address", "street_address",
                 "mailing_address"):
        _v = _flatten_addr(customer.get(_k))
        if _v:
            return _v
    # Structured composite as a last resort. Accept either the
    # ``service_*`` prefix (new) or the bare fields (legacy).
    parts = list(filter(None, [
        (customer.get("service_street") or customer.get("street") or "").strip(),
        (customer.get("service_city")   or customer.get("city")   or "").strip(),
        (customer.get("service_state")  or customer.get("state")  or "").strip(),
        (customer.get("service_zip")    or customer.get("zip")    or "").strip(),
    ]))
    return " ".join(parts).strip()


# ═════════════════════════════════════════════════════════════════
# Phase I1.7.e · Chunk 3 · Feb-2026 — Platform raw-httpx impl.
# Extracted so :mod:`services.maps.dispatcher` can call it directly
# for the platform-fallback branch. Never touches the cache — that
# lives in :func:`geocode_address`.
# ═════════════════════════════════════════════════════════════════
async def _platform_geocode_http(address: str) -> Optional[Dict[str, Any]]:
    """Raw Google Geocoding v1 call + response parse. No cache. No
    persistence. Returns ``{lat, lng, formatted_address, place_id,
    precision}`` or ``None`` on ZERO_RESULTS / error / missing key."""
    if not address or not _API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_ENDPOINT, params={
                "address": address, "key": _API_KEY,
            })
            data = r.json()
    except Exception as exc:
        logger.warning("[geocode] http error for %r: %s", address, exc)
        return None
    if data.get("status") == "REQUEST_DENIED":
        logger.error("[geocode] REQUEST_DENIED — check GOOGLE_MAPS_API_KEY + Geocoding API enabled: %s", data.get("error_message"))
        return None
    results = data.get("results") or []
    if not results:
        return None
    top = results[0]
    loc = top["geometry"]["location"]
    return {
        "lat": loc["lat"], "lng": loc["lng"],
        "formatted_address": top.get("formatted_address"),
        "place_id": top.get("place_id"),
        "precision": top["geometry"].get("location_type"),
    }


async def geocode_address(
    address: str,
    *,
    tenant_id: Optional[str] = None,
    db_conn: Any = None,
    trigger_reason: GeocodeTrigger = GeocodeTrigger.UNKNOWN,
    entity_type: str = "unknown",
    entity_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return ``{lat, lng, formatted_address, place_id, precision}`` or
    None on ZERO_RESULTS / error. Never raises.

    Phase I1.7.e Chunk 3 (Feb-2026): when ``MAPS_BYO_ENABLED=true``
    AND ``tenant_id`` is supplied, routes through the BYO Maps
    dispatcher so per-tenant BYO keys + monthly caps fire. When the
    flag is off, OR ``tenant_id`` is None, uses
    :func:`_platform_geocode_http` directly — byte-for-byte
    identical to the pre-Chunk-3 code path.

    P0-GEOCODE-LEAK-C2 (Feb-2026): writes exactly ONE row into
    ``db.geocode_call_log`` per invocation via fail-safe
    :func:`write_geocode_log`.  ``trigger_reason`` propagates from
    every caller (routers / lifespan / admin backfill) so the Phase
    3 ``migration_status`` sentinel + diagnostics endpoint can
    attribute spend accurately.  Telemetry outage is swallowed —
    the geocode flow is NEVER blocked by a log-write failure.
    """
    _started_at = datetime.now(timezone.utc)
    _trigger_value = (
        trigger_reason.value
        if isinstance(trigger_reason, GeocodeTrigger)
        else str(trigger_reason or GeocodeTrigger.UNKNOWN.value)
    )

    async def _log(outcome: GeocodeOutcome,
                    *, lat: Optional[float] = None,
                    lng: Optional[float] = None,
                    error: Optional[str] = None) -> None:
        await write_geocode_log(
            db_conn=db, logger=logger,
            tenant_id=tenant_id, entity_type=entity_type,
            entity_id=entity_id, address=address or "",
            trigger_reason=_trigger_value, outcome=outcome.value,
            lat=lat, lng=lng, error=error,
            started_at=_started_at, api_key=_API_KEY,
        )

    if not address:
        await _log(GeocodeOutcome.NO_ADDR)
        return None
    norm = _normalize(address)
    now = datetime.now(timezone.utc)

    cached = await db.geocode_cache.find_one({"key": norm}, {"_id": 0})
    if cached:
        try:
            cached_at = datetime.fromisoformat(
                cached["cached_at"].replace("Z", "+00:00")
            )
            if now - cached_at < timedelta(days=_CACHE_TTL_DAYS):
                _res = cached.get("result") or {}
                await _log(
                    GeocodeOutcome.SKIPPED_CACHED,
                    lat=_res.get("lat"), lng=_res.get("lng"),
                )
                return cached.get("result")
        except Exception:
            pass

    result: Optional[Dict[str, Any]] = None
    # Chunk 3 · Feb-2026 — feature-flag gate.
    try:
        from services.maps.feature_flag import maps_byo_enabled
        from services.maps.dispatcher import dispatch_maps_geocode
        from services.maps.models import TenantMapsRequestCapExceeded
    except Exception:  # pragma: no cover
        maps_byo_enabled = lambda: False  # noqa: E731
        dispatch_maps_geocode = None
        TenantMapsRequestCapExceeded = Exception

    use_dispatcher = bool(
        tenant_id and maps_byo_enabled() and dispatch_maps_geocode is not None
    )
    if use_dispatcher:
        try:
            env = await dispatch_maps_geocode(
                tenant_id=tenant_id, address=address, db=db_conn,
            )
            if env and (env.lat or env.lng or env.formatted_address):
                result = {
                    "lat": float(env.lat),
                    "lng": float(env.lng),
                    "formatted_address": env.formatted_address,
                    "place_id": env.provider_response_id,
                    "precision": (env.raw or {}).get("precision"),
                }
        except TenantMapsRequestCapExceeded as cap:
            logger.warning(
                "[geocode] tenant=%s cap exceeded provider=%s used=%s/%s — "
                "skipping",
                tenant_id, cap.provider, cap.used, cap.cap,
            )
            await _log(
                GeocodeOutcome.ERROR,
                error=f"TenantMapsRequestCapExceeded:{cap.provider}:{cap.used}/{cap.cap}",
            )
            return None
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("[geocode] dispatcher error: %s", e)
            result = None
            await _log(
                GeocodeOutcome.ERROR,
                error=f"{type(e).__name__}:{str(e)[:200]}",
            )
            # Still fall through to the cache upsert path for parity
            # with the pre-C2 contract (we DON'T re-raise).
    else:
        try:
            result = await _platform_geocode_http(address)
        except Exception as e:        # pragma: no cover — defensive
            logger.warning("[geocode] http path error: %s", e)
            result = None
            await _log(
                GeocodeOutcome.ERROR,
                error=f"{type(e).__name__}:{str(e)[:200]}",
            )

    await db.geocode_cache.update_one(
        {"key": norm},
        {"$set": {"key": norm, "result": result,
                  "cached_at": now.isoformat()}},
        upsert=True,
    )
    if result:
        await _log(
            GeocodeOutcome.HIT,
            lat=result.get("lat"), lng=result.get("lng"),
        )
    # Error already logged above when applicable; nothing further to
    # write here (an unlogged ``result=None`` would indicate the
    # ZERO_RESULTS path through ``_platform_geocode_http``).
    elif use_dispatcher is False:
        await _log(GeocodeOutcome.ERROR, error="zero_results_or_no_key")
    return result


async def geocode_and_persist_customer(
    customer_id: str, tenant_id: str,
    *, trigger_reason: GeocodeTrigger = GeocodeTrigger.UNKNOWN,
) -> bool:
    """Compose the customer's canonical address from either
    ``service_address`` (free-form) or the structured street/city/state/
    zip fields, geocode it, and write lat/lng + GeoJSON to the doc.
    Idempotent — skips if ``geocoded_at`` < 30d old.

    P0-GEOCODE-LEAK-C2: propagates ``trigger_reason`` to the core
    :func:`geocode_address` for diagnostics attribution.  When the
    30-day ``geocoded_at`` short-circuit fires the wrapper writes a
    ``skipped_cached`` log row directly so the ratio of skipped vs
    hit calls is visible in ``/admin/diagnostics/geocode-usage``.
    """
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not cust:
        return False
    _trig = trigger_reason.value if isinstance(trigger_reason, GeocodeTrigger) \
        else str(trigger_reason or GeocodeTrigger.UNKNOWN.value)
    if cust.get("geocoded_at"):
        try:
            g = datetime.fromisoformat(cust["geocoded_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - g < timedelta(days=_CACHE_TTL_DAYS):
                await write_geocode_log(
                    db_conn=db, logger=logger,
                    tenant_id=tenant_id, entity_type="customer",
                    entity_id=customer_id,
                    address=resolve_customer_address(cust),
                    trigger_reason=_trig,
                    outcome=GeocodeOutcome.SKIPPED_CACHED.value,
                    lat=cust.get("latitude") or cust.get("service_lat"),
                    lng=cust.get("longitude") or cust.get("service_lng"),
                    api_key=_API_KEY,
                )
                return False
        except Exception:
            pass
    # Feb-2026 · Fix — Re-geocode button. The fallback chain now
    # walks EVERY historical address field (``service_address`` →
    # ``address`` → ``street_address`` → ``mailing_address`` →
    # structured composite) so a customer whose only populated
    # field is the display-renderer's ``address`` still geocodes.
    addr = resolve_customer_address(cust)
    if not addr.strip():
        return False
    hit = await geocode_address(
        addr, tenant_id=tenant_id,
        trigger_reason=trigger_reason,
        entity_type="customer", entity_id=customer_id,
    )
    if not hit:
        return False
    await db.customers.update_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"$set": {
            "service_lat": hit["lat"], "service_lng": hit["lng"],
            # Feb-2026 · P37a — canonical lat/lng fields mirrored
            # alongside the legacy ``service_lat/lng`` so every
            # downstream caller can read a single field pair.
            "latitude": hit["lat"], "longitude": hit["lng"],
            "geocode_precision": hit.get("precision"),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
            "geocode_source": "google",
            "service_location": {"type": "Point",
                                   "coordinates": [hit["lng"], hit["lat"]]},
        }},
    )
    return True


# ═════════════════════════════════════════════════════════════════
# Feb-2026 · P37a — Job + Property geocode helpers.
# Same 30-day cache + on-write persistence pattern as customers.
# Persist to BOTH the legacy field pair (``site_lat/lng`` for jobs;
# properties get canonical ``latitude/longitude``) AND the unified
# ``latitude/longitude`` field pair so downstream callers can pick.
# ═════════════════════════════════════════════════════════════════

async def geocode_and_persist_job(
    job_id: str, tenant_id: str,
    *, trigger_reason: GeocodeTrigger = GeocodeTrigger.UNKNOWN,
) -> bool:
    """Compose the job's address from its own ``service_address`` /
    structured fields OR from its linked customer, geocode it, and
    write ``site_lat/lng`` + ``latitude/longitude`` + ``geocoded_at``.
    Idempotent — skips if ``geocoded_at`` < 30d old. Silent on
    missing key / ZERO_RESULTS."""
    job = await db.jobs.find_one(
        {"id": job_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not job:
        return False
    if job.get("geocoded_at"):
        try:
            g = datetime.fromisoformat(job["geocoded_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - g < timedelta(days=_CACHE_TTL_DAYS):
                return False
        except Exception:
            pass

    addr = _flatten_addr(job.get("service_address"))
    if not addr:
        addr = " ".join(filter(None, [
            job.get("service_street"), job.get("service_city"),
            job.get("service_state"), job.get("service_zip"),
        ])).strip()
    if not addr and job.get("customer_id"):
        # Fall back to the customer's address.
        cust = await db.customers.find_one(
            {"id": job["customer_id"], "tenant_id": tenant_id},
            {"_id": 0, "service_address": 1, "address": 1,
              "service_street": 1, "service_city": 1,
              "service_state": 1, "service_zip": 1,
              "latitude": 1, "longitude": 1,
              "service_lat": 1, "service_lng": 1},
        ) or {}
        # If the customer is already geocoded, inherit the fix
        # directly rather than re-geocode.
        c_lat = cust.get("latitude") or cust.get("service_lat")
        c_lng = cust.get("longitude") or cust.get("service_lng")
        if c_lat is not None and c_lng is not None:
            await db.jobs.update_one(
                {"id": job_id, "tenant_id": tenant_id},
                {"$set": {
                    "site_lat": c_lat, "site_lng": c_lng,
                    "latitude": c_lat, "longitude": c_lng,
                    "geocoded_at": datetime.now(timezone.utc).isoformat(),
                    "geocode_source": "inherited_from_customer",
                }},
            )
            return True
        addr = (_flatten_addr(cust.get("service_address"))
                or (cust.get("address") if isinstance(cust.get("address"), str) else "")
                or " ".join(filter(None, [
                    cust.get("service_street"), cust.get("service_city"),
                    cust.get("service_state"), cust.get("service_zip"),
                ]))).strip()
    if not addr:
        return False
    hit = await geocode_address(
        addr, tenant_id=tenant_id,
        trigger_reason=trigger_reason,
        entity_type="job", entity_id=job_id,
    )
    if not hit:
        return False
    await db.jobs.update_one(
        {"id": job_id, "tenant_id": tenant_id},
        {"$set": {
            "site_lat": hit["lat"], "site_lng": hit["lng"],
            "latitude": hit["lat"], "longitude": hit["lng"],
            "geocode_precision": hit.get("precision"),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
            "geocode_source": "google",
        }},
    )
    return True


async def geocode_and_persist_property(property_id: str,
                                              tenant_id: str,
                                              *,
                                              trigger_reason: GeocodeTrigger = GeocodeTrigger.UNKNOWN,
                                              ) -> bool:
    """Property version of the customer helper. Persists to the
    canonical ``latitude/longitude`` + ``geocoded_at``.

    Feb-2026 · Skip-jobs postmortem — emit a structured trace line on
    every call outcome so operators can post-verify a backfill run
    end-to-end. The ``method`` tag disambiguates:

      * ``"google"``   — Google hit + write landed.
      * ``"cache"``    — within the ``_CACHE_TTL_DAYS`` window; skipped.
      * ``"no_addr"``  — property had no resolvable address string.
      * ``"missing"``  — property id didn't match any row.
      * ``"no_hit"``   — Google returned nothing.

    Reads a `[geocode-property]` prefix so the lines are grep-friendly
    (`sudo tail -n 2000 /var/log/supervisor/backend.*.log | \\
      grep '\\[geocode-property\\]'`).
    """
    prop = await db.properties.find_one(
        {"id": property_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not prop:
        logger.info(
            "[geocode-property] pid=%s tenant=%s method=missing",
            property_id, tenant_id,
        )
        return False
    old_lat = prop.get("latitude")
    old_lng = prop.get("longitude")
    if prop.get("geocoded_at"):
        try:
            g = datetime.fromisoformat(prop["geocoded_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - g < timedelta(days=_CACHE_TTL_DAYS):
                logger.info(
                    "[geocode-property] pid=%s tenant=%s method=cache "
                    "old=(%s, %s) geocoded_at=%s",
                    property_id, tenant_id, old_lat, old_lng,
                    prop.get("geocoded_at"),
                )
                # P0-GEOCODE-LEAK-C2: log the wrapper-level cache
                # short-circuit so the diagnostics endpoint can
                # compare ``skipped_cached`` vs ``hit`` ratios.
                _trig = trigger_reason.value if isinstance(trigger_reason, GeocodeTrigger) \
                    else str(trigger_reason or GeocodeTrigger.UNKNOWN.value)
                try:
                    _addr_doc = prop.get("address") or {}
                    _addr_str = " ".join(filter(None, [
                        _addr_doc.get("line1") or _addr_doc.get("address_line1"),
                        _addr_doc.get("city"), _addr_doc.get("state"),
                        _addr_doc.get("postal_code") or _addr_doc.get("zip"),
                    ])).strip()
                except Exception:
                    _addr_str = ""
                await write_geocode_log(
                    db_conn=db, logger=logger,
                    tenant_id=tenant_id, entity_type="property",
                    entity_id=property_id, address=_addr_str,
                    trigger_reason=_trig,
                    outcome=GeocodeOutcome.SKIPPED_CACHED.value,
                    lat=old_lat, lng=old_lng, api_key=_API_KEY,
                )
                return False
        except Exception:
            pass
    address_doc = prop.get("address") or {}
    # TD-57 · Feb-2026 — accept BOTH address-key schemas. The current
    # ``routers/properties.py::_AddressIn`` validator persists under
    # ``address.line1 / line2 / postal_code`` and actively nullifies
    # the legacy ``address_line1 / address_line2`` keys on every
    # write; pre-P37-migration docs may still carry the legacy
    # ``address_line1 / zip`` shape in Mongo. Read both, prefer the
    # current canonical shape (since any live-writer path emits it),
    # fall back to legacy for un-migrated rows. ``city`` + ``state``
    # share the same key under both schemas so no fallback is
    # needed there. Sibling callers ``services/stop_geo.py::
    # _fmt_property_address`` and the P37 backfill migration both
    # use the canonical shape; this helper is the only outlier that
    # read legacy-only, which made the TD-40 fire-and-forget call a
    # no-op for every property created via the Pydantic-validated
    # admin endpoint. See TECH_DEBT.md · TD-57 for the full
    # reclassification story.
    _line1 = address_doc.get("line1") or address_doc.get("address_line1")
    _line2 = address_doc.get("line2") or address_doc.get("address_line2")
    _postal = address_doc.get("postal_code") or address_doc.get("zip")
    addr = " ".join(filter(None, [
        _line1, _line2,
        address_doc.get("city"), address_doc.get("state"),
        _postal,
    ])).strip()
    if not addr:
        logger.info(
            "[geocode-property] pid=%s tenant=%s method=no_addr "
            "old=(%s, %s)",
            property_id, tenant_id, old_lat, old_lng,
        )
        return False
    hit = await geocode_address(
        addr, tenant_id=tenant_id,
        trigger_reason=trigger_reason,
        entity_type="property", entity_id=property_id,
    )
    if not hit:
        logger.info(
            "[geocode-property] pid=%s tenant=%s method=no_hit "
            "addr=%r old=(%s, %s)",
            property_id, tenant_id, addr[:120], old_lat, old_lng,
        )
        return False
    await db.properties.update_one(
        {"id": property_id, "tenant_id": tenant_id},
        {"$set": {
            "latitude": hit["lat"], "longitude": hit["lng"],
            "geocode_precision": hit.get("precision"),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
            "geocode_source": "google",
        }},
    )
    logger.info(
        "[geocode-property] pid=%s tenant=%s method=google "
        "old=(%s, %s) new=(%s, %s) precision=%s",
        property_id, tenant_id, old_lat, old_lng,
        hit["lat"], hit["lng"], hit.get("precision"),
    )
    return True
