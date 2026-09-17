"""Feb-2026 · Timezone Finalization — tenant timezone helpers.

Provides:
  * :func:`get_tenant_timezone` — resolve a ``ZoneInfo`` for a tenant
    doc, with a documented fallback chain.
  * :func:`now_in_tenant_tz` — the tenant-local ``datetime.now`` used
    by day/week/month bucketing endpoints so they never bucket a
    "yesterday-in-local" event into today.

Fallback chain (matches the pre-fix behavior of every helper that
already reads ``tenant.get("timezone")`` — do NOT change the ordering
without a data migration audit):

    tenant.timezone                    (canonical, top-level)
        → tenant.settings.timezone     (legacy, seldom-populated)
        → "America/Phoenix"            (Pool & Landscaping HQ; no
                                          DST → cron-friendly)

The ``America/Phoenix`` ultimate fallback is INTENTIONAL. It matches
the pre-Timezone-Finalization behaviour of every tz-aware call site
in the codebase (schedule, analytics_monthly, reports,
crew_productivity, quiet_hours, weekly_digest, referral_watcher, etc.).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TENANT_TZ = "America/Phoenix"


def _extract_tz_name(tenant: Optional[Mapping[str, Any]]) -> str:
    """Return the raw IANA name from a tenant doc — no normalisation."""
    if not tenant:
        return DEFAULT_TENANT_TZ
    # Top-level canonical field (written by
    # PATCH /api/tenants/mine/settings and read by every existing
    # tz-aware call site).
    top = (tenant.get("timezone") or "").strip()
    if top:
        return top
    # Legacy nested path — schedule.py pre-fix erroneously read
    # ``tenant.settings.tz`` (a field that was never written). Both
    # ``settings.timezone`` and ``settings.tz`` are accepted here so
    # any stray legacy tenant that has one of them keeps working.
    settings = tenant.get("settings") or {}
    if isinstance(settings, Mapping):
        legacy = (settings.get("timezone") or settings.get("tz") or "").strip()
        if legacy:
            return legacy
    return DEFAULT_TENANT_TZ


def get_tenant_timezone(tenant: Optional[Mapping[str, Any]]) -> ZoneInfo:
    """Resolve the tenant's IANA timezone as a :class:`ZoneInfo`.

    Never raises — an unknown IANA string coerces to the
    :data:`DEFAULT_TENANT_TZ` fallback so a mis-typed value can't
    500 every schedule / dashboard endpoint.
    """
    name = _extract_tz_name(tenant)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TENANT_TZ)


def get_tenant_timezone_name(tenant: Optional[Mapping[str, Any]]) -> str:
    """Same fallback chain as :func:`get_tenant_timezone` but returns
    the IANA string. Used by Mongo aggregation stages
    (``$dateToString`` etc.) that take a string ``timezone`` option.
    """
    name = _extract_tz_name(tenant)
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return DEFAULT_TENANT_TZ
    return name


def now_in_tenant_tz(
    tenant: Optional[Mapping[str, Any]],
) -> datetime:
    """Return the current wall-clock datetime in the tenant's tz.

    The returned datetime is timezone-aware and can be compared to
    other tz-aware datetimes safely. Callers that need the tenant-tz
    "today" as an ISO date string use ``.date().isoformat()``.
    """
    return datetime.now(timezone.utc).astimezone(get_tenant_timezone(tenant))
