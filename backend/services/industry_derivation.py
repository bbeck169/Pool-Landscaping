"""Phase L1.2 · Feb-2026 — industry derivation for jobs.

Replaces the string-matching-only ``classify_job`` shim in
``routers.jobs`` with a tenant-aware resolver.  Retained as a
service so future MI-cluster work (industry-specific checklists /
proposal templates / KPI rollups) can reuse the same function.

Resolution order (first non-``None`` wins)
------------------------------------------
1.  ``job.industry`` — explicit override written on the job itself.
2.  ``tenant.settings.default_industry`` — operator-configured
    fallback for tenants that always run one industry (Vistancia is
    the canonical example).
3.  Single-element ``tenant.industries`` — some tenants have a
    single-industry list at the top level.
4.  ``classify_job(job.service_type)`` — legacy keyword match.
    Kept as the last-resort fallback so pre-migration jobs still
    render the correct checklist.
5.  ``None`` — the caller decides how to render (usually "pool"
    default for backwards-compatibility with the pool CRM roots).

Return value
------------
Lowercase slug matching one of ``INDUSTRY_SLUGS`` from
``routers.industry_checklists``.  Callers are free to coerce to
``"pool"`` when ``None`` is returned — the function does not
force a default so the caller can log a debug metric.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Slugs the CRM knows about — mirrors
# ``routers.industry_checklists.INDUSTRY_SLUGS``.  Repeated locally
# to avoid a circular import (jobs → services → industry_checklists →
# routers.tenants → …).  Sync with the MI1 canonical list.
_KNOWN_SLUGS = {
    "pool", "landscaping", "hvac", "pest_control",
    "cleaning", "solar", "handyman",
    "plumbing", "electrical", "roofing", "painting",
    "garage_door", "appliance_repair", "locksmith",
    "chimney_sweep", "gutter", "window_cleaning",
    "carpet_cleaning", "pressure_washing", "tree_service",
    "snow_removal", "fencing", "irrigation",
}


def _normalize(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in _KNOWN_SLUGS else None


def _fallback_keyword(service_type: Optional[str]) -> Optional[str]:
    """Legacy 2-way match — mirrors the removed ``classify_job``.

    Returns ``"landscaping"`` when ``service_type`` contains
    ``"landscap"`` (case-insensitive), else ``"pool"``. ``None``
    when ``service_type`` is falsy.
    """
    if not service_type:
        return None
    st = str(service_type).lower()
    return "landscaping" if "landscap" in st else "pool"


def derive_industry_for_job(
    job: Dict[str, Any],
    tenant: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Resolve the effective industry for a job — see module docstring."""
    # 1. Explicit override on the job.
    explicit = _normalize((job or {}).get("industry"))
    if explicit:
        return explicit

    # 2. Tenant-configured default.
    settings = ((tenant or {}).get("settings")) or {}
    tenant_default = _normalize(settings.get("default_industry"))
    if tenant_default:
        return tenant_default

    # 3. Single-industry tenant.
    industries = (tenant or {}).get("industries") or []
    if isinstance(industries, list) and len(industries) == 1:
        one = _normalize(industries[0])
        if one:
            return one

    # 4. Legacy keyword match.
    return _fallback_keyword((job or {}).get("service_type"))
