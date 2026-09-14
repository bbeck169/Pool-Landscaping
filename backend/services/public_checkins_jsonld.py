"""Phase Feb-2026 · Public Check-ins Feed — Structured Data (JSON-LD).

Pure builder for the schema.org JSON-LD payload the public feed page
and the embed widget emit for SEO. Kept side-effect-free so router
handlers can call it directly and tests can assert the exact shape
without spinning up a request.

Schema types emitted
--------------------
* ``LocalBusiness``   — top-level provider block, one per feed page.
* ``ItemList``        — ordered list of the emitted check-ins.
* ``Service``         — one per approved check-in, wrapped as an
                        ``ListItem`` inside ``ItemList``.

Design rules
------------
* **Neutral factual tone** — no marketing hyperbole per Google's spam
  policy (https://developers.google.com/search/docs/essentials/spam-policies).
  The description generator emits one sentence, deterministic per
  ``(service_type, city, state, zip)`` combo.
* **``geo`` opt-in only** — a ``GeoCoordinates`` block is included on a
  ``Service`` only when both ``lat_public`` and ``lng_public`` are
  populated (post-obfuscation coords from the tech-submit path).
  Rows without coords silently omit the ``geo`` block; the ``Service``
  is still valid without it.
* **``postalCode`` opt-in only** — the masked address strips zip for
  privacy. We do NOT re-attach zip from raw_address here — that would
  defeat the mask. Callers may inject ``postal_code`` per-checkin if
  they have a safe zone-level source; otherwise omitted.
* **Deterministic output** — a given (tenant, checkin_list) input
  produces the exact same JSON-LD every call, which keeps the emitted
  HTML byte-stable and helps SEO consistency.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _title_case_service(service_type: str) -> str:
    """Format a service_type string into a factual title-cased noun
    (e.g. ``"pool_service"`` → ``"Pool service"``).  Kept simple: we
    replace underscores with spaces and title-case the first word only
    so multi-word categories don't get over-capitalised."""
    if not service_type:
        return "Service"
    cleaned = str(service_type).replace("_", " ").strip()
    if not cleaned:
        return "Service"
    # Sentence-case: first letter upper, rest as authored.
    return cleaned[0].upper() + cleaned[1:]


def build_description(
    service_type: Optional[str],
    city: Optional[str],
    state: Optional[str],
    postal_code: Optional[str] = None,
) -> str:
    """Return the neutral factual one-sentence description used on
    each ``Service`` block.

    * With city + state (+ optional zip):
        ``"Pool service completed in Peoria, AZ 85383."``
    * With city + state, no zip:
        ``"Pool service completed in Peoria, AZ."``
    * With only city or only state:
        ``"Pool service completed in Peoria."``
    * Nothing usable:
        ``"Service completed in the local area."``
    """
    has_type = bool(service_type and str(service_type).strip())
    svc = _title_case_service(service_type) if has_type else "Service"
    suffix = "service completed" if has_type else "completed"
    city = (city or "").strip()
    state = (state or "").strip()
    zip_ = (postal_code or "").strip()

    if city and state:
        base = f"{svc} {suffix} in {city}, {state}"
        if zip_:
            return f"{base} {zip_}."
        return f"{base}."
    if city:
        return f"{svc} {suffix} in {city}."
    if state:
        return f"{svc} {suffix} in {state}."
    return f"{svc} {suffix} in the local area."


def _tenant_postal_address(business_card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a PostalAddress dict from the tenant business_card.

    ``service_area`` currently ships as a single freeform string (e.g.
    ``"Peoria & Vistancia, Arizona"``). Best-effort split on comma so
    the ``addressLocality`` + ``addressRegion`` fields hydrate.
    """
    area = (business_card.get("service_area") or "").strip()
    if not area:
        return None
    locality, region = area, ""
    if "," in area:
        left, right = area.split(",", 1)
        locality, region = left.strip(), right.strip()
    addr: Dict[str, Any] = {"@type": "PostalAddress"}
    if locality:
        addr["addressLocality"] = locality
    if region:
        addr["addressRegion"] = region
    return addr


def build_local_business(
    tenant: Dict[str, Any],
    business_card: Dict[str, Any],
) -> Dict[str, Any]:
    """Return the schema.org ``LocalBusiness`` block emitted once per
    feed page. Trims empty fields so the JSON-LD stays clean and doesn't
    surface ``null`` values (rich-results validators warn on nulls)."""
    name = (business_card.get("company_name")
            or tenant.get("name") or "").strip()
    obj: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": name,
    }
    addr = _tenant_postal_address(business_card)
    if addr:
        obj["address"] = addr
    phone = (business_card.get("phone") or "").strip()
    if phone:
        obj["telephone"] = phone
    url = (business_card.get("website_url") or "").strip()
    if url:
        obj["url"] = url
    return obj


def _service_area(checkin: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build the ``areaServed`` PostalAddress from the check-in's
    ``masked_address`` (city / state). Zip intentionally omitted — the
    masker strips it, and we don't re-attach here (privacy)."""
    location = checkin.get("location") or checkin.get("masked_address") or {}
    if not isinstance(location, dict):
        return None
    city = (location.get("city") or "").strip()
    state = (location.get("state") or "").strip()
    if not (city or state):
        return None
    addr: Dict[str, Any] = {"@type": "PostalAddress"}
    if city:
        addr["addressLocality"] = city
    if state:
        addr["addressRegion"] = state
    return addr


def build_service_block(
    checkin: Dict[str, Any],
    provider_name: str,
) -> Dict[str, Any]:
    """Return one ``Service`` block for a single check-in row.

    Expects the sanitized shape emitted by ``public_feed`` (``location``
    dict with city/state) or the raw ``public_checkins`` row (with
    ``masked_address``). Handles both.
    """
    location = checkin.get("location") or checkin.get("masked_address") or {}
    city = (location.get("city") or "") if isinstance(location, dict) else ""
    state = (location.get("state") or "") if isinstance(location, dict) else ""

    service_type = (checkin.get("service_name")
                     or checkin.get("service_category")
                     or "").strip()

    svc: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Service",
        "provider": {
            "@type": "LocalBusiness",
            "name": provider_name,
        },
        "serviceType": service_type or "Service",
        "description": build_description(service_type, city, state),
    }

    area = _service_area(checkin)
    if area:
        svc["areaServed"] = area

    lat = checkin.get("lat_public")
    lng = checkin.get("lng_public")
    if lat is not None and lng is not None:
        try:
            svc["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": float(lat),
                "longitude": float(lng),
            }
        except (TypeError, ValueError):
            # Silently skip malformed coord rows — description keeps
            # the block valid.
            pass

    return svc


def build_item_list(
    checkins: List[Dict[str, Any]],
    provider_name: str,
) -> Dict[str, Any]:
    """Wrap all Service blocks in an ordered ItemList."""
    items = []
    for i, c in enumerate(checkins):
        items.append({
            "@type": "ListItem",
            "position": i + 1,
            "item": build_service_block(c, provider_name),
        })
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": items,
    }


def build_feed_jsonld(
    tenant: Dict[str, Any],
    business_card: Dict[str, Any],
    checkins: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compose the full feed-page JSON-LD payload — one dict callers
    can dump into a single ``<script type="application/ld+json">``
    block or split into two blocks if they prefer.

    Returned shape::

        {
          "local_business": {...LocalBusiness...},
          "item_list":      {...ItemList of Services...}
        }
    """
    local_business = build_local_business(tenant, business_card)
    provider_name = local_business.get("name") or tenant.get("name") or ""
    item_list = build_item_list(checkins, provider_name)
    return {
        "local_business": local_business,
        "item_list": item_list,
    }
