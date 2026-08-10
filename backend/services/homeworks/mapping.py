"""Phase 55-b · Aug-2026 — Homeworks → AquaTerra field mapping.

Deterministic, side-effect-free helpers. Given a raw payload harvested
by the Playwright scraper (dict), produce the mapped_payload that
lands in ``homeworks_staging.mapped_payload``. The commit engine
(Phase 55-f) then applies the mapped payload verbatim to the target
collection with FK stamping.

Mapping is spec-locked in the Phase 55 design doc §4.1 + §4.2. Only
customers + properties are covered here; jobs / invoices / etc arrive
in phases 55-c and 55-d.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _s(v: Any) -> str:
    """Coerce to trimmed string. ``None`` → ``''``."""
    return str(v).strip() if v is not None else ""


def _list(v: Any) -> List[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        # Comma-separated fallback.
        return [t.strip() for t in v.split(",") if t.strip()]
    return []


def map_customer(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map Homeworks customer → AquaTerra ``customers`` shape."""
    first = _s(raw.get("first_name"))
    last = _s(raw.get("last_name"))
    name = _s(raw.get("name")) or f"{first} {last}".strip()
    mapped: Dict[str, Any] = {
        "name": name or None,
        "first_name": first or None,
        "last_name": last or None,
        "email": _s(raw.get("email")).lower() or None,
        "phone": _s(raw.get("phone")) or None,
        "home_phone": _s(raw.get("home_phone")) or None,
        "billing_address": _s(raw.get("billing_address")) or None,
        "address": _s(raw.get("address")) or _s(raw.get("billing_address")) or None,
        "notes": _s(raw.get("notes")) or None,
        "tags": _list(raw.get("tags")),
        # Preserve Homeworks provenance for audit / cross-referencing
        # from properties + future entity types.
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_created_at": _s(raw.get("created_at")) or None,
    }
    return {k: v for k, v in mapped.items() if v not in (None, "", [])}


def map_property(
    raw: Dict[str, Any],
    parent_customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks property/service-location → AquaTerra
    ``properties`` shape. ``parent_customer_id`` is resolved by the
    orchestrator (either the matched target for merges or the
    pre-generated UUID stashed on a new-customer staging row)."""
    address_line = _s(raw.get("address"))
    label = _s(raw.get("label")) or address_line or "Service Location"
    mapped: Dict[str, Any] = {
        "label": label,
        "customer_id": parent_customer_id,
        "address": {
            "line1": address_line or None,
            "city": _s(raw.get("city")) or None,
            "state": _s(raw.get("state")) or None,
            "zip": _s(raw.get("zip")) or None,
        },
        "pool_size_gallons": raw.get("pool_size_gallons"),
        "landscape_sq_ft": raw.get("landscape_sq_ft"),
        "gate_code": _s(raw.get("gate_code")) or None,
        "service_notes": {
            "access": _s(raw.get("access_notes")) or None,
        } if raw.get("access_notes") else None,
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_customer_id": _s(raw.get("customer_homeworks_id")) or None,
    }
    # Prune empty subdocs / None values but keep required top-level
    # keys so PropertyIn's Pydantic model accepts the payload.
    if mapped["address"] and not any(mapped["address"].values()):
        mapped["address"] = None
    return {k: v for k, v in mapped.items() if v is not None}
