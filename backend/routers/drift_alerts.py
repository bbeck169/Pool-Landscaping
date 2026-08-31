"""Phase D · Feb-2026 — Drift Alerts settings + test-fire router.

Endpoints
---------
GET  /api/admin/settings/drift-alerts            — read (masked webhook)
PUT  /api/admin/settings/drift-alerts            — write
POST /api/admin/settings/drift-alerts/test-fire  — super_admin only

Also exposes ``GET /api/admin/settings/drift-alerts/last-dispatch``
for the settings card so ops sees the most recent status without
hitting audit_events directly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger  # noqa: F401
from utils import require_admin, require_super_admin
from services.drift_alerting import (
    AUDIT_EVENT_TYPE, dispatch_for_tenant,
    public_settings, save_settings,
)

router = APIRouter()


class DriftAlertSettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    slack_webhook_url: Optional[str] = None
    email_recipients: Optional[List[str]] = Field(default=None, max_length=25)
    timezone: Optional[str] = None


@router.get("/admin/settings/drift-alerts")
async def get_drift_alert_settings(
    user: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "user has no tenant_id")
    return await public_settings(tid)


@router.put("/admin/settings/drift-alerts")
async def put_drift_alert_settings(
    body: DriftAlertSettingsPatch = Body(...),
    user: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "user has no tenant_id")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return await save_settings(tid, patch)


@router.post("/admin/settings/drift-alerts/test-fire")
async def test_fire_drift_alert(
    user: Dict[str, Any] = Depends(require_super_admin),
) -> Dict[str, Any]:
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "user has no tenant_id")
    tenant = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    if not tenant:
        raise HTTPException(404, "tenant not found")
    tenant = {"id": tid, **tenant}
    return await dispatch_for_tenant(tenant, force=True)


@router.get("/admin/settings/drift-alerts/last-dispatch")
async def get_last_dispatch(
    user: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    tid = user.get("tenant_id")
    row = await db.audit_events.find_one(
        {"event_type": AUDIT_EVENT_TYPE, "tenant_id": tid},
        {"_id": 0},
        sort=[("timestamp", -1)],
    )
    if not row:
        return {"present": False}
    payload = row.get("payload") or {}
    return {
        "present": True,
        "timestamp": row.get("timestamp"),
        "date": payload.get("date"),
        "dispatched": bool(payload.get("dispatched")),
        "reason": payload.get("reason"),
        "channels_notified": payload.get("channels_notified") or [],
        "dangling_refs_total": payload.get("dangling_refs_total") or 0,
    }
