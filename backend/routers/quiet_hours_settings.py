"""Feb-2026 · P34 — Automation quiet-hours settings endpoints.

  * ``GET  /api/settings/quiet-hours`` — any authenticated staff.
  * ``PATCH /api/settings/quiet-hours`` — super_admin / admin / manager.

Writes the four fields on ``tenants``:
    quiet_hours_enabled: bool
    quiet_hours_start:   "HH:MM" (24h)
    quiet_hours_end:     "HH:MM" (24h)
    quiet_hours_timezone: Optional IANA name (falls back to tenants.timezone)
"""
from __future__ import annotations

from typing import Optional
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, now_iso
from services.quiet_hours import _parse_hhmm, DEFAULT_START, DEFAULT_END
from routers.customers import _p27_write_audit


router = APIRouter(tags=["quiet-hours"])


# Feb-2026 · P34 — Internal on-demand release trigger. Exposed so
# tests + external cron can invoke the tick without waiting for the
# 5-min APScheduler cadence. Admin/manager/super_admin only.
@router.post("/internal/quiet-hours/release")
async def internal_release_now(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Only admin, manager, or super_admin.")
    from services.quiet_hours_release import run_release_tick
    result = await run_release_tick()
    return result


class QuietHoursPatch(BaseModel):
    enabled: Optional[bool] = None
    # Length validation happens in ``_parse_hhmm`` so we always return
    # a 400 with a stable ``detail: invalid_start/end`` payload (rather
    # than FastAPI's default 422 pydantic shape).
    start: Optional[str] = None
    end:   Optional[str] = None
    timezone: Optional[str] = Field(None, max_length=64)


def _staff_only(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if role not in ("technician", "admin", "manager", "super_admin"):
        raise HTTPException(403, "Not allowed")


def _writer_only(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if role not in ("admin", "manager", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"detail": "role_not_permitted",
                      "message": "Only admin, manager, or super_admin can edit quiet hours."},
        )


@router.get("/settings/quiet-hours")
async def get_quiet_hours(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _staff_only(user)
    return {
        "enabled": bool(tenant.get("quiet_hours_enabled", False)),
        "start":   tenant.get("quiet_hours_start")    or DEFAULT_START,
        "end":     tenant.get("quiet_hours_end")      or DEFAULT_END,
        "timezone": tenant.get("quiet_hours_timezone")
                       or tenant.get("timezone") or "America/Phoenix",
        "tenant_timezone": tenant.get("timezone") or "America/Phoenix",
    }


@router.patch("/settings/quiet-hours")
async def patch_quiet_hours(
    body: QuietHoursPatch,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _writer_only(user)

    updates: dict = {}
    if body.enabled is not None:
        updates["quiet_hours_enabled"] = bool(body.enabled)

    if body.start is not None:
        try:
            _parse_hhmm(body.start)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"detail": "invalid_start",
                          "message": "start must be HH:MM 24-hour format (e.g. 08:00)."},
            )
        updates["quiet_hours_start"] = body.start

    if body.end is not None:
        try:
            _parse_hhmm(body.end)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"detail": "invalid_end",
                          "message": "end must be HH:MM 24-hour format (e.g. 20:00)."},
            )
        updates["quiet_hours_end"] = body.end

    if body.timezone is not None:
        # Empty string → clear the override (fall back to tenants.timezone).
        if body.timezone == "":
            updates["quiet_hours_timezone"] = None
        else:
            if body.timezone not in available_timezones():
                raise HTTPException(
                    status_code=400,
                    detail={"detail": "invalid_timezone",
                              "message": f"unknown IANA timezone: {body.timezone!r}"},
                )
            updates["quiet_hours_timezone"] = body.timezone

    # Post-validation: if BOTH start and end resolve to the same value,
    # reject — "always closed" is a footgun.
    resolved_start = updates.get("quiet_hours_start") or tenant.get("quiet_hours_start") or DEFAULT_START
    resolved_end   = updates.get("quiet_hours_end")   or tenant.get("quiet_hours_end")   or DEFAULT_END
    if resolved_start == resolved_end:
        raise HTTPException(
            status_code=400,
            detail={"detail": "invalid_window",
                      "message": "start and end must differ (an equal window is always closed)."},
        )

    if not updates:
        # No-op PATCH — return current state.
        return await get_quiet_hours(user=user, tenant=tenant)

    updates["updated_at"] = now_iso()
    updates["updated_by"] = user.get("id")
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": updates})

    try:
        await _p27_write_audit(event="quiet_hours_update",
                                  cid=tenant["id"], tenant_id=tenant["id"],
                                  user=user, request=request, extra=updates)
    except Exception as e:
        logger.warning("[p34] audit log write failed: %s", e)

    fresh = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    return {
        "enabled": bool(fresh.get("quiet_hours_enabled", False)),
        "start":   fresh.get("quiet_hours_start")    or DEFAULT_START,
        "end":     fresh.get("quiet_hours_end")      or DEFAULT_END,
        "timezone": fresh.get("quiet_hours_timezone")
                       or fresh.get("timezone") or "America/Phoenix",
        "tenant_timezone": fresh.get("timezone") or "America/Phoenix",
    }
