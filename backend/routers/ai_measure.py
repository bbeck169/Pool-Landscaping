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
import re
import time
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
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
    we take ``abs`` at the end.

    Phase CAD-2 · Feb-2026 — the implementation now lives in
    ``services.geometry`` so the CAD router can share it without
    pulling in the Google + Vision stack. This wrapper is preserved
    verbatim for import-compat with existing call-sites + tests.
    """
    from services.geometry import polygon_area_pixels as _impl
    return _impl(polygon)


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
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Phase AIM0 · Feb-2026 — resolve an address using the same
    referrer-restricted key the rest of the Google surface uses
    (``_resolve_google_key``). This is a thin local helper because
    ``routers.google._geocode_one`` is hard-wired to the legacy
    ``GOOGLE_API_KEY`` (which is billing-disabled in this pod) and
    editing it would ripple across every geocoding caller in the app.
    Same return shape as ``_geocode_one``: ``{lat, lng, formatted,
    place_id}`` or ``None``.

    P0-GEOCODE-LEAK-C2.5 · TD-62 (Feb-2026): fail-safe telemetry
    injection — every invocation writes one row into
    ``db.geocode_call_log`` with ``trigger_reason=ai_measure_resolve``.
    We DELIBERATELY did NOT refactor this helper to delegate to the
    core ``services.google_maps.geocoding.geocode_address`` because
    ``_resolve_google_key`` falls back from ``GOOGLE_MAPS_API_KEY``
    to ``GOOGLE_API_KEY`` while the core reads only
    ``GOOGLE_MAPS_API_KEY`` — refactoring would silently break pods
    provisioned with only the legacy key. Log write never blocks
    the geocode result."""
    from config import db as _db, logger as _logger
    from services.google_maps.geocode_trigger import (
        GeocodeOutcome, GeocodeTrigger, write_geocode_log,
    )
    _started_at = datetime.now(timezone.utc)
    _outcome = GeocodeOutcome.ERROR.value
    _err: Optional[str] = None
    _result: Optional[Dict[str, Any]] = None

    key = _resolve_google_key()
    if not key:
        _err = "no_api_key"
        await write_geocode_log(
            db_conn=_db, logger=_logger,
            tenant_id=tenant_id, entity_type="ai_measure",
            entity_id=None, address=address or "",
            trigger_reason=GeocodeTrigger.AI_MEASURE_RESOLVE.value,
            outcome=_outcome, error=_err,
            started_at=_started_at, api_key=key,
        )
        return None
    if not address:
        _outcome = GeocodeOutcome.NO_ADDR.value
        await write_geocode_log(
            db_conn=_db, logger=_logger,
            tenant_id=tenant_id, entity_type="ai_measure",
            entity_id=None, address="",
            trigger_reason=GeocodeTrigger.AI_MEASURE_RESOLVE.value,
            outcome=_outcome,
            started_at=_started_at, api_key=key,
        )
        return None
    close = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        close = True
    try:
        r = await client.get(GEOCODE_URL, params={"address": address, "key": key})
        if r.status_code != 200:
            _err = f"http_{r.status_code}"
        else:
            j = r.json()
            if j.get("status") != "OK" or not j.get("results"):
                _err = f"status_{j.get('status', 'unknown')}"
            else:
                top = j["results"][0]
                loc = top.get("geometry", {}).get("location", {})
                _result = {
                    "lat": loc.get("lat"), "lng": loc.get("lng"),
                    "formatted": top.get("formatted_address"),
                    "place_id": top.get("place_id"),
                }
                _outcome = GeocodeOutcome.HIT.value
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ai-measure] geocode failed for {address!r}: {e}")
        _err = f"{type(e).__name__}:{str(e)[:200]}"
    finally:
        if close:
            await client.aclose()

    await write_geocode_log(
        db_conn=_db, logger=_logger,
        tenant_id=tenant_id, entity_type="ai_measure",
        entity_id=None, address=address or "",
        trigger_reason=GeocodeTrigger.AI_MEASURE_RESOLVE.value,
        outcome=_outcome,
        lat=(_result or {}).get("lat"),
        lng=(_result or {}).get("lng"),
        error=_err,
        started_at=_started_at, api_key=key,
    )
    return _result


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


# Phase AIM0.1 · Feb-2026 — MIME sniffer.  Google Static Maps returns
# PNG by default (magic ``\x89PNG``), not JPEG.  Emit the correct
# ``image/png`` (or ``image/jpeg`` for the ``\xFF\xD8`` case) header
# on the inlined data URL so the browser doesn't waste a first
# render pass on a mislabelled decoder.  Table-driven so a future
# addition (WebP / AVIF returned by ``format=webp``) doesn't require
# a code edit.
_IMAGE_MAGIC_TO_MIME: List[Tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n",         "image/png"),
    (b"\xff\xd8\xff",              "image/jpeg"),
    (b"GIF87a",                    "image/gif"),
    (b"GIF89a",                    "image/gif"),
    (b"RIFF",                      "image/webp"),  # first 4 bytes; WEBP has "WEBP" at offset 8
]


def sniff_image_mime(image_bytes: bytes, default: str = "image/png") -> str:
    """Return the appropriate MIME string for ``image_bytes`` based
    on the first few magic bytes.  Falls back to ``default`` when no
    known signature matches.  The image bytes are inspected — the
    HTTP ``Content-Type`` header is intentionally ignored because
    Google's proxy occasionally sends ``application/octet-stream``
    on a re-serve, whereas the on-wire bytes never lie."""
    if not image_bytes:
        return default
    head = image_bytes[:12]
    for magic, mime in _IMAGE_MAGIC_TO_MIME:
        if head.startswith(magic):
            return mime
    return default

# Phase AIM0.1 · Feb-2026 — tolerant JSON extraction.
#
# Both vision providers ship the JSON reply wrapped in a Markdown
# fenced code block (```json\n{"features":[...]}\n```), and Claude
# often trails prose commentary after the fence.  The upstream
# ``services.llm_provider._extract_json`` uses a first-brace-to-
# last-brace slice which:
#   * silently drops **bare-array** replies (``[{...}]``) — the
#     ``find("{")`` returns -1 and it returns ``{}``.
#   * loses the fence structure when a model dumps prose BEFORE the
#     JSON and includes the JSON's braces inside its own ``[...]``.
#
# We keep AIM0's endpoint contract 200-safe by (a) requesting
# ``parse_json=False`` so the raw model text lands on
# ``result.content`` verbatim, and (b) running this local parser
# which tolerates every shape the models actually emit.
_FENCE_RE = re.compile(
    r"```(?:json|JSON|Json)?\s*(.*?)\s*```",
    re.DOTALL,
)


def _strip_code_fences(text: str) -> str:
    """Return the content of the FIRST fenced code block in ``text``
    if any, otherwise return ``text`` unchanged.  Preserves the raw
    string when the fence is malformed."""
    if not isinstance(text, str):
        return ""
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _first_balanced_json(text: str) -> Optional[Any]:
    """Extract the first balanced JSON expression (object OR array)
    from ``text``.  Returns the parsed value or ``None``.  This is
    the workhorse behind :func:`_extract_features` when the model
    dumps prose alongside the JSON."""
    if not text:
        return None
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
    return None


def _unwrap_dispatcher_envelope(raw: Any) -> Any:
    """Peel the dispatcher / llm_provider envelope so callers see
    the actual model reply, whatever level of nesting it landed at.

    Envelopes we handle:

      * ``{"raw": <inner>, "provider": "..."}`` — the
        ``call_llm_with_fallback`` return shape.
      * ``{"raw": {"text": "..."}}`` — the ``parse_json=False`` path
        in ``_call_emergent_text``.
      * ``{"raw": {"features": [...]}}`` — the ``parse_json=True``
        path when the upstream ``_extract_json`` did the work.
      * ``{"text": "..."}`` — bare text envelope (some legacy adapters).
    """
    visited = 0
    while isinstance(raw, dict) and visited < 4:
        visited += 1
        if "features" in raw:
            return raw
        # Prefer the ``"raw"`` field over ``"text"``: some responses
        # carry both (raw = parsed JSON, text = raw string).
        if "raw" in raw and raw["raw"] is not None:
            raw = raw["raw"]
            continue
        if "text" in raw and isinstance(raw["text"], str):
            return raw["text"]
        break
    return raw


def _extract_features(raw: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Parse the vision reply into a normalized ``features`` list.

    Tolerant of every shape the two vision providers actually emit:

      1. ``{"features": [...]}``     — the spec shape.
      2. ``[{...}, {...}]``          — bare-array response (wrap it).
      3. ``"```json\\n{...}\\n```"``  — fenced JSON string.
      4. Prose + JSON in the same response (extract via balanced-
         brace / -bracket walk).
      5. Dispatcher envelope wrapper (unwrapped upfront).

    On any residual shape drift we return (``[]``, error_msg) so
    the endpoint still 200s per the AIM0 spec (the empty-features
    + ``error`` branch).
    """
    raw = _unwrap_dispatcher_envelope(raw)
    # String path — most common: strip fences, then try full-JSON
    # parse, then balanced-brace / -bracket walk as a last resort.
    if isinstance(raw, str):
        stripped = _strip_code_fences(raw)
        parsed: Any = None
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = _first_balanced_json(stripped) or _first_balanced_json(raw)
        if parsed is None:
            return [], "json_parse_failed"
        raw = parsed
    # Bare-array shape → wrap.
    if isinstance(raw, list):
        raw = {"features": raw}
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
    returned dict so the sibling provider still gets a chance.

    Phase AIM0.1 · Feb-2026 — the dispatcher's built-in JSON extractor
    (``_extract_json`` in ``services.llm_provider``) uses a first-``{``
    to last-``}`` slice which silently drops bare-array replies and
    strips context around fenced JSON.  Both vision providers actually
    emit fenced Markdown code blocks (``\\`\\`\\`json\\n{...}\\n\\`\\`\\```) with Claude
    frequently trailing prose commentary AFTER the fence.  We request
    ``parse_json=False`` here so the untouched raw text lands on
    ``result.content`` and we run our own tolerant parser
    (:func:`_extract_features`) locally.
    """
    started = time.perf_counter()
    label = "openai_gpt-4o" if route == "openai_vision" else "anthropic_claude"
    try:
        result = await dispatch_ai_completion(
            tenant_id=tenant_id,
            system_prompt="You are a precise satellite-image analyst.",
            user_text=prompt,
            parse_json=False,   # Phase AIM0.1 — see docstring above.
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

    # Phase AIM0.1 · Feb-2026 — try ``result.content`` first (the
    # raw text extracted by the dispatcher when ``parse_json=False``)
    # then fall back to the envelope ``result.raw``.  We try both
    # sources because BYO providers historically populate ``raw``
    # while the Emergent platform fallback populates ``content``;
    # picking the one with an actual features array beats guessing
    # from provider identity.
    content_text: str = getattr(result, "content", "") or ""
    raw_env: Any = getattr(result, "raw", None) or {}

    features, err = _extract_features(content_text)
    if err or not features:
        # ``content`` was empty or unparseable — try the raw envelope.
        env_features, env_err = _extract_features(raw_env)
        if env_features or (env_err is None and not err):
            features, err = env_features, env_err
    tokens = getattr(result, "tokens_total", 0)

    # Phase AIM0.1 debug log — captures the actual response shape
    # so future extractor drift is caught at deploy time.  Truncated
    # to 400 chars to avoid log-line explosion on prose-heavy
    # replies.  Emitted at INFO for the first week post-ship, then
    # can be demoted to DEBUG in a follow-up.
    _log_source = content_text if isinstance(content_text, str) and content_text else raw_env
    _text_for_log = _log_source if isinstance(_log_source, str) else json.dumps(_log_source)[:800]
    _top_keys: Any = "-"
    try:
        _peek = json.loads(_strip_code_fences(_log_source) if isinstance(_log_source, str) else "")
        if isinstance(_peek, dict):
            _top_keys = list(_peek.keys())
        elif isinstance(_peek, list):
            _top_keys = f"bare-array(len={len(_peek)})"
    except Exception:
        _top_keys = "not-valid-json-at-root"
    logger.info(
        "[ai-measure] provider=%s latency_ms=%d tokens=%d features=%d err=%s "
        "top_keys=%s raw_first_400=%r",
        label, elapsed, tokens, len(features), err or "-",
        _top_keys, (_text_for_log or "")[:400],
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
    # Resolve tenant_id early so the geocode telemetry row carries
    # proper per-tenant attribution (P0-GEOCODE-LEAK-C2.5).
    _tenant_id_for_geo = str(
        (tenant or {}).get("id") or (tenant or {}).get("_id") or ""
    ) or None
    if (lat is None or lng is None) and body.address:
        async with httpx.AsyncClient(timeout=10.0) as client:
            g = await geocode_address(
                body.address, http_client=client,
                tenant_id=_tenant_id_for_geo,
            )
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
    # Phase AIM0.1 · Feb-2026 — sniff the actual bytes for the MIME
    # rather than hard-coding image/jpeg. Static Maps returns PNG by
    # default (magic ``\x89PNG``) — a mislabelled data URL forces
    # the browser to fall back to a slow content-sniff path.
    tile_mime = sniff_image_mime(tile_bytes)
    data_url = f"data:{tile_mime};base64,{tile_b64}"

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
