"""Phase Feb-2026 · Multi-industry — canonical industry enum + labels.

Phase A groundwork: no UI, no gating, no branch flipping.  Two
public surfaces are exposed here so the rest of the codebase can
depend on a single source of truth for the 25 tenant-facing
verticals:

* ``INDUSTRIES``      — ordered tuple of canonical slugs.
* ``INDUSTRY_LABELS`` — dict mapping slug → display label.

Both are mirrored verbatim on the frontend in
``frontend/src/config/industries.js``.  If you edit one, edit the
other and re-run the parity assertion in
``backend/tests/test_multi_industry_phase_a.py`` (which parses the
frontend module).

``tenant_has_industry`` is the read-time helper any router / service
can import to gate a new feature behind an active industry without
importing the tenant router.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple


INDUSTRIES: Tuple[str, ...] = (
    "pools",
    "landscaping",
    "hvac",
    "plumbing",
    "pest_control",
    "notary",
    "photography",
    "handyman",
    "electrical",
    "pressure_washing",
    "window_cleaning",
    "pet_waste_removal",
    "trash_can_cleaning",
    "moving",
    "snow_removal",
    "lighting_installation",
    "epoxy_coating",
    "garage_storage",
    "custom_closets",
    "pet_grooming",
    "beauty",
    "garage_door",
    "roofing",
    "flooring",
    "automotive",
)

# Default industry for tenants missing every hint — mirrors the
# codebase's historical single-industry default (Aquaterra / demo
# tenants are all pool-first).
DEFAULT_INDUSTRY: str = "pools"

INDUSTRY_LABELS: Dict[str, str] = {
    "pools":                "Pools",
    "landscaping":          "Landscaping",
    "hvac":                 "HVAC",
    "plumbing":             "Plumbing",
    "pest_control":         "Pest Control",
    "notary":               "Notary",
    "photography":          "Photography",
    "handyman":             "Handyman",
    "electrical":           "Electrical",
    "pressure_washing":     "Pressure Washing",
    "window_cleaning":      "Window Cleaning",
    "pet_waste_removal":    "Pet Waste Removal",
    "trash_can_cleaning":   "Trash Can Cleaning",
    "moving":               "Moving",
    "snow_removal":         "Snow Removal",
    "lighting_installation":"Lighting Installation",
    "epoxy_coating":        "Epoxy Coating",
    "garage_storage":       "Garage Storage",
    "custom_closets":       "Custom Closets",
    "pet_grooming":         "Pet Grooming",
    "beauty":               "Beauty",
    "garage_door":          "Garage Door",
    "roofing":              "Roofing",
    "flooring":             "Flooring",
    "automotive":           "Automotive",
}

# Contract: every enum slug has a matching label.  Kept as a
# module-load assertion so an import-time bug surfaces on boot
# rather than during a request.
assert set(INDUSTRIES) == set(INDUSTRY_LABELS.keys()), (
    "INDUSTRIES / INDUSTRY_LABELS keys are out of sync — edit both "
    "or run the phase A parity test to see the mismatch."
)


def is_valid_industry(slug: str) -> bool:
    """Return True when ``slug`` is one of the canonical enum values."""
    return isinstance(slug, str) and slug in INDUSTRY_LABELS


def normalize_industries(values: Iterable[Any]) -> Tuple[list, list]:
    """Split an incoming iterable into ``(valid, invalid)`` lists in
    input order, de-duped.  Used by the PATCH endpoint to build a
    single ``invalid_industry: <slug>`` error message that carries
    the first bad value.
    """
    seen: set = set()
    valid: list = []
    invalid: list = []
    for v in values or ():
        s = str(v).strip() if v is not None else ""
        if not s or s in seen:
            continue
        seen.add(s)
        if is_valid_industry(s):
            valid.append(s)
        else:
            invalid.append(s)
    return valid, invalid


def tenant_has_industry(tenant: Dict[str, Any] | None, slug: str) -> bool:
    """Return True when ``slug`` appears on the tenant's ``industries``
    array.  Safe on missing / malformed tenant docs — returns False.
    """
    if not isinstance(tenant, dict):
        return False
    industries = tenant.get("industries") or []
    if not isinstance(industries, list):
        return False
    return slug in industries


__all__ = [
    "INDUSTRIES",
    "INDUSTRY_LABELS",
    "DEFAULT_INDUSTRY",
    "is_valid_industry",
    "normalize_industries",
    "tenant_has_industry",
]
