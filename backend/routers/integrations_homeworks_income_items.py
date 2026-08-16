"""Queue Item 5 · Feb-2026 — Homeworks Pricebook (income items)
importer routes.

STATUS: The pricebook (income items) importer implementation itself
is a P1 backlog item scheduled after the delta-sync ship. This
router exposes the same URL surface the frontend Import Center
polls so the "Import Income Items" button can be wired end-to-end
today; the ``run`` endpoint returns HTTP 501 with a stable
``not_implemented`` reason so the FE can render a "Coming next"
badge without a code branch of its own.

The four read endpoints (``/dry-run``, ``/{run_id}/status``,
``/active``, ``/history``) all report a truthful zero-work state so
the polling client never breaks.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user

router = APIRouter(
    prefix="/integrations/homeworks/imports/income-items",
    tags=["Integrations · Homeworks · Imports"],
)


def _require_super(user: dict) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


_NOT_IMPLEMENTED_REASON = (
    "pricebook_importer_not_yet_implemented: coming in the next "
    "P1 slice after delta-sync ships"
)


@router.post("/dry-run",
              operation_id="hw.imports.income_items.dry_run")
async def dry_run(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    # Explicitly truthful — reports zero, tells the UI why.
    return {
        "not_implemented": True,
        "reason": _NOT_IMPLEMENTED_REASON,
        "total_item_count": 0,
        "existing_in_aquaterra_by_original_id": 0,
        "estimated_duration_minutes": 0,
    }


@router.post("/run", operation_id="hw.imports.income_items.run")
async def start_run(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    raise HTTPException(501, _NOT_IMPLEMENTED_REASON)


@router.get("/{run_id}/status",
             operation_id="hw.imports.income_items.status")
async def status_(run_id: str,
                    user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    doc = await db.homeworks_import_runs.find_one(
        {"run_id": run_id, "tenant_id": tenant_id,
         "kind": "income_items"},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "run_not_found")
    return doc


@router.get("/active",
             operation_id="hw.imports.income_items.active")
async def active_runs(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    return {"active_runs": []}


@router.get("/history",
             operation_id="hw.imports.income_items.history")
async def history(user: Dict[str, Any] = Depends(get_current_user),
                   limit: int = Query(20, ge=1, le=100)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    rows = await db.homeworks_import_runs.find(
        {"tenant_id": tenant_id, "kind": "income_items"},
        {"_id": 0},
    ).sort("started_at", -1).to_list(length=limit)
    return {"runs": rows}
