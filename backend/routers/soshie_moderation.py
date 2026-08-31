"""Phase F3 · Feb-2026 — Soshie moderation queue + publishing summary.

Endpoints
---------
GET  /api/soshie/moderation/queue                       — flagged/blocked list
POST /api/soshie/moderation/{post_id}/approve           — human override → publish
POST /api/soshie/moderation/{post_id}/reject            — mark rejected
GET  /api/soshie/publishing/today-summary               — dashboard tile data

All endpoints are admin+ (super_admin / admin / owner) and scoped to the
caller's tenant via ``get_current_tenant``.  Approve / reject write
``audit_events`` rows so the moderation trail is durable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


AUDIT_EVENT_TYPE_APPROVE = "soshie_moderation_approve"
AUDIT_EVENT_TYPE_REJECT = "soshie_moderation_reject"
_QUEUE_STATUSES = {"awaiting_review", "blocked", "rejected"}


class RejectBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


# ─── Helpers ──────────────────────────────────────────────────────────
async def _audit(tenant_id: str, event_type: str,
                 user: Dict[str, Any], post_id: str,
                 payload: Dict[str, Any]) -> None:
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event_type": event_type,
            "actor_id": user.get("id"),
            "actor_role": user.get("role"),
            "post_id": post_id,
            "payload": payload,
            "timestamp": now_iso(),
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[soshie.moderation] audit insert failed: %s", e)


def _serialize_post(row: Dict[str, Any]) -> Dict[str, Any]:
    row.pop("_id", None)
    draft = row.get("draft") or {}
    params = row.get("params") or {}
    return {
        "id": row.get("id"),
        "tenant_id": row.get("tenant_id"),
        "platform": row.get("platform")
                       or params.get("platform")
                       or (params.get("platforms") or [None])[0],
        "status": row.get("status"),
        "scheduled_at": row.get("scheduled_at")
                            or row.get("execute_at")
                            or row.get("created_at"),
        "preview": (draft.get("text") or "")[:180],
        "media_url": row.get("media_url") or draft.get("media_url"),
        "moderation_decision": row.get("moderation_decision"),
        "moderation_reasons": row.get("moderation_reasons") or [],
        "moderation_risk_level": row.get("moderation_risk_level"),
        "moderation_cost_usd": row.get("moderation_cost_usd") or 0.0,
        "moderation_reviewed_by": row.get("moderation_reviewed_by"),
        "moderation_reviewed_at": row.get("moderation_reviewed_at"),
    }


async def _load_post(post_id: str, tenant_id: str) -> Dict[str, Any]:
    row = await db.ai_employee_actions.find_one(
        {"id": post_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Post not found")
    return row


# ─── Queue endpoints ──────────────────────────────────────────────────
@router.get("/soshie/moderation/queue")
async def list_moderation_queue(
    status: str = Query("awaiting_review"),
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """List moderation-gated action rows for the caller's tenant.

    ``status`` may be ``awaiting_review`` (human review needed),
    ``blocked`` (auto-rejected by the LLM), or ``rejected`` (human
    said no).  Anything else falls back to ``awaiting_review``.
    """
    s = status if status in _QUEUE_STATUSES else "awaiting_review"
    cursor = db.ai_employee_actions.find(
        {"tenant_id": tenant["id"], "status": s},
        {"_id": 0},
    ).sort([("scheduled_at", 1), ("created_at", 1)]).limit(200)
    rows: List[Dict[str, Any]] = [_serialize_post(r) async for r in cursor]
    return {"status": s, "count": len(rows), "posts": rows}


@router.post("/soshie/moderation/{post_id}/approve")
async def approve_post(
    post_id: str,
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Human override: send a previously flagged post through to the
    publisher.  Blocked posts CAN also be re-approved here — the human
    always outranks the LLM."""
    row = await _load_post(post_id, tenant["id"])
    if row.get("status") not in _QUEUE_STATUSES:
        raise HTTPException(
            409,
            f"post status must be one of {sorted(_QUEUE_STATUSES)} "
            f"(currently {row.get('status')!r})",
        )
    await db.ai_employee_actions.update_one(
        {"id": post_id, "tenant_id": tenant["id"]},
        {"$set": {
            "status": "pending",
            "moderation_reviewed_by": user.get("id"),
            "moderation_reviewed_at": now_iso(),
            "moderation_override": True,
            "updated_at": now_iso(),
        }},
    )
    await _audit(tenant["id"], AUDIT_EVENT_TYPE_APPROVE, user, post_id,
                 {"prior_status": row.get("status"),
                  "moderation_decision": row.get("moderation_decision")})
    # Best-effort publisher call — deferred to the next autopilot tick
    # in real use, but the caller may still hand-off publishing right
    # away. We stay on the safe side and only re-queue for pickup.
    return {"ok": True, "post_id": post_id, "new_status": "pending"}


@router.post("/soshie/moderation/{post_id}/reject")
async def reject_post(
    post_id: str,
    body: Optional[RejectBody] = None,
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    row = await _load_post(post_id, tenant["id"])
    if row.get("status") not in _QUEUE_STATUSES:
        raise HTTPException(
            409,
            f"post status must be one of {sorted(_QUEUE_STATUSES)} "
            f"(currently {row.get('status')!r})",
        )
    reason = ((body.reason if body else None) or "").strip() or None
    await db.ai_employee_actions.update_one(
        {"id": post_id, "tenant_id": tenant["id"]},
        {"$set": {
            "status": "rejected",
            "moderation_reviewed_by": user.get("id"),
            "moderation_reviewed_at": now_iso(),
            "moderation_reject_reason": reason,
            "updated_at": now_iso(),
        }},
    )
    await _audit(tenant["id"], AUDIT_EVENT_TYPE_REJECT, user, post_id,
                 {"prior_status": row.get("status"),
                  "reason": reason,
                  "moderation_decision": row.get("moderation_decision")})
    return {"ok": True, "post_id": post_id, "new_status": "rejected"}


# ─── Publishing summary (dashboard tile) ──────────────────────────────
def _today_bounds_utc() -> Dict[str, str]:
    """UTC-day bounds — good enough for the tile; tenants that need
    tz-accurate windows can extend later."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(),
            "date": start.date().isoformat()}


@router.get("/soshie/publishing/today-summary")
async def publishing_today_summary(
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    tid = tenant["id"]
    bounds = _today_bounds_utc()
    # Counters — one $in per row to keep query planner happy.
    async def _c(match: Dict[str, Any]) -> int:
        return await db.ai_employee_actions.count_documents(match)

    scheduled = await _c({"tenant_id": tid,
                            "status": {"$in": ["pending", "scheduled"]},
                            "scheduled_at": {"$gte": bounds["start"],
                                              "$lt": bounds["end"]}})
    published = await _c({"tenant_id": tid, "status": "published",
                            "executed_at": {"$gte": bounds["start"],
                                              "$lt": bounds["end"]}})
    flagged = await _c({"tenant_id": tid, "status": "awaiting_review"})
    blocked = await _c({"tenant_id": tid, "status": "blocked"})
    failed = await _c({"tenant_id": tid, "status": "failed",
                          "executed_at": {"$gte": bounds["start"],
                                            "$lt": bounds["end"]}})
    # "Next up" — up to 3 upcoming posts across pending/scheduled/awaiting.
    cursor = db.ai_employee_actions.find(
        {"tenant_id": tid,
         "status": {"$in": ["pending", "scheduled", "awaiting_review"]},
         "scheduled_at": {"$gte": bounds["start"]}},
        {"_id": 0},
    ).sort([("scheduled_at", 1)]).limit(3)
    next_up: List[Dict[str, Any]] = []
    async for r in cursor:
        d = _serialize_post(r)
        next_up.append({
            "post_id": d["id"], "platform": d["platform"],
            "scheduled_at": d["scheduled_at"], "preview": d["preview"],
        })
    return {
        "tenant_id": tid,
        "date": bounds["date"],
        "scheduled": scheduled,
        "published": published,
        "flagged": flagged,
        "blocked": blocked,
        "failed": failed,
        "next_up": next_up,
    }
