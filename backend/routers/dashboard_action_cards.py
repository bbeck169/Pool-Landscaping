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
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from config import db
from routers.tenants import get_current_tenant
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


async def _count_leads_today(tenant_id: str, day_start: datetime) -> int:
    return await db.leads.count_documents({
        "tenant_id": tenant_id,
        "created_at": {"$gte": day_start.isoformat()},
    })


async def _count_open_alerts(tenant_id: str) -> int:
    return await db.intelligence_alerts.count_documents({
        "tenant_id": tenant_id, "dismissed_at": None,
    })


async def _count_missed_services_today(
    tenant_id: str, day_start: datetime, today_iso: str,
) -> int:
    # ``intelligence_alerts.created_at`` is persisted as a BSON
    # datetime — compare against the datetime directly, not the ISO
    # string.  Storing ISO on leads / invoices is the historic
    # convention; alerts diverge, hence the split $gte types.
    q = {
        "tenant_id": tenant_id,
        "category": "missed_service",
        "dismissed_at": None,
        "created_at": {"$gte": day_start},
    }
    return await db.intelligence_alerts.count_documents(q)


@router.get("/dashboard/action-cards")
async def get_action_cards(
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_dashboard_role(user)
    tenant_id = tenant["id"]
    now = datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    today_iso = now.date().isoformat()

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
                                     tenant_id, day_start),
        "open_alerts":           await _count_open_alerts(tenant_id),
        "missed_services_today": await _count_missed_services_today(
                                     tenant_id, day_start, today_iso),
        "generated_at":          now.isoformat(),
    }
