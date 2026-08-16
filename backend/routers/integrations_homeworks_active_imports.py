"""Feb-2026 · Phase 1b-B — Active-customers importer routes.

Mounted under ``/api/integrations/homeworks/imports/active-customers``.
Super-admin only. Mirrors the inactive-customers router surface so
the frontend can reuse the same polling client.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from services.homeworks_mcp import active_customers_importer as imp
from utils import get_current_user

logger = logging.getLogger("homeworks_mcp.active_imports_router")

router = APIRouter(
    prefix="/integrations/homeworks/imports/active-customers",
    tags=["Integrations · Homeworks · Imports"],
)


def _require_super(user: dict) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


# ── Dry-run cache — 15 min per tenant ────────────────────────────────
_dry_run_cache: Dict[str, Dict[str, Any]] = {}
_DRY_RUN_TTL_S = 15 * 60


@router.post("/dry-run",
              operation_id="hw.imports.active_customers.dry_run")
async def dry_run(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "missing_tenant")
    report = await imp.dry_run(tenant_id, user_id=user.get("id"))
    _dry_run_cache[tenant_id] = {"at": time.time(),
                                   "report": report.to_dict()}
    return report.to_dict()


@router.post("/run",
              operation_id="hw.imports.active_customers.run")
async def start_run(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "missing_tenant")
    cached = _dry_run_cache.get(tenant_id)
    if not cached or (time.time() - cached["at"]) > _DRY_RUN_TTL_S:
        raise HTTPException(
            412, "dry_run_required_within_15_minutes_before_run",
        )
    dry = imp.DryRunReport(**cached["report"])
    run_id = await imp.create_run(
        tenant_id=tenant_id, user_id=user.get("id"),
        dry_run_report=dry, status="queued",
    )
    return {"run_id": run_id, "status": "queued"}


@router.post("/{run_id}/cancel",
              operation_id="hw.imports.active_customers.cancel")
async def cancel_run(run_id: str,
                      user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    r = await db.homeworks_import_runs.update_one(
        {"run_id": run_id, "tenant_id": tenant_id,
         "status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "cancelling",
                   "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "run_not_found_or_not_cancellable")
    return {"ok": True}


@router.get("/{run_id}/status",
             operation_id="hw.imports.active_customers.status")
async def status(run_id: str,
                  user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    doc = await db.homeworks_import_runs.find_one(
        {"run_id": run_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "run_not_found")
    return doc


@router.get("/active",
             operation_id="hw.imports.active_customers.active")
async def active_runs(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    rows = await db.homeworks_import_runs.find(
        {"tenant_id": tenant_id, "kind": "active_customers",
         "status": {"$in": ["queued", "running"]}},
        {"_id": 0, "run_id": 1, "status": 1, "started_at": 1,
         "updated_at": 1, "counters": 1},
    ).to_list(length=20)
    return {"active_runs": rows}


@router.get("/history",
             operation_id="hw.imports.active_customers.history")
async def history(user: Dict[str, Any] = Depends(get_current_user),
                   limit: int = Query(20, ge=1, le=100)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    rows = await db.homeworks_import_runs.find(
        {"tenant_id": tenant_id, "kind": "active_customers"},
        {"_id": 0},
    ).sort("started_at", -1).to_list(length=limit)
    return {"runs": rows}
