"""Queue Item 5b · Feb-2026 — Homeworks Pricebook (income items)
importer routes.

Mounted under ``/api/integrations/homeworks/imports/income-items``.
Super-admin only. Mirrors the customer importers' router surface so
the Import Center's polling client reuses the same call shape.

Sanity gates (from user brief) are enforced on POST /run:
  * STOP if count == 0
  * STOP if count > 20 000
  * STOP if sample latency > 2 000 ms/item
  * STOP if dry-run reports a fatal_error
  * STOP if expected name-collision % > 95%
Each failed gate raises HTTP 412 with a stable ``reason`` string.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from services.homeworks_mcp import pricebook_importer as imp
from utils import get_current_user

logger = logging.getLogger("homeworks_mcp.pricebook_router")

router = APIRouter(
    prefix="/integrations/homeworks/imports/income-items",
    tags=["Integrations · Homeworks · Imports"],
)


def _require_super(user: dict) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


# ── Dry-run cache — 15 min per tenant ────────────────────────────────
_dry_run_cache: Dict[str, Dict[str, Any]] = {}
_DRY_RUN_TTL_S = 15 * 60


def _apply_sanity_gates(report: imp.DryRunReport) -> None:
    """Raise HTTPException(412, <reason>) when a gate trips."""
    if report.fatal_error:
        raise HTTPException(412, f"dry_run_fatal:{report.fatal_error}")
    if report.total_item_count < imp.GATE_MIN_COUNT:
        raise HTTPException(412, "gate_min_count: 0 items reported")
    if report.total_item_count > imp.GATE_MAX_COUNT:
        raise HTTPException(
            412,
            f"gate_max_count: {report.total_item_count} exceeds "
            f"cap of {imp.GATE_MAX_COUNT}",
        )
    if report.sample_avg_latency_ms > imp.GATE_MAX_SAMPLE_LATENCY_MS:
        raise HTTPException(
            412,
            f"gate_latency: sample latency "
            f"{report.sample_avg_latency_ms}ms exceeds "
            f"{imp.GATE_MAX_SAMPLE_LATENCY_MS}ms",
        )
    if report.name_collision_pct > imp.GATE_MAX_NAME_COLLISION_PCT:
        raise HTTPException(
            412,
            f"gate_collisions: expected "
            f"{report.name_collision_pct * 100:.1f}% name collisions",
        )


@router.post("/dry-run",
              operation_id="hw.imports.income_items.dry_run")
async def dry_run(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "missing_tenant")
    report = await imp.dry_run(tenant_id, user_id=user.get("id"))
    _dry_run_cache[tenant_id] = {"at": time.time(),
                                   "report": report.to_dict()}
    return report.to_dict()


@router.post("/run", operation_id="hw.imports.income_items.run")
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
    _apply_sanity_gates(dry)
    run_id = await imp.create_run(
        tenant_id=tenant_id, user_id=user.get("id"),
        dry_run_report=dry, status="queued",
    )
    return {"run_id": run_id, "status": "queued"}


@router.post("/{run_id}/cancel",
              operation_id="hw.imports.income_items.cancel")
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
             operation_id="hw.imports.income_items.status")
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
             operation_id="hw.imports.income_items.active")
async def active_runs(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    rows = await db.homeworks_import_runs.find(
        {"tenant_id": tenant_id, "kind": "pricebook",
         "status": {"$in": ["queued", "running"]}},
        {"_id": 0, "run_id": 1, "status": 1, "started_at": 1,
         "updated_at": 1, "counters": 1},
    ).to_list(length=20)
    return {"active_runs": rows}


@router.get("/history",
             operation_id="hw.imports.income_items.history")
async def history(user: Dict[str, Any] = Depends(get_current_user),
                   limit: int = Query(20, ge=1, le=100)):
    _require_super(user)
    tenant_id = user.get("tenant_id")
    rows = await db.homeworks_import_runs.find(
        {"tenant_id": tenant_id, "kind": "pricebook"},
        {"_id": 0},
    ).sort("started_at", -1).to_list(length=limit)
    return {"runs": rows}
