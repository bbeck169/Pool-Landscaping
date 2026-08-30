"""Phase B3 · Feb-2026 — Stripe admin dead-letter surface.

Super_admin-only endpoints for operators to see + replay events
that crashed inside ``handle_webhook_event``. Kept intentionally
minimal — the retry endpoint just re-runs the shipped handler with
the payload we stashed at dead-letter time.

Prefix: ``/admin/stripe`` (mounted at ``/api/admin/stripe`` by the
main ``api_router``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from utils import get_current_user
from services.payments import stripe_charge as stripe_svc
from services.payments.stripe_webhook_ledger import (
    get_dead_letter_row,
    list_dead_letter,
    mark_dead_letter_resolved,
    mark_handled,
    mark_failed,
    record_dead_letter,
)


router = APIRouter(prefix="/admin/stripe", tags=["admin-stripe"])
logger = logging.getLogger("admin_stripe")


def _require_super_admin(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


@router.get("/dead-letter")
async def get_dead_letter(
    resolved: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_super_admin(user)
    rows = await list_dead_letter(resolved=resolved, limit=limit)
    return {"count": len(rows), "rows": rows}


@router.post("/dead-letter/{event_id}/retry")
async def retry_dead_letter(
    event_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_super_admin(user)
    row = await get_dead_letter_row(event_id)
    if not row:
        raise HTTPException(404, f"event {event_id} not in dead-letter")
    if row.get("resolved"):
        return {"status": "already_resolved", "event_id": event_id}
    payload = row.get("raw_payload") or {}
    if not payload:
        raise HTTPException(422, "dead-letter row has no raw_payload; cannot replay")
    try:
        result = await stripe_svc.handle_webhook_event(payload)
    except Exception as exc:  # noqa: BLE001
        import traceback
        await record_dead_letter(
            payload,
            error_class=type(exc).__name__,
            error_message=str(exc),
            stack_trace=traceback.format_exc(),
        )
        await mark_failed(event_id, error=str(exc))
        raise HTTPException(500, f"retry failed: {exc}")
    await mark_handled(event_id, result=result)
    await mark_dead_letter_resolved(event_id)
    return {"status": "resolved", "event_id": event_id, "handler_result": result}
