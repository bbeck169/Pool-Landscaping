"""Feb 2026 · Phase 3 · Trigger-Builder test hooks.

Small router mounted ONLY when ``ALLOW_TEST_HOOKS=1`` so E2E pytest
suites can drive the marketing pipeline over HTTP (backend owns the
Motor client + loop). Never exposed in production — the same env
gate + boot-time force-clear that guards other ``*_test_hooks.py``
routers applies here too (see ``server.py`` around line 800).

Endpoints
---------
* ``POST /api/test-hooks/marketing/emit-event`` — thin wrapper over
  ``services.marketing.event_dispatcher.emit_event``. Body accepts
  the same kwargs the internal helper takes.

* ``POST /api/test-hooks/marketing/run-sweep`` — invokes one of the
  cron sweeps by name. Currently supports
  ``invoice_overdue`` and ``customer_birthday``.

Both endpoints are super_admin only (mirrors the persona-avatar
admin endpoint's RBAC) so accidentally leaving the env flag on in
a hardened environment still requires a super_admin JWT.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from utils import get_current_user


router = APIRouter(tags=["Test hooks · Marketing"])


def _require_super_admin(user: Dict[str, Any]) -> None:
    if not user or (user.get("role") or "").lower() != "super_admin":
        raise HTTPException(status_code=403, detail="super_admin only")


class _EmitEventBody(BaseModel):
    event: str
    tenant_id: str
    entity_id: Optional[str] = None
    customer_id: Optional[str] = None
    scheduled_at: Optional[str] = None
    payload_extras: Optional[Dict[str, Any]] = Field(default_factory=dict)
    correlation_id: Optional[str] = None


@router.post("/test-hooks/marketing/emit-event",
              operation_id="test_hooks.marketing.emit_event")
async def emit_event_hook(body: _EmitEventBody,
                            user: Dict[str, Any] = Depends(get_current_user)):
    """Fire a marketing event through the real pipeline. Same
    dedupe / evaluator / enrolment path as production."""
    _require_super_admin(user)
    from services.marketing.event_dispatcher import emit_event
    out = await emit_event(
        event=body.event, tenant_id=body.tenant_id,
        entity_id=body.entity_id, customer_id=body.customer_id,
        scheduled_at=body.scheduled_at,
        payload_extras=body.payload_extras,
        correlation_id=body.correlation_id,
    )
    return out


@router.post("/test-hooks/marketing/run-sweep",
              operation_id="test_hooks.marketing.run_sweep")
async def run_sweep_hook(
    sweep: str = Query(..., description=(
        "One of: ``invoice_overdue``, ``customer_birthday``, ``daily``"
    )),
    tenant_id: str = Query(...),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Invoke a single sweep helper against ``tenant_id``. Returns
    the sweep's summary dict (or ``{ok: True}`` if the underlying
    helper doesn't return one)."""
    _require_super_admin(user)
    from services.marketing.phase1_sweeps import (
        _sweep_invoice_overdue,
        _sweep_customer_birthday,
        daily_phase1_trigger_sweep,
    )
    if sweep == "invoice_overdue":
        out = await _sweep_invoice_overdue(tenant_id)
    elif sweep == "customer_birthday":
        out = await _sweep_customer_birthday(tenant_id)
    elif sweep == "daily":
        out = await daily_phase1_trigger_sweep()
    else:
        raise HTTPException(400, "unknown sweep")
    return {"ok": True, "sweep": sweep, "tenant_id": tenant_id,
             "result": out}
