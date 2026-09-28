"""SO-A · Feb-2026 — /api/schedule/* AI-recommendation endpoints.

Two endpoints:

  * ``POST /api/schedule/ai-recommendation`` — synthesise up to
    ``max_suggestions`` best-fit (tech, insertion) pairs for a given
    job on a target date.  Read-only; writes ONE audit row to
    ``ai_employee_actions`` after computing.
  * ``POST /api/schedule/apply-recommendation`` — apply the picked
    (tech, insertion) pair.  Persists the reassignment on the target
    job + reflows ``route_index`` for the tech's remaining stops on
    that date.  Gated by
    ``rules.auto_action_allowlist["dispatch.reassign"]``: ``auto``
    executes immediately, ``admin_approval`` queues into
    ``ai_employee_actions`` for admin review.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user
from routers.tenants import get_current_tenant
from services.schedule_optimizer.endpoint import (
    generate_recommendations,
    MAX_SUGGESTIONS_HARD_CAP, REASSIGN_ACTION_KEY, DISPATCH_EMPLOYEE_KEY,
)
from services.schedule_optimizer.rate_limit import (
    check_and_record as _rl_check, DEFAULT_LIMIT as _RL_LIMIT,
    DEFAULT_WINDOW_S as _RL_WINDOW,
)

router = APIRouter()
_ADMIN_ROLES = {"admin", "super_admin", "manager"}


def _require_admin_or_manager(user: dict) -> None:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin or manager only")


# ─── /schedule/ai-recommendation ─────────────────────────────────


class RecommendationBody(BaseModel):
    """SO-A · Feb-2026 — Body for
    ``POST /api/schedule/ai-recommendation``.
    """
    job_id: str = Field(..., min_length=1)
    target_date: str = Field(..., min_length=8, max_length=10)
    eligible_technician_ids: Optional[List[str]] = None
    max_suggestions: int = Field(3, ge=1, le=MAX_SUGGESTIONS_HARD_CAP)


@router.post("/schedule/ai-recommendation")
async def schedule_ai_recommendation(
    body: RecommendationBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Generate top-N AI recommendations for a job insertion."""
    _require_admin_or_manager(user)
    user_id = str(user.get("id") or user.get("email") or "")
    allowed, remaining, retry_after = _rl_check(user_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "schedule_ai_rate_limit_exceeded",
                "message": (
                    f"Suggestion budget hit — {_RL_LIMIT} per "
                    f"{_RL_WINDOW}s per user. Retry in {retry_after}s."
                ),
                "retry_after_seconds": retry_after,
                "limit": _RL_LIMIT,
                "window_seconds": _RL_WINDOW,
            },
            headers={"Retry-After": str(retry_after)},
        )

    started = datetime.now(timezone.utc)
    result = await generate_recommendations(
        tenant_id=tenant["id"],
        job_id=body.job_id, target_date=body.target_date,
        eligible_technician_ids=body.eligible_technician_ids,
        max_suggestions=body.max_suggestions,
        now_utc=started,
    )
    if "error_code" in result:
        raise HTTPException(422, detail={
            "error_code": result["error_code"],
            "message": result.get("message") or "recommendation_error",
        })

    compute_ms = int(
        (datetime.now(timezone.utc) - started).total_seconds() * 1000,
    )
    result["compute_ms"] = compute_ms
    result["rate_limit"] = {
        "limit": _RL_LIMIT, "window_seconds": _RL_WINDOW,
        "remaining": remaining,
    }

    # Audit — synth is a suggestion, not an action.  Row lands
    # auto-approved so it never blocks anything.
    try:
        await db.ai_employee_actions.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant["id"],
            "employee_key": DISPATCH_EMPLOYEE_KEY,
            "action_key": "dispatch.schedule_recommendation",
            "status": "approved",
            "auto_approved": True,
            "decided_by": "system:recommendation_synthesis",
            "reason": "recommendation_synthesis",
            "payload": {
                "job_id": body.job_id,
                "target_date": body.target_date,
                "suggestions_summary": [
                    {"technician_id": s["technician_id"],
                      "rank": s.get("rank"),
                      "detour_minutes": s["detour_minutes"]}
                    for s in result.get("suggestions") or []
                ],
                "provider_used": result.get("provider_used"),
                "plain_english_source": result.get("plain_english_source"),
                "compute_ms": compute_ms,
            },
            "created_at": started.isoformat(),
            "created_by": user.get("id"),
        })
    except Exception:                                              # noqa: BLE001
        logger.exception(
            "[so-a] recommendation audit write failed tenant=%s",
            tenant["id"],
        )

    return result


# ─── /schedule/apply-recommendation ─────────────────────────────


class ApplyBody(BaseModel):
    job_id: str = Field(..., min_length=1)
    technician_id: str = Field(..., min_length=1)
    insertion_index: int = Field(..., ge=0)
    # ``source_recommendation`` is optional metadata for audit — the
    # original detour delta, rank, etc.  Client sends what it has.
    source_recommendation: Optional[Dict[str, Any]] = None


async def _resolve_apply_authority(
    *, tenant_id: str,
) -> Dict[str, Any]:
    """Return ``{"one_click": bool, "master_on": bool,
    "dispatch_enabled": bool, "reason": str}``."""
    from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
    resolved = await resolve_rules_for_tenant(tenant_id, use_cache=True)
    master_on = bool(resolved.get("master_ai_send_live_comms"))
    rules = resolved.get("rules") or {}
    emp_on = bool((rules.get("employee_enable_disable") or {}).get(
        DISPATCH_EMPLOYEE_KEY, False))
    mode = (rules.get("auto_action_allowlist") or {}).get(
        REASSIGN_ACTION_KEY)
    if not master_on:
        return {"one_click": False, "master_on": False,
                 "dispatch_enabled": emp_on, "reason": "master_switch_off"}
    if not emp_on:
        return {"one_click": False, "master_on": True,
                 "dispatch_enabled": False, "reason": "employee_disabled"}
    if mode != "auto":
        return {"one_click": False, "master_on": True,
                 "dispatch_enabled": True,
                 "reason": f"allowlist_{mode or 'unset'}"}
    return {"one_click": True, "master_on": True,
             "dispatch_enabled": True, "reason": "ok"}


async def _apply_reassignment(
    *, tenant_id: str, target_job: Dict[str, Any],
    technician_id: str, insertion_index: int,
    actor_id: Optional[str],
) -> Dict[str, Any]:
    """Persist the reassignment: set ``technician_id`` +
    ``route_index`` on the target job, shift subsequent stops on
    the same date + tech by +1.
    """
    target_date = target_job.get("scheduled_date")
    if not target_date:
        raise HTTPException(422, {
            "error_code": "target_missing_scheduled_date",
            "message": "Target job has no scheduled_date — cannot reflow route.",
        })

    # Existing stops for the target tech on that date, ordered.
    existing_cursor = db.jobs.find(
        {"tenant_id": tenant_id,
          "technician_id": technician_id,
          "scheduled_date": target_date,
          "id": {"$ne": target_job["id"]},
          "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "route_index": 1, "scheduled_start": 1,
          "created_at": 1},
    )
    existing: List[Dict[str, Any]] = []
    if hasattr(existing_cursor, "to_list"):
        existing = await existing_cursor.to_list(500)
    else:
        async for r in existing_cursor:                            # pragma: no cover
            existing.append(r)

    def _ri(j: Dict[str, Any]) -> float:
        v = j.get("route_index")
        return float(v) if isinstance(v, (int, float)) else float("inf")
    existing.sort(key=lambda j: (_ri(j),
                                     str(j.get("scheduled_start") or ""),
                                     str(j.get("created_at") or "")))
    clamped = max(0, min(int(insertion_index), len(existing)))

    now_iso = datetime.now(timezone.utc).isoformat()

    # Reindex: 0..clamped-1 keep their slot; clamped becomes the
    # target job; clamped..end shift by +1.
    for slot, job in enumerate(existing[:clamped]):
        await db.jobs.update_one(
            {"tenant_id": tenant_id, "id": job["id"]},
            {"$set": {"route_index": slot, "updated_at": now_iso}},
        )
    await db.jobs.update_one(
        {"tenant_id": tenant_id, "id": target_job["id"]},
        {"$set": {
            "technician_id": technician_id,
            "route_index": clamped,
            "updated_at": now_iso,
            "last_reassigned_at": now_iso,
            "last_reassigned_by": actor_id,
        }},
    )
    for offset, job in enumerate(existing[clamped:]):
        await db.jobs.update_one(
            {"tenant_id": tenant_id, "id": job["id"]},
            {"$set": {"route_index": clamped + 1 + offset,
                        "updated_at": now_iso}},
        )
    return {
        "job_id": target_job["id"],
        "technician_id": technician_id,
        "route_index": clamped,
        "shifted_job_count": len(existing[clamped:]),
    }


@router.post("/schedule/apply-recommendation")
async def apply_recommendation(
    body: ApplyBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Apply an AI recommendation.

    Response shape:
        {
          "status": "applied" | "queued_for_approval",
          "job_id": str, "technician_id": str,
          "route_index": int | None,
          "action_id": str | None,     # queued only
        }
    """
    _require_admin_or_manager(user)
    target_job = await db.jobs.find_one(
        {"tenant_id": tenant["id"], "id": body.job_id,
          "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    )
    if target_job is None:
        raise HTTPException(404, {
            "error_code": "target_job_not_found",
            "message": "Target job not visible under this tenant.",
        })
    auth = await _resolve_apply_authority(tenant_id=tenant["id"])

    if auth["one_click"]:
        # Apply immediately + audit row (auto-approved).
        applied = await _apply_reassignment(
            tenant_id=tenant["id"], target_job=target_job,
            technician_id=body.technician_id,
            insertion_index=body.insertion_index,
            actor_id=user.get("id"),
        )
        try:
            await db.ai_employee_actions.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant["id"],
                "employee_key": DISPATCH_EMPLOYEE_KEY,
                "action_key": REASSIGN_ACTION_KEY,
                "status": "approved",
                "auto_approved": True,
                "decided_by": "system:auto_allowlist",
                "reason": "auto_action_allowlist",
                "payload": {
                    "job_id": body.job_id,
                    "technician_id": body.technician_id,
                    "insertion_index": applied["route_index"],
                    "source_recommendation": body.source_recommendation,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": user.get("id"),
            })
        except Exception:                                          # noqa: BLE001
            logger.exception(
                "[so-a] applied-audit write failed tenant=%s",
                tenant["id"],
            )
        return {"status": "applied", **applied}

    # Queued path — insert a pending row for admin review.
    action_id = str(uuid.uuid4())
    await db.ai_employee_actions.insert_one({
        "id": action_id,
        "tenant_id": tenant["id"],
        "employee_key": DISPATCH_EMPLOYEE_KEY,
        "action_key": REASSIGN_ACTION_KEY,
        "status": "pending",
        "auto_approved": False,
        "reason": auth["reason"],
        "payload": {
            "job_id": body.job_id,
            "technician_id": body.technician_id,
            "insertion_index": body.insertion_index,
            "source_recommendation": body.source_recommendation,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user.get("id"),
    })
    return {
        "status": "queued_for_approval",
        "job_id": body.job_id,
        "technician_id": body.technician_id,
        "route_index": None,
        "action_id": action_id,
        "reason": auth["reason"],
    }
