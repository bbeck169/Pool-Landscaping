"""CAD Studio backend router.

Phase CAD-1 · Feb-2026 — extends the original ``/api/designs``
CRUD with a server-proxied Google Static Maps backdrop
(``GET /api/cad/map-tile``) so the FE never sees
``GOOGLE_MAPS_API_KEY``. Geocoded coordinates are cached in a
``geocode_cache`` collection (30-day TTL enforced by
``db_indexes.py``).

All routes are admin-only + tenant-scoped, matching the original
CRUD contract.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


class DesignIn(BaseModel):
    name: str = "Untitled design"
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    canvas_w_ft: float = 60.0
    canvas_h_ft: float = 40.0
    boundary: List[Any] = Field(default_factory=list)
    elements: List[Any] = Field(default_factory=list)
    area_sqft: float = 0.0
    perimeter_ft: float = 0.0
    thumbnail: Optional[str] = None
    # Phase CAD-1 · Feb-2026 — Map-backdrop foundation. All optional
    # so pre-existing designs keep serialising as before.
    map_center_lat: Optional[float] = None
    map_center_lng: Optional[float] = None
    map_zoom: Optional[int] = None
    feet_per_pixel: Optional[float] = None
    map_size_px: Optional[Dict[str, int]] = None


def _doc_public(d: dict) -> dict:
    d.pop("_id", None)
    return d


def _design_write_dict(body: DesignIn) -> Dict[str, Any]:
    """Fields persisted on both create + update. Kept as a helper so
    the two handlers stay in sync when Phase CAD-1 (and later) add
    optional fields."""
    return {
        "name": body.name or "Untitled design",
        "customer_id": body.customer_id,
        "lead_id": body.lead_id,
        "canvas_w_ft": body.canvas_w_ft,
        "canvas_h_ft": body.canvas_h_ft,
        "boundary": body.boundary,
        "elements": body.elements,
        "area_sqft": body.area_sqft,
        "perimeter_ft": body.perimeter_ft,
        "thumbnail": body.thumbnail,
        "map_center_lat": body.map_center_lat,
        "map_center_lng": body.map_center_lng,
        "map_zoom": body.map_zoom,
        "feet_per_pixel": body.feet_per_pixel,
        "map_size_px": body.map_size_px,
    }


@router.post("/designs")
async def create_design(body: DesignIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    now = now_iso()
    doc: Dict[str, Any] = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    doc.update(_design_write_dict(body))
    await db.designs.insert_one(doc)
    return _doc_public(doc)


@router.get("/designs")
async def list_designs(customer_id: Optional[str] = Query(None),
                       lead_id: Optional[str] = Query(None),
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    docs = await db.designs.find(
        q,
        {"_id": 0, "elements": 0, "boundary": 0},
    ).sort("updated_at", -1).to_list(300)
    return docs


@router.get("/designs/{did}")
async def get_design(did: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    d = await db.designs.find_one({"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Design not found")
    return d


@router.put("/designs/{did}")
async def update_design(did: str, body: DesignIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    d = await db.designs.find_one({"id": did, "tenant_id": tenant["id"]})
    if not d:
        raise HTTPException(404, "Design not found")
    update = _design_write_dict(body)
    update["updated_at"] = now_iso()
    await db.designs.update_one({"id": did, "tenant_id": tenant["id"]}, {"$set": update})
    return await get_design(did, user, tenant)


@router.delete("/designs/{did}")
async def delete_design(did: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    await db.designs.delete_one({"id": did, "tenant_id": tenant["id"]})
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# Phase CAD-1 · Map-tile backdrop
# ═══════════════════════════════════════════════════════════════════

STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Zoom clamps per Phase CAD-1 spec — Static Maps supports 0..21 but
# only 15..21 is useful for property-scale drawings.
_ZOOM_MIN, _ZOOM_MAX = 15, 21
# Google Static Maps free size ceiling is 640×640 (1280×1280 with
# scale=2); we're pinned to scale=1 for exact feet-per-pixel math,
# so 1280 is the pragmatic ceiling.
_SIZE_MIN, _SIZE_MAX = 200, 1280


def _normalize_address(a: str) -> str:
    """Lower-case, strip, collapse whitespace. Deterministic input
    for the sha256 cache key so tiny formatting variations collapse
    onto a single geocode-cache row."""
    return re.sub(r"\s+", " ", (a or "").strip().lower())


def _address_hash(a: str) -> str:
    return hashlib.sha256(_normalize_address(a).encode("utf-8")).hexdigest()


def _feet_per_pixel(lat: float, zoom: int) -> float:
    """Metres-per-pixel at Google's Web Mercator zoom ``z`` and
    latitude ``lat``: ``156543.03392 * cos(lat°) / 2^z``. Converted
    to feet via the exact multiplier ``3.28084``.

    Endpoint pins ``scale=1`` on the Static Maps request so the
    returned value corresponds one-to-one with displayed pixels.
    """
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom) * 3.28084


def _google_key() -> str:
    return (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()


async def _geocode_live(address: str) -> Optional[Dict[str, Any]]:
    """Call Google Geocoding. Returns ``{lat, lng, formatted}`` or
    ``None`` on any failure (missing key / non-200 / no results /
    network error). Callers decide the user-facing error code."""
    key = _google_key()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                GEOCODE_URL, params={"address": address, "key": key},
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[cad] geocode network error for {address!r}: {e}")
        return None
    if r.status_code != 200:
        logger.warning(f"[cad] geocode HTTP {r.status_code}")
        return None
    try:
        j = r.json()
    except Exception:
        return None
    if j.get("status") != "OK" or not j.get("results"):
        return None
    top = j["results"][0]
    loc = top.get("geometry", {}).get("location", {})
    lat = loc.get("lat")
    lng = loc.get("lng")
    if lat is None or lng is None:
        return None
    return {
        "lat": float(lat),
        "lng": float(lng),
        "formatted": top.get("formatted_address", "") or "",
    }


async def _fetch_static_map_bytes(
    *, lat: float, lng: float, zoom: int, width: int, height: int,
) -> bytes:
    """Fetch the Static Maps PNG. Raises
    ``HTTPException(424, google_maps_key_missing)`` when the API key
    is not configured and ``HTTPException(502, map_tile_upstream_error)``
    when Google returns non-200 or the network call itself fails."""
    key = _google_key()
    if not key:
        raise HTTPException(
            424, {"error_code": "google_maps_key_missing"},
        )
    params = {
        "center": f"{lat},{lng}",
        "zoom": str(zoom),
        "size": f"{width}x{height}",
        "scale": "1",
        "maptype": "satellite",
        "key": key,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(STATIC_MAPS_URL, params=params)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            502,
            {"error_code": "map_tile_upstream_error",
             "detail": f"network: {type(e).__name__}"},
        )
    if r.status_code != 200:
        body = ""
        try:
            body = r.text[:200]
        except Exception:
            pass
        raise HTTPException(
            502,
            {"error_code": "map_tile_upstream_error",
             "detail": f"upstream {r.status_code}: {body}"},
        )
    return r.content


@router.get("/cad/map-tile")
async def get_map_tile(
    customer_id: str = Query(..., min_length=1),
    zoom: int = Query(19),
    size: str = Query("800x500"),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Return a satellite backdrop PNG for the customer's address.

    Response headers ``X-Map-Lat`` / ``X-Map-Lng`` / ``X-Map-Zoom``
    / ``X-Feet-Per-Pixel`` / ``X-Geocode-Source`` carry the
    server-side metadata the CAD editor needs to render the scale
    bar and persist coordinates on the design doc. Never exposes
    the Google API key to the browser.
    """
    # Zoom clamp.
    try:
        z = int(zoom)
    except (TypeError, ValueError):
        raise HTTPException(400, {"error_code": "invalid_zoom_param"})
    z = max(_ZOOM_MIN, min(_ZOOM_MAX, z))
    # Size parse + clamp.
    try:
        w_str, h_str = (size or "").lower().split("x", 1)
        w = max(_SIZE_MIN, min(_SIZE_MAX, int(w_str)))
        h = max(_SIZE_MIN, min(_SIZE_MAX, int(h_str)))
    except Exception:
        raise HTTPException(400, {"error_code": "invalid_size_param"})
    # Customer lookup (tenant-scoped).
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant["id"]},
        {"_id": 0, "address": 1, "id": 1},
    )
    if not cust:
        raise HTTPException(404, {"error_code": "customer_not_found"})
    address = (cust.get("address") or "").strip()
    if not address:
        raise HTTPException(
            424, {"error_code": "customer_address_missing"},
        )
    # Geocode-cache lookup.
    addr_hash = _address_hash(address)
    source = "cache"
    cached = await db.geocode_cache.find_one(
        {"address_hash": addr_hash}, {"_id": 0},
    )
    if cached and cached.get("lat") is not None and cached.get("lng") is not None:
        lat = float(cached["lat"])
        lng = float(cached["lng"])
    else:
        source = "live"
        gc = await _geocode_live(address)
        if not gc:
            if not _google_key():
                raise HTTPException(
                    424, {"error_code": "google_maps_key_missing"},
                )
            raise HTTPException(
                424, {"error_code": "geocode_failed"},
            )
        lat, lng = gc["lat"], gc["lng"]
        # Best-effort cache write; TTL is set by the ``created_at``
        # BSON Date + the ``geocode_cache`` index in ``db_indexes.py``.
        try:
            await db.geocode_cache.update_one(
                {"address_hash": addr_hash},
                {"$set": {
                    "address_hash": addr_hash,
                    "lat": lat,
                    "lng": lng,
                    "formatted_address": gc.get("formatted", ""),
                    "created_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[cad] geocode cache write failed: {e}")
    # Fetch Static Maps PNG.
    png = await _fetch_static_map_bytes(
        lat=lat, lng=lng, zoom=z, width=w, height=h,
    )
    fpp = _feet_per_pixel(lat, z)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Map-Lat": f"{lat:.7f}",
            "X-Map-Lng": f"{lng:.7f}",
            "X-Map-Zoom": str(z),
            "X-Feet-Per-Pixel": f"{fpp:.6f}",
            "X-Geocode-Source": source,
            # Custom headers must be listed on ``Access-Control-
            # Expose-Headers`` for cross-origin ``fetch()`` to read
            # them via ``response.headers.get(...)``.
            "Access-Control-Expose-Headers":
                "X-Map-Lat, X-Map-Lng, X-Map-Zoom, "
                "X-Feet-Per-Pixel, X-Geocode-Source",
        },
    )
