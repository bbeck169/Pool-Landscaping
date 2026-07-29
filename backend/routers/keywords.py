"""Phase SEO-C · Feb-2026 — Keyword ideation endpoints.

Admin+/manager only. Tenant-scoped. Backed by
``services.keyword_ideator``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from services.keyword_ideator import (check_rate_limit, run_ideation)
from utils import get_current_user

router = APIRouter()

_MOD_ROLES = {"admin", "super_admin", "manager", "owner"}


def _require_mod(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


class IdeateBody(BaseModel):
    seed_keyword: str = Field(..., min_length=1)
    language: str = "en"
    region: str = "US"
    force_refresh: bool = False


@router.post("/keywords/ideate", operation_id="keywords.ideate")
async def ideate_keywords(body: IdeateBody,
                              caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    try:
        await check_rate_limit(caller["id"], limit_per_hour=20)
    except ValueError:
        raise HTTPException(429, {"error": "rate_limited",
                                    "limit_per_hour": 20})
    try:
        row = await run_ideation(
            seed=body.seed_keyword,
            language=body.language,
            region=body.region,
            tenant_id=tenant_id,
            user_id=caller["id"],
            force_refresh=body.force_refresh)
    except ValueError as e:
        raise HTTPException(400, {"error": str(e)})
    return row


@router.get("/keywords/history", operation_id="keywords.history")
async def history(
    limit: int = Query(25, ge=1, le=100),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    items: List[Dict[str, Any]] = []
    async for r in db.keyword_search_history.find(
            {"tenant_id": tenant_id, "user_id": caller["id"]},
            {"_id": 0}).sort("requested_at", -1).limit(limit):
        items.append(r)
    return {"items": items, "total": len(items)}


@router.get("/keywords/lookup/{lookup_id}",
             operation_id="keywords.getLookup")
async def get_lookup(lookup_id: str,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    row = await db.keyword_lookups.find_one(
        {"id": lookup_id, "tenant_id": tenant_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, {"error": "not_found"})
    return row
