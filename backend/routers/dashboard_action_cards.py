"""Phase L1.5 · Feb-2026 — Dashboard action-cards summary endpoint.

Single batched read that powers the row of action cards on the
admin dashboard.  Each card carries a count; the frontend hides
cards with count 0 (except Open Intelligence Alerts, which is
always shown so the operator has a stable link to the alerts page).

Route
-----
``GET /api/dashboard/action-cards`` — admin / super_admin / manager
only.  Anything else → 403 ``insufficient_role_for_dashboard``.

Response shape
--------------
::

    {
      "today_routes":          int,
      "pending_checkins":      int,
      "unpaid_invoices":       int,
      "overdue_invoices":      int,
      "new_leads_today":       int,
      "open_alerts":           int,
      "missed_services_today": int,
      "generated_at":          "ISO8601"
    }

Phase P15 · Feb-2026 — every "today" bucket below is anchored to
the tenant's local timezone (via
``services.tenant_helpers.tenant_day_utc_bounds`` + ``now_in_tenant_tz``)
so a request at 01:30 UTC / 18:30 Phoenix returns the CURRENT
Phoenix day's counts — not tomorrow-in-UTC's.  Reports / analytics
tiles are intentionally out of scope (deferred to a later phase).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from config import db
from routers.tenants import get_current_tenant
from services.tenant_helpers import (
    now_in_tenant_tz,
    tenant_day_utc_bounds,
)
from utils import get_current_user

router = APIRouter(tags=["dashboard"])

_ALLOWED_ROLES = {"admin", "super_admin", "manager", "owner"}


def _require_dashboard_role(user: Dict[str, Any]) -> None:
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=403, detail="insufficient_role_for_dashboard",
        )


async def _count_today_routes(tenant_id: str, today_iso: str) -> int:
    """Distinct technicians (or crews) with at least one scheduled
    job today.  Empty tenants → 0."""
    tech_ids = await db.jobs.distinct(
        "technician_id",
        {"tenant_id": tenant_id,
          "scheduled_date": today_iso,
          "status": {"$in": ["scheduled", "pending",
                              "in_progress", "completed"]}},
    )
    return len([t for t in tech_ids if t])


async def _count_pending_checkins(tenant_id: str) -> int:
    """Best-effort count — pings the ``pending_checkins`` collection
    if it exists, else falls back to zero. Kept resilient so an
    unseeded tenant never 500s the whole dashboard."""
    try:
        return await db.pending_checkins.count_documents(
            {"tenant_id": tenant_id, "reviewed_at": None})
    except Exception:                                       # noqa: BLE001
        return 0


async def _count_invoices_by_status(
    tenant_id: str, statuses: list,
) -> int:
    return await db.invoices.count_documents(
        {"tenant_id": tenant_id, "status": {"$in": statuses}})


async def _count_leads_today(tenant_id: str, day_start_utc_iso: str) -> int:
    """Phase P15 · Feb-2026 — anchored to the tenant-local day's
    UTC start (was: UTC midnight).  ``leads.created_at`` is a UTC
    ISO string, so the string ``$gte`` compare is safe."""
    return await db.leads.count_documents({
        "tenant_id": tenant_id,
        "created_at": {"$gte": day_start_utc_iso},
    })


async def _count_open_alerts(tenant_id: str) -> int:
    return await db.intelligence_alerts.count_documents({
        "tenant_id": tenant_id, "dismissed_at": None,
    })


async def _count_missed_services_today(
    tenant_id: str, day_start_utc: datetime,
) -> int:
    """Phase P15 · Feb-2026 — anchored to the tenant-local day's
    UTC start (was: UTC midnight).  ``intelligence_alerts.created_at``
    is stored as a BSON datetime; the tz-aware ``day_start_utc``
    compares against it directly."""
    q = {
        "tenant_id": tenant_id,
        "category": "missed_service",
        "dismissed_at": None,
        "created_at": {"$gte": day_start_utc},
    }
    return await db.intelligence_alerts.count_documents(q)


@router.get("/dashboard/action-cards")
async def get_action_cards(
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_dashboard_role(user)
    tenant_id = tenant["id"]
    # Phase P15 · Feb-2026 — every "today" bucket is anchored to
    # the tenant's local calendar day, not UTC.  ``now_in_tenant_tz``
    # returns a tz-aware datetime in the tenant's zone; its
    # ``.date().isoformat()`` yields the local YYYY-MM-DD that
    # ``jobs.scheduled_date`` was written with.  ``tenant_day_utc_bounds``
    # converts that back to the UTC window
    # ``[day_start_utc, day_end_utc)`` for datetime-typed fields
    # (leads.created_at, intelligence_alerts.created_at).
    now_local = now_in_tenant_tz(tenant)
    today_iso = now_local.date().isoformat()
    day_start_utc_iso, _ = tenant_day_utc_bounds(tenant, today_iso)
    # BSON datetime version of the same anchor for the
    # intelligence_alerts.created_at compare.
    day_start_utc = datetime.fromisoformat(day_start_utc_iso)

    return {
        "today_routes":          await _count_today_routes(
                                     tenant_id, today_iso),
        "pending_checkins":      await _count_pending_checkins(tenant_id),
        "unpaid_invoices":       await _count_invoices_by_status(
                                     tenant_id, ["unpaid", "issued",
                                                  "sent"]),
        "overdue_invoices":      await _count_invoices_by_status(
                                     tenant_id, ["overdue", "past_due"]),
        "new_leads_today":       await _count_leads_today(
                                     tenant_id, day_start_utc_iso),
        "open_alerts":           await _count_open_alerts(tenant_id),
        "missed_services_today": await _count_missed_services_today(
                                     tenant_id, day_start_utc),
        "generated_at":          datetime.now(timezone.utc).isoformat(),
    }
