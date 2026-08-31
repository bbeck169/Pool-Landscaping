"""Phase F2 · Feb-2026 — Charge Template Bundles.

Reusable "bundles" of 3-4 line items (e.g. "Chlorine Shock Combo") that
admins can apply to a job in one click instead of adding each line item
individually.

Endpoints
---------
GET    /api/charge-templates                          — list active for tenant
GET    /api/charge-templates/{tid}                    — single detail
POST   /api/charge-templates                          — create (admin+)
PUT    /api/charge-templates/{tid}                    — update (admin+)
DELETE /api/charge-templates/{tid}                    — soft-delete (admin+)
POST   /api/charge-templates/{tid}/apply-to-job/{jid} — append to job.line_items

Tenant isolation: every read/write is scoped via ``get_current_tenant``.
Techs may LIST/READ + APPLY; only admin/super_admin/owner can create,
update, or archive templates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()


COLLECTION = "charge_templates"
_ALLOWED_CATEGORIES = {"chemicals", "maintenance", "repair", "custom"}


# ─── Schemas ──────────────────────────────────────────────────────────
class TemplateLineItemIn(BaseModel):
    pricebook_item_id: Optional[str] = Field(None, max_length=200)
    name: str = Field(..., min_length=1, max_length=200)
    unit_price: float = Field(..., ge=0)
    quantity: float = Field(1, gt=0)
    category: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    pricebook_writeback_flag: bool = False
    custom_price_override_flag: bool = False


class ChargeTemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    category: str = Field(..., min_length=1)
    line_items: List[TemplateLineItemIn] = Field(..., min_length=1, max_length=20)


class ChargeTemplatePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    category: Optional[str] = None
    line_items: Optional[List[TemplateLineItemIn]] = Field(
        None, min_length=1, max_length=20,
    )


# ─── Helpers ──────────────────────────────────────────────────────────
def _is_admin(user: Dict[str, Any]) -> bool:
    return user.get("role") in ("admin", "super_admin", "owner")


def _require_admin_or_403(user: Dict[str, Any]) -> None:
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")


def _validate_category(cat: str) -> str:
    c = (cat or "").strip().lower()
    if c not in _ALLOWED_CATEGORIES:
        raise HTTPException(
            422,
            f"category must be one of: {sorted(_ALLOWED_CATEGORIES)}",
        )
    return c


async def _assert_name_unique(
    tenant_id: str, name: str, exclude_id: Optional[str] = None,
) -> None:
    """Case-insensitive uniqueness within a tenant, across non-archived rows."""
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "archived": {"$ne": True},
        "name": {"$regex": f"^{_re_escape(name)}$", "$options": "i"},
    }
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    hit = await db[COLLECTION].find_one(q, {"_id": 0, "id": 1})
    if hit:
        raise HTTPException(409, "A template with this name already exists")


def _re_escape(s: str) -> str:
    import re as _re
    return _re.escape(s or "")


def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
    row.pop("_id", None)
    return row


async def _load_template(tid: str, tenant_id: str,
                         include_archived: bool = False) -> Dict[str, Any]:
    q: Dict[str, Any] = {"id": tid, "tenant_id": tenant_id}
    if not include_archived:
        q["archived"] = {"$ne": True}
    row = await db[COLLECTION].find_one(q, {"_id": 0})
    if not row:
        raise HTTPException(404, "Charge template not found")
    return row


async def _load_job(jid: str, tenant_id: str) -> Dict[str, Any]:
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _normalize_line_items(items: List[TemplateLineItemIn]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for li in items:
        d = li.model_dump()
        # Round money fields for deterministic reads.
        d["unit_price"] = round(float(d["unit_price"]), 2)
        d["quantity"] = float(d["quantity"])
        out.append(d)
    return out


# ─── Endpoints ────────────────────────────────────────────────────────
@router.get("/charge-templates")
async def list_charge_templates(
    include_archived: bool = False,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if not include_archived:
        q["archived"] = {"$ne": True}
    cursor = db[COLLECTION].find(q, {"_id": 0}).sort([("name", 1)])
    rows = [_serialize(r) async for r in cursor]
    return {"templates": rows, "count": len(rows)}


@router.get("/charge-templates/{tid}")
async def get_charge_template(
    tid: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    return await _load_template(tid, tenant["id"])


@router.post("/charge-templates", status_code=201)
async def create_charge_template(
    body: ChargeTemplateIn,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_403(user)
    category = _validate_category(body.category)
    name = body.name.strip()
    await _assert_name_unique(tenant["id"], name)
    row = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": name,
        "description": (body.description or "").strip() or None,
        "category": category,
        "line_items": _normalize_line_items(body.line_items),
        "created_by": user.get("id"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "archived": False,
    }
    await db[COLLECTION].insert_one(row)
    return _serialize(dict(row))


@router.put("/charge-templates/{tid}")
async def update_charge_template(
    tid: str,
    body: ChargeTemplatePatch,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_403(user)
    row = await _load_template(tid, tenant["id"])
    patch: Dict[str, Any] = {}
    if body.name is not None:
        name = body.name.strip()
        await _assert_name_unique(tenant["id"], name, exclude_id=tid)
        patch["name"] = name
    if body.description is not None:
        patch["description"] = (body.description or "").strip() or None
    if body.category is not None:
        patch["category"] = _validate_category(body.category)
    if body.line_items is not None:
        patch["line_items"] = _normalize_line_items(body.line_items)
    if not patch:
        return row
    patch["updated_at"] = now_iso()
    await db[COLLECTION].update_one(
        {"id": tid, "tenant_id": tenant["id"]},
        {"$set": patch},
    )
    return await _load_template(tid, tenant["id"])


@router.delete("/charge-templates/{tid}")
async def delete_charge_template(
    tid: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_403(user)
    row = await _load_template(tid, tenant["id"])
    await db[COLLECTION].update_one(
        {"id": tid, "tenant_id": tenant["id"]},
        {"$set": {"archived": True, "updated_at": now_iso(),
                  "archived_at": now_iso(), "archived_by": user.get("id")}},
    )
    return {"ok": True, "id": row["id"], "archived": True}


@router.post("/charge-templates/{tid}/apply-to-job/{jid}")
async def apply_template_to_job(
    tid: str,
    jid: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    template = await _load_template(tid, tenant["id"])
    job = await _load_job(jid, tenant["id"])
    existing = list(job.get("line_items") or [])
    added: List[Dict[str, Any]] = []
    for src in template.get("line_items") or []:
        qty = float(src.get("quantity") or 1)
        unit_price = float(src.get("unit_price") or 0)
        row = {
            "id": new_id(),
            "pricebook_item_id": src.get("pricebook_item_id"),
            "name": src.get("name") or "",
            "description": src.get("description") or None,
            "quantity": qty,
            "unit_price": unit_price,
            "subtotal": round(unit_price * qty, 2),
            "tax_rate": None,
            "cost": None,
            "notes": None,
            "category": src.get("category") or None,
            "custom_price_override_flag": bool(
                src.get("custom_price_override_flag")),
            "pricebook_writeback_flag": bool(
                src.get("pricebook_writeback_flag")),
            "added_by": user.get("id"),
            "added_at": now_iso(),
            "applied_from_template_id": tid,
            "applied_from_template_name": template.get("name"),
        }
        added.append(row)
    merged = existing + added
    # Recompute totals inline (mirrors ``_refresh_job_totals``).
    subtotal = 0.0
    tax = 0.0
    for li in merged:
        st = float(li.get("subtotal") or 0)
        subtotal += st
        tr = li.get("tax_rate")
        if isinstance(tr, (int, float)) and tr:
            tax += st * float(tr)
    totals = {
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "total": round(subtotal + tax, 2),
    }
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": {"line_items": merged, "job_totals": totals,
                  "updated_at": now_iso()},
         "$inc": {"charge_template_apply_count": 1}},
    )
    # Bump the template's last_used_at so admin surface can sort by usage.
    await db[COLLECTION].update_one(
        {"id": tid, "tenant_id": tenant["id"]},
        {"$set": {"last_used_at": now_iso()},
         "$inc": {"apply_count": 1}},
    )
    return {
        "ok": True,
        "job_id": jid,
        "template_id": tid,
        "template_name": template.get("name"),
        "added_count": len(added),
        "line_items": merged,
        "job_totals": totals,
    }
