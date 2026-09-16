"""Phase AIM0 · Feb-2026 — AI Measurement Tool (POC).

``POST /api/tools/ai-measure/preview`` — admin-only pipeline that

    1. Resolves an address (or lat/lng) to coordinates.
    2. Fetches a Google Static Maps satellite tile at high-DPI.
    3. Sends the tile to GPT-4o AND Claude via ``dispatch_ai_completion``
       and asks each for pixel-space polygons of pool / deck / yard.
    4. Runs the shoelace formula on each polygon and converts pixel²
       → square metres → square feet / yards using the standard
       Google web-Mercator meters-per-pixel formula.

Guardrails (POC — do NOT ship to public users yet)
--------------------------------------------------
* ``require_admin`` guard (admin / super_admin / owner only — see
  ``backend/utils.py::require_admin`` line 156).
* 20 requests / hour / user, enforced with an in-process token bucket
  (no persistence — POC only).
* No measurement is persisted, no quote / job linkage, no ground-
  truth benchmarking.
* Every request logs ``[ai-measure] provider=... latency_ms=...
  image_bytes=... user=...`` for cost telemetry.
"""
from __future__ import annotations

import asyncio
import base64
import math
import os
import time
import json
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import GOOGLE_API_KEY, logger
from routers.google import _geocode_one
from routers.tenants import get_current_tenant
from services.ai.dispatcher import dispatch_ai_completion
from utils import require_admin


router = APIRouter(tags=["AI Measure (POC)"])


# Phase AIM0 · Feb-2026 — resolves the same referrer-restricted key
# the Places autocomplete uses (``GOOGLE_MAPS_API_KEY``) with a
# fallback to ``GOOGLE_API_KEY`` for pods where only the legacy
# server-side key is provisioned. The spec's directive was "use the
# existing Google API key already integrated for Places" — that's
# ``GOOGLE_MAPS_API_KEY`` per ``routers/public_places.py`` and
# ``routers/config.py``.
def _resolve_google_key() -> str:
    return (
        os.environ.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or GOOGLE_API_KEY
        or ""
    ).strip()


# ─── Rate limit — in-process, per-user, 20 / hour ─────────────────────
RATE_LIMIT_PER_HOUR = 20
RATE_LIMIT_WINDOW_SEC = 3600
_rate_hits: Dict[str, deque] = defaultdict(deque)


def _rate_limit_or_429(user_id: str) -> None:
    """Sliding-window token bucket. POC-scoped — never persisted."""
    now = time.monotonic()
    q = _rate_hits[user_id]
    while q and (now - q[0]) > RATE_LIMIT_WINDOW_SEC:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"AI Measure rate limit reached ({RATE_LIMIT_PER_HOUR}/hour). "
                   f"Try again in a few minutes.",
        )
    q.append(now)


# ─── Geometry helpers ────────────────────────────────────────────────
# Google web-Mercator meters-per-pixel at zoom Z:
#     mpp = 156543.03392 * cos(lat_rad) / (2^Z)
# `scale=2` halves the effective mpp because each returned pixel now
# maps to half the ground distance.
GOOGLE_STATIC_MAPS_BASE_MPP = 156543.03392  # metres / pixel at equator, zoom=0


def meters_per_pixel(*, lat: float, zoom: int, scale: int = 1) -> float:
    lat_rad = math.radians(lat)
    mpp = GOOGLE_STATIC_MAPS_BASE_MPP * math.cos(lat_rad) / (2 ** zoom)
    return mpp / max(1, scale)


def polygon_area_pixels(polygon: List[List[float]]) -> float:
    """Shoelace formula on a pixel-space polygon. Returns absolute
    signed area in square pixels. Order (CW / CCW) doesn't matter —
    we take ``abs`` at the end."""
    n = len(polygon)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = polygon[i][0], polygon[i][1]
        x2, y2 = polygon[(i + 1) % n][0], polygon[(i + 1) % n][1]
        s += (x1 * y2) - (x2 * y1)
    return abs(s) / 2.0


def area_to_sqft_sqyd(*, area_pixels: float, mpp: float) -> Tuple[float, float]:
    area_m2 = area_pixels * (mpp ** 2)
    area_sqft = area_m2 * 10.7639
    area_sqyd = area_sqft / 9.0
    return round(area_sqft, 1), round(area_sqyd, 2)


# ─── Prompt (locked — do NOT reflow without a phase bump) ────────────
FEATURE_DEFINITIONS = (
    "- pool: swimming pool water surface (blue/turquoise water). "
    "Exclude decking around it.\n"
    "- deck: hardscape/decking adjacent to the pool (concrete, pavers, coping). "
    "Exclude pool water itself.\n"
    "- yard: turf/lawn area (grass, natural or artificial). "
    "Exclude rocks, gravel, decking, pool, driveway."
)


def build_vision_prompt(feature_types: List[str]) -> str:
    return (
        "You are an expert at identifying features in overhead satellite imagery.\n"
        "The image is 640x640 pixels showing a residential property from directly above.\n"
        "For each of these features that you can see clearly, return a polygon "
        "(list of [x, y] pixel coordinates in clockwise order, closed shape):\n"
        f"{feature_types}\n"
        "Feature definitions:\n"
        f"{FEATURE_DEFINITIONS}\n"
        "Return ONLY valid JSON in this shape:\n"
        '{"features": [{"type": "pool", "polygon": [[x1,y1], [x2,y2], ...], '
        '"confidence": 0.85, "notes": "brief note"}, ...]}\n'
        "If a feature is not clearly visible, omit it. Do not fabricate."
    )


# ─── Static Maps fetch ───────────────────────────────────────────────
STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


async def geocode_address(
    address: str, *, http_client: Optional[httpx.AsyncClient] = None,
) -> Optional[Dict[str, Any]]:
    """Phase AIM0 · Feb-2026 — resolve an address using the same
    referrer-restricted key the rest of the Google surface uses
    (``_resolve_google_key``). This is a thin local helper because
    ``routers.google._geocode_one`` is hard-wired to the legacy
    ``GOOGLE_API_KEY`` (which is billing-disabled in this pod) and
    editing it would ripple across every geocoding caller in the app.
    Same return shape as ``_geocode_one``: ``{lat, lng, formatted,
    place_id}`` or ``None``."""
    key = _resolve_google_key()
    if not key:
        return None
    close = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        close = True
    try:
        r = await client.get(GEOCODE_URL, params={"address": address, "key": key})
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get("status") != "OK" or not j.get("results"):
            return None
        top = j["results"][0]
        loc = top.get("geometry", {}).get("location", {})
        return {
            "lat": loc.get("lat"), "lng": loc.get("lng"),
            "formatted": top.get("formatted_address"),
            "place_id": top.get("place_id"),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ai-measure] geocode failed for {address!r}: {e}")
        return None
    finally:
        if close:
            await client.aclose()


async def fetch_static_map(
    *, lat: float, lng: float, zoom: int,
    http_client: Optional[httpx.AsyncClient] = None,
) -> bytes:
    key = _resolve_google_key()
    if not key:
        raise HTTPException(424, "GOOGLE_MAPS_API_KEY not configured")
    params = {
        "center": f"{lat},{lng}",
        "zoom": str(zoom),
        "size": "640x640",
        "scale": "2",
        "maptype": "satellite",
        "key": key,
    }
    close = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
        close = True
    try:
        r = await client.get(STATIC_MAPS_URL, params=params)
        if r.status_code != 200:
            # Surface Google's error body when the API isn't enabled
            # (403 with a human-readable message from GCP).
            body = ""
            try:
                body = r.text[:240]
            except Exception:
                pass
            raise HTTPException(
                r.status_code,
                f"Google Static Maps returned HTTP {r.status_code}"
                + (f": {body}" if body else ""),
            )
        return r.content
    finally:
        if close:
            await client.aclose()


# ─── Vision helpers ──────────────────────────────────────────────────
ALLOWED_FEATURES = ("pool", "deck", "yard")


def _extract_features(raw: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Parse the vision reply. Returns (features, error). On any
    JSON-shape drift we return (``[]``, error_msg) so the endpoint
    still 200s per the spec."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception as e:
            return [], f"json_parse_failed: {e}"
    if not isinstance(raw, dict):
        return [], "response_not_object"
    feats = raw.get("features")
    if not isinstance(feats, list):
        return [], "features_field_missing"
    out: List[Dict[str, Any]] = []
    for f in feats:
        if not isinstance(f, dict):
            continue
        ftype = str(f.get("type", "")).lower().strip()
        if ftype not in ALLOWED_FEATURES:
            continue
        poly = f.get("polygon")
        if not isinstance(poly, list) or len(poly) < 3:
            continue
        # Coerce polygon to [[x, y], ...] floats.
        clean_poly: List[List[float]] = []
        for pt in poly:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    clean_poly.append([float(pt[0]), float(pt[1])])
                except Exception:
                    pass
        if len(clean_poly) < 3:
            continue
        conf = f.get("confidence")
        try:
            conf = float(conf) if conf is not None else None
        except Exception:
            conf = None
        out.append({
            "type": ftype,
            "polygon": clean_poly,
            "confidence": conf,
            "notes": str(f.get("notes", ""))[:240],
        })
    return out, None


async def _run_vision(
    *, tenant_id: str, prompt: str, image_b64: str, route: str,
) -> Dict[str, Any]:
    """One vision round-trip. Never raises — errors surface on the
    returned dict so the sibling provider still gets a chance."""
    started = time.perf_counter()
    label = "openai_gpt-4o" if route == "openai_vision" else "anthropic_claude"
    try:
        result = await dispatch_ai_completion(
            tenant_id=tenant_id,
            system_prompt="You are a precise satellite-image analyst.",
            user_text=prompt,
            parse_json=True,
            image_b64s=[image_b64],
            route=route,
        )
    except Exception as e:  # noqa: BLE001 — provider-level failures
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "[ai-measure] provider=%s elapsed_ms=%d ERROR %s: %s",
            label, elapsed, type(e).__name__, e,
        )
        return {
            "provider": label,
            "latency_ms": elapsed,
            "features": [],
            "error": f"{type(e).__name__}: {e}",
        }
    elapsed = int((time.perf_counter() - started) * 1000)
    raw_payload: Any = getattr(result, "raw", None) or {}
    if isinstance(raw_payload, dict) and "text" in raw_payload and not any(
        k in raw_payload for k in ("features",)
    ):
        # Emergent adapter shape: {"raw": {"text": "..."}}. Try to parse the text.
        raw_payload = raw_payload.get("text", "")
    features, err = _extract_features(raw_payload)
    tokens = getattr(result, "tokens_total", 0)
    logger.info(
        "[ai-measure] provider=%s latency_ms=%d tokens=%d features=%d err=%s",
        label, elapsed, tokens, len(features), err or "-",
    )
    out = {
        "provider": label,
        "latency_ms": elapsed,
        "features": features,
    }
    if err:
        out["error"] = err
    return out


def _annotate_areas(features: List[Dict[str, Any]], *, mpp: float) -> None:
    for f in features:
        px_area = polygon_area_pixels(f["polygon"])
        sqft, sqyd = area_to_sqft_sqyd(area_pixels=px_area, mpp=mpp)
        f["area_sqft"] = sqft
        f["area_sqyd"] = sqyd
        f["area_pixels"] = round(px_area, 2)


# ─── Request / response models ───────────────────────────────────────
class AiMeasureRequest(BaseModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    feature_types: List[str] = Field(default_factory=lambda: ["pool", "deck", "yard"])
    zoom: int = 20

    def sanitized_feature_types(self) -> List[str]:
        out: List[str] = []
        for f in (self.feature_types or []):
            k = str(f).lower().strip()
            if k in ALLOWED_FEATURES and k not in out:
                out.append(k)
        return out or list(ALLOWED_FEATURES)


# ─── Endpoint ────────────────────────────────────────────────────────
@router.post("/tools/ai-measure/preview")
async def ai_measure_preview(
    body: AiMeasureRequest,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Run one AI measurement preview.

    See module docstring for guardrails. Returns the shape defined in
    the AIM0 spec (``providers`` × features, satellite tile inline as
    a base64 data URL).
    """
    user_id = str(user.get("id") or user.get("_id") or "")
    _rate_limit_or_429(user_id)

    if body.zoom < 1 or body.zoom > 21:
        raise HTTPException(400, "zoom must be in 1..21")

    # 1. Resolve coordinates.
    lat, lng = body.lat, body.lng
    formatted: Optional[str] = None
    if (lat is None or lng is None) and body.address:
        async with httpx.AsyncClient(timeout=10.0) as client:
            g = await geocode_address(body.address, http_client=client)
        if not g:
            raise HTTPException(422, "Address could not be geocoded")
        lat = g.get("lat")
        lng = g.get("lng")
        formatted = g.get("formatted")
    if lat is None or lng is None:
        raise HTTPException(
            400, "Provide either `address` or both `lat` and `lng`",
        )
    formatted = formatted or (body.address or f"{lat},{lng}")

    # 2. Fetch satellite tile.
    tile_bytes = await fetch_static_map(lat=lat, lng=lng, zoom=body.zoom)
    tile_b64 = base64.b64encode(tile_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{tile_b64}"

    # 3. Compute meters-per-pixel (scale=2 halves).
    mpp = meters_per_pixel(lat=lat, zoom=body.zoom, scale=2)

    # 4. Kick off both vision calls in parallel.
    features = body.sanitized_feature_types()
    prompt = build_vision_prompt(features)
    logger.info(
        "[ai-measure] request user=%s lat=%.6f lng=%.6f zoom=%d "
        "features=%s image_bytes=%d",
        user_id, lat, lng, body.zoom, features, len(tile_bytes),
    )
    tenant_id = str((tenant or {}).get("id") or (tenant or {}).get("_id") or "")
    openai_task = _run_vision(
        tenant_id=tenant_id, prompt=prompt, image_b64=tile_b64,
        route="openai_vision",
    )
    claude_task = _run_vision(
        tenant_id=tenant_id, prompt=prompt, image_b64=tile_b64,
        route="anthropic_vision",
    )
    openai_res, claude_res = await asyncio.gather(openai_task, claude_task)

    # 5. Compute areas per polygon.
    _annotate_areas(openai_res["features"], mpp=mpp)
    _annotate_areas(claude_res["features"], mpp=mpp)

    return {
        "address_resolved": formatted,
        "lat": lat,
        "lng": lng,
        "zoom": body.zoom,
        "image_size": [640 * 2, 640 * 2],  # scale=2 doubles the returned pixel dims
        "mpp_effective": mpp,
        "requested_features": features,
        "satellite_image_data_url": data_url,
        "providers": [openai_res, claude_res],
    }


# ─── Test-only helper (imported by tests) ────────────────────────────
def _reset_rate_limit_for_tests() -> None:
    """Wipe the in-process rate-limit deque. Used by pytest fixtures
    so parallel test runs don't leak state across tests. Never called
    from application code."""
    _rate_hits.clear()


__all__ = [
    "router",
    "AiMeasureRequest",
    "meters_per_pixel",
    "polygon_area_pixels",
    "area_to_sqft_sqyd",
    "build_vision_prompt",
    "fetch_static_map",
    "ALLOWED_FEATURES",
    "RATE_LIMIT_PER_HOUR",
    "_reset_rate_limit_for_tests",
]
