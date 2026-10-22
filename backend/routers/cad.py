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
from utils import now_iso, new_id, require_admin, require_admin_or_manager
from routers.tenants import get_current_tenant

router = APIRouter()


# TD-cad-phase1 · Oct-2026 — vendor-split clarifier. The CAD surface
# uses **Google Static Maps** (``maps.googleapis.com/maps/api/staticmap``)
# via ``GOOGLE_MAPS_API_KEY`` — see ``_fetch_static_map_bytes`` below.
# The project ALSO carries ``MAPBOX_ACCESS_TOKEN`` in ``.env`` but that
# token is consumed by *other* surfaces (``routers.property``,
# ``routers.gps_route``, ``services.maps.dispatcher``,
# ``services.reverse_geocoder``, ``services.gps_stops_batch``) — NOT by
# ``cad.py``. Any vendor-cleanup refactor must keep ``MAPBOX_ACCESS_TOKEN``
# in place; removing it breaks the 5 surfaces listed above. The Phase 0
# scoping doc (``memory/td_cad_phase0_scoping.md § 3.3``) incorrectly
# flagged the token as dead config; this inline comment is the
# authoritative correction.
#
# TD-cad-phase1 · Oct-2026 — role widening on the 5 ``/designs`` CRUD
# endpoints: ``require_admin`` → ``require_admin_or_manager`` to let
# the ``manager`` role (newly widened in utils.py:231 per Phase 34 Task
# X) use the admin CAD tool. The map-tile + generate + site-plan-pdf
# endpoints keep ``require_admin`` — they consume AI credits / Google
# Maps quota and remain restricted to the narrower admin tier.


class DesignIn(BaseModel):
    name: str = "Untitled design"
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    # TD-cad-phase1 · Oct-2026 — additive-nullable attach fields so a
    # design can hang off a specific property OR quote in addition to
    # the pre-existing customer/lead attach. Backward-compat: existing
    # designs serialise without either field; the ``_design_write_dict``
    # helper writes ``None`` for pre-existing docs on update.
    property_id: Optional[str] = None
    quote_id: Optional[str] = None
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
    # Phase CAD-2 · Feb-2026 — precision-tools snapping threshold.
    # In on-canvas pixel units; the frontend snaps vertices within
    # this radius of any existing edge (boundary + element edges).
    snap_threshold_px: Optional[int] = 8


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
        # TD-cad-phase1 · Oct-2026 — additive attach fields.
        "property_id": body.property_id,
        "quote_id": body.quote_id,
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
        "snap_threshold_px": body.snap_threshold_px,
    }


@router.post("/designs")
async def create_design(body: DesignIn,
                        user: dict = Depends(require_admin_or_manager),
                        tenant: dict = Depends(get_current_tenant)):
    # TD-cad-phase1 · Oct-2026 — tenant-scoped FK validation on
    # property_id + quote_id; cross-tenant → 404 (parity with the
    # existing _404 behavior for a missing design doc).
    await _validate_fk_refs(body, tenant["id"])
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
                       property_id: Optional[str] = Query(None),
                       quote_id: Optional[str] = Query(None),
                       user: dict = Depends(require_admin_or_manager),
                       tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    # TD-cad-phase1 · Oct-2026 — additive filters.
    if property_id:
        q["property_id"] = property_id
    if quote_id:
        q["quote_id"] = quote_id
    docs = await db.designs.find(
        q,
        {"_id": 0, "elements": 0, "boundary": 0},
    ).sort("updated_at", -1).to_list(300)
    return docs


@router.get("/designs/{did}")
async def get_design(did: str,
                     user: dict = Depends(require_admin_or_manager),
                     tenant: dict = Depends(get_current_tenant)):
    d = await db.designs.find_one({"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Design not found")
    # Phase CAD-3 · Feb-2026 — surface media attachments (site plan
    # PDFs etc.) inline on the design payload so the editor can
    # render an attachments strip without a second round-trip.
    media = await db.design_media.find(
        {"design_id": did, "tenant_id": tenant["id"]},
        {"_id": 0},
    ).sort("generated_at", -1).to_list(50)
    d["media_attachments"] = media
    return d


@router.put("/designs/{did}")
async def update_design(did: str, body: DesignIn,
                        user: dict = Depends(require_admin_or_manager),
                        tenant: dict = Depends(get_current_tenant)):
    d = await db.designs.find_one({"id": did, "tenant_id": tenant["id"]})
    if not d:
        raise HTTPException(404, "Design not found")
    # TD-cad-phase1 · Oct-2026 — same cross-tenant FK validation on
    # update as on create.
    await _validate_fk_refs(body, tenant["id"])
    update = _design_write_dict(body)
    update["updated_at"] = now_iso()
    await db.designs.update_one({"id": did, "tenant_id": tenant["id"]}, {"$set": update})
    return await get_design(did, user, tenant)


@router.delete("/designs/{did}")
async def delete_design(did: str,
                        user: dict = Depends(require_admin_or_manager),
                        tenant: dict = Depends(get_current_tenant)):
    await db.designs.delete_one({"id": did, "tenant_id": tenant["id"]})
    return {"ok": True}


# TD-cad-phase1 · Oct-2026 — tenant-scoped FK validator. Guards both
# POST + PUT against cross-tenant property/quote attach attempts.
# A missing reference raises 404; a null reference (field unset) is a
# no-op so the field remains additive-nullable per Phase 0 §3.1.
async def _validate_fk_refs(body: "DesignIn", tenant_id: str) -> None:
    if body.property_id:
        p = await db.properties.find_one(
            {"id": body.property_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1},
        )
        if not p:
            raise HTTPException(404, "Property not found")
    if body.quote_id:
        q = await db.quotes.find_one(
            {"id": body.quote_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1},
        )
        if not q:
            raise HTTPException(404, "Quote not found")


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


@router.get("/cad/map-tile-by-coords")
async def get_map_tile_by_coords(
    lat: float = Query(...),
    lng: float = Query(...),
    zoom: int = Query(19),
    size: str = Query("800x500"),
    label: Optional[str] = Query(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase CAD-ADDR · Feb-2026 — address-based site mapping.

    Fetches a Google Static Maps satellite tile for the caller-
    supplied ``lat`` / ``lng`` pair, skipping the geocode step the
    ``/cad/map-tile`` endpoint performs.  Used by the CAD editor's
    ``AddressAutocomplete`` field so a designer can drop a pin on
    any address (not just the associated customer's) without a
    round-trip through the customer record.

    Response
    --------
    Body: ``image/png`` bytes.

    Headers mirror ``/cad/map-tile`` — ``X-Map-Lat`` / ``X-Map-Lng``
    / ``X-Map-Zoom`` / ``X-Feet-Per-Pixel`` — plus:

    * ``X-Geocode-Source: coords`` — flags the tile as
      caller-provided (vs. ``cache`` / ``live`` on the primary
      endpoint) so the FE can label the state pill accordingly.
    * ``X-Map-Label`` — echoes the ``label`` query param verbatim
      when provided, omitted otherwise. The FE displays this as a
      caption under the map.

    Error codes are byte-identical with ``/cad/map-tile``:

    * ``400 invalid_coords``           — lat/lng out of range.
    * ``400 invalid_zoom_param``       — non-integer zoom.
    * ``400 invalid_size_param``       — malformed ``WxH``.
    * ``424 google_maps_key_missing``  — server-side key unset.
    * ``502 map_tile_upstream_error``  — Google returned non-200.
    """
    # ── Coord validation.  Match the geodetic range and reject
    # NaN / inf which ``float(Query)`` will otherwise happily pass
    # through.  ``_fetch_static_map_bytes`` would refuse a bogus
    # tile too but a 400 here is a clearer contract for callers.
    from math import isfinite
    if not isfinite(lat) or not isfinite(lng):
        raise HTTPException(400, {"error_code": "invalid_coords"})
    if lat < -90.0 or lat > 90.0 or lng < -180.0 or lng > 180.0:
        raise HTTPException(400, {"error_code": "invalid_coords"})
    # ── Zoom clamp (shared bounds with /cad/map-tile).
    try:
        z = int(zoom)
    except (TypeError, ValueError):
        raise HTTPException(400, {"error_code": "invalid_zoom_param"})
    z = max(_ZOOM_MIN, min(_ZOOM_MAX, z))
    # ── Size parse + clamp (shared bounds with /cad/map-tile).
    try:
        w_str, h_str = (size or "").lower().split("x", 1)
        w = max(_SIZE_MIN, min(_SIZE_MAX, int(w_str)))
        h = max(_SIZE_MIN, min(_SIZE_MAX, int(h_str)))
    except Exception:
        raise HTTPException(400, {"error_code": "invalid_size_param"})
    # ── Fetch (raises 424 google_maps_key_missing / 502
    # map_tile_upstream_error via _fetch_static_map_bytes).
    png = await _fetch_static_map_bytes(
        lat=lat, lng=lng, zoom=z, width=w, height=h,
    )
    fpp = _feet_per_pixel(lat, z)
    # ── Response headers.  ``X-Map-Label`` only rendered when
    # provided so the CORS ``Expose-Headers`` list still lets the
    # FE read it; empty labels don't leak into the DOM.
    headers = {
        "X-Map-Lat": f"{lat:.7f}",
        "X-Map-Lng": f"{lng:.7f}",
        "X-Map-Zoom": str(z),
        "X-Feet-Per-Pixel": f"{fpp:.6f}",
        "X-Geocode-Source": "coords",
    }
    exposed = ("X-Map-Lat, X-Map-Lng, X-Map-Zoom, "
               "X-Feet-Per-Pixel, X-Geocode-Source")
    if label:
        # Header values must be latin-1 encodable — encode any
        # non-ASCII glyphs so the response header survives the
        # ASGI transport without a 500.
        headers["X-Map-Label"] = label.encode(
            "latin-1", "replace",
        ).decode("latin-1")
        exposed = exposed + ", X-Map-Label"
    headers["Access-Control-Expose-Headers"] = exposed
    return Response(
        content=png, media_type="image/png", headers=headers,
    )


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



# ═══════════════════════════════════════════════════════════════════
# Phase CAD-2 · MARCO AI shape generation
# ═══════════════════════════════════════════════════════════════════
import json as _json  # noqa: E402  (kept scoped to the CAD-2 block)

from services.geometry import clamp_normalized_coords  # noqa: E402


# The valid ``type`` values the generator is allowed to return.
# Anything else is discarded post-parse with a warning — we don't
# want the LLM inventing new shape types the FE has no renderer for.
_MARCO_ALLOWED_SHAPE_TYPES = {"pool", "spa", "paver", "wall", "icon"}
_MARCO_ALLOWED_ICONS = {
    # Plants
    "tree", "shrub", "bush", "palm", "grass",
    # Lighting
    "path_light", "spot_light", "wall_light",
    # Legacy — MARCO may still emit these; keep supported.
    "cactus", "firepit",
}


class GenerateContext(BaseModel):
    canvas_w_ft: Optional[float] = None
    canvas_h_ft: Optional[float] = None
    feet_per_pixel: Optional[float] = None
    boundary: Optional[List[Any]] = None
    existing_elements: Optional[List[Any]] = None


class GenerateBody(BaseModel):
    design_id: Optional[str] = None
    prompt: str = Field(..., min_length=1, max_length=2000)
    context: Optional[GenerateContext] = None


def _marco_system_prompt(
    *, canvas_w_ft: float, canvas_h_ft: float,
    feet_per_pixel: Optional[float],
    boundary: List[Any], existing_elements: List[Any],
    tone_directive: str,
) -> str:
    """Compose the strict-JSON MARCO system prompt. All numeric
    fields are inlined so the LLM has zero excuse to invent
    dimensions outside the property canvas."""
    fpp_line = (
        f"feet_per_pixel: {feet_per_pixel:.4f}\n"
        if feet_per_pixel else "feet_per_pixel: unknown\n"
    )
    boundary_line = (
        f"boundary_polygon: {_json.dumps(boundary)}\n"
        if boundary else "boundary_polygon: (no property line supplied)\n"
    )
    existing_line = (
        f"existing_elements: {_json.dumps(existing_elements[:40])}\n"
        if existing_elements else "existing_elements: []\n"
    )
    return (
        "You are MARCO, the property-design assistant for a pool + "
        "landscaping business. You will design outdoor spaces in a "
        "top-down 2D layout.\n"
        f"{tone_directive}\n\n"
        "Canvas + scale (all coordinates are normalized 0..1 relative "
        "to this canvas):\n"
        f"  canvas_w_ft: {canvas_w_ft}\n"
        f"  canvas_h_ft: {canvas_h_ft}\n"
        f"  {fpp_line}"
        f"  {boundary_line}"
        f"  {existing_line}"
        "\n"
        "Return ONLY valid strict JSON matching this schema:\n"
        '{"shapes": [{"type": "pool"|"spa"|"paver"|"wall"|"icon", '
        '"coords": [{"x": 0..1, "y": 0..1}, ...], '
        '"dims_ft": {"w": number, "h": number} | '
        '{"length_ft": number} | null, '
        '"icon": "tree"|"shrub"|"bush"|"palm"|"grass"|"path_light"|'
        '"spot_light"|"wall_light" | null, '
        '"label": string | null}], '
        '"reasoning": "one-paragraph explanation of the layout"}\n'
        "\n"
        "Rules:\n"
        "  * pool/spa: 4-corner rectangle (coords length == 4).\n"
        "  * paver: closed polygon (3+ vertices).\n"
        "  * wall: open polyline (2+ vertices).\n"
        "  * icon: single-point (coords length == 1) + icon key.\n"
        "  * coords MUST stay in [0..1]. If a shape must extend beyond "
        "the boundary, prefer to shrink it — the server will clamp "
        "anything out of range and warn.\n"
        "  * Never invent new shape types.\n"
        "  * Do not wrap the JSON in backticks or prose. Return the "
        "JSON object and nothing else.\n"
    )


def _try_parse_json_body(raw: str) -> Optional[Dict[str, Any]]:
    """Robust JSON parse — accepts bare object, code-fenced object,
    or JSON preceded/followed by prose (matches the tolerance the
    ``ai_measure`` extractor already ships to callers)."""
    if not raw or not isinstance(raw, str):
        return None
    txt = raw.strip()
    # Strip ```json fences if present.
    if txt.startswith("```"):
        # Drop leading fence + optional language tag.
        first_nl = txt.find("\n")
        if first_nl != -1:
            txt = txt[first_nl + 1:]
        if txt.rstrip().endswith("```"):
            txt = txt.rstrip()[:-3].rstrip()
    try:
        return _json.loads(txt)
    except Exception:
        pass
    # Fallback — find the first ``{`` and try to json-load from there.
    start = txt.find("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return _json.loads(txt[start:end + 1])
    except Exception:
        return None


def _sanitize_shapes(
    raw_shapes: List[Any],
) -> tuple[List[Dict[str, Any]], List[str]]:
    """Filter to allowed types, clamp coords, return
    ``(shapes, warnings)``. Never silently drops a shape — a
    disallowed type surfaces as a warning so the caller can see the
    LLM misbehaved."""
    shapes: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if not isinstance(raw_shapes, list):
        return shapes, ["shapes field missing or not a list"]
    for idx, s in enumerate(raw_shapes):
        if not isinstance(s, dict):
            warnings.append(f"shape {idx} skipped — not an object")
            continue
        stype = s.get("type")
        if stype not in _MARCO_ALLOWED_SHAPE_TYPES:
            warnings.append(
                f"shape {idx} skipped — unknown type {stype!r}",
            )
            continue
        coords_in = s.get("coords") or []
        if not isinstance(coords_in, list):
            warnings.append(
                f"shape {idx} skipped — coords is not a list",
            )
            continue
        coords_out, was_clamped = clamp_normalized_coords(coords_in)
        if was_clamped:
            warnings.append(
                f"shape {idx} ({stype}) extends beyond property "
                f"boundary — clamped",
            )
        icon = s.get("icon")
        if stype == "icon":
            if icon not in _MARCO_ALLOWED_ICONS:
                # Downgrade unknown icons to ``tree`` rather than
                # dropping the placement — MARCO's spatial intent
                # is preserved, only the glyph is defaulted.
                warnings.append(
                    f"shape {idx} — unknown icon {icon!r} → 'tree'",
                )
                icon = "tree"
        else:
            icon = None
        # Only carry through fields the FE renders.
        shapes.append({
            "type": stype,
            "coords": coords_out,
            "dims_ft": s.get("dims_ft"),
            "icon": icon,
            "label": s.get("label"),
        })
    return shapes, warnings


@router.post("/cad/generate")
async def cad_generate(
    body: GenerateBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """MARCO AI shape generation. Returns a preview batch of
    shapes the FE renders (in-memory) until the operator hits
    Accept. Persistence happens via the existing ``PUT /designs/
    {did}`` — this endpoint never writes to ``db.designs``."""
    if not (os.environ.get("EMERGENT_LLM_KEY") or "").strip():
        raise HTTPException(
            424, {"error_code": "emergent_llm_key_missing"},
        )
    # Resolve canvas + boundary + existing elements. Priority:
    # explicit body context → loaded design → fail with 400.
    canvas_w_ft: Optional[float] = None
    canvas_h_ft: Optional[float] = None
    feet_per_pixel: Optional[float] = None
    boundary: List[Any] = []
    existing_elements: List[Any] = []
    if body.design_id:
        design = await db.designs.find_one(
            {"id": body.design_id, "tenant_id": tenant["id"]},
            {"_id": 0},
        )
        if not design:
            raise HTTPException(404, {"error_code": "design_not_found"})
        canvas_w_ft = float(design.get("canvas_w_ft") or 60.0)
        canvas_h_ft = float(design.get("canvas_h_ft") or 40.0)
        fpp_val = design.get("feet_per_pixel")
        feet_per_pixel = float(fpp_val) if fpp_val else None
        boundary = list(design.get("boundary") or [])
        existing_elements = list(design.get("elements") or [])
    if body.context:
        if body.context.canvas_w_ft is not None:
            canvas_w_ft = float(body.context.canvas_w_ft)
        if body.context.canvas_h_ft is not None:
            canvas_h_ft = float(body.context.canvas_h_ft)
        if body.context.feet_per_pixel is not None:
            feet_per_pixel = float(body.context.feet_per_pixel)
        if body.context.boundary is not None:
            boundary = list(body.context.boundary)
        if body.context.existing_elements is not None:
            existing_elements = list(body.context.existing_elements)
    if canvas_w_ft is None or canvas_h_ft is None:
        raise HTTPException(
            400,
            {"error_code": "missing_canvas_context",
             "detail": "Either design_id or context.canvas_w_ft + "
                       "canvas_h_ft must be provided."},
        )

    # Persona directive — try to fetch tenant AI-rules tone, but
    # fall back silently to a sane default if the resolver errors
    # (unrelated tenant provisioning gaps must not gate MARCO).
    tone_directive = (
        "Persona: concise, technical, prioritise usability + code "
        "compliance. Never overpromise. Prefer real-world dimensions "
        "over stylistic flourishes."
    )
    try:
        from services.tenant_ai_rules.resolver import (
            resolve_rules_for_tenant,
        )
        resolved = await resolve_rules_for_tenant(tenant["id"])
        tone = (resolved.get("rules") or {}).get("tone_voice") or {}
        style = (tone.get("style") or "").strip()
        directive = (tone.get("custom_directive") or "").strip()
        if style or directive:
            tone_directive = (
                f"Persona style: {style or 'default'}.\n"
                + (f"Directive: {directive}" if directive else "")
            )
    except Exception:  # noqa: BLE001
        pass

    sys_prompt = _marco_system_prompt(
        canvas_w_ft=canvas_w_ft, canvas_h_ft=canvas_h_ft,
        feet_per_pixel=feet_per_pixel,
        boundary=boundary, existing_elements=existing_elements,
        tone_directive=tone_directive,
    )
    user_text = body.prompt.strip()

    # Lazy import so tests can ``monkeypatch.setattr("routers.cad.
    # dispatch_ai_completion", ...)`` without dragging the real
    # LLM chain in at collection time.
    from services.ai import dispatch_ai_completion

    async def _one_completion() -> Optional[Dict[str, Any]]:
        try:
            result = await dispatch_ai_completion(
                tenant_id=tenant["id"],
                system_prompt=sys_prompt,
                user_text=user_text,
                parse_json=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[cad] MARCO dispatch failed: {e}")
            return None
        content = getattr(result, "content", None) or ""
        return _try_parse_json_body(content)

    parsed = await _one_completion()
    if parsed is None or not isinstance(parsed.get("shapes"), list):
        # Retry once.
        logger.info("[cad] MARCO invalid-JSON — retrying once")
        parsed = await _one_completion()
    if parsed is None or not isinstance(parsed.get("shapes"), list):
        raise HTTPException(
            502,
            {"error_code": "marco_invalid_shape_json"},
        )

    shapes, warnings = _sanitize_shapes(parsed.get("shapes") or [])
    return {
        "generation_id": new_id(),
        "shapes": shapes,
        "reasoning": (parsed.get("reasoning") or "").strip()[:2000],
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════
# Phase CAD-3 · Site Plan PDF export
# ═══════════════════════════════════════════════════════════════════
from pathlib import Path as _Path  # noqa: E402


_SITE_PLAN_UPLOAD_ROOT = _Path("/app/backend/uploads/design_pdfs")


def _pdf_filename(design: Dict[str, Any]) -> str:
    """Human-safe filename: ``site-plan-<slug>-YYYY-MM-DD.pdf``.
    Slug is a whitespace-collapsed, non-word-stripped design name."""
    raw = (design.get("name") or "untitled").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "design"
    ymd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"site-plan-{slug}-{ymd}.pdf"


@router.post("/cad/designs/{did}/site-plan-pdf")
async def generate_site_plan_pdf(
    did: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Render + persist a 2-page Site Plan PDF for the design.
    Bytes are written to pod-local ``uploads/design_pdfs/{tenant}/
    {media_id}.pdf`` and served via the existing legacy
    ``/api/uploads/{path}`` handler in ``routers/objects.py``.
    Every call creates a NEW ``design_media`` row (versioning) —
    prior PDFs are never overwritten.
    """
    design = await db.designs.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not design:
        raise HTTPException(404, {"error_code": "design_not_found"})
    if not design.get("customer_id"):
        raise HTTPException(
            400,
            {"error_code": "design_customer_missing",
             "detail": "Design must reference a customer_id before "
                       "a site plan PDF can be generated."},
        )
    customer = await db.customers.find_one(
        {"id": design["customer_id"], "tenant_id": tenant["id"]},
        {"_id": 0},
    )

    # Attempt to fetch the satellite backdrop when the design has
    # persisted coordinates. Failures degrade to a blank backdrop
    # (Page 2 renders a "No satellite backdrop available" caption).
    map_bytes: Optional[bytes] = None
    if (
        design.get("map_center_lat") is not None
        and design.get("map_center_lng") is not None
    ):
        try:
            map_bytes = await _fetch_static_map_bytes(
                lat=float(design["map_center_lat"]),
                lng=float(design["map_center_lng"]),
                zoom=int(design.get("map_zoom") or 19),
                width=int((design.get("map_size_px") or {}).get("w") or 800),
                height=int((design.get("map_size_px") or {}).get("h") or 500),
            )
        except HTTPException as e:
            logger.info(
                f"[cad-3] map backdrop unavailable "
                f"({getattr(e, 'status_code', '?')}) — falling back "
                f"to blank white background",
            )
            map_bytes = None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[cad-3] map fetch error: {e}")
            map_bytes = None

    # Build render context + PDF bytes.
    from services.cad.site_plan_pdf import (
        build_render_context, render_pdf,
    )
    ctx = build_render_context(
        design=design, customer=customer, tenant=tenant,
        map_bytes=map_bytes, generated_by=user.get("id"),
    )
    # Brand hex — reuse tenant primary token if configured.
    brand_hex = (tenant.get("brand_primary_hex")
                 or "#0B4A6F")
    try:
        pdf_bytes = render_pdf(ctx, brand_hex=brand_hex)
    except Exception as e:  # noqa: BLE001
        logger.exception("[cad-3] render_pdf failed")
        raise HTTPException(
            500,
            {"error_code": "site_plan_render_failed",
             "detail": str(e)[:200]},
        )

    # Persist bytes to pod-local disk under a UUID so repeat calls
    # never collide (versioning). Served via /api/uploads/{path}.
    media_id = new_id()
    tenant_dir = _SITE_PLAN_UPLOAD_ROOT / tenant["id"]
    try:
        tenant_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        logger.exception("[cad-3] mkdir failed")
        raise HTTPException(
            500,
            {"error_code": "site_plan_storage_unavailable",
             "detail": str(e)[:200]},
        )
    filepath = tenant_dir / f"{media_id}.pdf"
    filepath.write_bytes(pdf_bytes)
    media_url = f"/api/uploads/design_pdfs/{tenant['id']}/{media_id}.pdf"

    filename = _pdf_filename(design)
    generated_at = datetime.now(timezone.utc).isoformat()
    media_doc = {
        "id": media_id,
        "tenant_id": tenant["id"],
        "design_id": did,
        "kind": "site_plan_pdf",
        "filename": filename,
        "url": media_url,
        "size_bytes": len(pdf_bytes),
        "generated_at": generated_at,
        "generated_by": user.get("id"),
    }
    await db.design_media.insert_one(dict(media_doc))
    media_doc.pop("_id", None)

    return {
        "media_id": media_id,
        "media_url": media_url,
        "filename": filename,
        "pages": ctx["page_count"],
        "size_bytes": len(pdf_bytes),
        "generated_at": generated_at,
    }

