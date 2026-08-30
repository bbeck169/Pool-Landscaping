"""Income category enforcement · Feb-2026.

Endpoints:
  • GET    /api/income-categories             — list (admin)
  • POST   /api/income-categories             — create (admin)
  • PATCH  /api/income-categories/{id}        — edit (admin)
  • POST   /api/income-categories/{id}/archive
  • POST   /api/income-categories/{id}/restore
  • GET    /api/reports/uncategorized-count   — banner data (admin)
  • GET    /api/reports/uncategorized-items   — list (admin, range-filtered)
  • POST   /api/reports/uncategorized-items/{invoice_id}/{line_item_index}/assign
                                                — inline single-row assign
  • POST   /api/reports/uncategorized-items/bulk-assign
                                                — bulk assign N rows to one category

Grandfather rule: existing invoice line items with a null/empty
``category`` remain readable, but any NEW create or any EDIT that
touches a line item MUST supply a valid category id or name.

Enforcement is exposed as a helper (``validate_line_item_categories``)
that quotes.py and invoice_edit.py call.  It resolves either category
NAMES (backwards compatible — the existing line items use names like
``"Pool"``, ``"Chem"``) OR ids to an active row, and rejects any line
that has neither.
"""
from __future__ import annotations

import colorsys
import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()

_DEFAULTS = [
    "Pool", "Chemicals", "Landscaping", "Repair", "Late Fee", "Other",
]


def _require_admin(user: dict) -> None:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _auto_color(name: str) -> str:
    h = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)  # non-security: stable name→color slot
    hue = (h % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
    return "#" + "".join(f"{int(round(x * 255)):02x}" for x in (r, g, b))


# ═══════════════════════════════════════════════════════════════════
# Seed on first access
# ═══════════════════════════════════════════════════════════════════
async def ensure_defaults_for_tenant(tenant_id: str) -> None:
    """Idempotent — seeds the 6 default categories only if none exist."""
    if not tenant_id:
        return
    existing = await db.income_categories.count_documents({"tenant_id": tenant_id})
    if existing > 0:
        return
    now = _now()
    docs = [
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": "",
            "color": _auto_color(name),
            "is_archived": False,
            "sort_order": i,
            "tenant_id": tenant_id,
            "created_at": now,
            "created_by_user_id": "system:seed",
            "updated_at": now,
        }
        for i, name in enumerate(_DEFAULTS)
    ]
    await db.income_categories.insert_many(docs)
    logger.info("[income_categories] seeded %d defaults for tenant=%s",
                len(docs), tenant_id)


# ═══════════════════════════════════════════════════════════════════
# Category enforcement helper — called by quotes.py + invoice_edit.py
# ═══════════════════════════════════════════════════════════════════
async def validate_line_item_categories(
    tenant_id: str, line_items: List[Dict[str, Any]],
) -> None:
    """Reject if ANY line item is missing a category or references an
    inactive/foreign one.  Called from create + edit paths.

    Accepts EITHER a category **id** (uuid) OR a category **name**
    (string that matches ``income_categories.name`` case-insensitively).
    """
    await ensure_defaults_for_tenant(tenant_id)
    active = await db.income_categories.find(
        {"tenant_id": tenant_id, "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    valid_ids = {c["id"] for c in active}
    valid_names = {(c["name"] or "").strip().lower() for c in active}
    available = [c["name"] for c in active]

    for idx, li in enumerate(line_items or []):
        cat = (li.get("category") or "").strip() if isinstance(
            li.get("category"), str) else li.get("category")
        if not cat:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "category_required",
                    "error_code": "category_required",
                    "field": f"line_items[{idx}].category",
                    "line_index": idx,
                    "message": ("Each income line item must have a "
                                 "category. Available categories: "
                                 f"{available}"),
                    "available_categories": available,
                },
            )
        cat_str = str(cat).strip()
        if cat_str in valid_ids or cat_str.lower() in valid_names:
            continue
        raise HTTPException(
            status_code=400,
            detail={
                "error": "category_invalid",
                "error_code": "archived_category",
                "field": f"line_items[{idx}].category",
                "line_index": idx,
                "attempted_category": cat_str,
                "message": (f"Unknown or archived category: {cat_str!r}. "
                             f"Available categories: {available}"),
                "available_categories": available,
            },
        )


# ═══════════════════════════════════════════════════════════════════
# CRUD models
# ═══════════════════════════════════════════════════════════════════
class CategoryIn(BaseModel):
    name: str
    description: Optional[str] = ""
    color: Optional[str] = None
    sort_order: Optional[int] = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════
@router.post("/income-categories/resolve-or-create")
async def resolve_or_create_income_category(
    body: CategoryIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Backlog #iii · Feb-2026 — Autocomplete get-or-create.

    Case-insensitive lookup on ``name`` within the caller's tenant.
    If found → return the row with ``created: false``. Otherwise
    insert a new row using the same seeding shape as ``POST
    /income-categories`` and return with ``created: true``.

    Idempotent: two consecutive calls with the same input return the
    same id; the second call gets ``created: false``. Case-preserving
    on first insert — "Chemicals" typed by the user stays "Chemicals"
    even though a later "chemicals" resolves to the same id.
    """
    _require_admin(user)
    tenant_id = tenant["id"]
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    await ensure_defaults_for_tenant(tenant_id)
    import re as _re
    existing = await db.income_categories.find_one(
        {"tenant_id": tenant_id,
          "is_archived": False,
          "name": {"$regex": f"^{_re.escape(name)}$", "$options": "i"}},
        {"_id": 0},
    )
    if existing:
        for k in ("created_at", "updated_at"):
            if isinstance(existing.get(k), datetime):
                existing[k] = existing[k].isoformat()
        return {"created": False, "category": existing}
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": body.description or "",
        "color": body.color or _auto_color(name),
        "is_archived": False,
        "sort_order": body.sort_order or 0,
        "tenant_id": tenant_id,
        "created_at": now,
        "created_by_user_id": user.get("id") or "pricebook:autocomplete",
        "updated_at": now,
    }
    await db.income_categories.insert_one(dict(doc))
    doc.pop("_id", None)
    doc["created_at"] = now.isoformat()
    doc["updated_at"] = now.isoformat()
    return {"created": True, "category": doc}


@router.get("/income-categories")
async def list_categories(
    include_archived: bool = Query(False),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    await ensure_defaults_for_tenant(tenant_id)
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if not include_archived:
        q["is_archived"] = False
    cur = db.income_categories.find(q, {"_id": 0}).sort(
        [("sort_order", 1), ("name", 1)])
    items = await cur.to_list(1000)
    for c in items:
        if isinstance(c.get("created_at"), datetime):
            c["created_at"] = c["created_at"].isoformat()
        if isinstance(c.get("updated_at"), datetime):
            c["updated_at"] = c["updated_at"].isoformat()
    return {"items": items, "total": len(items)}


@router.post("/income-categories")
async def create_category(
    body: CategoryIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    existing = await db.income_categories.find_one(
        {"tenant_id": tenant_id,
          "name": {"$regex": f"^{name}$", "$options": "i"}},
        {"_id": 0, "id": 1},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate_name", "field": "name"},
        )
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": body.description or "",
        "color": body.color or _auto_color(name),
        "is_archived": False,
        "sort_order": body.sort_order or 0,
        "tenant_id": tenant_id,
        "created_at": now,
        "created_by_user_id": user.get("id") or "",
        "updated_at": now,
    }
    await db.income_categories.insert_one(dict(doc))
    doc.pop("_id", None)
    doc["created_at"] = now.isoformat()
    doc["updated_at"] = now.isoformat()
    return doc


@router.patch("/income-categories/{cid}")
async def update_category(
    cid: str, body: CategoryUpdate,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    cat = await db.income_categories.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "category_not_found")
    upd = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "name" in upd:
        upd["name"] = upd["name"].strip()
        if upd["name"] and upd["name"].lower() != (cat.get("name") or "").lower():
            dup = await db.income_categories.find_one(
                {"tenant_id": tenant_id,
                  "name": {"$regex": f"^{upd['name']}$", "$options": "i"},
                  "id": {"$ne": cid}},
                {"_id": 0, "id": 1},
            )
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "duplicate_name", "field": "name"},
                )
    upd["updated_at"] = _now()
    await db.income_categories.update_one(
        {"id": cid, "tenant_id": tenant_id}, {"$set": upd})
    return await db.income_categories.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0})


@router.post("/income-categories/{cid}/archive")
async def archive_category(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    r = await db.income_categories.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_archived": True, "updated_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "category_not_found")
    return {"ok": True, "id": cid, "is_archived": True}


@router.post("/income-categories/{cid}/restore")
async def restore_category(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    r = await db.income_categories.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_archived": False, "updated_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "category_not_found")
    return {"ok": True, "id": cid, "is_archived": False}


# ═══════════════════════════════════════════════════════════════════
# Uncategorized report
# ═══════════════════════════════════════════════════════════════════
@router.get("/reports/uncategorized-count")
async def uncategorized_count(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    count = 0
    sample: List[Dict[str, Any]] = []
    cur = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "id": 1, "invoice_number": 1, "line_items": 1},
    )
    async for inv in cur:
        for idx, li in enumerate(inv.get("line_items") or []):
            cat = li.get("category")
            if not cat or (isinstance(cat, str) and not cat.strip()):
                count += 1
                if len(sample) < 10:
                    sample.append({
                        "invoice_id": inv.get("id"),
                        "invoice_number": inv.get("invoice_number"),
                        "line_item_index": idx,
                        "amount": (li.get("quantity", 0) or 0)
                                   * (li.get("unit_price", 0) or 0),
                    })
    return {"count": count, "sample_invoices": sample}


@router.get("/reports/uncategorized-items")
async def uncategorized_items(
    range: str = Query(
        "all",
        description=(
            "Feb-2026 · UncategorizedItemsReport — date filter. Values: "
            "``all`` (no bound, matches the Dashboard banner default), "
            "``this_month``, ``last_month``, ``this_quarter``, "
            "``custom`` (requires ``from`` + ``to`` as ISO dates "
            "YYYY-MM-DD)."
        ),
    ),
    missing: str = Query(
        "either",
        description=(
            "Feb-2026 · Scope-addendum — filter by which taxonomy is "
            "missing. ``income`` = missing income category only; "
            "``service`` = missing service category only; ``either`` "
            "(default, matches the banner) = missing at least one; "
            "``both`` = missing both taxonomies."
        ),
    ),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Full list of line items with a missing taxonomy — used by the
    "Review" click-through from the dashboard banner.

    Feb-2026 · Report page — accepts an optional ``?range=`` filter
    (default ``all`` matches the banner). Feb-2026 · Scope-addendum —
    also accepts ``?missing=income|service|either|both`` so the
    admin can zero in on one taxonomy at a time.

    For each surfaced line item we return BOTH taxonomies resolved:
      * income_category_id / income_category_name  (Taxonomy C —
        drives the Revenue-by-Category tile)
      * service_category_id / service_category_name  (Taxonomy B —
        drives the Income-by-Service-Category tile)
    together with two booleans (``missing_income``, ``missing_service``)
    so the frontend can highlight only the actually-missing control.
    """
    _require_admin(user)
    tenant_id = tenant["id"]
    key = (missing or "either").lower()
    if key not in ("income", "service", "either", "both"):
        raise HTTPException(
            422, {"error": "invalid_missing",
                    "allowed": ["income", "service", "either", "both"]},
        )

    range_bounds = _resolve_uncat_range(range, from_, to)

    # Preload the two category lookup tables once. Both tables are
    # tenant-scoped small (< a few hundred rows on any real tenant)
    # so a full fetch beats N per-row point-lookups.
    inc_cats: Dict[str, Dict[str, Any]] = {}
    async for c in db.income_categories.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "color": 1,
         "is_archived": 1},
    ):
        inc_cats[c["id"]] = c
    inc_by_name: Dict[str, Dict[str, Any]] = {
        (c.get("name") or "").strip().lower(): c
        for c in inc_cats.values() if c.get("name")
    }
    svc_cats: Dict[str, Dict[str, Any]] = {}
    async for c in db.service_categories.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "color": 1,
         "is_archived": 1},
    ):
        svc_cats[c["id"]] = c

    rows: List[Dict[str, Any]] = []
    query: Dict[str, Any] = {"tenant_id": tenant_id, "doc_type": "invoice"}
    if range_bounds is not None:
        start_iso, end_iso = range_bounds
        query["created_at"] = {"$gte": start_iso, "$lt": end_iso}
    # Track the pricebook item ids we need to resolve for service-
    # category inheritance so we can batch-fetch them at the end.
    pending: List[Dict[str, Any]] = []
    seen_item_ids: set = set()
    cur = db.quotes.find(
        query,
        {"_id": 0, "id": 1, "invoice_number": 1, "line_items": 1,
          "customer_name": 1, "customer_id": 1, "created_at": 1,
          "service_category": 1},
    )
    async for inv in cur:
        for idx, li in enumerate(inv.get("line_items") or []):
            # Resolve income category (Taxonomy C):
            #   1. Canonical id field, if present
            #   2. Legacy ``category`` field — either a UUID or a
            #      case-insensitive name that maps back into inc_cats
            inc_id: Optional[str] = None
            inc_name: Optional[str] = None
            raw_inc_id = li.get("income_category_id")
            if raw_inc_id and isinstance(raw_inc_id, str) and raw_inc_id.strip():
                row = inc_cats.get(raw_inc_id.strip())
                if row and not row.get("is_archived"):
                    inc_id = row["id"]
                    inc_name = row.get("name")
            if not inc_id:
                legacy = li.get("category")
                if legacy and isinstance(legacy, str) and legacy.strip():
                    v = legacy.strip()
                    row = inc_cats.get(v) or inc_by_name.get(v.lower())
                    if row and not row.get("is_archived"):
                        inc_id = row["id"]
                        inc_name = row.get("name")
                    elif len(v) > 0:
                        # Legacy free-form name that doesn't map to a
                        # known category — treat as "categorized"
                        # (grandfather rule) but expose the raw name
                        # for the operator's context.
                        inc_name = v
                        inc_id = ""    # sentinel: known but non-canonical
            missing_income = not inc_id and not inc_name

            # Resolve service category (Taxonomy B):
            #   1. Snapshotted ``service_category_id`` on the line
            #   2. Inherited from the pricebook item via ``item_id``
            svc_id: Optional[str] = None
            svc_name: Optional[str] = None
            raw_svc_id = li.get("service_category_id")
            if raw_svc_id and isinstance(raw_svc_id, str) and raw_svc_id.strip():
                row = svc_cats.get(raw_svc_id.strip())
                if row and not row.get("is_archived"):
                    svc_id = row["id"]
                    svc_name = row.get("name")
            item_id = li.get("item_id") or li.get("pricebook_item_id")
            if not svc_id and item_id:
                seen_item_ids.add(item_id)
            pending.append({
                "invoice": inv,
                "idx": idx,
                "li": li,
                "inc_id": inc_id or "",
                "inc_name": inc_name or "",
                "svc_id": svc_id or "",
                "svc_name": svc_name or "",
                "missing_income": missing_income,
                "needs_svc_from_item": bool(not svc_id and item_id),
                "item_id": item_id,
            })

    # Batch-fetch pricebook items for service_category inheritance.
    item_svc_lookup: Dict[str, str] = {}
    if seen_item_ids:
        async for it in db.items.find(
            {"id": {"$in": list(seen_item_ids)},
             "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "service_category_id": 1},
        ):
            svc = it.get("service_category_id")
            if svc:
                item_svc_lookup[it["id"]] = svc

    # Second pass — populate inherited service category + apply the
    # ``?missing=`` filter.
    for row in pending:
        if row["needs_svc_from_item"]:
            inherited = item_svc_lookup.get(row["item_id"])
            if inherited:
                sc = svc_cats.get(inherited)
                if sc and not sc.get("is_archived"):
                    row["svc_id"] = sc["id"]
                    row["svc_name"] = sc.get("name") or ""
        missing_service = not row["svc_id"]
        # Apply filter.
        if key == "income" and not row["missing_income"]:
            continue
        if key == "service" and not missing_service:
            continue
        if key == "either" and not (row["missing_income"] or missing_service):
            continue
        if key == "both" and not (row["missing_income"] and missing_service):
            continue

        inv = row["invoice"]
        li = row["li"]
        qty = li.get("quantity", 0) or 0
        unit_price = li.get("unit_price", 0) or 0
        rows.append({
            "invoice_id": inv.get("id"),
            "invoice_number": inv.get("invoice_number"),
            "customer_name": inv.get("customer_name"),
            "customer_id": inv.get("customer_id"),
            "created_at": inv.get("created_at"),
            "line_item_index": row["idx"],
            "description": li.get("description"),
            "quantity": qty,
            "unit_price": unit_price,
            "amount": qty * unit_price,
            "income_category_id": row["inc_id"],
            "income_category_name": row["inc_name"],
            "service_category_id": row["svc_id"],
            "service_category_name": row["svc_name"],
            "missing_income": row["missing_income"],
            "missing_service": missing_service,
            # Invoice-level service_category field (legacy Taxonomy
            # A/B string on the invoice header — kept for admin
            # context; separate from the line-item service category
            # this page mutates).
            "invoice_service_category": inv.get("service_category"),
        })
    return {"items": rows, "total": len(rows), "range": range,
            "range_bounds": range_bounds, "missing": key}


# ═══════════════════════════════════════════════════════════════════
# Inline assign — Feb-2026 · UncategorizedItemsReport
# ═══════════════════════════════════════════════════════════════════
class _AssignBody(BaseModel):
    # Legacy single-taxonomy body (backwards-compat for any in-
    # flight callers pointing at the POST /assign path).
    category_id: Optional[str] = None
    # Feb-2026 · Scope-addendum — two-taxonomy body. At least one
    # of these must be supplied. ``category_id`` above still works
    # and is treated as ``income_category_id`` for backwards compat.
    income_category_id: Optional[str] = None
    service_category_id: Optional[str] = None


class _UndoBody(BaseModel):
    # Feb-2026 · Scope-addendum — DELETE (undo) now takes an optional
    # body telling us WHICH taxonomies to clear. Default (empty body)
    # clears the income category only, matching the pre-addendum
    # behaviour so a stale undo call from the earlier code still
    # works.
    clear_income: bool = True
    clear_service: bool = False


async def _resolve_active_category(
    tenant_id: str, category_id: str,
    *, collection: str = "income_categories",
) -> Dict[str, Any]:
    """Resolve an income OR service category by id (uuid). Raises
    404 if the id doesn't resolve to an active row on the current
    tenant. Kept intentionally strict — the caller (report page
    autocomplete) already runs a ``resolve-or-create`` round-trip
    that returns a canonical id, so any input hitting this endpoint
    should be a valid uuid.
    """
    if not category_id or not category_id.strip():
        raise HTTPException(
            422, {"error": "category_id_required"},
        )
    cat = await db[collection].find_one(
        {"id": category_id, "tenant_id": tenant_id,
         "is_archived": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "color": 1},
    )
    if not cat:
        raise HTTPException(
            404, {"error": "category_not_found_or_archived",
                    "category_id": category_id,
                    "collection": collection},
        )
    return cat


async def _write_recategorize_audit(
    *, tenant_id: str, invoice_id: str, line_item_index: int,
    actor: Dict[str, Any], before: Dict[str, Any],
    after: Dict[str, Any],
) -> None:
    """Feb-2026 · Scope-addendum — paper trail for any per-row
    recategorize (single or bulk). Writes ONE ``audit_logs`` row
    per line-item mutation with a compact before/after diff, plus
    the actor + timestamp. Never blocks the caller on a write
    failure — logs and returns.
    """
    diff: Dict[str, Dict[str, Any]] = {}
    for field in ("income_category_id", "income_category_name",
                  "service_category_id", "service_category_name"):
        if field in after and before.get(field) != after.get(field):
            diff[field] = {"before": before.get(field),
                            "after": after.get(field)}
    if not diff:
        return
    try:
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "event": "line_item.recategorize",
            "invoice_id": invoice_id,
            "line_item_index": line_item_index,
            "actor_id": (actor or {}).get("id"),
            "actor_email": (actor or {}).get("email"),
            "actor_role": ((actor or {}).get("role") or "").lower(),
            "diff": diff,
            "created_at": _now().isoformat(),
        })
    except Exception:                                              # noqa: BLE001
        logger.exception(
            "[uncategorized-items.audit] insert failed for %s[%d]",
            invoice_id, line_item_index,
        )


async def _apply_line_item_recategorize(
    *, tenant_id: str, invoice_id: str, line_item_index: int,
    income_category_id: Optional[str],
    service_category_id: Optional[str],
    actor: Dict[str, Any],
) -> Dict[str, Any]:
    """Shared handler for the POST-assign, PATCH, and bulk-assign
    paths. Never runs the ``validate_line_item_categories`` guard
    (that guard is for whole-invoice edits; here we mutate one
    element in isolation and by design).

    Sets whichever taxonomy fields the caller supplied. Ignores
    idempotent no-ops (already-set-to-the-same-value returns
    ``changed=false``). Writes an audit_logs row per mutation.
    """
    if line_item_index < 0:
        raise HTTPException(422, {"error": "line_item_index_negative"})
    if not income_category_id and not service_category_id:
        raise HTTPException(
            422, {"error": "at_least_one_category_required",
                    "message": "supply income_category_id and/or "
                                "service_category_id"},
        )

    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "line_items": 1},
    )
    if not inv:
        raise HTTPException(404, {"error": "invoice_not_found"})
    items = inv.get("line_items") or []
    if line_item_index >= len(items):
        raise HTTPException(
            404, {"error": "line_item_out_of_bounds",
                    "line_items_len": len(items),
                    "line_item_index": line_item_index},
        )
    li = items[line_item_index]

    before: Dict[str, Any] = {
        "income_category_id": li.get("income_category_id") or li.get("category"),
        "income_category_name": li.get("category_name"),
        "service_category_id": li.get("service_category_id"),
        "service_category_name": li.get("service_category_name"),
    }

    set_ops: Dict[str, Any] = {}
    after: Dict[str, Any] = {}
    resolved_income = None
    resolved_service = None
    if income_category_id:
        resolved_income = await _resolve_active_category(
            tenant_id, income_category_id,
            collection="income_categories",
        )
        set_ops[f"line_items.{line_item_index}.income_category_id"] = resolved_income["id"]
        set_ops[f"line_items.{line_item_index}.category"] = resolved_income["id"]
        set_ops[f"line_items.{line_item_index}.category_name"] = resolved_income.get("name")
        after["income_category_id"] = resolved_income["id"]
        after["income_category_name"] = resolved_income.get("name")
    if service_category_id:
        resolved_service = await _resolve_active_category(
            tenant_id, service_category_id,
            collection="service_categories",
        )
        set_ops[f"line_items.{line_item_index}.service_category_id"] = resolved_service["id"]
        set_ops[f"line_items.{line_item_index}.service_category_name"] = resolved_service.get("name")
        after["service_category_id"] = resolved_service["id"]
        after["service_category_name"] = resolved_service.get("name")

    # No-op guard — if the caller supplied a value that matches the
    # existing snapshot exactly, skip the write + skip the audit.
    real_ops = {
        k: v for k, v in set_ops.items()
        if li.get(k.rsplit(".", 1)[-1]) != v
    }
    changed = bool(real_ops)
    if changed:
        real_ops["updated_at"] = _now().isoformat()
        r = await db.quotes.update_one(
            {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
            {"$set": real_ops},
        )
        if r.matched_count == 0:
            raise HTTPException(404, {"error": "invoice_not_found"})
        await _write_recategorize_audit(
            tenant_id=tenant_id, invoice_id=invoice_id,
            line_item_index=line_item_index, actor=actor,
            before=before, after=after,
        )
        logger.info(
            "[uncategorized-items.recategorize] actor=%s "
            "invoice=%s idx=%d income=%s service=%s",
            (actor or {}).get("email"), invoice_id, line_item_index,
            resolved_income and resolved_income["id"],
            resolved_service and resolved_service["id"],
        )
    return {
        "ok": True, "changed": changed,
        "invoice_id": invoice_id,
        "line_item_index": line_item_index,
        "income_category": (
            {"id": resolved_income["id"], "name": resolved_income.get("name"),
             "color": resolved_income.get("color")} if resolved_income else None),
        "service_category": (
            {"id": resolved_service["id"], "name": resolved_service.get("name"),
             "color": resolved_service.get("color")} if resolved_service else None),
    }


@router.post(
    "/reports/uncategorized-items/{invoice_id}/{line_item_index}/assign",
)
async def assign_uncategorized_line_item_category(
    invoice_id: str,
    line_item_index: int,
    body: _AssignBody = Body(...),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Set the income and/or service category on a single line item
    without touching the rest of the invoice.

    Feb-2026 · Scope-addendum — accepts BOTH taxonomies (either or
    both). Legacy body shape ``{category_id}`` is treated as
    ``income_category_id`` for backwards compat.
    """
    _require_admin(user)
    income_id = (body.income_category_id or body.category_id or "").strip() or None
    service_id = (body.service_category_id or "").strip() or None
    return await _apply_line_item_recategorize(
        tenant_id=tenant["id"], invoice_id=invoice_id,
        line_item_index=line_item_index,
        income_category_id=income_id,
        service_category_id=service_id,
        actor=user,
    )


@router.patch(
    "/reports/uncategorized-items/{invoice_id}/{line_item_index}",
)
async def patch_uncategorized_line_item(
    invoice_id: str,
    line_item_index: int,
    body: _AssignBody = Body(...),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Feb-2026 · Scope-addendum — canonical PATCH shape for
    updating either or both category taxonomies on a single line
    item. Delegates to the shared handler used by ``POST /assign``
    and ``POST /bulk-assign`` so all three surfaces share the same
    resolver, no-op guard, and audit-log write.
    """
    _require_admin(user)
    income_id = (body.income_category_id or body.category_id or "").strip() or None
    service_id = (body.service_category_id or "").strip() or None
    return await _apply_line_item_recategorize(
        tenant_id=tenant["id"], invoice_id=invoice_id,
        line_item_index=line_item_index,
        income_category_id=income_id,
        service_category_id=service_id,
        actor=user,
    )


@router.delete(
    "/reports/uncategorized-items/{invoice_id}/{line_item_index}/assign",
)
async def undo_assign_line_item_category(
    invoice_id: str,
    line_item_index: int,
    body: Optional[_UndoBody] = Body(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Undo a previous ``assign`` — clears the specified taxonomy
    field(s) on the line item so it reappears in the uncategorized
    report.

    Purpose-built for the report page's 5-second Undo toast. Kept
    intentionally narrow: the caller supplies (invoice_id, index) +
    an optional body ``{clear_income?, clear_service?}`` that tells
    us which taxonomies to clear. Empty body defaults to clearing
    income only (matches the pre-addendum behaviour). Bypasses the
    ``validate_line_item_categories`` enforcement on purpose — this
    is the deliberate escape hatch for an operator undo action.

    Also writes an audit_logs row so the paper trail is symmetric
    with the assign path.
    """
    _require_admin(user)
    tenant_id = tenant["id"]
    if line_item_index < 0:
        raise HTTPException(422, {"error": "line_item_index_negative"})
    payload = body or _UndoBody()
    if not payload.clear_income and not payload.clear_service:
        raise HTTPException(
            422, {"error": "nothing_to_clear",
                    "message": "at least one of clear_income / "
                                "clear_service must be true"},
        )

    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "line_items": 1},
    )
    if not inv:
        raise HTTPException(404, {"error": "invoice_not_found"})
    items = inv.get("line_items") or []
    if line_item_index >= len(items):
        raise HTTPException(
            404, {"error": "line_item_out_of_bounds"},
        )
    li = items[line_item_index]

    before = {
        "income_category_id": li.get("income_category_id") or li.get("category"),
        "income_category_name": li.get("category_name"),
        "service_category_id": li.get("service_category_id"),
        "service_category_name": li.get("service_category_name"),
    }
    unset_ops: Dict[str, Any] = {}
    after: Dict[str, Any] = {}
    if payload.clear_income:
        unset_ops[f"line_items.{line_item_index}.category"] = ""
        unset_ops[f"line_items.{line_item_index}.category_name"] = ""
        unset_ops[f"line_items.{line_item_index}.income_category_id"] = ""
        after["income_category_id"] = None
        after["income_category_name"] = None
    if payload.clear_service:
        unset_ops[f"line_items.{line_item_index}.service_category_id"] = ""
        unset_ops[f"line_items.{line_item_index}.service_category_name"] = ""
        after["service_category_id"] = None
        after["service_category_name"] = None

    r = await db.quotes.update_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"$unset": unset_ops,
         "$set": {"updated_at": _now().isoformat()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, {"error": "invoice_not_found"})
    await _write_recategorize_audit(
        tenant_id=tenant_id, invoice_id=invoice_id,
        line_item_index=line_item_index, actor=user,
        before=before, after=after,
    )
    logger.info(
        "[uncategorized-items.undo] actor=%s invoice=%s idx=%d "
        "cleared income=%s service=%s",
        user.get("email"), invoice_id, line_item_index,
        payload.clear_income, payload.clear_service,
    )
    return {"ok": True, "undone": True,
            "invoice_id": invoice_id,
            "line_item_index": line_item_index,
            "cleared": {"income": payload.clear_income,
                          "service": payload.clear_service}}


# ═══════════════════════════════════════════════════════════════════
# Bulk assign — Feb-2026 · UncategorizedItemsReport
# ═══════════════════════════════════════════════════════════════════
class _BulkAssignRow(BaseModel):
    invoice_id: str
    line_item_index: int


class _BulkAssignBody(BaseModel):
    items: List[_BulkAssignRow]
    # Legacy single-taxonomy field (backwards compat).
    category_id: Optional[str] = None
    # Feb-2026 · Scope-addendum — one or both.
    income_category_id: Optional[str] = None
    service_category_id: Optional[str] = None


@router.post("/reports/uncategorized-items/bulk-assign")
async def bulk_assign_uncategorized(
    body: _BulkAssignBody = Body(...),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Bulk-assign N (invoice_id, line_item_index) pairs to one or
    both category taxonomies. Runs the single-row assign per pair
    without short-circuiting on partial failures — a row that fails
    is reported in ``errors`` but doesn't block the rest.

    Feb-2026 · Scope-addendum — body accepts BOTH
    ``income_category_id`` and ``service_category_id``; at least
    one required. Legacy ``category_id`` still works for
    backwards-compat and is treated as ``income_category_id``.

    Cap: 200 rows per call. Frontend paginates larger selections.
    """
    _require_admin(user)
    tenant_id = tenant["id"]
    income_id = (body.income_category_id or body.category_id or "").strip() or None
    service_id = (body.service_category_id or "").strip() or None
    if not income_id and not service_id:
        raise HTTPException(
            422, {"error": "at_least_one_category_required"},
        )

    if not body.items:
        return {"assigned": 0, "unchanged": 0,
                "failed": 0, "errors": []}
    if len(body.items) > 200:
        raise HTTPException(
            422, {"error": "bulk_cap_exceeded", "cap": 200,
                    "received": len(body.items)},
        )

    # Pre-resolve categories once (avoids N lookups on N rows).
    resolved_income = None
    resolved_service = None
    if income_id:
        resolved_income = await _resolve_active_category(
            tenant_id, income_id, collection="income_categories",
        )
    if service_id:
        resolved_service = await _resolve_active_category(
            tenant_id, service_id, collection="service_categories",
        )

    assigned = 0
    unchanged = 0
    failed = 0
    errors: List[Dict[str, Any]] = []
    for row in body.items:
        try:
            result = await _apply_line_item_recategorize(
                tenant_id=tenant_id,
                invoice_id=row.invoice_id,
                line_item_index=row.line_item_index,
                income_category_id=income_id,
                service_category_id=service_id,
                actor=user,
            )
            if result.get("changed"):
                assigned += 1
            else:
                unchanged += 1
        except HTTPException as exc:
            failed += 1
            errors.append({
                "invoice_id": row.invoice_id,
                "line_item_index": row.line_item_index,
                "status": exc.status_code,
                "error": (
                    exc.detail if isinstance(exc.detail, str)
                    else (exc.detail or {}).get("error", "http_error")
                ),
            })
        except Exception as exc:                                   # noqa: BLE001
            failed += 1
            errors.append({
                "invoice_id": row.invoice_id,
                "line_item_index": row.line_item_index,
                "error": str(exc)[:200],
            })
    logger.info(
        "[uncategorized-items.bulk_assign] actor=%s "
        "income=%s service=%s assigned=%d unchanged=%d failed=%d",
        user.get("email"),
        resolved_income and resolved_income["id"],
        resolved_service and resolved_service["id"],
        assigned, unchanged, failed,
    )
    return {
        "assigned": assigned,
        "unchanged": unchanged,
        "failed": failed,
        "errors": errors[:50],
        "income_category": (
            {"id": resolved_income["id"], "name": resolved_income.get("name"),
             "color": resolved_income.get("color")}
            if resolved_income else None),
        "service_category": (
            {"id": resolved_service["id"], "name": resolved_service.get("name"),
             "color": resolved_service.get("color")}
            if resolved_service else None),
    }


# ═══════════════════════════════════════════════════════════════════
# Range resolver — Feb-2026 · UncategorizedItemsReport
# ═══════════════════════════════════════════════════════════════════
_UNCAT_MAX_CUSTOM_DAYS = 366


def _resolve_uncat_range(
    range_key: str,
    from_: Optional[str],
    to: Optional[str],
) -> Optional[tuple]:
    """Return (start_iso, end_iso_exclusive) or ``None`` for the
    ``all`` sentinel (no bound).

    Values:
      * ``all``          → None
      * ``this_month``   → (first_of_month, first_of_next_month)
      * ``last_month``   → (first_of_last_month, first_of_this_month)
      * ``this_quarter`` → (first_of_quarter, first_of_next_quarter)
      * ``custom``       → (from, to+1day)   (``to`` is inclusive in
                            the query semantics; we add a day so
                            Mongo ``$lt`` gives inclusive-end.)
    """
    key = (range_key or "all").lower()
    if key == "all":
        return None
    today = datetime.now(timezone.utc).date()
    if key == "this_month":
        start = date(today.year, today.month, 1)
        end = _first_of_next_month(start)
    elif key == "last_month":
        first_of_this = date(today.year, today.month, 1)
        last_month_last = first_of_this - timedelta(days=1)
        start = date(last_month_last.year, last_month_last.month, 1)
        end = first_of_this
    elif key == "this_quarter":
        q_start_month = (((today.month - 1) // 3) * 3) + 1
        start = date(today.year, q_start_month, 1)
        end = _first_of_month_offset(start, 3)
    elif key == "custom":
        if not from_ or not to:
            raise HTTPException(
                422, {"error": "custom_requires_from_to"},
            )
        try:
            start = date.fromisoformat(from_)
            end_inclusive = date.fromisoformat(to)
        except ValueError as exc:
            raise HTTPException(
                422, {"error": "invalid_date_format"},
            ) from exc
        if end_inclusive < start:
            raise HTTPException(
                422, {"error": "to_before_from"},
            )
        if (end_inclusive - start).days > _UNCAT_MAX_CUSTOM_DAYS:
            raise HTTPException(
                422, {"error": "range_too_large",
                        "max_days": _UNCAT_MAX_CUSTOM_DAYS},
            )
        end = end_inclusive + timedelta(days=1)
    else:
        raise HTTPException(
            422, {"error": "invalid_range",
                    "allowed": ["all", "this_month", "last_month",
                                 "this_quarter", "custom"]},
        )
    return (start.isoformat(), end.isoformat())


def _first_of_next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _first_of_month_offset(d: date, months: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + months
    return date(total // 12, (total % 12) + 1, 1)
