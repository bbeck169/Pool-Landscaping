"""Phase 17 · Feb-2026 — Route reassignment endpoints (temporary + permanent).

Four admin-only endpoints power the "shift route" feature on the
Dispatch Board:

  * ``POST   /api/dispatch/reassign``              — create override OR permanent move
  * ``GET    /api/dispatch/reassign``              — list active overrides
  * ``POST   /api/dispatch/reassign/{id}/cancel``  — soft-cancel
  * ``GET    /api/dispatch/assignment-change-log`` — permanent-move audit

RBAC: admin + super_admin only. Techs never see this surface.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user
from routers.tenants import get_current_tenant
from services.route_reassign import (
    compute_end_at, is_same_day_no_op, create_override,
    find_conflicting_overrides, perform_permanent_reassign,
)

router = APIRouter()

_ADMIN_ROLES = {"admin", "super_admin"}


def _require_admin(user: dict):
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")


class ReassignRequest(BaseModel):
    source_tech_user_id: str
    target_tech_user_id: str
    scope: str = Field(..., pattern="^(whole_route|partial)$")
    customer_ids: Optional[List[str]] = None
    duration: str = Field("week", pattern="^(week|permanent)$")
    day: Optional[str] = None
    notes: Optional[str] = None
    force: bool = False   # bypass conflict warning on second confirm


@router.post("/dispatch/reassign", tags=["dispatch"],
              operation_id="dispatchReassign.create")
async def create_reassign(
    body: ReassignRequest,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    if body.source_tech_user_id == body.target_tech_user_id:
        raise HTTPException(400, "Source and target tech must differ")

    # Resolve customer_ids.
    cids = body.customer_ids or []
    if body.scope == "partial":
        if not cids:
            raise HTTPException(400, "customer_ids required for partial scope")
    else:  # whole_route
        # Every customer currently denorm-assigned to the source tech.
        q = {"tenant_id": tenant["id"],
              "assigned_tech_ids": body.source_tech_user_id}
        if body.day:
            q["service_days"] = body.day.lower()
        docs = await db.customers.find(q, {"_id": 0, "id": 1}).to_list(2000)
        cids = [d["id"] for d in docs]
        if not cids:
            raise HTTPException(400, "No customers currently assigned to source tech")

    now = datetime.now(timezone.utc)

    # ── PERMANENT — mutate the master ──────────────────────────
    if body.duration == "permanent":
        result = await perform_permanent_reassign(
            tenant_id=tenant["id"],
            source_tech_user_id=body.source_tech_user_id,
            target_tech_user_id=body.target_tech_user_id,
            customer_ids=cids, tenant=tenant,
            changed_by=user.get("id"),
            scope=body.scope, notes=body.notes,
        )
        return result

    # ── TEMPORARY (default) — additive override ────────────────
    conflicts = await find_conflicting_overrides(tenant["id"], cids)
    if conflicts and not body.force:
        # Return 200 + warning per PRD so the UI can surface the
        # confirm-again modal.
        return {
            "warning": "existing_override_conflict",
            "conflicts": [{
                "id": c["id"],
                "target_tech_user_id": c["target_tech_user_id"],
                "customer_ids": c["customer_ids"],
                "end_at": c["end_at"],
            } for c in conflicts],
            "customer_ids": cids,
        }

    same_day = is_same_day_no_op(now, tenant)
    doc = await create_override(
        tenant_id=tenant["id"],
        source_tech_user_id=body.source_tech_user_id,
        target_tech_user_id=body.target_tech_user_id,
        customer_ids=cids, scope=body.scope,
        tenant=tenant, created_by=user.get("id"),
        notes=body.notes,
    )
    doc["same_day_warning"] = same_day
    return doc


@router.get("/dispatch/reassign", tags=["dispatch"],
             operation_id="dispatchReassign.list")
async def list_reassigns(
    active: bool = Query(True),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    q = {"tenant_id": tenant["id"]}
    if active:
        now = datetime.now(timezone.utc).isoformat()
        q["canceled_at"] = {"$exists": False}
        q["end_at"] = {"$gte": now}
    rows = await db.route_assignment_overrides.find(
        q, {"_id": 0},
    ).sort("created_at", -1).to_list(200)

    # Enrich with tech names for the sidebar list.
    tech_ids = set()
    for r in rows:
        tech_ids.add(r.get("source_tech_user_id"))
        tech_ids.add(r.get("target_tech_user_id"))
    tech_ids.discard(None)
    name_map = {}
    if tech_ids:
        async for u in db.users.find(
            {"id": {"$in": list(tech_ids)}},
            {"_id": 0, "id": 1, "name": 1, "display_color_hex": 1},
        ):
            name_map[u["id"]] = {
                "name": u.get("name") or u["id"],
                "color_hex": u.get("display_color_hex"),
            }
    for r in rows:
        r["source_tech_name"] = (name_map.get(r.get("source_tech_user_id")) or {}).get("name")
        r["source_tech_color"] = (name_map.get(r.get("source_tech_user_id")) or {}).get("color_hex")
        r["target_tech_name"] = (name_map.get(r.get("target_tech_user_id")) or {}).get("name")
        r["target_tech_color"] = (name_map.get(r.get("target_tech_user_id")) or {}).get("color_hex")
        r["stop_count"] = len(r.get("customer_ids") or [])
    return {"items": rows, "total": len(rows)}


@router.post("/dispatch/reassign/{oid}/cancel", tags=["dispatch"],
              operation_id="dispatchReassign.cancel")
async def cancel_reassign(
    oid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    res = await db.route_assignment_overrides.update_one(
        {"id": oid, "tenant_id": tenant["id"],
          "canceled_at": {"$exists": False}},
        {"$set": {"canceled_at": datetime.now(timezone.utc).isoformat(),
                    "canceled_by": user.get("id")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Override not found or already canceled")
    return {"ok": True}


@router.get("/dispatch/assignment-change-log", tags=["dispatch"],
             operation_id="dispatchReassign.auditLog")
async def get_change_log(
    customer_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    q = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    rows = await db.assignment_change_log.find(
        q, {"_id": 0},
    ).sort("changed_at", -1).to_list(limit)
    # Enrich with tech names.
    tech_ids = set()
    for r in rows:
        tech_ids.add(r.get("from_tech_user_id"))
        tech_ids.add(r.get("to_tech_user_id"))
    tech_ids.discard(None)
    name_map = {}
    if tech_ids:
        async for u in db.users.find(
            {"id": {"$in": list(tech_ids)}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            name_map[u["id"]] = u.get("name") or u["id"]
    for r in rows:
        r["from_tech_name"] = name_map.get(r.get("from_tech_user_id"))
        r["to_tech_name"] = name_map.get(r.get("to_tech_user_id"))
    return {"items": rows, "total": len(rows)}
