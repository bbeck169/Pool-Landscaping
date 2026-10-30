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


# ─── Phase 2 UX — Queue viewer + per-row cancel ────────────────────
# Feb-2026 · Operator Phase-2 (β scope) — expose the pending
# ``outbound_deferred`` queue to admin/manager/super_admin so they
# can inspect what's waiting + cancel individual rows. Mirrors the
# ``_writer_only`` role gate already enforced on the PATCH path so
# a technician never sees scheduled payloads for a tenant they
# can't configure.
_QUEUE_CHANNELS = {"email", "sms"}


def _recipient_from_payload(channel: str, payload: dict) -> str:
    """Best-effort recipient extraction from the frozen payload row
    (payload shape differs by channel — see ``defer_send`` callers
    in ``comms_email_adapter`` / ``comms_sms_adapter``)."""
    if not isinstance(payload, dict):
        return ""
    if channel == "email":
        to = payload.get("to")
        if isinstance(to, list) and to:
            return str(to[0] or "")
        return str(to or "")
    if channel == "sms":
        return str(payload.get("to_phone") or "")
    return ""


def _subject_from_payload(channel: str, payload: dict) -> Optional[str]:
    """Email subject if present; SMS has no subject."""
    if channel != "email" or not isinstance(payload, dict):
        return None
    sub = payload.get("subject")
    return str(sub) if sub else None


@router.get("/quiet-hours/queue")
async def list_quiet_hours_queue(
    limit: int = 50,
    offset: int = 0,
    channel: Optional[str] = None,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Pending ``outbound_deferred`` rows for the current tenant.

    Returns ``count`` (total pending, independent of limit/offset),
    ``next_release_at`` (earliest ``scheduled_for`` across all
    pending rows, or ``None`` when empty), and ``items`` (up to
    ``limit`` rows ordered by ``scheduled_for`` asc).
    """
    _writer_only(user)
    if limit < 1 or limit > 500:
        limit = 50
    if offset < 0:
        offset = 0
    q: dict = {"tenant_id": tenant["id"], "status": "pending"}
    if channel is not None:
        ch = channel.strip().lower()
        if ch not in _QUEUE_CHANNELS:
            raise HTTPException(
                status_code=400,
                detail={"detail": "invalid_channel",
                        "message": "channel must be 'email' or 'sms'."},
            )
        q["channel"] = ch

    count = await db.outbound_deferred.count_documents(q)
    next_doc = None
    if count:
        next_doc = await db.outbound_deferred.find_one(
            {"tenant_id": tenant["id"], "status": "pending"},
            {"_id": 0, "scheduled_for": 1},
            sort=[("scheduled_for", 1)],
        )
    cursor = db.outbound_deferred.find(
        q, {"_id": 0, "id": 1, "channel": 1, "payload": 1,
            "scheduled_for": 1, "created_at": 1},
    ).sort("scheduled_for", 1).skip(offset).limit(limit)
    rows = await cursor.to_list(length=limit)
    items: list[dict] = []
    for r in rows:
        ch = r.get("channel") or ""
        pl = r.get("payload") or {}
        items.append({
            "id": r.get("id"),
            "channel": ch,
            "recipient": _recipient_from_payload(ch, pl),
            "scheduled_release_at": r.get("scheduled_for"),
            "deferred_at": r.get("created_at"),
            "subject": _subject_from_payload(ch, pl),
        })
    return {
        "count": count,
        "next_release_at": (next_doc or {}).get("scheduled_for"),
        "items": items,
    }


@router.delete("/quiet-hours/queue/{row_id}")
async def cancel_quiet_hours_row(
    row_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    request: Request = None,
):
    """Hard-delete a single pending ``outbound_deferred`` row.

    Only pending rows are cancellable — a ``releasing`` row is
    mid-dispatch and the release worker owns its lifecycle. 404 on
    cross-tenant to avoid leaking existence.
    """
    _writer_only(user)
    row = await db.outbound_deferred.find_one(
        {"id": row_id, "tenant_id": tenant["id"], "status": "pending"},
        {"_id": 0, "id": 1, "channel": 1},
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"detail": "row_not_found",
                    "message": "Pending row not found for this tenant."},
        )
    res = await db.outbound_deferred.delete_one(
        {"id": row_id, "tenant_id": tenant["id"], "status": "pending"},
    )
    if res.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail={"detail": "row_not_found",
                    "message": "Pending row not found for this tenant."},
        )
    try:
        await _p27_write_audit(
            event="quiet_hours_queue_cancel",
            cid=tenant["id"], tenant_id=tenant["id"],
            user=user, request=request,
            extra={"row_id": row_id, "channel": row.get("channel")},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[p34] cancel audit log write failed: %s", e)
    return {"deleted": True, "row_id": row_id}




@router.post("/quiet-hours/queue/release-now")
async def release_quiet_hours_queue_now(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    request: Request = None,
):
    """Admin-triggered immediate release of every pending
    ``outbound_deferred`` row for the current tenant.

    Semantically distinct from the 5-min APScheduler tick: this
    endpoint ignores each row's ``scheduled_for`` and dispatches
    every pending row for this tenant RIGHT NOW. Dispatches run in
    the ``bypass_gate`` context inside ``_dispatch_row`` so the
    adapter's own quiet-hours check doesn't re-defer the row.
    """
    _writer_only(user)
    from services.quiet_hours_release import flush_tenant_queue
    result = await flush_tenant_queue(tenant["id"])
    try:
        await _p27_write_audit(
            event="quiet_hours_queue_release_now",
            cid=tenant["id"], tenant_id=tenant["id"],
            user=user, request=request,
            extra={
                "released_count": result.get("released_count", 0),
                "errors_count": len(result.get("errors") or []),
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[p34] release-now audit log write failed: %s", e)
    return result

