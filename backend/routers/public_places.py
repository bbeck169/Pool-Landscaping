"""Feb-2026 · P0 · Lead form address autofill (Google Places).

Public (no-auth) server-side proxy for the two Google Places calls
the embedded lead widget + admin form builder need:

* ``GET /api/public/places/autocomplete?input=…&session_token=…`` —
  proxies to the Places Autocomplete v1 endpoint with a US country
  bias, returning at most 5 lean suggestions.
* ``GET /api/public/places/details?place_id=…&session_token=…`` —
  proxies to Place Details v1, returning parsed street / city / state
  / zip / country + lat / lng.

Both endpoints:

* Are ``CORS``-open by design so the anonymous embed widget can call
  them from a tenant's marketing site.
* Never expose ``GOOGLE_MAPS_API_KEY`` to the browser — the key is
  read from the backend env and appended server-side.
* Are rate-limited to **30 requests / minute / IP** by a lightweight
  in-process sliding-window limiter, mirroring the pattern used by
  ``routers.leads._rate_limit_public_leads``. A ``TODO`` marker is
  left for the follow-up Redis migration once the widget graduates
  from single-node preview to multi-replica production.

Google Places quota safety
--------------------------

The autocomplete endpoint enforces ``input`` length ≥ 3 chars server-
side (an unrealistic tap on a mobile keyboard can otherwise blow
through the daily Places quota with single-char requests).
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from config import logger

router = APIRouter()

# ─── Rate limit (30/min/IP) ───────────────────────────────────────────
# TODO(Feb-2026 · P0 follow-up): migrate to Redis (or the same Mongo-
# TTL pattern used by ``services/reviews_rate_limit.py``) once the
# widget is deployed behind a multi-replica ingress. In-memory is
# fine for the single preview pod but will under-count across
# horizontally-scaled workers.
_RATE = 30
_WINDOW_S = 60.0
_hits: Dict[str, List[float]] = {}
_lock = asyncio.Lock()


async def _rate_limit(ip: str) -> None:
    now = time.monotonic()
    async with _lock:
        bucket = _hits.setdefault(ip, [])
        cutoff = now - _WINDOW_S
        i = 0
        while i < len(bucket) and bucket[i] < cutoff:
            i += 1
        if i:
            del bucket[:i]
        if len(bucket) >= _RATE:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit — max {_RATE}/minute per IP",
            )
        bucket.append(now)


# Test hook — the pytest suite calls this to reset the in-memory
# window between test cases. Never referenced by production code.
def _reset_rate_limit_for_tests() -> None:  # pragma: no cover
    _hits.clear()


def _client_ip(request: Request) -> str:
    """Resolve the real client IP behind our ingress.

    Preview + production run behind an ingress (Cloudflare Worker →
    K8s ingress → FastAPI) that terminates the browser TCP connection
    on one of ≥ 2 round-robin peers, so ``request.client.host`` is the
    peer IP — not the visitor's. A single abusive client can therefore
    push ~ ``30 × N_peers`` req/min before hitting the limiter unless
    we read the standard forwarded headers first.

    Precedence:
      1. ``X-Forwarded-For`` — leftmost entry (RFC 7239 / X-F-F
         convention: original client is first in the list).
      2. ``X-Real-IP`` — set by nginx-style ingresses.
      3. ``request.client.host`` — direct-peer fallback (unit tests
         and localhost curl land here).
    """
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        # Left-most token, stripped, non-empty.
        head = xff.split(",", 1)[0].strip()
        if head:
            return head
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    try:
        return (request.client.host if request.client else "") or ""
    except Exception:
        return ""


# ─── Google Places New API endpoints ──────────────────────────────────
_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
_DETAILS_URL_TMPL = "https://places.googleapis.com/v1/places/{place_id}"


def _google_api_key() -> str:
    return (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()


@router.get("/public/places/autocomplete")
async def public_places_autocomplete(
    request: Request,
    input: str = Query(..., min_length=3, max_length=200),
    session_token: Optional[str] = Query(default=None),
) -> List[Dict[str, Any]]:
    """Return up to 5 lean autocomplete suggestions for ``input``.

    Shape: ``[{place_id, description, main_text, secondary_text}]``.
    US-biased. Never exposes the server key to the caller.
    """
    ip = _client_ip(request)
    await _rate_limit(ip)
    api_key = _google_api_key()
    if not api_key:
        # Fail-closed with an empty list so the widget stays usable
        # (manual entry still works) but the caller sees no rows.
        logger.warning("[public_places] GOOGLE_MAPS_API_KEY not set — returning empty suggestions")
        return []

    payload: Dict[str, Any] = {
        "input": input,
        "includedRegionCodes": ["us"],
    }
    if session_token:
        payload["sessionToken"] = session_token

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                _AUTOCOMPLETE_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": "suggestions.placePrediction.placeId,"
                                          "suggestions.placePrediction.text.text,"
                                          "suggestions.placePrediction.structuredFormat",
                },
                json=payload,
            )
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[public_places] autocomplete http error: {exc}")
        return []
    if resp.status_code >= 400:
        logger.warning(f"[public_places] autocomplete {resp.status_code}: {resp.text[:200]}")
        return []
    try:
        data = resp.json() or {}
    except Exception:  # pragma: no cover
        return []
    suggestions = data.get("suggestions") or []
    out: List[Dict[str, Any]] = []
    for s in suggestions[:5]:
        pred = (s or {}).get("placePrediction") or {}
        pid = pred.get("placeId") or ""
        text = ((pred.get("text") or {}).get("text") or "").strip()
        struct = pred.get("structuredFormat") or {}
        main = ((struct.get("mainText") or {}).get("text") or "").strip()
        secondary = ((struct.get("secondaryText") or {}).get("text") or "").strip()
        if not pid or not text:
            continue
        out.append({
            "place_id": pid,
            "description": text,
            "main_text": main or text,
            "secondary_text": secondary,
        })
    return out


def _parse_components(components: List[Dict[str, Any]]) -> Dict[str, str]:
    """Fold Google's ``addressComponents`` array into a flat dict."""
    out = {"street_number": "", "route": "", "city": "", "state": "",
            "zip": "", "country": ""}
    for c in components or []:
        types = c.get("types") or []
        long_text = c.get("longText") or c.get("long_name") or ""
        short_text = c.get("shortText") or c.get("short_name") or ""
        if "street_number" in types:
            out["street_number"] = long_text
        elif "route" in types:
            out["route"] = long_text
        elif "locality" in types or "postal_town" in types:
            out["city"] = long_text
        elif "administrative_area_level_1" in types:
            out["state"] = short_text or long_text
        elif "postal_code" in types:
            out["zip"] = long_text
        elif "country" in types:
            out["country"] = short_text or long_text
    return out


@router.get("/public/places/details")
async def public_places_details(
    request: Request,
    place_id: str = Query(..., min_length=1, max_length=300),
    session_token: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return parsed address components + lat/lng for ``place_id``.

    Shape: ``{street, city, state, zip, country, latitude, longitude}``.
    """
    ip = _client_ip(request)
    await _rate_limit(ip)
    api_key = _google_api_key()
    if not api_key:
        raise HTTPException(status_code=503,
                              detail="Places service not configured")

    url = _DETAILS_URL_TMPL.format(place_id=place_id)
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "id,formattedAddress,addressComponents,location",
    }
    params: Dict[str, str] = {}
    if session_token:
        params["sessionToken"] = session_token
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[public_places] details http error: {exc}")
        raise HTTPException(status_code=502, detail="Places lookup failed") from exc
    if resp.status_code >= 400:
        logger.warning(f"[public_places] details {resp.status_code}: {resp.text[:200]}")
        raise HTTPException(status_code=502, detail="Places lookup failed")
    try:
        data = resp.json() or {}
    except Exception:  # pragma: no cover
        raise HTTPException(status_code=502, detail="Places lookup failed")

    comps = _parse_components(data.get("addressComponents") or [])
    street = " ".join(filter(None, [comps["street_number"], comps["route"]])).strip()
    loc = data.get("location") or {}
    latitude = loc.get("latitude")
    longitude = loc.get("longitude")
    return {
        "street": street,
        "city": comps["city"],
        "state": comps["state"],
        "zip": comps["zip"],
        "country": comps["country"] or "US",
        "latitude": float(latitude) if latitude is not None else None,
        "longitude": float(longitude) if longitude is not None else None,
    }
