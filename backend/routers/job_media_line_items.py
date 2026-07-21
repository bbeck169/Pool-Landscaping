"""Feb-2026 · Slice K — Job videos + Job line items.

Two independent surfaces bundled together because they both attach to
the ``jobs`` collection and share the same tenant/RBAC scaffolding.

K1 · Videos (companion to the existing photos surface):
* ``POST   /api/jobs/{jid}/videos`` — add a video (max 3 per job).
* ``DELETE /api/jobs/{jid}/videos/{vid}`` — delete a video.

RBAC: tech can only delete videos they uploaded; admin can delete any.
The existing photo delete on ``routers/jobs.py`` is left untouched
here (this slice only adds ``videos`` support so we don't churn a
proven surface).

K2 · Line items with tech-hidden pricing:
* ``POST   /api/jobs/{jid}/line-items``   — add from pricebook.
* ``PATCH  /api/jobs/{jid}/line-items/{lid}`` — quantity/notes edit.
* ``DELETE /api/jobs/{jid}/line-items/{lid}``.
* ``GET    /api/jobs/{jid}/line-items``   — role-projected list.
* ``GET    /api/pricebook-items``         — role-projected pricebook picker.

Projection rules — SERVER SIDE (client-side hiding is not sufficient):
* Admin/super_admin: full payload — unit_price, subtotal, tax_rate,
  job_totals, cost.
* Tech: unit_price, subtotal, tax_rate, cost, job_totals are all
  stripped from the payload.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()


# ─── Constants ────────────────────────────────────────────────────────
VIDEO_LIMIT = 3
VIDEO_MAX_BYTES = 100 * 1024 * 1024        # 100 MB
VIDEO_ALLOWED_MIME = {
    "video/mp4", "video/quicktime", "video/webm",
}
LINE_ITEM_PRICING_FIELDS = ("unit_price", "subtotal", "tax_rate", "cost")


def _is_admin(user: Dict[str, Any]) -> bool:
    return user.get("role") in ("admin", "super_admin")


def _is_tech(user: Dict[str, Any]) -> bool:
    return user.get("role") in ("technician", "tech")


async def _load_job(jid: str, tenant_id: str) -> Dict[str, Any]:
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant_id})
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _tech_can_touch(job: Dict[str, Any], user: Dict[str, Any]) -> bool:
    """Tech may only mutate a job they are assigned to."""
    if _is_admin(user):
        return True
    if not _is_tech(user):
        return False
    assigned = job.get("technician_id")
    return assigned in (user.get("id"), user.get("technician_id"))


# ═══════════════════════════════════════════════════════════════════════
# K1 · Job videos — HANDLED by ``routers/media_uploads.py`` (Phase 5A).
# This slice tightened media_uploads.py to enforce the 3-video cap +
# tech-own-delete RBAC as required by the Slice K1 spec. No new video
# endpoints live in this file to avoid route collisions.
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# K2 · Job line items — pricebook-backed, role-projected
# ═══════════════════════════════════════════════════════════════════════
class LineItemIn(BaseModel):
    pricebook_item_id: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    notes: Optional[str] = Field(None, max_length=500)


class LineItemPatch(BaseModel):
    quantity: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = Field(None, max_length=500)


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _compute_totals(items: List[Dict[str, Any]]) -> Dict[str, float]:
    subtotal = 0.0
    tax = 0.0
    for li in items:
        st = _num(li.get("subtotal"))
        subtotal += st
        tr = li.get("tax_rate")
        if isinstance(tr, (int, float)) and tr:
            tax += st * float(tr)
    return {
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "total": round(subtotal + tax, 2),
    }


def _strip_for_tech(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a NEW list with pricing fields removed. Tech never sees
    unit_price / subtotal / tax_rate / cost."""
    out: List[Dict[str, Any]] = []
    for li in items:
        row = {k: v for k, v in li.items() if k not in LINE_ITEM_PRICING_FIELDS}
        out.append(row)
    return out


async def _load_pricebook_item(pid: str, tenant_id: str) -> Dict[str, Any]:
    """Look up a pricebook item strictly within the caller's tenant.
    Cross-tenant reads return 404 (never 403 — attackers get no
    signal about which ids exist)."""
    item = await db.items.find_one(
        {"id": pid, "tenant_id": tenant_id, "active": {"$ne": False}},
        {"_id": 0},
    )
    if not item:
        # Backwards-compat: some tenants seeded ``items`` without a
        # tenant_id (legacy shared catalogue). Fall back to a tenant-
        # scoped OR-null match, but ONLY when the row is genuinely
        # tenantless — never allow cross-tenant reads.
        item = await db.items.find_one(
            {"id": pid, "tenant_id": {"$exists": False},
             "active": {"$ne": False}},
            {"_id": 0},
        )
    if not item:
        raise HTTPException(404, "Pricebook item not found")
    return item


@router.post("/jobs/{jid}/line-items", status_code=201)
async def add_line_item(jid: str, body: LineItemIn,
                         user: Dict[str, Any] = Depends(get_current_user),
                         tenant: Dict[str, Any] = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await _load_job(jid, tenant["id"])
    if not _tech_can_touch(job, user):
        raise HTTPException(403, "Not your job")
    pb = await _load_pricebook_item(body.pricebook_item_id, tenant["id"])
    unit_price = _num(pb.get("unit_price"))
    subtotal = round(unit_price * body.quantity, 2)
    tax_rate = pb.get("tax_rate")
    if tax_rate is None and pb.get("taxable"):
        # Fall back to the tenant's default tax rate when the item is
        # taxable but has no explicit rate.
        t = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0, "tax_rate": 1})
        tax_rate = _num((t or {}).get("tax_rate")) or None
    li = {
        "id": new_id(),
        "pricebook_item_id": pb.get("id"),
        "name": pb.get("name") or "",
        "description": pb.get("description") or pb.get("category") or "",
        "quantity": body.quantity,
        "unit_price": unit_price,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "cost": _num(pb.get("cost")) or None,
        "notes": body.notes or None,
        "added_by": user["id"],
        "added_at": now_iso(),
    }
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$push": {"line_items": li},
         "$set": {"updated_at": now_iso()}},
    )
    await _refresh_job_totals(jid, tenant["id"])
    if _is_tech(user):
        return {k: v for k, v in li.items() if k not in LINE_ITEM_PRICING_FIELDS}
    return li


async def _refresh_job_totals(jid: str, tenant_id: str) -> None:
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant_id},
        {"_id": 0, "line_items": 1},
    ) or {}
    totals = _compute_totals(job.get("line_items") or [])
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant_id},
        {"$set": {"job_totals": totals}},
    )


@router.patch("/jobs/{jid}/line-items/{lid}")
async def patch_line_item(jid: str, lid: str, body: LineItemPatch,
                            user: Dict[str, Any] = Depends(get_current_user),
                            tenant: Dict[str, Any] = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await _load_job(jid, tenant["id"])
    if not _tech_can_touch(job, user):
        raise HTTPException(403, "Not your job")
    items = job.get("line_items") or []
    li = next((x for x in items if x["id"] == lid), None)
    if not li:
        raise HTTPException(404, "Line item not found")
    if _is_tech(user) and li.get("added_by") != user["id"]:
        raise HTTPException(403, "You can only edit line items you added")
    updates: Dict[str, Any] = {}
    if body.quantity is not None:
        updates["quantity"] = body.quantity
        updates["subtotal"] = round(_num(li.get("unit_price")) * body.quantity, 2)
    if body.notes is not None:
        updates["notes"] = body.notes or None
    if not updates:
        return _strip_for_tech([li])[0] if _is_tech(user) else li
    # Motor positional update.
    set_ops = {f"line_items.$.{k}": v for k, v in updates.items()}
    set_ops["updated_at"] = now_iso()
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"], "line_items.id": lid},
        {"$set": set_ops},
    )
    await _refresh_job_totals(jid, tenant["id"])
    updated_job = await _load_job(jid, tenant["id"])
    updated_li = next((x for x in (updated_job.get("line_items") or []) if x["id"] == lid), None)
    if updated_li and _is_tech(user):
        return _strip_for_tech([updated_li])[0]
    return updated_li


@router.delete("/jobs/{jid}/line-items/{lid}")
async def delete_line_item(jid: str, lid: str,
                             user: Dict[str, Any] = Depends(get_current_user),
                             tenant: Dict[str, Any] = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await _load_job(jid, tenant["id"])
    if not _tech_can_touch(job, user):
        raise HTTPException(403, "Not your job")
    items = job.get("line_items") or []
    li = next((x for x in items if x["id"] == lid), None)
    if not li:
        raise HTTPException(404, "Line item not found")
    if _is_tech(user) and li.get("added_by") != user["id"]:
        raise HTTPException(403, "You can only delete line items you added")
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$pull": {"line_items": {"id": lid}},
         "$set": {"updated_at": now_iso()}},
    )
    await _refresh_job_totals(jid, tenant["id"])
    return {"ok": True, "deleted": lid}


@router.get("/jobs/{jid}/line-items")
async def list_line_items(jid: str,
                             user: Dict[str, Any] = Depends(get_current_user),
                             tenant: Dict[str, Any] = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await _load_job(jid, tenant["id"])
    if _is_tech(user) and not _tech_can_touch(job, user):
        raise HTTPException(403, "Not your job")
    items = job.get("line_items") or []
    if _is_tech(user):
        return {"line_items": _strip_for_tech(items)}
    return {"line_items": items,
            "job_totals": job.get("job_totals") or _compute_totals(items)}


# ─── Pricebook picker (tech + admin) ───────────────────────────────────
@router.get("/pricebook-items")
async def list_pricebook_items(
    active: bool = True,
    q: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    query: Dict[str, Any] = {
        "$or": [
            {"tenant_id": tenant["id"]},
            {"tenant_id": {"$exists": False}},   # legacy shared catalogue
        ],
    }
    if active:
        query["active"] = {"$ne": False}
    if q:
        # Cheap prefix/name/description search.
        query["$and"] = [
            {"$or": [
                {"name": {"$regex": q, "$options": "i"}},
                {"category": {"$regex": q, "$options": "i"}},
            ]},
        ]
    rows = await db.items.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    if _is_tech(user):
        # Tech projection strips pricing fields entirely.
        for r in rows:
            for k in ("unit_price", "cost", "tax_rate"):
                r.pop(k, None)
    return {"items": rows}
