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
from typing import Any, Dict

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
