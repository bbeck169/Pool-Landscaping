"""Pricebook × Profit-Reporting Phase 1 · Feb-2026 — reference-count
endpoints for the Categories admin archive-with-warn dialog.

Two GET endpoints — one per category axis — return the number of
pricebook items and historical line items that reference a category.
Frontend surfaces the counts inside the "Are you sure?" archive
dialog so an admin sees the impact before flipping ``is_archived`` to
True.

Rationale (locked with human on §7.2):
    * We do NOT block archive.
    * We DO warn with counts.
    * A historical doc that references an archived category gets an
      "Archived category" badge next to the category chip on the
      admin doc view (see PhaseC line-item chip in the frontend).

Endpoints:
    GET /api/income-categories/{cid}/references
    GET /api/service-categories/{cid}/references

Response shape:
    {
        "category_id": str,
        "kind": "income" | "service",
        "pricebook_item_count": int,   # active pricebook rows
        "line_item_count": int,        # invoices+quotes historical
        "is_archived": bool,
    }

Admin-only (403 otherwise), per-tenant, best-effort counts (uses
``count_documents`` — never streams the docs).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user


router = APIRouter()


def _require_admin(user: dict) -> None:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


async def _count_references(
    tenant_id: str, cid: str, *, field_on_item: str, field_on_line: str,
) -> dict:
    """Count both pricebook and line-item references.

    Args:
        tenant_id: current tenant scope.
        cid: category id to look up.
        field_on_item: name of the FK column on ``db.items``
            (``income_category_id`` or ``service_category_id``).
        field_on_line: name of the FK column on line-items inside
            ``db.quotes[.line_items[]]``. Same key as ``field_on_item``.
    """
    pricebook_q = {
        "tenant_id": tenant_id,
        field_on_item: cid,
        # Exclude soft-deleted / archived pricebook rows so the count
        # reflects only rows that will still surface on the pricebook
        # list. ``active=False`` rows are also filtered.
        "$and": [
            {"$or": [{"active": {"$ne": False}}, {"active": {"$exists": False}}]},
            {"$or": [{"is_archived": {"$ne": True}}, {"is_archived": {"$exists": False}}]},
        ],
    }
    pricebook_count = await db.items.count_documents(pricebook_q)

    # Line items live nested inside quote docs (both quote + invoice
    # doc_types share the same collection). ``elemMatch`` counts docs
    # that contain AT LEAST one referencing line — good enough for
    # the warn count. If we want a per-line count later, aggregate.
    quote_q = {
        "tenant_id": tenant_id,
        "line_items": {"$elemMatch": {field_on_line: cid}},
    }
    line_item_count = await db.quotes.count_documents(quote_q)

    return {
        "pricebook_item_count": int(pricebook_count),
        "line_item_count": int(line_item_count),
    }


@router.get("/income-categories/{cid}/references")
async def income_category_references(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    cat = await db.income_categories.find_one(
        {"id": cid, "tenant_id": tid}, {"_id": 0, "id": 1, "is_archived": 1},
    )
    if not cat:
        raise HTTPException(404, "not_found")
    counts = await _count_references(
        tid, cid,
        field_on_item="income_category_id",
        field_on_line="income_category_id",
    )
    return {
        "category_id": cid, "kind": "income",
        "is_archived": bool(cat.get("is_archived", False)),
        **counts,
    }


@router.get("/service-categories/{cid}/references")
async def service_category_references(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    cat = await db.service_categories.find_one(
        {"id": cid, "tenant_id": tid}, {"_id": 0, "id": 1, "is_archived": 1},
    )
    if not cat:
        raise HTTPException(404, "not_found")
    counts = await _count_references(
        tid, cid,
        field_on_item="service_category_id",
        field_on_line="service_category_id",
    )
    return {
        "category_id": cid, "kind": "service",
        "is_archived": bool(cat.get("is_archived", False)),
        **counts,
    }
