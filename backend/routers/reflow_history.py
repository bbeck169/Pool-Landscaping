"""Reflow History — Feb 2026.

Aggregates ``audit_log`` rows for jobs.bulk_update actions to give
dispatchers a browseable log of every mass reschedule. Each audit
row is per-target (one row per job) — this endpoint groups them
into a single dispatcher-facing "action" per (actor, at,
shift_days) tuple.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


@router.get("/admin/reflow-history", operation_id="admin.reflowHistory")
async def get_reflow_history(
    since: Optional[str] = Query(None, description="ISO datetime"),
    until: Optional[str] = Query(None, description="ISO datetime"),
    actor_user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None, description="ISO datetime for pagination"),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Aggregated view of jobs.bulk_update audit rows for the tenant."""
    match: dict = {
        "tenant_id": tenant["id"],
        "action": {"$in": ["job.bulk_update", "job.bulk_shift",
                              "job.bulk_reschedule"]},
    }
    if since:
        try:
            datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since must be ISO datetime")
        match.setdefault("at", {})["$gte"] = since
    if until:
        try:
            datetime.fromisoformat(until.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "until must be ISO datetime")
        match.setdefault("at", {})["$lte"] = until
    if actor_user_id:
        match["actor_user_id"] = actor_user_id
    if cursor:
        match.setdefault("at", {})["$lt"] = cursor
    # Group by (actor_user_id, at, shift_days) — an action fires at
    # roughly the same ISO ``at`` for every target in the same call,
    # so this collapses per-target rows into one dispatcher action.
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "actor_user_id": "$actor_user_id",
                "actor_email": "$actor_email",
                "at": "$at",
                "action": "$action",
                "shift_days": "$shift_days",
            },
            "count": {"$sum": 1},
            "anchored_count": {"$sum": {"$cond": ["$anchored", 1, 0]}},
            "target_ids_sample": {"$push": "$target_id"},
        }},
        {"$sort": {"_id.at": -1}},
        {"$limit": limit + 1},
    ]
    grouped = await db.audit_log.aggregate(pipeline).to_list(length=limit + 1)
    has_more = len(grouped) > limit
    items = []
    for g in grouped[:limit]:
        key = g["_id"]
        items.append({
            "at": key.get("at"),
            "actor_user_id": key.get("actor_user_id"),
            "actor_email": key.get("actor_email"),
            "action": key.get("action"),
            "shift_days": key.get("shift_days"),
            "anchored_count": g.get("anchored_count", 0),
            "count": g.get("count", 0),
            "target_ids_sample": (g.get("target_ids_sample") or [])[:5],
            "tenant_id": tenant["id"],
        })
    # Cursor is the ``at`` of the last item RETURNED (not the peeked
    # limit+1 row). Next page uses ``at < cursor`` to fetch strictly
    # older rows. This handles the common case where multiple audit
    # groups share the same ``at`` (e.g. bulk actions fired in the
    # same batch) — page 1 gives the newest N groups, page 2 continues
    # from the newest group of the older bucket.
    next_cursor = items[-1]["at"] if (items and has_more) else None
    return {"items": items, "cursor": next_cursor}
