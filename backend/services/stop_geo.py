"""Feb-2026 · Slice 4 (MP1.6) — Stop-geo resolver.

A "stop" on a tech's daily route is a ``jobs`` document. Historically
the optimizer keyed off ``job.site_lat/lng`` (falling back to
``job.lat/lng``) — which mirrored the customer's default address only.
Multi-property (MP1/MP1.5/MP2) added ``jobs.property_id`` so a single
customer can own multiple service addresses; the optimizer never
learned to prefer the property's coordinates for those jobs, so a
Peoria pool and a Vistancia pool on the same customer looked like the
same coordinate to the router.

This module is the single source of truth for "what are the coords +
address the router should use for this stop". Read + optimize paths
both call it so they can never disagree.

Resolution order
----------------
1. ``job.property_id`` set and ``properties.{lat,lng}`` present → use
   the property's coords + address (``address_source = "property"``).
2. ``job.property_id`` set but the property has no geocode YET → if
   ``geocode_if_missing`` is True, geocode via
   ``routers.google._geocode_one`` once, persist onto the property
   doc (``lat``, ``lng``, ``geocoded_address``, ``geocoded_place_id``,
   ``geocoded_at``) so subsequent runs are cache hits.
3. Otherwise fall back to ``job.site_lat/lng`` or ``job.lat/lng`` +
   the customer's default address (``address_source = "customer"``).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from config import db, logger


def _fmt_property_address(addr: Any) -> str:
    if not isinstance(addr, dict):
        return str(addr or "")
    parts = [
        addr.get("line1"),
        addr.get("line2"),
        addr.get("city"),
        addr.get("state"),
        addr.get("postal_code"),
    ]
    return ", ".join(p for p in parts if p)


async def resolve_stop_geo(
    job: Dict[str, Any],
    tenant_id: str,
    *,
    geocode_if_missing: bool = False,
) -> Dict[str, Any]:
    """Return ``{lat, lng, address, address_source}`` for a stop.

    ``address_source`` is ``"property"`` when the coords / address came
    from the property doc (multi-property mode), and ``"customer"``
    when they came from the customer / job fallback.

    Never raises — a stop with no resolvable geo returns ``lat=None,
    lng=None`` with ``address_source = "customer"`` and callers must
    handle the missing coords the same way they did before this
    refactor (nearest-neighbor skips them).
    """
    property_id = job.get("property_id")
    if property_id:
        prop = await db.properties.find_one(
            {"id": property_id, "tenant_id": tenant_id}, {"_id": 0},
        )
        if prop:
            lat = prop.get("lat") or prop.get("hq_lat")
            lng = prop.get("lng") or prop.get("hq_lng")
            addr_str = _fmt_property_address(prop.get("address"))
            if (lat is None or lng is None) and geocode_if_missing and addr_str:
                # Lazy backfill — geocode this property once, persist
                # the result on the property doc so the next optimizer
                # run is a cache hit.
                try:
                    import httpx

                    from routers.google import _geocode_one
                    from utils import now_iso

                    async with httpx.AsyncClient(timeout=10) as client:
                        geo = await _geocode_one(client, addr_str)
                    if geo and geo.get("lat") is not None:
                        lat = geo["lat"]
                        lng = geo["lng"]
                        await db.properties.update_one(
                            {"id": property_id, "tenant_id": tenant_id},
                            {"$set": {
                                "lat": lat,
                                "lng": lng,
                                "geocoded_address": geo.get("formatted"),
                                "geocoded_place_id": geo.get("place_id"),
                                "geocoded_at": now_iso(),
                            }},
                        )
                except Exception as exc:  # pragma: no cover — best-effort
                    logger.warning(
                        f"property {property_id} geocode failed: {exc}"
                    )
            if lat is not None and lng is not None:
                return {
                    "lat": lat,
                    "lng": lng,
                    "address": addr_str or None,
                    "address_source": "property",
                    "property_id": property_id,
                }
            # Property doc exists but still no geocode — fall through
            # so we don't lie about the address_source, but expose the
            # property address string so the UI can render it.
            if addr_str:
                return {
                    "lat": None,
                    "lng": None,
                    "address": addr_str,
                    "address_source": "property",
                    "property_id": property_id,
                }

    # Fallback — customer-scoped coords + address (current behaviour).
    lat = job.get("site_lat") or job.get("lat")
    lng = job.get("site_lng") or job.get("lng")
    addr = (
        job.get("address")
        or job.get("service_address")
        or job.get("customer_address")
    )
    return {
        "lat": lat,
        "lng": lng,
        "address": addr,
        "address_source": "customer",
        "property_id": None,
    }
