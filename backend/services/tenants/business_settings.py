"""Feb-2026 · Business Settings — effective-settings resolver.

Shared helper that reads the per-tenant Business Settings fields off
``db.tenants`` and materialises the "effective" record — every field
falls back to a sensible default so downstream consumers (PDFs,
emails, portal views) never see ``None`` gaps.

The Business Settings phase ships this helper as the single source
of truth. The next-phase Theme Refresh consumes it verbatim.

See /app/memory/FEATURE_BUSINESS_SETTINGS.md.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Palette defaults keyed off the existing "brand" tokens. When a
# tenant hasn't picked colours yet these are the values every
# renderer will see, keeping the current visual identity intact.
DEFAULT_PRIMARY_HEX = "#0B4A6F"
DEFAULT_SECONDARY_HEX = "#F97316"

# The full set of Business Settings columns on ``db.tenants``.
BUSINESS_SETTINGS_KEYS = (
    "company_display_name",
    "mailing_address",
    "phone",
    "website",
    "email",
    "brand_primary_hex",
    "brand_secondary_hex",
    "logo_url",
    "footer_note",
    "tax_id",
)

# ``brand_primary_hex`` / ``brand_secondary_hex`` regex — used by the
# router-side pydantic validator.
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _pick(tenant: Dict[str, Any], key: str) -> Optional[str]:
    """Return the raw stored value for ``key`` or ``None`` when unset
    / blank. Keeps the "falls-back-to-default" semantics contained in
    one place.
    """
    v = tenant.get(key)
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def build_business_settings_view(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{stored, effective}`` for a preloaded tenant doc.

    * ``stored`` — the raw fields as saved (``None`` when unset).
    * ``effective`` — the values a renderer should use with defaults
      resolved.

    Kept purely functional so tests exercise it without a Mongo
    round-trip.
    """
    stored = {k: _pick(tenant, k) for k in BUSINESS_SETTINGS_KEYS}
    company_fallback = (
        _pick(tenant, "company_display_name")
        or tenant.get("company_name")
        or ""
    )
    effective = {
        **stored,
        "company_display_name": company_fallback,
        "brand_primary_hex": stored["brand_primary_hex"] or DEFAULT_PRIMARY_HEX,
        "brand_secondary_hex": stored["brand_secondary_hex"] or DEFAULT_SECONDARY_HEX,
    }
    return {"stored": stored, "effective": effective}


async def get_effective_business_settings(db, tenant_id: str) -> Dict[str, Any]:
    """Async wrapper — reads the tenant doc and returns the
    ``effective`` view. Downstream callers (PDF renderers, email
    shell, estimate payload builders) go through this so nobody
    duplicates the fallback rules.
    """
    if not tenant_id:
        return build_business_settings_view({})["effective"]
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    return build_business_settings_view(t)["effective"]


CUSTOMER_SAFE_KEYS = (
    "company_display_name",
    "mailing_address",
    "phone",
    "website",
    "email",
    "logo_url",
    "brand_primary_hex",
    "brand_secondary_hex",
    "footer_note",
)


def to_public_branding(effective: Dict[str, Any]) -> Dict[str, Any]:
    """Filter an ``effective`` view down to the customer-safe keys.

    Explicitly drops ``tax_id`` and any admin-only surface. Used by
    the public ``GET /api/portal/tenant/branding`` route.
    """
    return {k: effective.get(k) for k in CUSTOMER_SAFE_KEYS}


__all__ = [
    "BUSINESS_SETTINGS_KEYS",
    "CUSTOMER_SAFE_KEYS",
    "DEFAULT_PRIMARY_HEX",
    "DEFAULT_SECONDARY_HEX",
    "HEX_RE",
    "build_business_settings_view",
    "get_effective_business_settings",
    "to_public_branding",
]
