"""Feb-2026 · P0 · Admin super-admin horizon backfill HTTP endpoint.

Companion to the CLI ``backend/scripts/backfill_recurring_jobs_window.py``.
Wraps the shared service ``services.recurring_jobs_backfill``
behind a super_admin gate so the sweep can be invoked when shell
access to the pod isn't available.

Route
-----
``POST /api/admin/recurring-jobs/backfill-horizon``

Body (JSON)
-----------
::

    {
      "days_ahead": 14,     // int, 1 <= x <= 30, default 14
      "dry_run": true,      // default TRUE — explicit opt-in required
      "tenant_id": null     // null = all tenants, str = scope one
    }

Auth
----
Super_admin only (``utils.require_super_admin``). 403 for every
other role.

Audit
-----
Writes two rows to ``db.audit_logs`` per invocation:

* ``admin.recurring_jobs.backfill_horizon.invoke`` — on receipt, before
  the sweep. Captures caller + request payload.
* ``admin.recurring_jobs.backfill_horizon.complete`` — after the sweep
  (success OR top-level exception). Captures the full summary dict +
  ``success: bool`` + ``error`` string if the sweep died with an
  uncaught exception.

The ``tenant_id`` on each audit row = the ``tenant_id`` from the
request body (``None`` when scope = all tenants).

Partial-failure contract
------------------------
Template-level failures (one bad seed row) and per-date insert
failures do NOT fail the HTTP call. The response is 200 with
``errored_templates`` / ``warnings`` populated — mirrors the CLI's
exit-2 non-fatal design. The ``.complete`` audit row has
``success=True`` in that case because the sweep ran end-to-end;
look at ``result.errored_templates`` for the detail.

Top-level uncaught exceptions (e.g. Mongo unreachable) are the
only 500 case. The ``.complete`` audit row still fires with
``success=False`` + ``error`` populated so the trail is intact.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from utils import new_id, now_iso, require_super_admin
from services.recurring_jobs_backfill import run_horizon_backfill


logger = logging.getLogger("admin_recurring_jobs_backfill")

router = APIRouter()


class BackfillHorizonBody(BaseModel):
    days_ahead: int = Field(
        default=14,
        ge=1,
        le=30,
        description=(
            "Horizon size in days from today. Hard bounds [1, 30]: "
            "the live cron horizon is 14; 30 gives operator room for "
            "longer-term heals without opening unbounded sweeps."
        ),
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "Safety-first default. Set to false to actually write to "
            "db.jobs. Idempotent either way: a second commit call with "
            "no new holes writes zero rows."
        ),
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description=(
            "Scope to a single tenant_id. Omit (or null) to sweep "
            "every active-template tenant."
        ),
    )


async def _write_audit(
    *,
    action: str,
    tenant_id: Optional[str],
    user: Dict[str, Any],
    payload: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    success: Optional[bool] = None,
    error: Optional[str] = None,
) -> None:
    """Direct ``db.audit_logs`` insert — matches the project convention
    (no shared ``write_audit`` helper exists; 20+ callsites use this
    exact shape).

    ``success`` + ``error`` + ``result`` are only populated on the
    ``.complete`` row. The ``.invoke`` row writes payload-only.
    """
    row: Dict[str, Any] = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "action": action,
        "actor_user_id": user.get("id"),
        "actor_role": user.get("role"),
        "payload": payload,
        "created_at": now_iso(),
    }
    if result is not None:
        row["result"] = result
    if success is not None:
        row["success"] = success
    if error is not None:
        row["error"] = error
    try:
        await db.audit_logs.insert_one(row)
    except Exception as exc:  # noqa: BLE001
        # Audit write failure must never mask the operational call.
        logger.warning(
            "audit_write_failed action=%s tenant=%s error=%r",
            action, tenant_id, exc,
        )


@router.post(
    "/admin/recurring-jobs/backfill-horizon",
    operation_id="admin.recurring_jobs.backfill_horizon",
)
async def backfill_horizon(
    body: BackfillHorizonBody = Body(...),
    user: Dict[str, Any] = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Super-admin HTTP wrapper around the shared horizon-backfill
    service. See module docstring for contract.
    """
    payload = {
        "days_ahead": body.days_ahead,
        "dry_run": body.dry_run,
        "tenant_id": body.tenant_id,
    }
    audit_tenant_id = body.tenant_id

    await _write_audit(
        action="admin.recurring_jobs.backfill_horizon.invoke",
        tenant_id=audit_tenant_id,
        user=user,
        payload=payload,
    )

    try:
        summary = await run_horizon_backfill(
            days_ahead=body.days_ahead,
            commit=(not body.dry_run),
            tenant_id=body.tenant_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "recurring_backfill_horizon_internal_error user=%s payload=%s",
            user.get("id"), payload,
        )
        await _write_audit(
            action="admin.recurring_jobs.backfill_horizon.complete",
            tenant_id=audit_tenant_id,
            user=user,
            payload=payload,
            result=None,
            success=False,
            error=repr(exc),
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "recurring_backfill_horizon_internal_error",
                "error": repr(exc),
            },
        )

    await _write_audit(
        action="admin.recurring_jobs.backfill_horizon.complete",
        tenant_id=audit_tenant_id,
        user=user,
        payload=payload,
        result=summary,
        success=True,
        error=None,
    )

    return summary
