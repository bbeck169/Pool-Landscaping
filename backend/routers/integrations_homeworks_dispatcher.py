"""Task 5 · Feb-2026 — "Run now" admin trigger for the Homeworks
import dispatcher.

Exposes ``POST /api/integrations/homeworks/imports/dispatcher/tick``
so a super_admin can manually invoke one dispatcher tick without
waiting for the scheduler's 30-second interval. Enforces a 5-second
cooldown per process so mashing the button can't stampede the
scheduler.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from services.homeworks_mcp.import_dispatcher import dispatcher_tick
from utils import get_current_user

logger = logging.getLogger("homeworks_mcp.dispatcher_router")

router = APIRouter(
    prefix="/integrations/homeworks/imports/dispatcher",
    tags=["Integrations · Homeworks · Imports"],
)

# Cooldown lives at module scope on purpose — a per-process counter
# is enough to smooth out button-mashing. Multi-replica deploys use
# the same guardrail per pod, which is fine given the atomic queued
# → running flip on the dispatcher itself.
_COOLDOWN_S = 5.0
_last_tick_at = 0.0


@router.post("/tick", operation_id="hw.imports.dispatcher.tick")
async def manual_tick(
    user: Dict[str, Any] = Depends(get_current_user),
):
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")
    global _last_tick_at
    now = time.monotonic()
    if now - _last_tick_at < _COOLDOWN_S:
        # No-op response so the FE can stay simple — surface the
        # cooldown so it can render a "just triggered" hint.
        wait_s = round(_COOLDOWN_S - (now - _last_tick_at), 1)
        return {"ok": True, "cooldown": True, "retry_in_s": wait_s}
    _last_tick_at = now
    summary = await dispatcher_tick()
    logger.info("[dispatcher_router] manual tick by user=%s summary=%s",
                 user.get("id"), summary)
    return {"ok": True, "cooldown": False, "summary": summary}


# ─── Feb-2026 · Reset stuck job(s) ────────────────────────────────────
@router.post("/reset-stuck", operation_id="hw.imports.dispatcher.reset_stuck")
async def reset_stuck(
    kind: str | None = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Force any stuck ``{queued, running}`` Homeworks import job for
    this tenant back to ``queued`` so the dispatcher picks it up on
    the next tick.

    Root cause the endpoint addresses: a doc that got stranded in
    ``queued`` (dispatcher tick never claimed it — e.g. pod died
    between insert and the next 30s poll) or in ``running`` (crashed
    coroutine that never wrote a terminal status).  The 15-minute
    watchdog in :func:`dispatcher_tick` normally sweeps these to
    ``failed_stale`` on the next tick, but ops sometimes wants to
    re-arm faster than the watchdog window (e.g. right after
    resolving the underlying OAuth or API-key issue).

    * Super_admin only.
    * ``kind`` (optional query arg) — limits the reset to one
      importer kind (e.g. ``inactive_customers``).  Omit to reset
      every stuck job for the tenant.
    * Preserves ``counters`` + ``resume_cursor`` so a mid-flight
      run resumes rather than restarts.  Pushes an ``error_log``
      row so the audit trail records the manual reset.
    """
    from config import db
    from services.homeworks_mcp.import_dispatcher import _IMPORTER_KIND_MAP
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "missing_tenant")
    if kind and kind not in _IMPORTER_KIND_MAP:
        raise HTTPException(400, f"unknown_kind:{kind}")

    now = datetime.now(timezone.utc).isoformat()
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "status": {"$in": ["queued", "running"]},
    }
    if kind:
        q["kind"] = kind

    stuck_ids: List[str] = []
    async for d in db.homeworks_import_runs.find(
        q, {"_id": 0, "run_id": 1, "kind": 1, "status": 1},
    ):
        stuck_ids.append(d["run_id"])

    if not stuck_ids:
        return {"ok": True, "reset": 0, "run_ids": []}

    r = await db.homeworks_import_runs.update_many(
        {"run_id": {"$in": stuck_ids}},
        {"$set": {
            "status": "queued",
            "updated_at": now,
            # Clear the lock fields the dispatcher stamps on claim
            # so a follow-up tick can transition queued->running
            # cleanly.  ``dispatcher_pid`` / ``dispatcher_claimed_at``
            # / ``finished_at`` are dropped.
            "dispatcher_pid": None,
            "dispatcher_claimed_at": None,
            "finished_at": None,
         },
         "$push": {"error_log": {
             "stage": "manual_reset_stuck",
             "actor_user_id": user.get("id"),
             "at": now,
         }}},
    )
    logger.info(
        "[dispatcher_router] reset_stuck by user=%s tenant=%s kind=%s "
        "modified=%s run_ids=%s",
        user.get("id"), tenant_id, kind or "*",
        r.modified_count, stuck_ids,
    )
    # Kick a dispatcher tick right now so the FE doesn't have to
    # wait up to 30s for the scheduler.  Best-effort — if the
    # cooldown gate rejects, the next scheduled tick still fires.
    global _last_tick_at
    if time.monotonic() - _last_tick_at >= _COOLDOWN_S:
        _last_tick_at = time.monotonic()
        summary = await dispatcher_tick()
        return {"ok": True, "reset": r.modified_count,
                "run_ids": stuck_ids, "dispatcher_summary": summary}
    return {"ok": True, "reset": r.modified_count, "run_ids": stuck_ids}
