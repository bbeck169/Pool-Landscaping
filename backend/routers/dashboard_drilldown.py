"""Phase K41 · Feb-2026 — Dashboard tile drill-down endpoints.

Three read endpoints + one write endpoint powering the K41 tile
drill-down modal (see ``frontend/src/components/dashboard/
DashboardDrillDownModal.jsx``).  All four are admin/super only per
the phase brief (dispatcher / office / tech / customer → 403).

Read endpoints
──────────────
1. ``GET /api/dashboard/data-integrity/rows``
     query: ``class`` ∈ {orphaned_customer_refs, orphaned_technician_refs,
                          unassigned_pending_jobs}
            ``limit`` (default 100, max 500)
            ``cursor`` (int offset — cursor-shaped for symmetry with 2 & 3)
     Result rows are those produced by ``data_repair._scan_dangling_refs``
     — one job per dangling ref — so the drill-down matches the tile
     exactly.  The read is cached for ``DRY_RUN_CACHE_TTL_SECONDS``
     just like the sibling ``/admin/data-repair/jobs/dry-run`` endpoint.

2. ``GET /api/dashboard/income/by-category/rows``
     query: ``category`` (pricebook display label — "Uncategorized" for
                            the fallback bucket), ``from``, ``to``,
            ``limit``, ``cursor``.
     Reuses the same query filters + line-item resolution ladder as
     :func:`routers.dashboard_revenue.revenue_by_category` so the
     drill-down row set sums to the exact tile bucket amount.

3. ``GET /api/dashboard/income/by-service/rows``
     query: ``service_category_id`` (or the literal string
             ``"Uncategorized"``), ``from``, ``to``, ``limit``, ``cursor``.
     Reuses :func:`routers.dashboard_revenue.income_by_service_category`
     resolution chain.

Write endpoint
──────────────
4. ``POST /api/dashboard/data-integrity/resolve``
     body: ``{ ref_class, job_id, action, target_id? }``
     action ∈ {assign, delete}
     Applies the fix to the underlying job document.  Emits both
     ``dashboard_drilldown_edit`` and — when the parent job is
     completed — the K6 ``job_edited_after_completion`` audit event
     per the K6 completed-job-unlock contract in
     ``services/edit_window.py``.

     Line-item edits do NOT go through this endpoint — they use the
     existing ``PATCH /api/quotes/{invoice_id}`` in ``invoice_edit.py``.
     The dashboard-drilldown audit event is emitted separately by the
     web modal (via a companion audit call — see K41 audit contract).

Audit contract
──────────────
Every write action emits ``dashboard_drilldown_edit`` into
``db.audit_events`` with the shape mandated by the K41 phase brief:

    { tile, field, before, after, actor_id }

plus ``tenant_id`` / ``timestamp`` / ``event_type`` /
``job_id`` (data-integrity variant) for downstream discovery.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from routers.data_repair import _scan_dangling_refs
from routers.dashboard_revenue import _parse_range, _UNCATEGORISED, _UUID_RE
from routers.tenants import get_current_tenant
from services.edit_window import (
    K6_UNLOCK_ROLES,
    role_bypasses_edit_window,
)
from utils import get_current_user, new_id, now_iso

logger = logging.getLogger("dashboard_drilldown")
router = APIRouter()


# ═════════════════════════════════════════════════════════════════════
# Auth — admin + super only (K41 brief).  Explicit function so the
# error string matches the 4-role negative-test expectation exactly.
# ═════════════════════════════════════════════════════════════════════
_ADMIN_ROLES = {"admin", "super_admin"}


def _require_admin_or_super(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role.lower() not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="admin_only")


# ═════════════════════════════════════════════════════════════════════
# Cursor helpers — offset-based, deterministic, safe against N++.
# ═════════════════════════════════════════════════════════════════════
_MAX_LIMIT = 500
_DEFAULT_LIMIT = 100


def _clamp_limit(limit: int) -> int:
    if limit <= 0:
        return _DEFAULT_LIMIT
    return min(limit, _MAX_LIMIT)


def _parse_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        return max(int(cursor), 0)
    except (TypeError, ValueError):
        return 0


def _make_next_cursor(offset: int, limit: int, total: int) -> Optional[str]:
    nxt = offset + limit
    return str(nxt) if nxt < total else None


# ═════════════════════════════════════════════════════════════════════
# In-memory cache (mirrors data_repair._dry_run_cache TTL).
# ═════════════════════════════════════════════════════════════════════
_DANGLING_CACHE_TTL_S = 60.0
_dangling_cache: Dict[str, Any] = {"expires_at": 0.0, "payload": None}


async def _cached_scan_dangling() -> Dict[str, List[Dict[str, Any]]]:
    now = time.monotonic()
    payload = _dangling_cache.get("payload")
    if payload is not None and now < _dangling_cache["expires_at"]:
        return payload
    fresh = await _scan_dangling_refs()
    _dangling_cache["payload"] = fresh
    _dangling_cache["expires_at"] = now + _DANGLING_CACHE_TTL_S
    return fresh


# ═════════════════════════════════════════════════════════════════════
# 1) Data-integrity drill-down rows
# ═════════════════════════════════════════════════════════════════════
_VALID_INTEGRITY_CLASSES = frozenset({
    "orphaned_customer_refs",
    "orphaned_technician_refs",
    "unassigned_pending_jobs",
})


@router.get("/dashboard/data-integrity/rows")
async def data_integrity_rows(
    issue_class: str = Query(..., alias="class",
                              description="Dangling-ref class"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    if issue_class not in _VALID_INTEGRITY_CLASSES:
        raise HTTPException(400, "invalid_class")

    scan = await _cached_scan_dangling()
    rows_all = scan.get(issue_class) or []
    total = len(rows_all)
    offset = _parse_cursor(cursor)
    limit = _clamp_limit(limit)

    slice_ = rows_all[offset:offset + limit]

    # Enrich with the header context the modal renders read-only.
    cs = {}
    # Best-effort — the tile itself owns the fuller current-state
    # widget; here we just surface counts so the drill-down modal
    # header can print a summary without a second network call.
    cs["counts"] = {
        cls: len(scan.get(cls) or [])
        for cls in _VALID_INTEGRITY_CLASSES
    }

    return {
        "class": issue_class,
        "rows": slice_,
        "total": total,
        "next_cursor": _make_next_cursor(offset, limit, total),
        "header": cs,
    }


# ═════════════════════════════════════════════════════════════════════
# Shared line-item row builder for the two income drill-downs
# ═════════════════════════════════════════════════════════════════════
async def _load_income_category_maps(
    tenant_id: str,
) -> Dict[str, Any]:
    """Same three-map bootstrap used by ``revenue_by_category``:
    pricebook item→category, income_category id→name.
    """
    item_id_to_category: Dict[str, str] = {}
    async for row in db.items.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "category": 1, "service_category_id": 1,
         "name": 1},
    ):
        cat = (row.get("category") or "").strip()
        if cat and row.get("id"):
            item_id_to_category[row["id"]] = cat

    income_cat_by_id: Dict[str, str] = {}
    async for row in db.income_categories.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    ):
        rid = row.get("id")
        name = (row.get("name") or "").strip()
        if rid and name:
            income_cat_by_id[rid] = name

    svc_id_to_name: Dict[str, str] = {}
    async for c in db.service_categories.find(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1, "name": 1},
    ):
        svc_id_to_name[c["id"]] = c["name"]

    item_id_to_service: Dict[str, str] = {}
    async for r in db.items.find(
        {"tenant_id": tenant_id, "service_category_id": {"$ne": None}},
        {"_id": 0, "id": 1, "service_category_id": 1},
    ):
        if r.get("service_category_id"):
            item_id_to_service[r["id"]] = r["service_category_id"]

    return {
        "item_id_to_category": item_id_to_category,
        "income_cat_by_id": income_cat_by_id,
        "svc_id_to_name": svc_id_to_name,
        "item_id_to_service": item_id_to_service,
    }


def _resolve_line_category(
    li: Dict[str, Any],
    item_id_to_category: Dict[str, str],
    income_cat_by_id: Dict[str, str],
) -> str:
    """Mirrors the resolution ladder in revenue_by_category."""
    ic_id = (li.get("income_category_id") or "").strip()
    if ic_id:
        resolved = income_cat_by_id.get(ic_id)
        if resolved:
            return resolved
    inline_cat = (li.get("category") or "").strip()
    if inline_cat:
        if _UUID_RE.match(inline_cat):
            resolved = income_cat_by_id.get(inline_cat)
            if resolved:
                return resolved
            return _UNCATEGORISED
        return inline_cat
    pb_cat = item_id_to_category.get(li.get("item_id") or "")
    return pb_cat or _UNCATEGORISED


async def _paid_invoice_cursor(
    tenant_id: str, s_iso: str, e_iso: str,
):
    """Same filter used by revenue_by_category / income_by_service_category."""
    return db.quotes.find(
        {
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "payment_status": "paid",
            "$and": [
                {"$or": [
                    {"created_at": {"$gte": s_iso, "$lte": e_iso}},
                    {"issue_date": {"$gte": s_iso, "$lte": e_iso}},
                    {"invoice_date": {"$gte": s_iso, "$lte": e_iso}},
                ]},
                {"$or": [
                    {"deleted_at": None},
                    {"deleted_at": {"$exists": False}},
                ]},
            ],
        },
        {"_id": 0, "id": 1, "invoice_number": 1, "customer_id": 1,
         "customer_name": 1, "line_items": 1, "total": 1, "tax": 1,
         "status": 1, "payment_status": 1, "paid_at": 1,
         "payment_method": 1, "job_id": 1, "issue_date": 1,
         "invoice_date": 1, "created_at": 1, "currency": 1},
    )


def _row_for_line_item(
    inv: Dict[str, Any], li: Dict[str, Any], category_display: str,
    service_display: Optional[str],
) -> Dict[str, Any]:
    qty = float(li.get("quantity") or 0)
    unit_price = float(li.get("unit_price") or 0)
    extended = round(qty * unit_price, 2)
    return {
        "invoice_id": inv.get("id"),
        "invoice_number": inv.get("invoice_number") or "",
        "job_id": inv.get("job_id"),
        "customer_id": inv.get("customer_id"),
        "customer_name": inv.get("customer_name") or "",
        "line_item_id": li.get("id"),  # may be None on very old rows
        "line_index": li.get("_index"),  # populated by caller
        "date": (inv.get("issue_date") or inv.get("invoice_date")
                  or inv.get("created_at") or ""),
        "description": li.get("description") or "",
        "category": category_display,
        "service_category": service_display,
        "item_id": li.get("item_id"),
        "quantity": qty,
        "unit_price": unit_price,
        "extended": extended,
        # Locked / computed / status context (read-only in modal):
        "invoice_total": float(inv.get("total") or 0),
        "invoice_tax": float(inv.get("tax") or 0),
        "invoice_status": inv.get("status") or "",
        "payment_status": inv.get("payment_status") or "",
        "paid_at": inv.get("paid_at"),
        "payment_method": inv.get("payment_method"),
    }


# ═════════════════════════════════════════════════════════════════════
# 2) Income by category · drill-down rows
# ═════════════════════════════════════════════════════════════════════
@router.get("/dashboard/income/by-category/rows")
async def income_by_category_rows(
    category: str = Query(..., description="Display label (e.g. 'Cleaning' or 'Uncategorized')"),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    s_iso, e_iso = _parse_range(from_, to)
    tenant_id = tenant["id"]

    maps = await _load_income_category_maps(tenant_id)

    matched: List[Dict[str, Any]] = []
    cur = await _paid_invoice_cursor(tenant_id, s_iso, e_iso)
    async for inv in cur:
        items = inv.get("line_items") or []
        recognised_any = False
        for idx, li in enumerate(items):
            resolved_cat = _resolve_line_category(
                li, maps["item_id_to_category"], maps["income_cat_by_id"],
            )
            if resolved_cat != category:
                continue
            recognised_any = True
            svc_id = maps["item_id_to_service"].get(li.get("item_id") or "")
            svc_name = maps["svc_id_to_name"].get(svc_id) if svc_id else None
            li_copy = {**li, "_index": idx}
            matched.append(_row_for_line_item(inv, li_copy, resolved_cat, svc_name))
        # Priority-6 fallback echo — an invoice with zero recognised
        # lines but positive total collapses to Uncategorized.  Surface
        # it as a synthetic single row so the drill-down math ties
        # back to the tile.
        try:
            inv_total = float(inv.get("total") or 0)
        except (TypeError, ValueError):
            inv_total = 0.0
        if (category == _UNCATEGORISED and inv_total > 0
                and not recognised_any and not items):
            matched.append({
                "invoice_id": inv.get("id"),
                "invoice_number": inv.get("invoice_number") or "",
                "job_id": inv.get("job_id"),
                "customer_id": inv.get("customer_id"),
                "customer_name": inv.get("customer_name") or "",
                "line_item_id": None,
                "line_index": None,
                "date": (inv.get("issue_date") or inv.get("invoice_date")
                          or inv.get("created_at") or ""),
                "description": "(invoice total — no line items)",
                "category": _UNCATEGORISED,
                "service_category": None,
                "item_id": None,
                "quantity": 1,
                "unit_price": round(inv_total, 2),
                "extended": round(inv_total, 2),
                "invoice_total": round(inv_total, 2),
                "invoice_tax": float(inv.get("tax") or 0),
                "invoice_status": inv.get("status") or "",
                "payment_status": inv.get("payment_status") or "",
                "paid_at": inv.get("paid_at"),
                "payment_method": inv.get("payment_method"),
                "synthetic_fallback": True,
            })

    matched.sort(key=lambda r: r["date"] or "", reverse=True)
    total = len(matched)
    offset = _parse_cursor(cursor)
    limit = _clamp_limit(limit)
    slice_ = matched[offset:offset + limit]

    return {
        "category": category,
        "range": {"from": s_iso, "to": e_iso},
        "rows": slice_,
        "total": total,
        "next_cursor": _make_next_cursor(offset, limit, total),
    }


# ═════════════════════════════════════════════════════════════════════
# 3) Income by service (business unit) · drill-down rows
# ═════════════════════════════════════════════════════════════════════
@router.get("/dashboard/income/by-service/rows")
async def income_by_service_rows(
    service_category_id: str = Query(...,
                                        description="service_category_id or literal 'Uncategorized'"),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    s_iso, e_iso = _parse_range(from_, to)
    tenant_id = tenant["id"]

    maps = await _load_income_category_maps(tenant_id)
    target_svc_id: Optional[str] = None
    target_svc_name = "Uncategorized"
    if service_category_id != "Uncategorized":
        # Accept either the raw service_category_id OR its display
        # name.  The RevenueByCategoryTile sibling only surfaces the
        # display label in its legend, so K41 falls back to a
        # name→id resolve when the incoming param isn't a known id.
        if service_category_id in maps["svc_id_to_name"]:
            target_svc_id = service_category_id
            target_svc_name = maps["svc_id_to_name"][service_category_id]
        else:
            name_to_id = {v: k for k, v in maps["svc_id_to_name"].items()}
            resolved_id = name_to_id.get(service_category_id)
            if resolved_id:
                target_svc_id = resolved_id
                target_svc_name = service_category_id
            else:
                # Neither an id nor a known name — treat as an empty
                # bucket instead of a 400 so the modal renders a
                # graceful "no rows" state.
                target_svc_id = service_category_id
                target_svc_name = service_category_id

    matched: List[Dict[str, Any]] = []
    cur = await _paid_invoice_cursor(tenant_id, s_iso, e_iso)
    async for inv in cur:
        items = inv.get("line_items") or []
        recognised_any = False
        for idx, li in enumerate(items):
            iid = li.get("item_id")
            svc_id = maps["item_id_to_service"].get(iid) if iid else None
            svc_name = (maps["svc_id_to_name"].get(svc_id) if svc_id
                        else "Uncategorized")
            if target_svc_id is None:
                # Uncategorized bucket
                if svc_id is not None and svc_name != "Uncategorized":
                    continue
            else:
                if svc_id != target_svc_id:
                    continue
            recognised_any = True
            resolved_cat = _resolve_line_category(
                li, maps["item_id_to_category"], maps["income_cat_by_id"],
            )
            li_copy = {**li, "_index": idx}
            matched.append(_row_for_line_item(inv, li_copy, resolved_cat, svc_name))
        try:
            inv_total = float(inv.get("total") or 0)
        except (TypeError, ValueError):
            inv_total = 0.0
        if (target_svc_id is None and inv_total > 0
                and not recognised_any and not items):
            matched.append({
                "invoice_id": inv.get("id"),
                "invoice_number": inv.get("invoice_number") or "",
                "job_id": inv.get("job_id"),
                "customer_id": inv.get("customer_id"),
                "customer_name": inv.get("customer_name") or "",
                "line_item_id": None,
                "line_index": None,
                "date": (inv.get("issue_date") or inv.get("invoice_date")
                          or inv.get("created_at") or ""),
                "description": "(invoice total — no line items)",
                "category": _UNCATEGORISED,
                "service_category": "Uncategorized",
                "item_id": None,
                "quantity": 1,
                "unit_price": round(inv_total, 2),
                "extended": round(inv_total, 2),
                "invoice_total": round(inv_total, 2),
                "invoice_tax": float(inv.get("tax") or 0),
                "invoice_status": inv.get("status") or "",
                "payment_status": inv.get("payment_status") or "",
                "paid_at": inv.get("paid_at"),
                "payment_method": inv.get("payment_method"),
                "synthetic_fallback": True,
            })

    matched.sort(key=lambda r: r["date"] or "", reverse=True)
    total = len(matched)
    offset = _parse_cursor(cursor)
    limit = _clamp_limit(limit)
    slice_ = matched[offset:offset + limit]

    return {
        "service_category_id": service_category_id,
        "service_category_name": target_svc_name,
        "range": {"from": s_iso, "to": e_iso},
        "rows": slice_,
        "total": total,
        "next_cursor": _make_next_cursor(offset, limit, total),
    }


# ═════════════════════════════════════════════════════════════════════
# 4) Data-integrity resolve (write path)
# ═════════════════════════════════════════════════════════════════════
class DataIntegrityResolveBody(BaseModel):
    ref_class: str = Field(...)
    job_id: str = Field(...)
    action: str = Field(...)  # "assign" | "delete"
    target_id: Optional[str] = None  # required for action="assign"


_INTEGRITY_ACTIONS = frozenset({"assign", "delete"})


async def _emit_drilldown_audit(
    *,
    tile: str, field: str, before: Any, after: Any,
    actor_id: str, tenant_id: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    audit_id = new_id()
    doc = {
        "id": audit_id,
        "event_type": "dashboard_drilldown_edit",
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "timestamp": now_iso(),
        "tile": tile,
        "field": field,
        "before": before,
        "after": after,
    }
    if extra:
        doc.update(extra)
    try:
        await db.audit_events.insert_one(doc)
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("[k41] audit insert failed: %s", exc)
    return audit_id


async def _emit_k6_completion_audit(
    *,
    job: Dict[str, Any], actor: Dict[str, Any],
    changed_field: str, before: Any, after: Any,
) -> None:
    """Mirrors the K6 completed-job audit hook so the customer
    Communication Timeline surfaces this edit exactly the same way
    a Job-detail edit would.  Fires ONLY when the parent job is in
    ``status='completed'`` — this is the K6 window unlock case.
    """
    if (job.get("status") or "").lower() != "completed":
        return
    if not role_bypasses_edit_window(actor.get("role")):
        # The role-gate is asserted upstream (admin_only for K41), but
        # a defence-in-depth check keeps the K6 contract honest.
        raise HTTPException(
            status_code=403, detail="edit_window_role_forbidden",
        )
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "job_edited_after_completion",
            "actor_id": actor.get("id"),
            "tenant_id": job.get("tenant_id"),
            "timestamp": now_iso(),
            "job_id": job.get("id"),
            "changed_field": changed_field,
            "before": before,
            "after": after,
            "source": "dashboard_drilldown",
        })
    except Exception as exc:  # pragma: no cover
        logger.warning("[k41] K6 audit insert failed: %s", exc)


@router.post("/dashboard/data-integrity/resolve")
async def data_integrity_resolve(
    body: DataIntegrityResolveBody = Body(...),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    if body.ref_class not in _VALID_INTEGRITY_CLASSES:
        raise HTTPException(400, "invalid_ref_class")
    if body.action not in _INTEGRITY_ACTIONS:
        raise HTTPException(400, "invalid_action")

    job = await db.jobs.find_one({"id": body.job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "job_not_found")

    actor_id = user.get("id") or user.get("_id") or ""
    now = now_iso()

    if body.ref_class == "orphaned_customer_refs":
        if body.action == "assign":
            if not body.target_id:
                raise HTTPException(400, "target_id_required")
            cust = await db.customers.find_one(
                {"id": body.target_id}, {"_id": 0, "id": 1, "name": 1},
            )
            if not cust:
                raise HTTPException(400, "target_customer_not_found")
            before = job.get("customer_id")
            after = body.target_id
            await db.jobs.update_one(
                {"id": body.job_id},
                {"$set": {"customer_id": after,
                          "customer_name": cust.get("name") or "",
                          "updated_at": now}},
            )
            await _emit_drilldown_audit(
                tile="data-integrity", field="customer_id",
                before=before, after=after,
                actor_id=actor_id, tenant_id=job.get("tenant_id"),
                extra={"job_id": body.job_id, "action": "assign"},
            )
            await _emit_k6_completion_audit(
                job=job, actor=user,
                changed_field="customer_id", before=before, after=after,
            )
            return {"ok": True, "resolved": True,
                    "action": "assign", "target_id": after}
        # delete → soft-delete the job (matches data_repair strategy)
        await db.jobs.update_one(
            {"id": body.job_id},
            {"$set": {"status": "deleted",
                      "deleted_at": now,
                      "deleted_reason": "data_repair_orphaned_customer",
                      "deleted_by_user_id": actor_id,
                      "updated_at": now}},
        )
        await _emit_drilldown_audit(
            tile="data-integrity", field="status",
            before=job.get("status"), after="deleted",
            actor_id=actor_id, tenant_id=job.get("tenant_id"),
            extra={"job_id": body.job_id, "action": "delete"},
        )
        return {"ok": True, "resolved": True, "action": "delete"}

    if body.ref_class == "orphaned_technician_refs":
        if body.action == "assign":
            if not body.target_id:
                raise HTTPException(400, "target_id_required")
            tech = await db.users.find_one(
                {"id": body.target_id}, {"_id": 0, "id": 1, "name": 1,
                                          "email": 1},
            )
            if not tech:
                raise HTTPException(400, "target_technician_not_found")
            before = job.get("technician_id")
            after = body.target_id
            await db.jobs.update_one(
                {"id": body.job_id},
                {"$set": {"technician_id": after,
                          "technician_name": (tech.get("name")
                                               or tech.get("email") or ""),
                          "updated_at": now}},
            )
            await _emit_drilldown_audit(
                tile="data-integrity", field="technician_id",
                before=before, after=after,
                actor_id=actor_id, tenant_id=job.get("tenant_id"),
                extra={"job_id": body.job_id, "action": "assign"},
            )
            await _emit_k6_completion_audit(
                job=job, actor=user,
                changed_field="technician_id", before=before, after=after,
            )
            return {"ok": True, "resolved": True,
                    "action": "assign", "target_id": after}
        # delete → null out technician_id (matches data_repair strategy)
        before = job.get("technician_id")
        await db.jobs.update_one(
            {"id": body.job_id},
            {"$set": {"technician_id": None,
                      "updated_at": now}},
        )
        await _emit_drilldown_audit(
            tile="data-integrity", field="technician_id",
            before=before, after=None,
            actor_id=actor_id, tenant_id=job.get("tenant_id"),
            extra={"job_id": body.job_id, "action": "delete"},
        )
        return {"ok": True, "resolved": True, "action": "delete"}

    # unassigned_pending_jobs — assign a tech.
    if body.action != "assign":
        raise HTTPException(400, "unassigned_jobs_only_support_assign")
    if not body.target_id:
        raise HTTPException(400, "target_id_required")
    tech = await db.users.find_one(
        {"id": body.target_id}, {"_id": 0, "id": 1, "name": 1, "email": 1},
    )
    if not tech:
        raise HTTPException(400, "target_technician_not_found")
    before = job.get("technician_id")
    after = body.target_id
    await db.jobs.update_one(
        {"id": body.job_id},
        {"$set": {"technician_id": after,
                  "technician_name": (tech.get("name")
                                        or tech.get("email") or ""),
                  "updated_at": now}},
    )
    await _emit_drilldown_audit(
        tile="data-integrity", field="technician_id",
        before=before, after=after,
        actor_id=actor_id, tenant_id=job.get("tenant_id"),
        extra={"job_id": body.job_id, "action": "assign"},
    )
    await _emit_k6_completion_audit(
        job=job, actor=user,
        changed_field="technician_id", before=before, after=after,
    )
    return {"ok": True, "resolved": True,
            "action": "assign", "target_id": after}


# ═════════════════════════════════════════════════════════════════════
# 5) Companion audit endpoint for line-item edits
# ═════════════════════════════════════════════════════════════════════
class DrilldownLineItemAuditBody(BaseModel):
    """Called by the modal AFTER a successful ``PATCH /api/quotes/{iid}``
    so the K41 audit event fires + the K6 job-completion hook records
    the change on the parent job.  Idempotent by design — audits are
    write-only and never mutate the invoice/job.
    """
    tile: str = Field(...)  # "income-by-category" | "income-by-service"
    invoice_id: str
    line_index: Optional[int] = None
    field: str
    before: Any = None
    after: Any = None


@router.post("/dashboard/drilldown/line-item-audit")
async def drilldown_line_item_audit(
    body: DrilldownLineItemAuditBody = Body(...),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    if body.tile not in ("income-by-category", "income-by-service"):
        raise HTTPException(400, "invalid_tile")

    inv = await db.quotes.find_one(
        {"id": body.invoice_id, "doc_type": "invoice"},
        {"_id": 0, "id": 1, "tenant_id": 1, "job_id": 1},
    )
    if not inv:
        raise HTTPException(404, "invoice_not_found")

    actor_id = user.get("id") or user.get("_id") or ""
    audit_id = await _emit_drilldown_audit(
        tile=body.tile, field=body.field,
        before=body.before, after=body.after,
        actor_id=actor_id, tenant_id=inv.get("tenant_id"),
        extra={"invoice_id": body.invoice_id,
                "line_index": body.line_index},
    )

    # K6 hook — only fires when the parent job is completed.
    if inv.get("job_id"):
        job = await db.jobs.find_one({"id": inv["job_id"]}, {"_id": 0})
        if job:
            await _emit_k6_completion_audit(
                job=job, actor=user,
                changed_field=f"invoice.line_item.{body.field}",
                before=body.before, after=body.after,
            )

    return {"ok": True, "audit_id": audit_id}


# ═════════════════════════════════════════════════════════════════════
# Introspection surface (used by the modal to list assign-picker
# targets without hitting several unrelated endpoints).
# ═════════════════════════════════════════════════════════════════════
@router.get("/dashboard/drilldown/pickers/customers")
async def drilldown_pickers_customers(
    q: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    filt: Dict[str, Any] = {"tenant_id": tenant["id"],
                             "$or": [
                                 {"deleted_at": None},
                                 {"deleted_at": {"$exists": False}},
                             ]}
    if q:
        filt["name"] = {"$regex": q, "$options": "i"}
    rows: List[Dict[str, Any]] = []
    async for c in db.customers.find(
        filt, {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).limit(limit):
        rows.append(c)
    return {"rows": rows}


@router.get("/dashboard/drilldown/pickers/technicians")
async def drilldown_pickers_technicians(
    q: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    filt: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "role": {"$in": ["tech", "technician", "manager", "admin"]},
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ],
    }
    if q:
        filt["$and"] = [
            {"$or": [
                {"name": {"$regex": q, "$options": "i"}},
                {"email": {"$regex": q, "$options": "i"}},
            ]},
        ]
    rows: List[Dict[str, Any]] = []
    async for u in db.users.find(
        filt, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1},
    ).limit(limit):
        rows.append(u)
    return {"rows": rows}


__all__ = ["router"]
