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
    # Phase K71 · Feb-2026 — additive seed names for the K71 inline
    # line-item editor income-category dropdown. Additive-merged
    # case-insensitively per tenant, so an existing "Pool" stays,
    # and only names not already present are inserted.
    "Service Revenue",
    "Product Sales",
    "Recurring Maintenance",
    "One-time Project",
    "Warranty Work",
    "Labor Income",
    "Materials",
    "Other Income",
]


def _require_admin(user: dict) -> None:
    # Phase L1.1 · Feb-2026 — detail rename for consistency with the
    # A/B/C cluster convention ("insufficient_role_for_*").
    # Frontend + tests updated in the same pass.
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "insufficient_role_for_categories")


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
    """Idempotent — additive seed. Phase K71 · Feb-2026: switched
    from the pre-K71 "only if count == 0" behaviour to a case-
    insensitive additive merge (mirroring ``service_categories.
    ensure_defaults_for_tenant``). Any DEFAULT names that aren't
    already present on the tenant get inserted. Names already used
    (case-insensitive) are skipped so operator-renamed rows stay
    intact."""
    if not tenant_id:
        return
    existing = await db.income_categories.find(
        {"tenant_id": tenant_id}, {"_id": 0, "name": 1},
    ).to_list(500)
    have = {(r.get("name") or "").strip().lower() for r in existing}
    missing = [n for n in _DEFAULTS if n.lower() not in have]
    if not missing:
        return
    now = _now()
    docs = [
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": "",
            "color": _auto_color(name),
            "is_archived": False,
            "sort_order": _DEFAULTS.index(name),
            "tenant_id": tenant_id,
            "created_at": now,
            "created_by_user_id": "system:seed",
            "updated_at": now,
        }
        for name in missing
    ]
    await db.income_categories.insert_many(docs)
    logger.info(
        "[income_categories] seeded %d defaults for tenant=%s (missing=%s)",
        len(docs), tenant_id, missing,
    )


# ═══════════════════════════════════════════════════════════════════
# Category enforcement helper — called by quotes.py + invoice_edit.py
# ═══════════════════════════════════════════════════════════════════
def _line_item_row_ref(idx: int, li: Dict[str, Any]) -> str:
    """Feb-2026 · Build a user-facing row reference for validation
    errors.

    Returns ``"Line Item {N} ({description})"`` where ``N`` is
    ``idx + 1`` (1-based, matches what the operator sees in the
    inline editor) and ``description`` is the line item's own
    description text — or ``"Untitled"`` when missing/blank
    (matches the codebase-wide fallback used by
    ``document_generators``, ``templates_library``,
    ``ai_employees``, etc.).

    Callers concatenate this against the specific validation
    complaint so a user with 20 line items can pinpoint the
    offending row without counting from zero. The machine-parseable
    ``field`` / ``line_index`` payload keys stay 0-based so
    Pydantic-style ``loc`` consumers on the frontend keep working
    unchanged — only the human ``message`` string is affected.
    """
    desc_raw = li.get("description") if li else None
    if isinstance(desc_raw, str):
        desc = desc_raw.strip()
    else:
        desc = ""
    return f"Line Item {idx + 1} ({desc or 'Untitled'})"


async def validate_line_item_categories(
    tenant_id: str, line_items: List[Dict[str, Any]],
    *, strict: bool = True,
) -> None:
    """Reject if ANY line item is missing a category or references an
    inactive/foreign one.  Called from create + edit paths.

    Accepts EITHER a category **id** (uuid) OR a category **name**
    (string that matches ``income_categories.name`` case-insensitively).

    Feb-2026 · invoice-category hard-block removal — callers from
    the invoice/quote save path pass ``strict=False`` so missing or
    inactive categories log + continue instead of raising 400.
    The job-media line-items path keeps the default ``strict=True``
    because its UX contract has not changed.
    """
    await ensure_defaults_for_tenant(tenant_id)
    active = await db.income_categories.find(
        {"tenant_id": tenant_id, "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    valid_ids = {c["id"] for c in active}
    valid_names = {(c["name"] or "").strip().lower() for c in active}
    available = [c["name"] for c in active]
    # Phase 26b · Feb-2026 — also fetch archived rows so refs to a
    # just-archived category soft-pass (null-out + auto-stamp)
    # instead of erroring.  Mirrors the archive-time fan-out shape.
    archived = await db.income_categories.find(
        {"tenant_id": tenant_id, "is_archived": True},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    archived_by_id = {c["id"]: c for c in archived}
    archived_by_name = {(c["name"] or "").strip().lower(): c for c in archived}
    from services.category_deactivation import (
        soft_pass_archived_ref_in_line_item,
    )

    for idx, li in enumerate(line_items or []):
        # Phase 26b · Feb-2026 — an auto-mapped row (either stamped
        # by the archive-time fan-out or by a prior save-time soft-
        # pass) is allowed to have an empty ``category`` on save —
        # treat it as a legacy grandfathered row.  Operator sees an
        # amber chip in the editor nudging them to re-pick.
        if li.get("category_auto_mapped") is True and not (
            li.get("category") or "").strip():
            continue
        cat = (li.get("category") or "").strip() if isinstance(
            li.get("category"), str) else li.get("category")
        if not cat:
            if not strict:
                logger.info(
                    "invoices.category_warning kind=missing_legacy "
                    "line_index=%d tenant_id=%s", idx, tenant_id,
                )
                continue
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "category_required",
                    "error_code": "category_required",
                    "field": f"line_items[{idx}].category",
                    "line_index": idx,
                    "message": (
                        f"{_line_item_row_ref(idx, li)} — Each income "
                        "line item must have a category. Available "
                        f"categories: {available}"
                    ),
                    "available_categories": available,
                },
            )
        cat_str = str(cat).strip()
        if cat_str in valid_ids or cat_str.lower() in valid_names:
            continue
        # Phase 26b · Feb-2026 — soft-pass archived refs instead of
        # erroring.  Mutates the line in-place; downstream write
        # path lands the null-out + auto-stamp alongside the rest
        # of the operator's edit.
        archived_cat = archived_by_id.get(cat_str) or \
            archived_by_name.get(cat_str.lower())
        if archived_cat:
            soft_pass_archived_ref_in_line_item(
                li=li, archived_cat=archived_cat, axis="income")
            continue
        if not strict:
            logger.info(
                "invoices.category_warning kind=invalid_legacy "
                "line_index=%d tenant_id=%s attempted=%r",
                idx, tenant_id, cat_str,
            )
            continue
        raise HTTPException(
            status_code=400,
            detail={
                "error": "category_invalid",
                "error_code": "archived_category",
                "field": f"line_items[{idx}].category",
                "line_index": idx,
                "attempted_category": cat_str,
                "message": (
                    f"{_line_item_row_ref(idx, li)} — Unknown or "
                    f"archived category: {cat_str!r}. Available "
                    f"categories: {available}"
                ),
                "available_categories": available,
            },
        )


# ═══════════════════════════════════════════════════════════════════
# Phase K71 · Feb-2026 — Line-item Service + Income category
# enforcement for the estimate / quote / invoice inline editor.
#
# Two-taxonomy validation with legacy grandfathering:
#   * NEW line items (any line whose payload mentions EITHER
#     ``service_category_id`` OR ``income_category_id`` — even as
#     an empty string) MUST resolve BOTH to active tenant rows.
#   * LEGACY line items (neither K71 field present in the payload)
#     are grandfathered and skipped.
#
# The K71 write path (frontend inline editor) always sends both
# fields for lines it just added/edited, so the presence-based rule
# cleanly separates "user is using K71" from "untouched legacy row".
# ═══════════════════════════════════════════════════════════════════
async def validate_line_item_k71_categories(
    tenant_id: str, line_items: List[Dict[str, Any]],
    *, strict: bool = True,
) -> None:
    """K71 gate — enforces service+income category pairs on NEW/edited
    line items. Legacy items (missing both K71 fields) pass silently.

    Feb-2026 · Phase P40 — error payloads now carry ``available_categories``
    + ``invalid_value`` + a ``code`` alias so callers (K71 editor +
    LineItemsSection retry flow + Income-by-Category upstream cure)
    can render the archived-category picker chip without a second
    round-trip to fetch the active list.

    Feb-2026 · invoice-category hard-block removal — callers from
    the invoice/quote save path pass ``strict=False`` so missing or
    inactive categories log + continue instead of raising 400.
    """
    from routers.service_categories import ensure_defaults_for_tenant \
        as _ensure_svc_defaults
    await ensure_defaults_for_tenant(tenant_id)
    await _ensure_svc_defaults(tenant_id)

    inc_cats = await db.income_categories.find(
        {"tenant_id": tenant_id, "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    inc_ids = {c["id"] for c in inc_cats}
    inc_names = {(c.get("name") or "").strip().lower() for c in inc_cats}
    inc_available = [c["name"] for c in inc_cats]

    svc_cats = await db.service_categories.find(
        {"tenant_id": tenant_id, "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    svc_ids = {c["id"] for c in svc_cats}
    svc_names = {(c.get("name") or "").strip().lower() for c in svc_cats}
    svc_available = [c["name"] for c in svc_cats]

    # Phase 26b · Feb-2026 — archived rows lookup for soft-pass.
    # Lines pointing at a just-archived category get null'd +
    # auto-stamped instead of raising HTTP 400.
    inc_archived = await db.income_categories.find(
        {"tenant_id": tenant_id, "is_archived": True},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    inc_archived_by_id = {c["id"]: c for c in inc_archived}
    inc_archived_by_name = {
        (c.get("name") or "").strip().lower(): c for c in inc_archived}
    svc_archived = await db.service_categories.find(
        {"tenant_id": tenant_id, "is_archived": True},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    svc_archived_by_id = {c["id"]: c for c in svc_archived}
    svc_archived_by_name = {
        (c.get("name") or "").strip().lower(): c for c in svc_archived}
    from services.category_deactivation import (
        soft_pass_archived_ref_in_line_item,
    )

    for idx, li in enumerate(line_items or []):
        # Phase K71 · Feb-2026 — K71-touched detection is str-typed
        # rather than presence-based. Pydantic's ``LineItem`` model
        # emits ``service_category_id: None`` / ``income_category_id:
        # None`` for legacy payloads via ``.dict()`` even when the
        # caller omitted them, so a naive ``"field" in li`` check
        # falsely flags every incoming line as K71. Treating the
        # field as K71 iff the value is a string (empty string still
        # counts — that is an operator who cleared the field via
        # inline edit and must be blocked) sidesteps the whole
        # serializer default problem.
        svc_raw = li.get("service_category_id")
        inc_raw = li.get("income_category_id")
        has_svc_field = isinstance(svc_raw, str)
        has_inc_field = isinstance(inc_raw, str)
        is_k71 = has_svc_field or has_inc_field
        if not is_k71:
            # Legacy grandfathered — skip validation entirely.
            continue

        svc_val = svc_raw.strip() if isinstance(svc_raw, str) else ""
        inc_val = inc_raw.strip() if isinstance(inc_raw, str) else ""

        # Phase 26b · Feb-2026 — auto-mapped rows (stamped by the
        # archive-time fan-out or a prior save-time soft-pass) are
        # allowed to have empty K71 fields on save.  Operator sees
        # an amber chip in the editor nudging them to re-pick.
        if li.get("category_auto_mapped") is True and not svc_val and not inc_val:
            continue

        if not svc_val:
            if not strict:
                logger.info(
                    "invoices.category_warning kind=missing_service "
                    "line_index=%d tenant_id=%s", idx, tenant_id,
                )
                continue
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "service_category_required",
                    "error_code": "k71_service_category_required",
                    "code": "invalid_line_item_category",
                    "field": f"line_items[{idx}].service_category_id",
                    "line_index": idx,
                    "message": (
                        f"{_line_item_row_ref(idx, li)} — Service "
                        "category is required for this line item. "
                        "Set it in the inline editor."
                    ),
                    "invalid_value": "",
                    "available_categories": svc_available,
                },
            )
        if svc_val not in svc_ids and svc_val.lower() not in svc_names:
            # Phase 26b · Feb-2026 — soft-pass archived svc refs.
            svc_archived_row = svc_archived_by_id.get(svc_val) or \
                svc_archived_by_name.get(svc_val.lower())
            if svc_archived_row:
                soft_pass_archived_ref_in_line_item(
                    li=li, archived_cat=svc_archived_row, axis="service")
                svc_val = ""   # downstream inc check still runs
            elif not strict:
                logger.info(
                    "invoices.category_warning kind=invalid_service "
                    "line_index=%d tenant_id=%s attempted=%r",
                    idx, tenant_id, svc_val,
                )
                svc_val = ""   # downstream inc check still runs
            else:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "service_category_invalid",
                        "error_code": "k71_service_category_invalid",
                        "code": "invalid_line_item_category",
                        "field": f"line_items[{idx}].service_category_id",
                        "line_index": idx,
                        "attempted": svc_val,
                        "invalid_value": svc_val,
                        "message": (
                            f"{_line_item_row_ref(idx, li)} — references "
                            f"an inactive or unknown service category: "
                            f"{svc_val!r}."
                        ),
                        "available_categories": svc_available,
                    },
                )

        if not inc_val:
            # Phase 26b · Feb-2026 — if svc soft-passed above (now
            # empty) and inc is also empty, we're an auto-mapped
            # row post-soft-pass and should allow through.
            if li.get("category_auto_mapped") is True:
                continue
            if not strict:
                logger.info(
                    "invoices.category_warning kind=missing_income "
                    "line_index=%d tenant_id=%s", idx, tenant_id,
                )
                continue
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "income_category_required",
                    "error_code": "k71_income_category_required",
                    "code": "invalid_line_item_category",
                    "field": f"line_items[{idx}].income_category_id",
                    "line_index": idx,
                    "message": (
                        f"{_line_item_row_ref(idx, li)} — Income "
                        "category is required for this line item. "
                        "Set it in the inline editor."
                    ),
                    "invalid_value": "",
                    "available_categories": inc_available,
                },
            )
        if inc_val not in inc_ids and inc_val.lower() not in inc_names:
            # Phase 26b · Feb-2026 — soft-pass archived inc refs.
            inc_archived_row = inc_archived_by_id.get(inc_val) or \
                inc_archived_by_name.get(inc_val.lower())
            if inc_archived_row:
                soft_pass_archived_ref_in_line_item(
                    li=li, archived_cat=inc_archived_row, axis="income")
                continue
            if not strict:
                logger.info(
                    "invoices.category_warning kind=invalid_income "
                    "line_index=%d tenant_id=%s attempted=%r",
                    idx, tenant_id, inc_val,
                )
                continue
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "income_category_invalid",
                    "error_code": "k71_income_category_invalid",
                    "code": "invalid_line_item_category",
                    "field": f"line_items[{idx}].income_category_id",
                    "line_index": idx,
                    "attempted": inc_val,
                    "invalid_value": inc_val,
                    "message": (
                        f"{_line_item_row_ref(idx, li)} — references "
                        f"an inactive or unknown income category: "
                        f"{inc_val!r}."
                    ),
                    "available_categories": inc_available,
                },
            )


def check_line_items_k71_gaps(line_items: List[Dict[str, Any]]) -> List[int]:
    """Read-side helper used by send/approve/convert gates.

    Returns the indices of line items whose K71 metadata was set
    once (either category field present) but is now missing/empty —
    i.e. items that WERE touched by the K71 editor but violate the
    "both required" rule. Legacy grandfathered items (neither field
    present) return no indices.
    """
    gaps: List[int] = []
    for idx, li in enumerate(line_items or []):
        svc_raw = li.get("service_category_id")
        inc_raw = li.get("income_category_id")
        has_svc = isinstance(svc_raw, str)
        has_inc = isinstance(inc_raw, str)
        if not (has_svc or has_inc):
            continue
        svc_val = svc_raw.strip() if isinstance(svc_raw, str) else ""
        inc_val = inc_raw.strip() if isinstance(inc_raw, str) else ""
        if not svc_val or not inc_val:
            gaps.append(idx)
    return gaps


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
    """Phase 26b · Feb-2026 — soft-delete + fan-out.

    1. Flips ``is_archived: True`` on the category.
    2. Fans out across tenant line items (``db.quotes.line_items[]``)
       + pricebook items (``db.items``) to NULL the archived ref +
       stamp ``category_auto_mapped: true`` + ``original_category_id``
       + ``original_category_name`` on each affected row.
    3. On fan-out failure, calls ``rollback_archive`` to flip
       ``is_archived`` back to ``False`` so the system stays in a
       consistent "not archived + line items untouched" state.

    Restore semantics:  ``POST /income-categories/{id}/restore``
    does NOT re-hydrate the null'd refs — the operator must affirm-
    atively re-pick a category via the inline editor.  Documented
    on ``restore_category`` below.
    """
    _require_admin(user)
    tenant_id = tenant["id"]
    cat = await db.income_categories.find_one(
        {"id": cid, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "is_archived": 1},
    )
    if not cat:
        raise HTTPException(404, "category_not_found")
    cat_name = cat.get("name") or ""
    await db.income_categories.update_one(
        {"id": cid, "tenant_id": tenant_id},
        {"$set": {"is_archived": True, "updated_at": _now()}},
    )
    # Fan-out — on failure, compensate by un-archiving.
    try:
        from services.category_deactivation import fan_out_archive
        stats = await fan_out_archive(
            axis="income", tenant_id=tenant_id,
            cat_id=cid, cat_name=cat_name,
        )
    except Exception as exc:                                        # noqa: BLE001
        from services.category_deactivation import rollback_archive
        await rollback_archive(
            axis="income", tenant_id=tenant_id, cat_id=cid)
        logger.exception(
            "[income_categories.archive] fan-out failed, rolled back")
        raise HTTPException(
            500, {"error": "fan_out_failed", "detail": str(exc)[:200]},
        ) from exc
    return {"ok": True, "id": cid, "is_archived": True, "fan_out": stats}


@router.post("/income-categories/{cid}/restore")
async def restore_category(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Flip ``is_archived`` back to ``False``.

    Phase 26b · Feb-2026 — restore does NOT re-hydrate the line
    items we null'd on archive.  Those rows retain their
    ``category_auto_mapped: true`` + ``original_category_*`` stamps
    and continue to surface in the uncategorized banner + editor
    amber chip until the operator manually re-picks a category.
    """
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
          "service_category": 1,
          # Feb-2026 · Bulk hard-delete for uncategorized line items —
          # the frontend needs ``payment_status`` per row so it can
          # tally how many selected lines belong to paid invoices
          # (G.4c amber-warning gate before the TypedConfirmModal).
          # ``updated_at`` is projected too so a follow-up write can
          # use it as the ``find_one_and_update`` concurrency guard.
          "payment_status": 1, "amount_paid": 1, "total": 1,
          "updated_at": 1},
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
            # Feb-2026 · Bulk hard-delete for uncategorized line items —
            # exposed so the frontend can render an amber warning
            # ("N of the selected lines belong to paid invoices")
            # BEFORE opening the TypedConfirmModal.
            "invoice_payment_status": inv.get("payment_status"),
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
        # ── P55 · Feb-2026 — Category sync fan-out to Pricebook ──
        # Propagate the new category to the master pricebook row
        # (db.items) via ``sync_invoice_line_to_pricebook`` if the
        # invoice line carries a pricebook FK. Origin marker
        # ``invoice_line_edit`` prevents cascading back into this
        # same handler through a future hook. Q · policy: ``None``
        # skips (pricebook is master; downstream ephemeral clears
        # must NOT wipe the master row) — the orchestrator
        # honours this.
        line_item_id = (li.get("id") or "")
        if line_item_id:
            from services.category_sync import (
                sync_invoice_line_to_pricebook,
                CategorySyncNameLookupError,
            )
            _sync_kwargs: Dict[str, Any] = {
                "origin": "invoice_line_edit",
            }
            if income_category_id:
                _sync_kwargs["income_category_id"] = income_category_id
            if service_category_id:
                _sync_kwargs["service_category_id"] = service_category_id
            try:
                await sync_invoice_line_to_pricebook(
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    line_item_id=line_item_id,
                    actor_id=(actor or {}).get("id"),
                    **_sync_kwargs,
                )
            except CategorySyncNameLookupError as _cs_exc:
                raise HTTPException(
                    422,
                    {"code": "category_deleted_after_source_write",
                     "category_id": _cs_exc.category_id,
                     "collection": _cs_exc.collection},
                )
            except Exception as _cs_exc:                   # noqa: BLE001
                logger.warning(
                    "[category_sync.invoice_line→pricebook.failed] "
                    "invoice=%s line=%s error=%s",
                    invoice_id, line_item_id, _cs_exc,
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


# ═══════════════════════════════════════════════════════════════════
# Phase L1.1 · Feb-2026 — batch reorder for drag-and-drop UI.
# Mirrors ``routers.service_categories.reorder_categories``.
# ═══════════════════════════════════════════════════════════════════
class _ReorderIn(BaseModel):
    ordered_ids: List[str]


@router.post("/income-categories/reorder")
async def reorder_categories(
    body: _ReorderIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    ids = [i for i in (body.ordered_ids or []) if i]
    if not ids:
        return {"ok": True, "updated": 0}
    rows = await db.income_categories.find(
        {"tenant_id": tid, "id": {"$in": ids}}, {"_id": 0, "id": 1},
    ).to_list(len(ids) + 1)
    tenant_ids = {r["id"] for r in rows}
    stray = [i for i in ids if i not in tenant_ids]
    if stray:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_ids", "ids": stray},
        )
    now = _now()
    for idx, cid in enumerate(ids):
        await db.income_categories.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {"sort_order": idx, "updated_at": now}})
    return {"ok": True, "updated": len(ids)}


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · Bulk hard-delete for uncategorized line items
# ═══════════════════════════════════════════════════════════════════
# Two endpoints:
#   * POST /reports/uncategorized-items/bulk-hard-delete
#   * POST /reports/uncategorized-items/bulk-hard-delete/{bulk_op_id}/undo
#
# Semantics locked in Phase 1 §G rulings — see the
# ``services.reports.uncategorized_line_deletes`` module docstring
# for the full rationale.  This block is the request/response +
# orchestration layer only; pure planning + math + audit-row
# construction live in the service module.
# ═══════════════════════════════════════════════════════════════════
from routers.tenants import get_current_tenant as _get_current_tenant   # noqa: E402
from utils import require_admin as _require_admin_dep                    # noqa: E402
from services.reports.uncategorized_line_deletes import (                # noqa: E402
    DeleteRequest,
    apply_deletions,
    build_audit_row,
    build_undo_audit_row,
    plan_deletions,
    recompute_totals,
)


_UNCAT_HARD_DELETE_CAP = 100


class _HardDeleteRow(BaseModel):
    invoice_id: str
    line_item_index: int
    description: str
    unit_price: float


class _HardDeleteBody(BaseModel):
    rows: List[_HardDeleteRow]
    acknowledged_lock_bypass: bool = False
    deletion_reason: Optional[str] = None


@router.post("/reports/uncategorized-items/bulk-hard-delete",
              operation_id="reports.uncategorizedItems.bulkHardDelete")
async def bulk_hard_delete_uncategorized_lines(
    body: _HardDeleteBody,
    user: dict = Depends(_require_admin_dep),
    tenant: dict = Depends(_get_current_tenant),
) -> Dict[str, Any]:
    """Bulk hard-delete line items from invoices.

    Response shape::

        {
            "bulk_op_id": <uuid4>,
            "requested":  <int>,
            "deleted":    <int>,
            "skipped":    [{"invoice_id": str,
                             "line_item_index": int,
                             "code": str}, ...],
        }

    Skip codes (verbatim taxonomy from §G.7):
      * ``not_found_or_cross_tenant``
      * ``line_index_out_of_bounds``
      * ``content_shifted``
      * ``locked_paid``
      * ``already_deleted``

    Cap: 100 rows per call (``422 bulk_cap_exceeded``).  Empty rows
    → ``422 empty_rows``.

    Per-row semantics — see ``services.reports.uncategorized_line_deletes``.

    Per-invoice writes use ``find_one_and_update`` with an
    ``updated_at`` guard (G.3b): on mismatch we retry ONCE with a
    fresh read; if still contested every row targeting that
    invoice is added to ``skipped[]`` with code
    ``content_shifted``.
    """
    tenant_id = tenant["id"]

    # ── Cap + empty payload guards ─────────────────────────
    rows = list(body.rows or [])
    if not rows:
        raise HTTPException(
            422, {"code": "empty_rows",
                    "detail": "rows is required"},
        )
    if len(rows) > _UNCAT_HARD_DELETE_CAP:
        raise HTTPException(
            422, {"code": "bulk_cap_exceeded",
                    "cap": _UNCAT_HARD_DELETE_CAP,
                    "attempted": len(rows)},
        )

    bulk_op_id = str(uuid.uuid4())
    invoice_ids = list({r.invoice_id for r in rows})

    # ── Load invoices (tenant-scoped) ──────────────────────
    inv_docs: Dict[str, Dict[str, Any]] = {}
    async for inv in db.quotes.find(
        {"tenant_id": tenant_id, "id": {"$in": invoice_ids},
          "doc_type": "invoice"},
        {"_id": 0},
    ):
        inv_docs[inv["id"]] = inv

    # ── Plan the deletions (pure) ──────────────────────────
    payload_typed = [
        DeleteRequest(
            invoice_id=r.invoice_id,
            line_item_index=r.line_item_index,
            description=r.description,
            unit_price=r.unit_price,
        )
        for r in rows
    ]
    plan = plan_deletions(
        payload_typed,
        invoices_by_id=inv_docs,
        acknowledged_lock_bypass=body.acknowledged_lock_bypass,
    )

    deleted = 0
    skipped_out: List[Dict[str, Any]] = [
        {"invoice_id": s.invoice_id,
          "line_item_index": s.line_item_index,
          "code": s.code}
        for s in plan.skipped
    ]

    # ── Apply per-invoice with updated_at guard (G.3b) ─────
    for invoice_id, planned in plan.deletes_by_invoice.items():
        inv = inv_docs.get(invoice_id)
        if inv is None:                                            # defensive
            continue
        applied = False
        for attempt in (1, 2):
            # ── Signal any pre-mutation snapshotting hooks ──
            # snapshot_before_mutation is our canonical audit
            # for document_versions.  Best-effort; never raises.
            try:
                from services.documents.versions import (
                    snapshot_before_mutation, has_signature,
                    invalidate_signature_if_present,
                )
            except Exception:                                      # noqa: BLE001
                snapshot_before_mutation = None                    # type: ignore
                has_signature = None                                # type: ignore
                invalidate_signature_if_present = None              # type: ignore

            had_signature = False
            if has_signature is not None:
                try:
                    had_signature = await has_signature(
                        doc_id=invoice_id, tenant_id=tenant_id,
                    )
                except Exception:                                  # noqa: BLE001
                    had_signature = False

            apply_result = apply_deletions(inv, planned)
            totals = recompute_totals(inv, apply_result.new_line_items)
            new_updated_at = _now().isoformat()

            update_doc = {
                "line_items": apply_result.new_line_items,
                "subtotal": totals["subtotal"],
                "tax": totals["tax"],
                "total": totals["total"],
                "remaining_balance": totals["remaining_balance"],
                "updated_at": new_updated_at,
            }

            if snapshot_before_mutation is not None:
                try:
                    await snapshot_before_mutation(
                        doc_type="invoice",
                        doc_id=invoice_id,
                        tenant_id=tenant_id,
                        current_doc=inv,
                        new_doc={**inv, **update_doc},
                        saved_by_user=user,
                        status_at_edit=(inv.get("status") or "draft"),
                        reason="line_item.hard_delete",
                        signature_invalidated=had_signature,
                    )
                except Exception:                                  # noqa: BLE001
                    logger.exception(
                        "[uncategorized.hard_delete] snapshot_before_mutation "
                        "failed for invoice=%s",
                        invoice_id,
                    )

            # ── Optimistic-lock write ──────────────────────
            guard = {"id": invoice_id, "tenant_id": tenant_id,
                      "doc_type": "invoice"}
            captured_updated_at = inv.get("updated_at")
            if captured_updated_at is not None:
                guard["updated_at"] = captured_updated_at
            r = await db.quotes.find_one_and_update(
                guard, {"$set": update_doc},
                return_document=False,
            )
            if r is None and attempt == 1:
                # Concurrent write — retry once with a fresh read.
                fresh = await db.quotes.find_one(
                    {"id": invoice_id, "tenant_id": tenant_id,
                      "doc_type": "invoice"},
                    {"_id": 0},
                )
                if fresh is None:
                    for p in planned:
                        skipped_out.append({
                            "invoice_id": invoice_id,
                            "line_item_index": p.line_item_index,
                            "code": "not_found_or_cross_tenant",
                        })
                    break
                # Re-run planner against the fresh doc for THIS
                # invoice only (other invoices already succeeded /
                # were skipped).
                re_plan = plan_deletions(
                    [
                        DeleteRequest(
                            invoice_id=invoice_id,
                            line_item_index=p.line_item_index,
                            description=p.description,
                            unit_price=p.unit_price,
                        )
                        for p in planned
                    ],
                    invoices_by_id={invoice_id: fresh},
                    acknowledged_lock_bypass=body.acknowledged_lock_bypass,
                )
                # Surface any newly-skipped rows from the retry planner.
                for s in re_plan.skipped:
                    skipped_out.append({
                        "invoice_id": s.invoice_id,
                        "line_item_index": s.line_item_index,
                        "code": s.code,
                    })
                planned = re_plan.deletes_by_invoice.get(invoice_id, [])
                if not planned:
                    break
                inv = fresh
                continue
            if r is None:
                # Second attempt also lost the race — bail with
                # content_shifted for the whole group.
                for p in planned:
                    skipped_out.append({
                        "invoice_id": invoice_id,
                        "line_item_index": p.line_item_index,
                        "code": "content_shifted",
                    })
                break

            # ── Success — write audit rows + invalidate sig ─
            audit_at = datetime.now(timezone.utc)
            audit_rows = []
            for snap in apply_result.deleted_snapshots:
                original_idx = snap.get("_pre_delete_index", -1)
                audit_rows.append(build_audit_row(
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    line_item_index=original_idx,
                    line_snapshot=snap,
                    actor=user,
                    bulk_op_id=bulk_op_id,
                    deletion_reason=body.deletion_reason,
                    at=audit_at,
                ))
            if audit_rows:
                try:
                    await db.audit_logs.insert_many(
                        audit_rows, ordered=False,
                    )
                except Exception:                                  # noqa: BLE001
                    logger.exception(
                        "[uncategorized.hard_delete] audit_logs "
                        "insert_many failed for invoice=%s",
                        invoice_id,
                    )
            if invalidate_signature_if_present is not None and had_signature:
                try:
                    await invalidate_signature_if_present(
                        doc_type="invoice",
                        doc_id=invoice_id,
                        tenant_id=tenant_id,
                        collection=db.quotes,
                    )
                except Exception:                                  # noqa: BLE001
                    logger.exception(
                        "[uncategorized.hard_delete] signature "
                        "invalidation failed for invoice=%s",
                        invoice_id,
                    )
            deleted += len(apply_result.deleted_snapshots)
            applied = True
            break

        if not applied:
            continue

    logger.info(
        "[uncategorized.hard_delete] actor=%s bulk_op=%s "
        "requested=%d deleted=%d skipped=%d",
        (user or {}).get("email"), bulk_op_id,
        len(rows), deleted, len(skipped_out),
    )
    return {
        "bulk_op_id": bulk_op_id,
        "requested": len(rows),
        "deleted": deleted,
        "skipped": skipped_out,
    }


@router.post(
    "/reports/uncategorized-items/bulk-hard-delete/{bulk_op_id}/undo",
    operation_id="reports.uncategorizedItems.bulkHardDelete.undo",
)
async def undo_bulk_hard_delete_uncategorized_lines(
    bulk_op_id: str,
    user: dict = Depends(_require_admin_dep),
    tenant: dict = Depends(_get_current_tenant),
) -> Dict[str, Any]:
    """Replay every ``line_item.hard_delete`` audit row for the
    given ``bulk_op_id`` by re-inserting each snapshot at the END
    of its target invoice's ``line_items`` array (G.6c ruling —
    original indexes are unsafe under concurrent edits).

    Idempotency: any audit row that already has a paired
    ``line_item.hard_delete.undo`` row with ``undo_of=<bulk_op_id>``
    is skipped so a second call is a no-op.

    Cross-tenant guard: rows are filtered by
    ``tenant_id == caller_tenant``, and any target invoice not
    found for the tenant is skipped.

    Response shape::

        {
            "bulk_op_id":     <str>,
            "audit_rows":     <int>,   # total rows found
            "restored":       <int>,   # newly re-inserted lines
            "already_undone": <int>,   # rows that had a prior undo
            "skipped":        [{"invoice_id": str,
                                 "reason": "invoice_not_found"}, ...],
        }
    """
    tenant_id = tenant["id"]

    # Load all delete-audit rows for the group.
    delete_rows: List[Dict[str, Any]] = []
    async for r in db.audit_logs.find(
        {"tenant_id": tenant_id,
          "event": "line_item.hard_delete",
          "bulk_op_id": bulk_op_id},
        {"_id": 0},
    ):
        delete_rows.append(r)
    if not delete_rows:
        raise HTTPException(
            404, {"code": "bulk_op_not_found",
                    "bulk_op_id": bulk_op_id},
        )

    # Load all EXISTING undo rows so idempotent re-runs are a
    # no-op per audit-row id.
    already_undone_audit_ids: set = set()
    async for r in db.audit_logs.find(
        {"tenant_id": tenant_id,
          "event": "line_item.hard_delete.undo",
          "undo_of": bulk_op_id},
        {"_id": 0, "undone_audit_id": 1},
    ):
        aid = r.get("undone_audit_id")
        if aid:
            already_undone_audit_ids.add(aid)

    # Group audit rows by invoice_id.
    by_invoice: Dict[str, List[Dict[str, Any]]] = {}
    for row in delete_rows:
        if row.get("id") in already_undone_audit_ids:
            continue
        by_invoice.setdefault(row["invoice_id"], []).append(row)

    restored = 0
    already_undone_count = len(delete_rows) - sum(len(v) for v in by_invoice.values())
    skipped_out: List[Dict[str, Any]] = []

    for invoice_id, audit_rows in by_invoice.items():
        inv = await db.quotes.find_one(
            {"id": invoice_id, "tenant_id": tenant_id,
              "doc_type": "invoice"},
            {"_id": 0},
        )
        if inv is None:
            skipped_out.append({
                "invoice_id": invoice_id,
                "reason": "invoice_not_found",
            })
            continue

        current_lines = list(inv.get("line_items") or [])
        undo_audit_rows: List[Dict[str, Any]] = []
        for ar in audit_rows:
            snap = dict(ar.get("line_snapshot") or {})
            if not snap:
                continue
            new_index = len(current_lines)
            current_lines.append(snap)
            undo_audit_rows.append(build_undo_audit_row(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                line_snapshot=snap,
                reinserted_at_index=new_index,
                actor=user,
                undo_of_bulk_op_id=bulk_op_id,
            ))
            # Stamp the ``undone_audit_id`` link so idempotency
            # works on subsequent undo calls.
            undo_audit_rows[-1]["undone_audit_id"] = ar.get("id")

        # Recompute totals + persist.
        totals = recompute_totals(inv, current_lines)
        await db.quotes.update_one(
            {"id": invoice_id, "tenant_id": tenant_id,
              "doc_type": "invoice"},
            {"$set": {
                "line_items": current_lines,
                "subtotal": totals["subtotal"],
                "tax": totals["tax"],
                "total": totals["total"],
                "remaining_balance": totals["remaining_balance"],
                "updated_at": _now().isoformat(),
            }},
        )
        if undo_audit_rows:
            try:
                await db.audit_logs.insert_many(
                    undo_audit_rows, ordered=False,
                )
            except Exception:                                  # noqa: BLE001
                logger.exception(
                    "[uncategorized.hard_delete.undo] audit insert "
                    "failed for invoice=%s",
                    invoice_id,
                )
        restored += len(undo_audit_rows)

    logger.info(
        "[uncategorized.hard_delete.undo] actor=%s bulk_op=%s "
        "restored=%d already_undone=%d",
        (user or {}).get("email"), bulk_op_id,
        restored, already_undone_count,
    )
    return {
        "bulk_op_id": bulk_op_id,
        "audit_rows": len(delete_rows),
        "restored": restored,
        "already_undone": already_undone_count,
        "skipped": skipped_out,
    }



# ═══════════════════════════════════════════════════════════════════
# Startup index ensure (called by scripts.ensure_indexes)
# ═══════════════════════════════════════════════════════════════════
async def ensure_indexes() -> None:
    """Feb-2026 · Bulk hard-delete for uncategorized line items —
    startup index installer.  Registered in
    ``scripts.ensure_indexes`` ROUTER_ENSURE_INDEXES.

    Adds ONE compound sparse partial index on ``audit_logs`` so the
    undo lookup (``{tenant_id, event, bulk_op_id}``) resolves in
    logarithmic time rather than scanning the entire tenant slice
    of ``audit_logs`` (26k rows at write time; grows linearly).

    Every index plan runs in its own ``try/except`` per the H.2
    self-healing pattern — a single failure logs at WARN but never
    blocks the rest.
    """
    async def _one(coll: str, keys, opts: dict) -> None:
        try:
            await db[coll].create_index(keys, **opts)
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[income_categories] index ensure failed on %s (%s): "
                "%s: %s",
                coll, opts.get("name"), type(exc).__name__, exc,
            )

    await _one(
        "audit_logs",
        [("tenant_id", 1), ("event", 1), ("bulk_op_id", 1)],
        {
            "name": "audit_logs_tenant_event_bulkop",
            "background": True,
            "partialFilterExpression": {"bulk_op_id": {"$exists": True}},
        },
    )



# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · TD-income-category-dupes-audit · Phase 1
#
# Admin audit endpoint — read-only, tenant-scoped — surfaces every
# ``income_categories`` duplicate set in the caller's tenant plus
# the inline-string-only line-item inventory. Operator runs this
# in production BEFORE invoking the Phase 2 migration script so
# the canonical pick per duplicate set is operator-reviewed.
#
# Normalization MUST match ``_resolve_line_category_identity`` from
# ``routers/dashboard_revenue.py`` (commit ``05e6cf590``): both the
# ``income_categories.name`` key and the inline-string ``line_item
# .category`` field normalize to ``(value or "").strip().lower()``.
# Reusing the SAME rule means the Phase 2 migration groups the
# same way the audit shows — no drift between what the operator
# previews and what the script does.
#
# ref_count semantics: number of ``invoice_line_items`` rows on
# paid+unpaid invoices (soft-delete filtered) in this tenant whose
# ``line_items.income_category_id`` equals the row's ``id``. Pure
# FK pointer count — does NOT follow inline-string back-references.
# would_be_canonical = row with MAX ref_count in the set; ties
# broken by lexicographic ``name`` (deterministic across runs).
# ═════════════════════════════════════════════════════════════════════
def _normalize_cat_name(raw: Any) -> str:
    """Byte-identical to ``_resolve_line_category_identity``'s
    inline-string normalization (``.strip().lower()``). Kept inline
    rather than imported so a future refactor of the dashboard
    helper cannot silently drift the audit grouping."""
    return str(raw or "").strip().lower()


@router.get("/admin/income-categories/duplicates")
async def income_categories_duplicates_audit(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Audit endpoint for the Phase 2 duplicate-merge migration.

    Returns every ``income_categories`` duplicate set in the
    caller's tenant (grouped by normalized name), plus a tally of
    line items whose ``income_category_id`` is null but whose
    inline ``category`` string could be FK-rooted post-migration.
    Pure read; never mutates.
    """
    _require_admin(user)
    tid = tenant["id"]

    # ── 1. Pull every live income_categories row in the tenant.
    cats_cursor = db.income_categories.find(
        {"tenant_id": tid, "$or": [
            {"deleted_at": None}, {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "id": 1, "name": 1, "is_archived": 1},
    )
    cats: List[Dict[str, Any]] = await cats_cursor.to_list(10_000)

    # ── 2. ref_count per income_categories.id — one aggregation
    # over invoice line items in the tenant.  Only count real
    # pointers (non-null ``income_category_id``).
    ref_counts: Dict[str, int] = {}
    agg_cursor = db.quotes.aggregate([
        {"$match": {"tenant_id": tid, "doc_type": "invoice",
                      "$or": [{"deleted_at": None},
                              {"deleted_at": {"$exists": False}}]}},
        {"$unwind": "$line_items"},
        {"$match": {"line_items.income_category_id":
                       {"$ne": None, "$exists": True}}},
        {"$group": {"_id": "$line_items.income_category_id",
                     "count": {"$sum": 1}}},
    ])
    async for row in agg_cursor:
        rid = row.get("_id")
        if rid:
            ref_counts[rid] = int(row.get("count") or 0)

    # ── 3. Group income_categories by normalized name; emit sets
    # with >1 row as duplicates.  Determinism: sort rows within a
    # set by (-ref_count, name) so would_be_canonical is stable.
    from collections import defaultdict
    by_norm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in cats:
        by_norm[_normalize_cat_name(c.get("name"))].append(c)

    duplicate_sets: List[Dict[str, Any]] = []
    for norm, rows in sorted(by_norm.items()):
        if len(rows) < 2 or not norm:
            continue
        enriched = [{
            "id":    r["id"],
            "name":  r.get("name") or "",
            "ref_count": int(ref_counts.get(r["id"], 0)),
            "is_archived": bool(r.get("is_archived")),
        } for r in rows]
        # Rank by ref_count desc, then name asc (lex tiebreak).
        enriched.sort(key=lambda r: (-r["ref_count"], r["name"]))
        for i, r in enumerate(enriched):
            r["would_be_canonical"] = (i == 0)
        duplicate_sets.append({
            "canonical_name_normalized": norm,
            "rows": enriched,
        })

    # ── 4. Inline-string-only line items — rows with no
    # ``income_category_id`` but a non-empty inline ``category``
    # string.  Group by normalized string; mark whether the
    # normalized value resolves to any ``income_categories`` row
    # (post-dedupe canonical pick) so the operator can preview the
    # s1 backfill coverage.
    name_to_canonical: Dict[str, str] = {}
    for norm, rows in by_norm.items():
        if not norm:
            continue
        enriched = [{
            "id": r["id"],
            "rc": int(ref_counts.get(r["id"], 0)),
            "name": r.get("name") or "",
        } for r in rows]
        enriched.sort(key=lambda r: (-r["rc"], r["name"]))
        name_to_canonical[norm] = enriched[0]["id"]

    inline_by_norm: Dict[str, int] = defaultdict(int)
    inline_cursor = db.quotes.aggregate([
        {"$match": {"tenant_id": tid, "doc_type": "invoice",
                      "$or": [{"deleted_at": None},
                              {"deleted_at": {"$exists": False}}]}},
        {"$unwind": "$line_items"},
        {"$match": {"$and": [
            {"$or": [{"line_items.income_category_id": None},
                     {"line_items.income_category_id":
                          {"$exists": False}}]},
            {"line_items.category": {"$ne": None, "$ne": "",
                                        "$exists": True}},
        ]}},
        {"$group": {"_id": "$line_items.category",
                     "count": {"$sum": 1}}},
    ])
    async for row in inline_cursor:
        norm = _normalize_cat_name(row.get("_id"))
        if norm:
            inline_by_norm[norm] += int(row.get("count") or 0)

    inline_rows: List[Dict[str, Any]] = []
    for norm, cnt in sorted(inline_by_norm.items(),
                                key=lambda kv: (-kv[1], kv[0])):
        inline_rows.append({
            "normalized":       norm,
            "count":            cnt,
            "resolves_to_fk_id": name_to_canonical.get(norm),
        })

    return {
        "tenant_id":                 tid,
        "duplicate_sets":            duplicate_sets,
        "inline_string_only_line_items": {
            "total":             sum(inline_by_norm.values()),
            "by_normalized_name": inline_rows,
        },
    }
