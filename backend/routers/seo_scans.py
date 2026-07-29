"""Phase SEO-A · Feb-2026 — Free on-page SEO auditor endpoints.

All routes admin+/manager only, tenant-scoped. See
``services.seo_scanner`` for the actual scanning logic — this router
only handles auth, RBAC, tenant scoping, pagination, and background-
task orchestration.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from services.seo_scanner import (
    check_rate_limit,
    normalize_url,
    run_scan,
    validate_target,
)
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_MOD_ROLES = {"admin", "super_admin", "manager"}


def _require_mod(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


# ─── Models ────────────────────────────────────────────────────────

class ScanCreateBody(BaseModel):
    target_url: str = Field(..., min_length=3)
    is_async: bool = Field(default=True, alias="async")

    model_config = {"populate_by_name": True}


# ─── POST /api/seo/scans ───────────────────────────────────────────

@router.post("/seo/scans", operation_id="seo.createScan")
async def create_seo_scan(
    body: ScanCreateBody,
    background: BackgroundTasks,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    try:
        target = normalize_url(body.target_url)
        validate_target(target)
    except ValueError as e:
        raise HTTPException(400, {"error": str(e)})

    try:
        await check_rate_limit(caller["id"], limit_per_hour=5)
    except ValueError:
        raise HTTPException(429, {"error": "rate_limited",
                                    "limit_per_hour": 5})

    scan_id = new_id()
    if body.is_async:
        background.add_task(run_scan, target, tenant_id,
                              caller["id"], scan_id)
        # Persist a queued row so the list view surfaces it immediately.
        await db.seo_scans.insert_one({
            "id": scan_id,
            "tenant_id": tenant_id,
            "requested_by_user_id": caller["id"],
            "requested_at": now_iso(),
            "target_url": target,
            "status": "queued",
            "results": None,
        })
        return {"scan_id": scan_id, "status": "queued",
                "target_url": target}

    # Synchronous path — awaits the full scan (used by tests and by
    # the "wait for result" UI toggle).
    doc = await run_scan(target, tenant_id, caller["id"], scan_id)
    return {"scan_id": scan_id, "status": doc.get("status"),
            "target_url": target,
            "results": doc.get("results")}


# ─── GET /api/seo/scans ────────────────────────────────────────────

@router.get("/seo/scans", operation_id="seo.listScans")
async def list_seo_scans(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    q = {"tenant_id": tenant_id}
    total = await db.seo_scans.count_documents(q)
    items: List[Dict[str, Any]] = []
    async for r in db.seo_scans.find(q, {"_id": 0}) \
                                  .sort("requested_at", -1) \
                                  .skip(offset).limit(limit):
        # Trim heavy fields for list view.
        if r.get("results"):
            r["results"] = {
                "score": r["results"].get("score"),
                "issue_count": r["results"].get("issue_count"),
            }
        items.append(r)
    return {"items": items, "total": total, "limit": limit,
             "offset": offset}


# ─── GET /api/seo/scans/history ────────────────────────────────────
# (Declared BEFORE the parameterized ``/seo/scans/{scan_id}`` route so
# FastAPI's linear path resolution never treats "history" as a scan_id.)

@router.get("/seo/scans/history", operation_id="seo.scanHistory")
async def scan_history(
    target_url: str = Query(..., min_length=3),
    limit: int = Query(30, ge=1, le=100),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    try:
        normalized = normalize_url(target_url)
    except ValueError:
        raise HTTPException(400, {"error": "invalid_url"})
    q = {"tenant_id": tenant_id, "target_url": normalized,
         "status": "complete"}
    points: List[Dict[str, Any]] = []
    async for r in db.seo_scans.find(q, {"_id": 0,
                                            "id": 1,
                                            "requested_at": 1,
                                            "finished_at": 1,
                                            "results.score": 1,
                                            "results.issue_count": 1}) \
                                  .sort("requested_at", -1) \
                                  .limit(limit):
        results = r.get("results") or {}
        points.append({
            "scan_id": r["id"],
            "requested_at": r.get("requested_at"),
            "finished_at": r.get("finished_at"),
            "score": results.get("score"),
            "issue_count": results.get("issue_count"),
        })
    return {"target_url": normalized, "points": list(reversed(points))}



# ─── GET /api/seo/scans/{id} ───────────────────────────────────────

@router.get("/seo/scans/{scan_id}", operation_id="seo.getScan")
async def get_seo_scan(scan_id: str,
                          caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    row = await db.seo_scans.find_one(
        {"id": scan_id, "tenant_id": tenant_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, {"error": "not_found"})
    return row


# ─── POST /api/seo/scans/{id}/rerun ────────────────────────────────

@router.post("/seo/scans/{scan_id}/rerun",
              operation_id="seo.rerunScan")
async def rerun_seo_scan(
    scan_id: str,
    background: BackgroundTasks,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    row = await db.seo_scans.find_one(
        {"id": scan_id, "tenant_id": tenant_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, {"error": "not_found"})
    try:
        await check_rate_limit(caller["id"], limit_per_hour=5)
    except ValueError:
        raise HTTPException(429, {"error": "rate_limited",
                                    "limit_per_hour": 5})
    new_scan_id = new_id()
    await db.seo_scans.insert_one({
        "id": new_scan_id,
        "tenant_id": tenant_id,
        "requested_by_user_id": caller["id"],
        "requested_at": now_iso(),
        "target_url": row["target_url"],
        "status": "queued",
        "results": None,
    })
    background.add_task(run_scan, row["target_url"], tenant_id,
                          caller["id"], new_scan_id)
    return {"scan_id": new_scan_id, "status": "queued",
            "target_url": row["target_url"]}
