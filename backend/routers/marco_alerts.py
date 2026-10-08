"""Feb-2026 · MARCO Proactive Monitoring Alerts — router.

Endpoints (all under the ``/api`` prefix via server.py's
``api_router``):

  * ``GET /ai/marco/alerts`` — list active alerts for the caller's
    tenant (dismissed_at IS NULL by default).  Query params:
    ``kind``, ``severity``, ``limit`` (default 50).
    Role gate: admin / super_admin / manager / owner (G5).
  * ``GET /ai/marco/alerts/count`` — lightweight breakdown
    ``{total, by_severity, by_kind}`` for the FAB badge poller.
    Same role gate.
  * ``POST /ai/marco/alerts/{alert_id}/acknowledge`` — set
    ``acknowledged_at`` / ``acknowledged_by``.  Does NOT dismiss.
    Same role gate.
  * ``POST /ai/marco/alerts/{alert_id}/dismiss`` — set
    ``dismissed_at`` / ``dismissed_by``.  Alert disappears from
    the active list.  Same role gate.
  * ``POST /ai/marco/alerts/sweep`` — admin-only manual trigger
    for all 5 detectors (dev / debug).  Returns summary.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import require_admin, require_admin_or_manager, now_iso

from services.marco_alerts import (
    ALL_ALERT_KINDS, sweep_tenant,
)


router = APIRouter()


def _clean(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    row.pop("_id", None)
    return row


@router.get("/ai/marco/alerts")
async def list_marco_alerts(
    kind: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    include_dismissed: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if not include_dismissed:
        q["dismissed_at"] = None
    if kind:
        if kind not in ALL_ALERT_KINDS:
            raise HTTPException(400, f"unknown alert kind: {kind!r}")
        q["kind"] = kind
    if severity:
        if severity not in ("info", "warn", "error"):
            raise HTTPException(400, "severity must be info|warn|error")
        q["severity"] = severity
    rows = await db.marco_alerts.find(
        q, {"_id": 0},
    ).sort("created_at", -1).to_list(limit)
    return rows


@router.get("/ai/marco/alerts/count")
async def count_marco_alerts(
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Lightweight count payload for the FAB badge poller."""
    rows = await db.marco_alerts.find(
        {"tenant_id": tenant["id"], "dismissed_at": None},
        {"_id": 0, "kind": 1, "severity": 1,
         "acknowledged_at": 1},
    ).to_list(2000)
    by_severity: Dict[str, int] = {"info": 0, "warn": 0, "error": 0}
    by_kind: Dict[str, int] = {k: 0 for k in ALL_ALERT_KINDS}
    unacked = 0
    for r in rows:
        sev = r.get("severity") or "info"
        by_severity[sev] = by_severity.get(sev, 0) + 1
        k = r.get("kind") or "other"
        by_kind[k] = by_kind.get(k, 0) + 1
        if not r.get("acknowledged_at"):
            unacked += 1
    return {
        "total": len(rows),
        "unacknowledged": unacked,
        "by_severity": by_severity,
        "by_kind": by_kind,
    }


@router.post("/ai/marco/alerts/{alert_id}/acknowledge")
async def ack_marco_alert(
    alert_id: str,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marco_alerts.find_one(
        {"id": alert_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "alert not found")
    if row.get("dismissed_at"):
        raise HTTPException(400, "alert already dismissed")
    now = now_iso()
    await db.marco_alerts.update_one(
        {"id": alert_id, "tenant_id": tenant["id"]},
        {"$set": {"acknowledged_at": now,
                   "acknowledged_by": user["id"]}},
    )
    row["acknowledged_at"] = now
    row["acknowledged_by"] = user["id"]
    return row


@router.post("/ai/marco/alerts/{alert_id}/dismiss")
async def dismiss_marco_alert(
    alert_id: str,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marco_alerts.find_one(
        {"id": alert_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "alert not found")
    if row.get("dismissed_at"):
        return _clean(row)
    now = now_iso()
    await db.marco_alerts.update_one(
        {"id": alert_id, "tenant_id": tenant["id"]},
        {"$set": {"dismissed_at": now,
                   "dismissed_by": user["id"]}},
    )
    row["dismissed_at"] = now
    row["dismissed_by"] = user["id"]
    return row


@router.post("/ai/marco/alerts/sweep")
async def manual_sweep(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only manual sweep for dev / debug — runs all 5
    detectors for the caller's tenant in-process and returns the
    summary.  Production sweeps run via the lifespan background
    task every 5 min."""
    summary = await sweep_tenant(db, tenant["id"])
    return summary
