"""Phase 7 · Feb-2026 — Scorecard Digest endpoints."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from services.scorecard_digest import (
    compute_digest, deliver_digest, get_settings, save_settings,
    public_settings, last_completed_week, already_generated_this_week,
    _iso,
)
from utils import get_current_user

router = APIRouter()
_MOD_ROLES = {"admin", "super_admin", "manager"}


def _require_mod(u: Dict[str, Any]) -> None:
    if (u.get("role") or "").lower() not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant(u: Dict[str, Any]) -> str:
    t = u.get("tenant_id") or ""
    if not t:
        raise HTTPException(400, {"error": "missing_tenant"})
    return t


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


class RunNowBody(BaseModel):
    period_end: Optional[str] = None
    deliver: bool = True
    channels: List[str] = Field(default_factory=lambda: ["slack", "email"])


@router.post("/scorecard/digest/run-now",
              operation_id="scorecard.runNow", tags=["scorecard"])
async def api_run_now(body: RunNowBody,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tenant(caller)
    tenant = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    tenant = {"id": tid, **tenant}
    pe = _parse_date(body.period_end)
    digest = await compute_digest(tenant, period_end=pe)
    digest["digest_id"] = f"dgst_{uuid.uuid4().hex[:10]}"
    digest["generated_by"] = caller.get("id", "")
    delivery = {"slack": {"sent": False}, "email": {"sent": False}}
    if body.deliver:
        settings = await get_settings(tid)
        delivery = await deliver_digest(tenant=tenant, digest=digest,
                                            settings=settings,
                                            channels=body.channels)
    digest["delivery"] = delivery
    await db.scorecard_digests.insert_one({**digest})
    return digest


@router.get("/scorecard/digest/preview",
             operation_id="scorecard.preview", tags=["scorecard"])
async def api_preview(period_end: Optional[str] = None,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tenant(caller)
    tenant = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    tenant = {"id": tid, **tenant}
    pe = _parse_date(period_end)
    return await compute_digest(tenant, period_end=pe)


@router.get("/scorecard/digest/history",
             operation_id="scorecard.history", tags=["scorecard"])
async def api_history(limit: int = 20,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tenant(caller)
    items: List[Dict[str, Any]] = []
    async for d in db.scorecard_digests.find({"tenant_id": tid},
                                                {"_id": 0}).sort("generated_at", -1).limit(limit):
        items.append(d)
    return {"items": items, "count": len(items)}


class SettingsBody(BaseModel):
    slack_webhook_url: Optional[str] = None
    slack_channel: Optional[str] = None
    recipient_emails: Optional[List[str]] = None
    enabled: Optional[bool] = None
    day_of_week: Optional[int] = None
    hour_utc: Optional[int] = None


@router.post("/scorecard/digest/settings",
              operation_id="scorecard.saveSettings", tags=["scorecard"])
async def api_save_settings(body: SettingsBody,
                              caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tenant(caller)
    return await save_settings(tid, body.model_dump(exclude_none=True))


@router.get("/scorecard/digest/settings",
             operation_id="scorecard.getSettings", tags=["scorecard"])
async def api_get_settings(caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tenant(caller)
    return await public_settings(tid)
