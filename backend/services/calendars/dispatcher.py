"""Phase I1.7.c.3 · Feb-2026 — dispatch_calendars_* wrappers.

Push (CRM job → Calendar) and pull (Calendar → CRM availability
block) are dispatched here so callsite migration in phase I1.7.e is
a single-line swap.

Fallback rules — Calendars have **NO platform fallback** (unlike
AI/Maps). Every technician who wants sync MUST connect their own
Google/Outlook account. If no link exists, both dispatchers raise
``TenantCalendarsNotConnected``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ._helpers import now_iso
from .models import (
    CalendarPullDelta,
    CalendarPushResult,
    TenantCalendarsNotConnected,
    TenantCalendarsSyncOpCapExceeded,
)
from .registry import get_calendar_provider, short_name_for
from .technician_link import (
    get_link,
    update_sync_token,
)
from .usage import enforce_cap_or_raise, record_usage


log = logging.getLogger("calendars.dispatch")


async def dispatch_calendars_push_event(
    *, tenant_id: str, technician_user_id: str,
    provider_key: str, event: Dict[str, Any],
    db=None,
) -> CalendarPushResult:
    """Push a CRM job to the technician's calendar."""
    link = await get_link(
        tenant_id=tenant_id, technician_user_id=technician_user_id,
        provider_key=provider_key, db=db,
    )
    if not link:
        raise TenantCalendarsNotConnected(
            f"No {provider_key} link for tenant={tenant_id} "
            f"technician={technician_user_id}"
        )
    short = short_name_for(provider_key) or provider_key
    await enforce_cap_or_raise(tenant_id=tenant_id, provider=short, db=db)
    provider = get_calendar_provider(provider_key)
    result = await provider.push_event(
        tenant_id=tenant_id, technician_user_id=technician_user_id,
        event=event,
    )
    try:
        await record_usage(
            tenant_id=tenant_id, provider=short,
            operation="push_event", db=db,
        )
    except Exception as e:  # pragma: no cover
        log.warning("[calendars.dispatch] record_usage push_event failed: %s", e)
    return result


async def dispatch_calendars_pull_delta(
    *, tenant_id: str, technician_user_id: str,
    provider_key: str, db=None,
) -> CalendarPullDelta:
    """Pull a delta batch from the technician's calendar. Persists the
    ``next_sync_token`` on success so the next poll picks up where
    this one left off."""
    link = await get_link(
        tenant_id=tenant_id, technician_user_id=technician_user_id,
        provider_key=provider_key, db=db,
    )
    if not link:
        raise TenantCalendarsNotConnected(
            f"No {provider_key} link for tenant={tenant_id} "
            f"technician={technician_user_id}"
        )
    short = short_name_for(provider_key) or provider_key
    await enforce_cap_or_raise(tenant_id=tenant_id, provider=short, db=db)
    provider = get_calendar_provider(provider_key)
    result = await provider.pull_delta(
        tenant_id=tenant_id, technician_user_id=technician_user_id,
        sync_token=link.get("sync_token"),
    )
    try:
        await update_sync_token(
            tenant_id=tenant_id, technician_user_id=technician_user_id,
            provider_key=provider_key,
            next_token=result.next_sync_token, db=db,
        )
    except Exception as e:  # pragma: no cover
        log.warning("[calendars.dispatch] update_sync_token failed: %s", e)
    try:
        await record_usage(
            tenant_id=tenant_id, provider=short,
            operation="pull_delta", db=db,
        )
    except Exception as e:  # pragma: no cover
        log.warning("[calendars.dispatch] record_usage pull_delta failed: %s", e)
    return result


async def ensure_indexes(db) -> None:
    """Boot-time index creation. Called by server startup."""
    from .oauth_state import ensure_state_indexes
    from .technician_link import ensure_indexes as _link_indexes
    await ensure_state_indexes(db)
    await _link_indexes(db)


__all__ = [
    "dispatch_calendars_push_event",
    "dispatch_calendars_pull_delta",
    "ensure_indexes",
    "TenantCalendarsNotConnected",
    "TenantCalendarsSyncOpCapExceeded",
]
