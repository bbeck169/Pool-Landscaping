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

── Phase F7 · Feb-2026 — line items on jobs power the "Add charge for
visit" flow.  auto_invoice.py inherits job.line_items[] verbatim when
the job flips to completed.  New optional fields on POST/PATCH:
* ``category``            — validated via ``validate_line_item_categories``
                            (same 4xx contract the invoice side uses).
* ``unit_price``          — admin override of pricebook default; stamps
                            ``custom_price_override_flag`` on the row
                            when divergent from pricebook.
* ``pricebook_writeback`` — when True, writeback fan-out fires AFTER
                            the row save via
                            ``services/pricebook/writeback.py``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant
# Feb-2026 · Phase F1 — crew-aware tech authorization helper. Line
# item mutations must accept crew-member techs, not just the direct
# ``technician_id`` on the row.
from services.authz import is_tech_authorized_on_job

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


async def _tech_can_touch(job: Dict[str, Any], user: Dict[str, Any],
                          tenant_id: Optional[str] = None) -> bool:
    """Tech may only mutate a job they are directly assigned to OR
    are a member of the assigned crew (Phase F1 · crew-aware).
    Async because the crew lookup requires a Motor call.
    """
    if _is_admin(user):
        return True
    if not _is_tech(user):
        return False
    return await is_tech_authorized_on_job(
        user, job, db, tenant_id or job.get("tenant_id"),
    )


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
    # ─── Phase F7 · Feb-2026 additions ────────────────────────────────
    # All optional so pre-F7 callers (e.g. existing K2 tests) keep
    # working — they simply denorm from the pricebook item.
    unit_price: Optional[float] = Field(None, ge=0)
    category: Optional[str] = Field(None, max_length=100)
    pricebook_writeback: Optional[bool] = Field(False)


class LineItemPatch(BaseModel):
    quantity: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = Field(None, max_length=500)
    # ─── Phase F7 · Feb-2026 additions ────────────────────────────────
    unit_price: Optional[float] = Field(None, ge=0)
    category: Optional[str] = Field(None, max_length=100)
    pricebook_writeback: Optional[bool] = None


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
    if not await _tech_can_touch(job, user, tenant["id"]):
        raise HTTPException(403, "Not your job")
    pb = await _load_pricebook_item(body.pricebook_item_id, tenant["id"])
    pb_unit_price = _num(pb.get("unit_price"))
    # ─── F7 · unit_price override + custom-price flag ─────────────────
    if body.unit_price is not None:
        unit_price = _num(body.unit_price)
        custom_price_override = (unit_price != pb_unit_price)
    else:
        unit_price = pb_unit_price
        custom_price_override = False
    subtotal = round(unit_price * body.quantity, 2)
    tax_rate = pb.get("tax_rate")
    if tax_rate is None and pb.get("taxable"):
        # Fall back to the tenant's default tax rate when the item is
        # taxable but has no explicit rate.
        t = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0, "tax_rate": 1})
        tax_rate = _num((t or {}).get("tax_rate")) or None
    # ─── F7 · category resolution + validation ────────────────────────
    # Prefer explicit body override; fall back to pricebook item's
    # category.  Only validate when a category actually resolves —
    # jobs may carry uncategorised lines (auto-invoice inheritance
    # preserves whatever is there; the invoice-side validate hook
    # will 400 later if the completed invoice is missing a category,
    # which is the correct choke point).
    category = body.category if body.category is not None else pb.get("category")
    if category:
        from routers.income_categories import validate_line_item_categories
        # Reuse the invoice-side validator so the 4xx contract is
        # bit-identical.  Wraps in a single-line-items list so
        # ``line_index`` in the error surfaces as 0 — client maps
        # to the just-submitted row.
        await validate_line_item_categories(tenant["id"], [{"category": category}])
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
        # ─── F7 · Feb-2026 additive fields ────────────────────────────
        "category": category or None,
        "custom_price_override_flag": bool(custom_price_override),
        "pricebook_writeback_flag": bool(body.pricebook_writeback),
    }
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$push": {"line_items": li},
         "$set": {"updated_at": now_iso()}},
    )
    await _refresh_job_totals(jid, tenant["id"])
    # ─── F7 · pricebook writeback fan-out ─────────────────────────────
    # Runs AFTER the row save settles so a writeback failure never
    # rolls back the line item.  ``process_pricebook_writebacks``
    # never raises; it returns a status dict we can log.
    if body.pricebook_writeback:
        try:
            from services.pricebook.writeback import process_pricebook_writebacks
            wb_result = await process_pricebook_writebacks(
                tenant_id=tenant["id"],
                invoice_id=jid,           # FK stamp on the audit event
                line_items=[{**li, "pricebook_writeback": True,
                              "item_id": pb.get("id")}],
                actor=user,
            )
            if wb_result.get("errors"):
                logger.info(
                    "[pricebook_writeback] job=%s (add-line) errors=%s",
                    jid, wb_result["errors"],
                )
        except Exception:                                        # noqa: BLE001
            logger.exception(
                "[pricebook_writeback] fan-out failed for job=%s (add-line)",
                jid,
            )
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
    if not await _tech_can_touch(job, user, tenant["id"]):
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
    # ─── F7 · unit_price override + custom-price flag ─────────────────
    if body.unit_price is not None and _is_admin(user):
        # Tech is never allowed to change price server-side.  Silently
        # dropped for tech role (matches the pricing-projection ethos
        # — tech cannot READ price and cannot WRITE price).
        updates["unit_price"] = _num(body.unit_price)
        # Recompute custom_price_override_flag against the pricebook
        # source-of-truth.  Uses the row's own pricebook_item_id
        # (may be None for legacy rows).
        pb_price = None
        if li.get("pricebook_item_id"):
            pb = await db.items.find_one(
                {"id": li["pricebook_item_id"], "tenant_id": tenant["id"]},
                {"_id": 0, "unit_price": 1},
            ) or {}
            pb_price = _num(pb.get("unit_price"))
        updates["custom_price_override_flag"] = bool(
            pb_price is not None and updates["unit_price"] != pb_price
        )
    # Recompute subtotal if either qty or unit_price changed.
    if "quantity" in updates or "unit_price" in updates:
        new_qty = updates.get("quantity", _num(li.get("quantity")))
        new_price = updates.get("unit_price", _num(li.get("unit_price")))
        updates["subtotal"] = round(new_price * new_qty, 2)
    # ─── F7 · category update + validation ────────────────────────────
    if body.category is not None:
        if body.category:  # non-empty → validate
            from routers.income_categories import validate_line_item_categories
            await validate_line_item_categories(
                tenant["id"], [{"category": body.category}],
            )
        updates["category"] = body.category or None
    if body.pricebook_writeback is not None:
        updates["pricebook_writeback_flag"] = bool(body.pricebook_writeback)
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
    # ─── F7 · writeback fan-out on save (post-transaction) ────────────
    # Fires when the row NOW carries pricebook_writeback_flag=True,
    # regardless of whether this specific PATCH set it — matches the
    # invoice PATCH semantics.  Never raises.
    if updated_li and updated_li.get("pricebook_writeback_flag"):
        try:
            from services.pricebook.writeback import process_pricebook_writebacks
            wb_result = await process_pricebook_writebacks(
                tenant_id=tenant["id"],
                invoice_id=jid,
                line_items=[{**updated_li, "pricebook_writeback": True,
                              "item_id": updated_li.get("pricebook_item_id")}],
                actor=user,
            )
            if wb_result.get("errors"):
                logger.info(
                    "[pricebook_writeback] job=%s (patch-line) errors=%s",
                    jid, wb_result["errors"],
                )
        except Exception:                                        # noqa: BLE001
            logger.exception(
                "[pricebook_writeback] fan-out failed for job=%s (patch-line)",
                jid,
            )
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
    if not await _tech_can_touch(job, user, tenant["id"]):
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
    if _is_tech(user) and not await _tech_can_touch(job, user, tenant["id"]):
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
