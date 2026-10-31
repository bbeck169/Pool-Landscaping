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
import uuid
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
from services.reports.service_category_bucketing import (
    UNCATEGORIZED_KEY,
    UNCATEGORIZED_NAME,
    bucket_service_category,
)
from utils import get_current_user, new_id, now_iso

logger = logging.getLogger("dashboard_drilldown")
router = APIRouter()


# ═════════════════════════════════════════════════════════════════════
# Auth — admin + super only (K41 brief).  Explicit function so the
# error string matches the 4-role negative-test expectation exactly.
#
# Feb-2026 · Drilldown role expansion — the three ``/rows`` endpoints
# (data-integrity + income-by-category + income-by-service) also
# admit ``manager`` and ``owner`` callers, matching the finance-read
# expectation across the platform (services/quotes/date_override,
# services/lead_admin_notifications, services/outreach_followups
# already recognise these two roles).  Destructive writes and
# picker fetches stay on the narrower admin/super gate.
# ═════════════════════════════════════════════════════════════════════
_ADMIN_ROLES = {"admin", "super_admin"}
_DRILLDOWN_READ_ROLES = {"admin", "super_admin", "manager", "owner"}


def _require_admin_or_super(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role.lower() not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="admin_only")


def _require_drilldown_read_role(user: Dict[str, Any]) -> None:
    """Feb-2026 · gate for the drill-down ``/rows`` read endpoints.

    Admits ``admin`` / ``super_admin`` / ``manager`` / ``owner``.
    Every other role (technician, dispatcher, customer, empty)
    receives the same 403 + ``admin_only`` detail as the tighter
    :func:`_require_admin_or_super` gate so the frontend's copy
    stays uniform across all drill-down endpoints.
    """
    role = (user or {}).get("role") or ""
    if role.lower() not in _DRILLDOWN_READ_ROLES:
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
# Feb-2026 · P0 fix — cache keyed by ``tenant_id`` so:
#   1. ``_scan_dangling_refs`` (now tenant-scoped after Phase R1)
#      never leaks tenant A's rows into tenant B's response, even
#      when tenant B's warm-cache lookup fires within 60s of A's
#      first miss.
#   2. Existing 60s TTL semantics preserved per bucket.
_dangling_cache: Dict[str, Dict[str, Any]] = {}


async def _cached_scan_dangling(
    tenant_id: str,
) -> Dict[str, List[Dict[str, Any]]]:
    now = time.monotonic()
    bucket = _dangling_cache.get(tenant_id)
    if bucket is not None:
        payload = bucket.get("payload")
        if payload is not None and now < bucket.get("expires_at", 0.0):
            return payload
    fresh = await _scan_dangling_refs(tenant_id)
    _dangling_cache[tenant_id] = {
        "payload": fresh,
        "expires_at": now + _DANGLING_CACHE_TTL_S,
    }
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
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_drilldown_read_role(user)
    if issue_class not in _VALID_INTEGRITY_CLASSES:
        raise HTTPException(400, "invalid_class")

    scan = await _cached_scan_dangling(tenant["id"])
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
         "invoice_date": 1, "created_at": 1, "currency": 1,
         # K48 Round-4 · Feb-2026 — project the invoice-level
         # ``business_unit`` tag written by the drill-down modal so
         # the read path can hydrate the row on modal reopen.
         # Bucket grouping is unchanged (still via line_items
         # income_category_id) — this is a projection-only add.
         # INCOME-DRILLDOWN-EDIT · Feb-2026 — also project the
         # canonical ``business_unit_id`` FK so the drill-down row
         # can carry it to the frontend for direct Select hydration.
         "business_unit": 1,
         "business_unit_id": 1},
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
        # K48 Round-4 · Feb-2026 — invoice-level Business Unit tag
        # (nullable).  ``resolveInitialBuId`` on the frontend prefers
        # this over the legacy income_category_id / category
        # resolution so the Select renders the saved value on
        # modal reopen.
        "business_unit": inv.get("business_unit"),
        # INCOME-DRILLDOWN-EDIT · Feb-2026 — paired-ID hydration
        # sources. The frontend Selects prefer canonical FK ids over
        # name-based fallbacks; project them onto every drill-down
        # row so the dropdowns render the correct value on reopen
        # without a second round-trip. All nullable — legacy rows
        # (pre-paired-ID writes) grandfather to None and fall back
        # to the case-insensitive name match on the frontend.
        "business_unit_id": inv.get("business_unit_id"),
        "income_category_id": li.get("income_category_id"),
        "service_category_id": li.get("service_category_id"),
    }


# ═════════════════════════════════════════════════════════════════════
# 2) Income by category · drill-down rows
# ═════════════════════════════════════════════════════════════════════
@router.get("/dashboard/income/by-category/rows")
async def income_by_category_rows(
    category: str = Query(..., description="Display label (e.g. 'Cleaning' or 'Uncategorized') — legacy name-match path; prefer ``category_key``."),
    category_key: Optional[str] = Query(
        None,
        description=(
            "Feb-2026 · TD-revenue-by-category-id-grouping — stable "
            "bucket identity emitted by the Revenue by Category tile. "
            "One of ``id:<uuid>``, ``name:<lower>``, ``pb:<lower>``, "
            "or ``uncategorized``.  Preferred over ``category`` for "
            "all new callers; eliminates the name-string collision "
            "that caused Hardscaping clicks to return Irrigation rows."
        ),
    ),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_drilldown_read_role(user)
    s_iso, e_iso = _parse_range(from_, to)
    tenant_id = tenant["id"]

    maps = await _load_income_category_maps(tenant_id)
    # Feb-2026 · TD-revenue-by-category-id-grouping — when a stable
    # bucket key is supplied, filter by it (eliminating the name-
    # match collision class).  Back-compat: without ``category_key``,
    # resolve each line via the identity helper and match by display
    # name against the legacy ``category`` param so pre-ticket
    # callers continue to work.
    from routers.dashboard_revenue import (
        _resolve_line_category_identity,
    )

    matched: List[Dict[str, Any]] = []
    cur = await _paid_invoice_cursor(tenant_id, s_iso, e_iso)
    async for inv in cur:
        items = inv.get("line_items") or []
        recognised_any = False
        for idx, li in enumerate(items):
            bucket_key, resolved_cat, _orphan = \
                _resolve_line_category_identity(
                    li, maps["item_id_to_category"],
                    maps["income_cat_by_id"],
                )
            if category_key is not None:
                if bucket_key != category_key:
                    continue
            else:
                if resolved_cat != category:
                    continue
            recognised_any = True
            # P53 tail (Feb-2026) — service-category display uses the
            # same PRECEDENCE as income_by_service_category:
            # line.service_category_id first, pricebook fallback second.
            # This row is for the income-category drilldown so bucket
            # selection is by the identity helper above; only the
            # displayed ``svc_name`` benefits from this fix.
            line_svc_id = li.get("service_category_id")
            if line_svc_id:
                svc_id = line_svc_id
            else:
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
        is_uncat_bucket = (
            (category_key == "uncategorized") if category_key is not None
            else (category == _UNCATEGORISED)
        )
        if (is_uncat_bucket and inv_total > 0
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
                # K48 Round-4 · Feb-2026 — surface BU on the
                # synthetic fallback too so a re-classified totals-
                # only echo still hydrates the Select on reopen.
                "business_unit": inv.get("business_unit"),
                # INCOME-DRILLDOWN-EDIT · Feb-2026 — paired-ID
                # hydration parity for the synthetic fallback row.
                # No line item exists here, so both line-scoped ids
                # are None; the invoice-level id still projects.
                "business_unit_id": inv.get("business_unit_id"),
                "income_category_id": None,
                "service_category_id": None,
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
    _require_drilldown_read_role(user)
    s_iso, e_iso = _parse_range(from_, to)
    tenant_id = tenant["id"]

    maps = await _load_income_category_maps(tenant_id)
    # Feb-2026 · Drill-down parity fix — route the target-bucket
    # resolution through the same ladder ``bucket_service_category``
    # uses on the chart tile.  The incoming ``service_category_id``
    # query param can be:
    #   1. The literal ``"Uncategorized"``  → target bucket_id
    #      collapses to ``UNCATEGORIZED_KEY``.
    #   2. A real ``service_category_id`` (UUID) known to
    #      ``svc_id_to_name``  → target bucket_id is that id.
    #   3. A display *name* that resolves to a known id  → target
    #      bucket_id is the resolved id (legacy caller contract).
    #   4. Anything else  → target bucket_id stays the incoming
    #      literal (returns 0 rows since ``bucket_service_category``
    #      only ever emits real ids or ``UNCATEGORIZED_KEY``).
    if service_category_id == "Uncategorized":
        target_bucket_id: str = UNCATEGORIZED_KEY
        target_svc_name = UNCATEGORIZED_NAME
    elif service_category_id in maps["svc_id_to_name"]:
        target_bucket_id = service_category_id
        target_svc_name = maps["svc_id_to_name"][service_category_id]
    else:
        name_to_id = {v: k for k, v in maps["svc_id_to_name"].items()}
        resolved_id = name_to_id.get(service_category_id)
        if resolved_id:
            target_bucket_id = resolved_id
            target_svc_name = service_category_id
        else:
            # Neither an id nor a known name — surface an empty
            # bucket rather than a 400.  bucket_service_category
            # will never return this string, so the loop matches
            # zero lines.
            target_bucket_id = service_category_id
            target_svc_name = service_category_id

    matched: List[Dict[str, Any]] = []
    cur = await _paid_invoice_cursor(tenant_id, s_iso, e_iso)
    async for inv in cur:
        items = inv.get("line_items") or []
        recognised_any = False
        for idx, li in enumerate(items):
            # Feb-2026 · Drill-down parity — canonical bucketing via
            # ``services.reports.service_category_bucketing`` so
            # lines whose ``service_category_id`` points at a
            # hard-deleted / stale category (no name in
            # ``svc_id_to_name``) roll up to ``UNCATEGORIZED_KEY``
            # on both the chart AND the drill-down.  Pre-fix the
            # drill-down explicitly skipped stale-ref lines while
            # the chart bucketed them under Uncategorized — parity
            # was broken.
            bucket_id, svc_name = bucket_service_category(
                li, maps["item_id_to_service"], maps["svc_id_to_name"],
            )
            if bucket_id != target_bucket_id:
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
        if (target_bucket_id == UNCATEGORIZED_KEY and inv_total > 0
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
                # K48 Round-4 · Feb-2026 — surface BU on the
                # synthetic fallback too so a re-classified totals-
                # only echo still hydrates the Select on reopen.
                "business_unit": inv.get("business_unit"),
                # INCOME-DRILLDOWN-EDIT · Feb-2026 — paired-ID
                # hydration parity for the synthetic fallback row.
                # No line item exists here, so both line-scoped ids
                # are None; the invoice-level id still projects.
                "business_unit_id": inv.get("business_unit_id"),
                "income_category_id": None,
                "service_category_id": None,
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
    action: str = Field(...)  # "assign" | "delete" (soft) | "hard_delete"
    target_id: Optional[str] = None  # required for action="assign"


# Feb-2026 · Data-Integrity hard-delete upgrade.  ``hard_delete``
# joins the soft ``delete`` (which sets status='deleted' + retains the
# row) with a NEW irreversible ``db.jobs.delete_one`` /
# ``db.jobs.delete_many`` path.  Only supported for
# ``orphaned_customer_refs`` per the phase scope; other ref_classes
# receive a 400 (see recon surprise S2).
_INTEGRITY_ACTIONS = frozenset({"assign", "delete", "hard_delete"})
_HARD_DELETE_SUPPORTED_CLASSES = frozenset({"orphaned_customer_refs"})


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


async def _apply_resolve_item(
    *,
    ref_class: str,
    job_id: str,
    action: str,
    target_id: Optional[str],
    user: Dict[str, Any],
    tenant_id: Optional[str] = None,
    bulk_batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Core resolve logic — shared by single-row + bulk endpoints.

    Raises HTTPException on validation / lookup errors so callers get
    the identical error contract as the single-row endpoint.  When
    ``bulk_batch_id`` is provided it is stamped onto every emitted
    ``dashboard_drilldown_edit`` audit event (K41b contract).

    ``tenant_id`` is used ONLY by the ``hard_delete`` branch to filter
    the ``db.jobs.find_one`` + ``db.jobs.delete_one`` queries per the
    Feb-2026 hard-delete phase (recon surprise S1, ruling R1=C).  The
    existing soft-delete + assign branches keep their pre-change
    behavior (tenant filter NOT enforced on find/update) so this
    commit stays scoped to hard-delete.  See
    ``memory/FOLLOWUP_DASHBOARD_DRILLDOWN_TENANT_ISOLATION.md`` for
    the backfill P2 followup.
    """
    if ref_class not in _VALID_INTEGRITY_CLASSES:
        raise HTTPException(400, "invalid_ref_class")
    if action not in _INTEGRITY_ACTIONS:
        raise HTTPException(400, "invalid_action")

    # Hard-delete gate — restricted to orphaned_customer_refs per S2.
    if action == "hard_delete" and ref_class not in _HARD_DELETE_SUPPORTED_CLASSES:
        raise HTTPException(
            400, "hard_delete_only_supports_orphaned_customer_refs",
        )

    # ── HARD-DELETE branch (irreversible) ────────────────────────
    # Tenant-scoped find + delete so cross-tenant job_ids submitted
    # directly to the endpoint cannot leak past the caller's tenant.
    if action == "hard_delete":
        find_filter: Dict[str, Any] = {"id": job_id}
        if tenant_id:
            find_filter["tenant_id"] = tenant_id
        job = await db.jobs.find_one(
            find_filter, {"_id": 0, "photos.data": 0},
        )
        if not job:
            raise HTTPException(404, "job_not_found")
        actor_id = user.get("id") or user.get("_id") or ""
        # Capture pre-mutation state BEFORE delete so audit `before`
        # preserves the row shape even after the row is gone.
        before_status = job.get("status")
        row_tenant_id = job.get("tenant_id")
        del_filter: Dict[str, Any] = {"id": job_id}
        if tenant_id:
            del_filter["tenant_id"] = tenant_id
        del_result = await db.jobs.delete_one(del_filter)
        deleted_count = int(getattr(del_result, "deleted_count", 0) or 0)

        # Feb-2026 · RECURRING-JOBS SAFETY NET (Cause C) — if this
        # orphan hard-delete removed a job tied to a recurring
        # template, rewind the parent's last_generated_through so
        # the next cron run re-materializes the hole. ``job`` is
        # the pre-fetched doc with photos.data stripped; it carries
        # recurring_template_id + scheduled_date. Fail-soft.
        if deleted_count and job.get("recurring_template_id"):
            try:
                from services.recurring_jobs_backfill import (
                    rewind_template_cursor_on_job_delete,
                )
                await rewind_template_cursor_on_job_delete(
                    job=job, tenant_id=row_tenant_id or tenant_id or "",
                    actor_user_id=actor_id,
                    source="orphan_single_hard_delete",
                )
            except Exception as _rw_exc:                        # noqa: BLE001
                logger.warning(
                    "recurring_job.cursor_rewind.failed "
                    "tenant=%s deleted_job=%s error=%s:%s",
                    row_tenant_id or tenant_id, job_id,
                    type(_rw_exc).__name__, _rw_exc,
                )

        def _extra_hd(**kw: Any) -> Dict[str, Any]:
            base: Dict[str, Any] = {"job_id": job_id, **kw}
            if bulk_batch_id:
                base["bulk_batch_id"] = bulk_batch_id
            return base

        # Emit audit with field="status", after="hard_deleted" so:
        #   * the row is discoverable via the existing K41 audit
        #     index (same event_type + tile + field key),
        #   * the K41c undo path's soft-delete matcher
        #     (``field == "status" and after == "deleted"``) does
        #     NOT match — undo cannot restore a hard-deleted row and
        #     already returns "job_not_found" per row (see line 1019
        #     comment).  Distinguishing after="hard_deleted" is a
        #     defence-in-depth signal for future audit consumers.
        await _emit_drilldown_audit(
            tile="data-integrity", field="status",
            before=before_status, after="hard_deleted",
            actor_id=actor_id, tenant_id=row_tenant_id,
            extra=_extra_hd(action="hard_delete"),
        )
        return {
            "ok": True, "resolved": True,
            "action": "hard_delete", "job_id": job_id,
            "deleted_count": deleted_count,
        }

    # ── SOFT-DELETE + ASSIGN branches (unchanged) ────────────────
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "job_not_found")

    actor_id = user.get("id") or user.get("_id") or ""
    now = now_iso()

    def _extra(**kw: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {"job_id": job_id, **kw}
        if bulk_batch_id:
            base["bulk_batch_id"] = bulk_batch_id
        return base

    if ref_class == "orphaned_customer_refs":
        if action == "assign":
            if not target_id:
                raise HTTPException(400, "target_id_required")
            cust = await db.customers.find_one(
                {"id": target_id}, {"_id": 0, "id": 1, "name": 1},
            )
            if not cust:
                raise HTTPException(400, "target_customer_not_found")
            before = job.get("customer_id")
            after = target_id
            await db.jobs.update_one(
                {"id": job_id},
                {"$set": {"customer_id": after,
                          "customer_name": cust.get("name") or "",
                          "updated_at": now}},
            )
            await _emit_drilldown_audit(
                tile="data-integrity", field="customer_id",
                before=before, after=after,
                actor_id=actor_id, tenant_id=job.get("tenant_id"),
                extra=_extra(action="assign"),
            )
            await _emit_k6_completion_audit(
                job=job, actor=user,
                changed_field="customer_id", before=before, after=after,
            )
            return {"ok": True, "resolved": True,
                    "action": "assign", "target_id": after,
                    "job_id": job_id}
        # delete → soft-delete the job (matches data_repair strategy)
        await db.jobs.update_one(
            {"id": job_id},
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
            extra=_extra(action="delete"),
        )
        return {"ok": True, "resolved": True, "action": "delete",
                "job_id": job_id}

    if ref_class == "orphaned_technician_refs":
        if action == "assign":
            if not target_id:
                raise HTTPException(400, "target_id_required")
            tech = await db.users.find_one(
                {"id": target_id}, {"_id": 0, "id": 1, "name": 1,
                                     "email": 1},
            )
            if not tech:
                raise HTTPException(400, "target_technician_not_found")
            before = job.get("technician_id")
            after = target_id
            await db.jobs.update_one(
                {"id": job_id},
                {"$set": {"technician_id": after,
                          "technician_name": (tech.get("name")
                                               or tech.get("email") or ""),
                          "updated_at": now}},
            )
            await _emit_drilldown_audit(
                tile="data-integrity", field="technician_id",
                before=before, after=after,
                actor_id=actor_id, tenant_id=job.get("tenant_id"),
                extra=_extra(action="assign"),
            )
            await _emit_k6_completion_audit(
                job=job, actor=user,
                changed_field="technician_id", before=before, after=after,
            )
            return {"ok": True, "resolved": True,
                    "action": "assign", "target_id": after,
                    "job_id": job_id}
        # delete → null out technician_id (matches data_repair strategy)
        before = job.get("technician_id")
        await db.jobs.update_one(
            {"id": job_id},
            {"$set": {"technician_id": None, "updated_at": now}},
        )
        await _emit_drilldown_audit(
            tile="data-integrity", field="technician_id",
            before=before, after=None,
            actor_id=actor_id, tenant_id=job.get("tenant_id"),
            extra=_extra(action="delete"),
        )
        return {"ok": True, "resolved": True, "action": "delete",
                "job_id": job_id}

    # unassigned_pending_jobs — assign a tech.
    if action != "assign":
        raise HTTPException(400, "unassigned_jobs_only_support_assign")
    if not target_id:
        raise HTTPException(400, "target_id_required")
    tech = await db.users.find_one(
        {"id": target_id}, {"_id": 0, "id": 1, "name": 1, "email": 1},
    )
    if not tech:
        raise HTTPException(400, "target_technician_not_found")
    before = job.get("technician_id")
    after = target_id
    await db.jobs.update_one(
        {"id": job_id},
        {"$set": {"technician_id": after,
                  "technician_name": (tech.get("name")
                                        or tech.get("email") or ""),
                  "updated_at": now}},
    )
    await _emit_drilldown_audit(
        tile="data-integrity", field="technician_id",
        before=before, after=after,
        actor_id=actor_id, tenant_id=job.get("tenant_id"),
        extra=_extra(action="assign"),
    )
    await _emit_k6_completion_audit(
        job=job, actor=user,
        changed_field="technician_id", before=before, after=after,
    )
    return {"ok": True, "resolved": True,
            "action": "assign", "target_id": after,
            "job_id": job_id}


@router.post("/dashboard/data-integrity/resolve")
async def data_integrity_resolve(
    body: DataIntegrityResolveBody = Body(...),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)
    return await _apply_resolve_item(
        ref_class=body.ref_class,
        job_id=body.job_id,
        action=body.action,
        target_id=body.target_id,
        user=user,
        tenant_id=tenant.get("id") if tenant else None,
    )


# ═════════════════════════════════════════════════════════════════════
# 4b) K41b — Bulk resolve.  Per-row audits share a bulk_batch_id UUID.
# ═════════════════════════════════════════════════════════════════════
_BULK_CAP = 100
_BULK_IDEMPOTENCY_TTL_S = 60.0
# Maps bulk_batch_id -> (expires_monotonic, cached_response_dict)
_bulk_idempotency_cache: Dict[str, Any] = {}


def _uuid_v4() -> str:
    return str(uuid.uuid4())


def _prune_idempotency_cache() -> None:
    now = time.monotonic()
    stale = [k for k, (exp, _p) in _bulk_idempotency_cache.items()
             if exp <= now]
    for k in stale:
        _bulk_idempotency_cache.pop(k, None)


class DataIntegrityResolveBulkItem(BaseModel):
    ref_class: str = Field(...)
    job_id: str = Field(...)
    action: str = Field(...)
    target_id: Optional[str] = None


class DataIntegrityResolveBulkBody(BaseModel):
    items: List[DataIntegrityResolveBulkItem] = Field(...)
    bulk_batch_id: Optional[str] = None


@router.post("/dashboard/data-integrity/resolve-bulk")
async def data_integrity_resolve_bulk(
    body: DataIntegrityResolveBulkBody = Body(...),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """K41b bulk resolve endpoint.

    Runs the single-row resolve logic per item, tagging every emitted
    ``dashboard_drilldown_edit`` audit event with the shared
    ``bulk_batch_id``.  Never rolls back — partial success is expected
    and surfaced via the ``results`` array.

    Batch cap: 100.  Idempotency: replay identical response for the
    same ``bulk_batch_id`` within 60s.

    Feb-2026 hard-delete fast-path (recon ruling R2=B): when every
    item has ``action="hard_delete"`` + ``ref_class="orphaned_customer_refs"``,
    short-circuit to a SINGLE tenant-scoped ``db.jobs.delete_many``
    instead of iterating per-item.  Emits N audit events after the
    delete completes.  Mixed bulks (any non-hard-delete item present)
    fall back to the per-item loop path — unchanged.
    """
    _require_admin_or_super(user)

    if not body.items:
        raise HTTPException(400, "items_required")
    if len(body.items) > _BULK_CAP:
        raise HTTPException(
            400, f"batch_cap_exceeded_max_{_BULK_CAP}",
        )

    _prune_idempotency_cache()

    batch_id = (body.bulk_batch_id or "").strip() or _uuid_v4()
    tenant_id = tenant.get("id") if tenant else None

    cached = _bulk_idempotency_cache.get(batch_id)
    if cached is not None:
        # Replay — client submitted the same batch again within TTL.
        _, payload = cached
        return {**payload, "replayed": True}

    # ── HARD-DELETE fast-path (single delete_many + N audits) ────
    # Detect when the whole batch is a homogeneous hard-delete on the
    # only ref_class that supports it.  Any deviation → fall back to
    # the per-item path so mixed batches keep working.
    all_hard_delete = (
        len(body.items) > 0
        and all(i.action == "hard_delete" for i in body.items)
        and all(
            i.ref_class == "orphaned_customer_refs" for i in body.items
        )
    )
    if all_hard_delete:
        job_ids = [i.job_id for i in body.items]
        # Capture pre-mutation state — needed for per-row audit
        # ``before`` field and to distinguish 404 vs deleted in the
        # results array.
        find_filter: Dict[str, Any] = {"id": {"$in": job_ids}}
        if tenant_id:
            find_filter["tenant_id"] = tenant_id
        pre_docs: List[Dict[str, Any]] = []
        async for j in db.jobs.find(
            find_filter,
            # Feb-2026 · RECURRING-JOBS SAFETY NET (Cause C) —
            # projection expanded to carry recurring_template_id +
            # scheduled_date so the per-row cursor-rewind helper
            # has what it needs after the delete_many persists.
            {"_id": 0, "id": 1, "tenant_id": 1, "status": 1,
             "recurring_template_id": 1, "scheduled_date": 1},
        ):
            pre_docs.append(j)
        found_ids = {j.get("id") for j in pre_docs}
        # Single delete_many — tenant-scoped.
        del_filter: Dict[str, Any] = {"id": {"$in": job_ids}}
        if tenant_id:
            del_filter["tenant_id"] = tenant_id
        del_result = await db.jobs.delete_many(del_filter)
        deleted_count = int(
            getattr(del_result, "deleted_count", 0) or 0,
        )
        actor_id = user.get("id") or user.get("_id") or ""
        # Feb-2026 · RECURRING-JOBS SAFETY NET (Cause C) — for every
        # pre-fetched doc that was tied to a recurring template,
        # rewind the parent template's cursor so the next cron run
        # re-materializes the hole. Looped per-row to keep failures
        # isolated. Fail-soft — bulk delete already succeeded.
        for _j in pre_docs:
            if not _j.get("recurring_template_id"):
                continue
            try:
                from services.recurring_jobs_backfill import (
                    rewind_template_cursor_on_job_delete,
                )
                await rewind_template_cursor_on_job_delete(
                    job=_j, tenant_id=_j.get("tenant_id") or "",
                    actor_user_id=actor_id,
                    source="orphan_bulk_hard_delete",
                )
            except Exception as _rw_exc:                        # noqa: BLE001
                logger.warning(
                    "recurring_job.cursor_rewind.failed "
                    "tenant=%s deleted_job=%s error=%s:%s",
                    _j.get("tenant_id"), _j.get("id"),
                    type(_rw_exc).__name__, _rw_exc,
                )
        # Emit one audit per pre-fetched doc — per-row observability
        # preserved even though the underlying op was a single call.
        for j in pre_docs:
            await _emit_drilldown_audit(
                tile="data-integrity", field="status",
                before=j.get("status"), after="hard_deleted",
                actor_id=actor_id, tenant_id=j.get("tenant_id"),
                extra={
                    "job_id": j.get("id"),
                    "bulk_batch_id": batch_id,
                    "action": "hard_delete",
                },
            )
        # Build per-item results array matching the shape of the
        # per-item path so the frontend consumer doesn't care which
        # branch ran.
        results: List[Dict[str, Any]] = []
        for i in body.items:
            if i.job_id in found_ids:
                results.append({
                    "job_id": i.job_id, "ok": True,
                    "action": "hard_delete", "target_id": None,
                })
            else:
                # Job wasn't visible under the caller's tenant — could
                # be cross-tenant, already-deleted, or a stale scan
                # result.  Return same 404 shape as the per-item path.
                results.append({
                    "job_id": i.job_id, "ok": False,
                    "error": "job_not_found",
                    "status_code": 404,
                })
        succeeded = sum(1 for r in results if r["ok"])
        failed = sum(1 for r in results if not r["ok"])
        payload = {
            "ok": failed == 0,
            "bulk_batch_id": batch_id,
            "total": len(body.items),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
            "deleted_count": deleted_count,
            "fast_path": "hard_delete_many",
        }
        _bulk_idempotency_cache[batch_id] = (
            time.monotonic() + _BULK_IDEMPOTENCY_TTL_S,
            payload,
        )
        return payload

    # ── Per-item loop path (unchanged for soft-delete + assigns) ─
    results = []
    succeeded = 0
    failed = 0

    for item in body.items:
        try:
            r = await _apply_resolve_item(
                ref_class=item.ref_class,
                job_id=item.job_id,
                action=item.action,
                target_id=item.target_id,
                user=user,
                tenant_id=tenant_id,
                bulk_batch_id=batch_id,
            )
            results.append({
                "job_id": item.job_id,
                "ok": True,
                "action": r.get("action"),
                "target_id": r.get("target_id"),
            })
            succeeded += 1
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            results.append({
                "job_id": item.job_id,
                "ok": False,
                "error": detail,
                "status_code": e.status_code,
            })
            failed += 1
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "[k41b] resolve-bulk unexpected error for %s: %s",
                item.job_id, exc,
            )
            results.append({
                "job_id": item.job_id,
                "ok": False,
                "error": "internal_error",
                "status_code": 500,
            })
            failed += 1

    payload = {
        "ok": failed == 0,
        "bulk_batch_id": batch_id,
        "total": len(body.items),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
    _bulk_idempotency_cache[batch_id] = (
        time.monotonic() + _BULK_IDEMPOTENCY_TTL_S,
        payload,
    )
    return payload


# ═════════════════════════════════════════════════════════════════════
# 4c) K41c — Undo last bulk (10-minute window).  Reverses every
# ``dashboard_drilldown_edit`` audit row keyed by ``bulk_batch_id``.
# ═════════════════════════════════════════════════════════════════════
_UNDO_WINDOW_SECONDS = 600  # 10 minutes
_UNDO_IDEMPOTENCY_TTL_S = 60.0
# Separate cache to avoid conflating undo replays with resolve replays.
_bulk_undo_idempotency_cache: Dict[str, Any] = {}


def _prune_undo_cache() -> None:
    now = time.monotonic()
    stale = [k for k, (exp, _p) in _bulk_undo_idempotency_cache.items()
             if exp <= now]
    for k in stale:
        _bulk_undo_idempotency_cache.pop(k, None)


def _parse_iso(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


class DataIntegrityUndoBulkBody(BaseModel):
    bulk_batch_id: str = Field(...)


async def _revert_single_audit_row(
    audit_row: Dict[str, Any],
    *,
    actor_id: str,
    undo_batch_id: str,
) -> Dict[str, Any]:
    """Reverse the mutation described by a single dashboard_drilldown_edit
    audit row.  Emits a companion ``dashboard_drilldown_bulk_undone``
    audit event linking back to the source batch.
    """
    job_id = audit_row.get("job_id")
    field = audit_row.get("field")
    before = audit_row.get("before")
    after = audit_row.get("after")
    action = audit_row.get("action")
    tenant_id = audit_row.get("tenant_id")

    if not job_id:
        return {"job_id": None, "ok": False, "error": "audit_missing_job_id"}

    job = await db.jobs.find_one({"id": job_id}, {"_id": 0, "photos.data": 0})
    if not job:
        # Hard-deleted after soft-delete — cannot restore.
        return {"job_id": job_id, "ok": False, "error": "job_not_found"}

    now = now_iso()
    set_doc: Dict[str, Any] = {"updated_at": now}
    unset_doc: Dict[str, Any] = {}

    if field == "status" and after == "deleted":
        # Undo soft-delete → restore prior status + clear delete markers.
        set_doc["status"] = before if before is not None else "scheduled"
        unset_doc["deleted_at"] = ""
        unset_doc["deleted_reason"] = ""
        unset_doc["deleted_by_user_id"] = ""
    elif field == "customer_id":
        set_doc["customer_id"] = before
        # Best-effort denorm restoration.
        if before:
            cust = await db.customers.find_one(
                {"id": before}, {"_id": 0, "name": 1},
            )
            set_doc["customer_name"] = (cust or {}).get("name") or ""
        else:
            set_doc["customer_name"] = ""
    elif field == "technician_id":
        set_doc["technician_id"] = before
        if before:
            tech = await db.users.find_one(
                {"id": before}, {"_id": 0, "name": 1, "email": 1},
            )
            set_doc["technician_name"] = (
                (tech or {}).get("name") or (tech or {}).get("email") or ""
            )
        else:
            set_doc["technician_name"] = ""
    else:
        return {"job_id": job_id, "ok": False,
                "error": f"unsupported_undo_field:{field}"}

    update_doc: Dict[str, Any] = {"$set": set_doc}
    if unset_doc:
        update_doc["$unset"] = unset_doc
    await db.jobs.update_one({"id": job_id}, update_doc)

    # Emit companion audit — one per row — pointing back to the source
    # batch via ``undone_from_batch_id``.
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "dashboard_drilldown_bulk_undone",
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "timestamp": now,
            "tile": "data-integrity",
            "job_id": job_id,
            "field": field,
            "restored_before": before,
            "reverted_after": after,
            "original_action": action,
            "undone_from_batch_id": audit_row.get("bulk_batch_id"),
            "undo_batch_id": undo_batch_id,
            "source": "dashboard_drilldown_undo",
        })
    except Exception as exc:  # pragma: no cover
        logger.warning("[k41c] undo audit insert failed: %s", exc)

    return {"job_id": job_id, "ok": True, "field": field,
            "restored_to": before}


@router.post("/dashboard/data-integrity/undo-bulk")
async def data_integrity_undo_bulk(
    body: DataIntegrityUndoBulkBody = Body(...),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """K41c undo endpoint.

    Reverses every ``dashboard_drilldown_edit`` audit row emitted for
    the given ``bulk_batch_id``, provided:

      * the newest row is within the 10-minute window,
      * the batch has not already been undone.

    Emits a ``dashboard_drilldown_bulk_undone`` audit event per row.
    Idempotent within a 60s TTL — replaying the same undo returns the
    identical response without re-mutating.
    """
    _require_admin_or_super(user)
    bulk_batch_id = (body.bulk_batch_id or "").strip()
    if not bulk_batch_id:
        raise HTTPException(400, "bulk_batch_id_required")

    _prune_undo_cache()
    cached = _bulk_undo_idempotency_cache.get(bulk_batch_id)
    if cached is not None:
        _, payload = cached
        return {**payload, "replayed": True}

    # Find the audit rows for this batch.
    audit_rows: List[Dict[str, Any]] = []
    async for a in db.audit_events.find(
        {"event_type": "dashboard_drilldown_edit",
         "bulk_batch_id": bulk_batch_id},
        {"_id": 0},
    ):
        audit_rows.append(a)

    if not audit_rows:
        raise HTTPException(404, "batch_not_found")

    # Already-undone check — any companion event for this batch.
    prior_undo = await db.audit_events.find_one(
        {"event_type": "dashboard_drilldown_bulk_undone",
         "undone_from_batch_id": bulk_batch_id},
        {"_id": 0, "id": 1},
    )
    if prior_undo is not None:
        raise HTTPException(409, "already_undone")

    # Age check — newest audit row must be within the 10-minute window.
    newest_ts: Optional[datetime] = None
    for a in audit_rows:
        parsed = _parse_iso(a.get("timestamp"))
        if parsed is not None and (newest_ts is None or parsed > newest_ts):
            newest_ts = parsed
    if newest_ts is None:
        raise HTTPException(500, "batch_timestamps_unreadable")
    now_utc = datetime.now(timezone.utc)
    age_s = (now_utc - newest_ts).total_seconds()
    if age_s > _UNDO_WINDOW_SECONDS:
        raise HTTPException(410, "window_expired")

    actor_id = user.get("id") or user.get("_id") or ""
    undo_batch_id = _uuid_v4()
    restored: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for a in audit_rows:
        try:
            r = await _revert_single_audit_row(
                a, actor_id=actor_id, undo_batch_id=undo_batch_id,
            )
            if r.get("ok"):
                restored.append(r)
            else:
                failed.append(r)
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "[k41c] undo unexpected error for %s: %s",
                a.get("job_id"), exc,
            )
            failed.append({
                "job_id": a.get("job_id"), "ok": False,
                "error": "internal_error",
            })

    payload = {
        "ok": len(failed) == 0,
        "bulk_batch_id": bulk_batch_id,
        "undo_batch_id": undo_batch_id,
        "total": len(audit_rows),
        "restored": restored,
        "failed": failed,
    }
    _bulk_undo_idempotency_cache[bulk_batch_id] = (
        time.monotonic() + _UNDO_IDEMPOTENCY_TTL_S,
        payload,
    )
    return payload



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
        job = await db.jobs.find_one({"id": inv["job_id"]}, {"_id": 0, "photos.data": 0})
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
