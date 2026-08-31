"""Feb-2026 · Public widget map surface (extension to
``public_widget.py``).

Two new public, CORS-open endpoints alongside the existing feed:

* ``GET /api/public/checkins/{tenant_slug}/pins``
    JSON with obfuscated coords for every approved row in the last
    12 months. Same 60/min per-IP rate limit as the feed. Used
    both by browser ``fetch()`` from the map.html template AND by
    third parties who want to build custom UIs on top of the pin
    data.

* ``GET /api/public/checkins/{tenant_slug}/map.html``
    Standalone HTML — Leaflet + OSM tiles + marker cluster plugin,
    all from CDN. Embed target for
    ``<iframe src=".../map.html">``. Includes schema.org
    ``LocalBusiness`` JSON-LD with ``areaServed[]`` and
    ``makesOffer[]`` derived from the same pin dataset.

PII / SEO invariants (pinned by ``test_widget_map_html_hides_pii``):

* No ``customer_name`` / ``customer_id`` / raw ``lat``, ``lng``
  in the response bodies.
* No ``job_id`` / exact ``completed_at``. Public dates are
  month-year only.
* Rejected / pending / unpublished rows never appear.

Rate limit: uses the same per-process ``_ip_buckets`` from
``public_widget`` so the whole widget surface shares a budget —
matches the user's spec ("60 rpm regardless of pin count").
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from config import db
from routers.public_widget import (
    _client_ip, _cors, _rate_ok, _tenant_by_slug, _tenant_logo_url,
)
from utils import now_iso

router = APIRouter()

# 12-month rolling window per user spec.
_WINDOW_DAYS = 365
# Cap on ``areaServed[]`` — deduplicated by area_label to keep the
# JSON-LD block reasonable (Googlebot has a soft 128kb ceiling).
_MAX_AREAS = 100


def _month_year_from_row(row: Dict[str, Any]) -> str:
    """Prefer the pre-computed field; fall back to a re-derivation
    from ``approved_at`` for older rows without the new field."""
    pre = row.get("completed_at_month_year")
    if pre:
        return str(pre)
    ts = row.get("completed_at") or row.get("approved_at") \
        or row.get("submitted_at")
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%B %Y")
    except (ValueError, TypeError):
        return ""


def _row_is_pinnable(row: Dict[str, Any]) -> bool:
    """A row is pinnable when the map has obfuscated coords AND is
    in the ``approved`` state. Rows submitted before Feb-2026 may
    lack ``lat_public``/``lng_public`` — those are silently
    filtered out (no auto-backfill; the tenant runs the migration
    if they want historical pins)."""
    if row.get("state") != "approved":
        return False
    return (row.get("lat_public") is not None
             and row.get("lng_public") is not None)


async def _load_approved_within_window(
    tenant_id: str,
) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    cutoff_iso = cutoff.isoformat()
    rows: List[Dict[str, Any]] = []
    async for row in db.public_checkins.find(
        {
            "tenant_id": tenant_id,
            "state": "approved",
            # ``approved_at`` is the definitive "we published this"
            # timestamp for a moderation queue row; fall back to
            # ``completed_at`` for rows migrated from the auto
            # enqueue path where both are set at once.
            "$or": [
                {"approved_at": {"$gte": cutoff_iso}},
                {"completed_at": {"$gte": cutoff_iso}},
            ],
        },
        {"_id": 0},
    ):
        if _row_is_pinnable(row):
            rows.append(row)
    return rows


def _pin_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return the caller-safe pin payload — obfuscated coords +
    service_type + month-year + area_label ONLY. No IDs, no raw
    coords, no customer name, no dates finer than month-year."""
    return {
        "lat": row.get("lat_public"),
        "lng": row.get("lng_public"),
        "service_type": row.get("service_name") or "",
        "completed_at_month_year": _month_year_from_row(row),
        "area_label": row.get("area_label") or "",
    }


# ═══════════════════════════════════════════════════════════════════
# 1) JSON pins endpoint
# ═══════════════════════════════════════════════════════════════════
@router.options("/public/checkins/{tenant_slug}/pins",
                 include_in_schema=False)
async def pins_options(tenant_slug: str):  # noqa: ARG001 — path param
    return _cors(Response(status_code=204))


@router.get("/public/checkins/{tenant_slug}/pins",
             operation_id="publicWidget.mapPins")
async def public_pins(
    tenant_slug: str,
    request: Request,
    response: Response,
):
    _cors(response)
    ip = _client_ip(request)
    if not _rate_ok(ip):
        raise HTTPException(429, {"error": "rate_limited"})

    tenant = await _tenant_by_slug(tenant_slug)
    rows = await _load_approved_within_window(tenant["id"])
    pins = [_pin_from_row(r) for r in rows]

    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "tenant": {
            "name": tenant.get("name"),
            "slug": tenant.get("slug"),
        },
        "pins": pins,
        "count": len(pins),
        "as_of": now_iso(),
        "window_days": _WINDOW_DAYS,
    }


# ═══════════════════════════════════════════════════════════════════
# 2) map.html — standalone Leaflet embed with JSON-LD
# ═══════════════════════════════════════════════════════════════════
def _json_ld_block(
    tenant: Dict[str, Any], pins: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the ``LocalBusiness`` schema.org block. Areas dedupe by
    ``area_label`` and cap at ``_MAX_AREAS`` to keep the JSON size
    reasonable. Services (``makesOffer``) dedupe by ``service_type``.
    """
    settings = tenant.get("settings") or {}
    website = (settings.get("website_url")
                or settings.get("public_url")
                or tenant.get("website_url") or "")
    phone = (settings.get("phone") or tenant.get("phone")
              or (settings.get("business_card") or {}).get("phone") or "")
    address = settings.get("business_card") or {}

    seen_areas: Dict[str, Dict[str, Any]] = {}
    seen_services: set = set()
    services: List[Dict[str, Any]] = []
    for p in pins:
        label = (p.get("area_label") or "").strip()
        if label and label not in seen_areas and len(seen_areas) < _MAX_AREAS:
            seen_areas[label] = {
                "@type": "Place",
                "name": label,
                "geo": {
                    "@type": "GeoCoordinates",
                    "latitude": p.get("lat"),
                    "longitude": p.get("lng"),
                },
            }
        stype = (p.get("service_type") or "").strip()
        if stype and stype not in seen_services:
            seen_services.add(stype)
            services.append({
                "@type": "Offer",
                "itemOffered": {"@type": "Service", "name": stype},
            })

    ld: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": tenant.get("name") or "",
        "areaServed": list(seen_areas.values()),
        "makesOffer": services,
    }
    if website:
        ld["@id"] = website
        ld["url"] = website
    if phone:
        ld["telephone"] = phone
    if address.get("city") or address.get("state"):
        ld["address"] = {
            "@type": "PostalAddress",
            "addressLocality": address.get("city") or "",
            "addressRegion": address.get("state") or "",
            "addressCountry": "US",
        }
    return ld


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
      crossorigin=""/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; font-family: system-ui, sans-serif; }}
  #checkins-map {{ position: absolute; inset: 0; }}
  .emg-tooltip {{ font-size: 12px; line-height: 1.35; }}
  .emg-tooltip strong {{ display: block; margin-bottom: 2px; }}
  .emg-badge {{
    position: absolute; z-index: 500; top: 8px; left: 52px;
    background: rgba(255,255,255,0.9); padding: 4px 8px;
    border-radius: 6px; font-size: 11px; color: #333;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    max-width: calc(100% - 60px); overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
  }}
</style>
</head>
<body>
<div id="checkins-map" data-testid="widget-map-container"></div>
<div class="emg-badge" data-testid="widget-map-badge">{badge}</div>
<script type="application/ld+json" data-testid="widget-map-jsonld">
{json_ld}
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin=""></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
(function() {{
  var pins = {pins_json};
  var map = L.map('checkins-map');
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);

  if (!pins.length) {{
    map.setView([39.5, -98.35], 4);  // continental US fallback
    return;
  }}

  var cluster = L.markerClusterGroup({{
    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,
    maxClusterRadius: 40,
  }});
  var bounds = L.latLngBounds([]);
  pins.forEach(function(p) {{
    if (typeof p.lat !== 'number' || typeof p.lng !== 'number') return;
    var m = L.marker([p.lat, p.lng]);
    var tooltip = '<div class="emg-tooltip">'
      + '<strong>' + (p.service_type || 'Service') + '</strong>'
      + (p.area_label ? p.area_label + '<br/>' : '')
      + (p.completed_at_month_year || '')
      + '</div>';
    m.bindPopup(tooltip);
    cluster.addLayer(m);
    bounds.extend([p.lat, p.lng]);
  }});
  map.addLayer(cluster);
  if (bounds.isValid()) {{
    map.fitBounds(bounds, {{ padding: [40, 40], maxZoom: 12 }});
  }}
}})();
</script>
</body>
</html>
"""


@router.options("/public/checkins/{tenant_slug}/map.html",
                 include_in_schema=False)
async def map_options(tenant_slug: str):  # noqa: ARG001
    return _cors(Response(status_code=204))


@router.get("/public/checkins/{tenant_slug}/map.html",
             operation_id="publicWidget.mapHtml",
             response_class=HTMLResponse)
async def public_map_html(
    tenant_slug: str,
    request: Request,
):
    ip = _client_ip(request)
    if not _rate_ok(ip):
        raise HTTPException(429, {"error": "rate_limited"})

    tenant = await _tenant_by_slug(tenant_slug)
    rows = await _load_approved_within_window(tenant["id"])
    pins = [_pin_from_row(r) for r in rows]
    ld = _json_ld_block(tenant, pins)

    tenant_name = str(tenant.get("name") or "Check-ins")
    title = html.escape(f"{tenant_name} · Recent Service Check-ins")
    badge = html.escape(f"{tenant_name} · {len(pins)} recent visits")

    body = _HTML_TEMPLATE.format(
        title=title,
        badge=badge,
        pins_json=json.dumps(pins, ensure_ascii=False),
        json_ld=json.dumps(ld, ensure_ascii=False),
    )
    response = HTMLResponse(content=body, status_code=200)
    _cors(response)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
