"""Feb 2026 · Dashboard global-search endpoint.

`GET /api/search?q=<query>&limit=5&entities=customers,jobs,invoices,leads`

Returns a compact grouped result set so the Dashboard's quick-find
search bar can render "Customers · N / Jobs · N / Invoices · N /
Leads · N" without hitting four separate endpoints (and without
duplicating tenant/soft-delete scoping in the frontend).

Scope:
  * Tenant-scoped via ``get_current_tenant``.
  * Role gate: ``admin | super_admin | manager`` — matches Dashboard
    visibility. Techs / customers get 403.
  * Skips soft-deleted rows (customers.deleted_at, jobs.deleted_at,
    quotes.deleted_at, leads.deleted_at).
  * Case-insensitive substring match across:
      - customers → name, email, phone
      - jobs → title, customer_name
      - invoices (db.quotes where doc_type=="invoice") →
        invoice_number, customer_name, title
      - leads → name, email, phone
  * ``limit`` caps top-N per entity (default 5, max 25). Global
    typing latency stays low even on tenants with 10k customers.
  * Regex is escaped so a user typing ``$100`` won't blow up the
    query. No fuzzy matching — plain substring is fast + predictable.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user


router = APIRouter()


_VALID_ENTITIES = ("customers", "jobs", "invoices", "leads")


def _require_dashboard_role(user: dict) -> None:
    """Match Dashboard visibility — admin / super_admin / manager only."""
    role = (user or {}).get("role", "")
    if role not in ("admin", "super_admin", "owner", "manager"):
        raise HTTPException(status_code=403, detail="Dashboard access required")


def _not_deleted() -> dict:
    """Soft-delete predicate — accepts both ``None`` and missing field."""
    return {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]}


def _build_or_regex(needle: str, fields: List[str]) -> List[Dict[str, Any]]:
    """Escape ``needle`` and build a case-insensitive $or clause."""
    escaped = re.escape(needle)
    return [{f: {"$regex": escaped, "$options": "i"}} for f in fields]


def _tenant_filter(tenant_id: str, needle: str, fields: List[str]) -> dict:
    """Compose tenant + soft-delete + case-insensitive search predicate.

    Two ``$or`` keys can't co-exist in one Mongo query dict (later key
    wins). Merge them under ``$and`` so both predicates apply.
    """
    return {
        "tenant_id": tenant_id,
        "$and": [
            _not_deleted(),
            {"$or": _build_or_regex(needle, fields)},
        ],
    }


async def _search_customers(tenant_id: str, q: str, limit: int) -> List[dict]:
    query = _tenant_filter(tenant_id, q, ["name", "email", "phone"])
    proj = {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1}
    docs = await db.customers.find(query, proj).limit(limit).to_list(limit)
    return [
        {
            "id": d.get("id"),
            "primary": d.get("name") or "(unnamed)",
            "secondary": d.get("email") or d.get("phone") or "",
        }
        for d in docs
        if d.get("id")
    ]


async def _search_jobs(tenant_id: str, q: str, limit: int) -> List[dict]:
    query = _tenant_filter(tenant_id, q, ["title", "customer_name"])
    proj = {"_id": 0, "id": 1, "title": 1, "customer_name": 1, "status": 1}
    docs = await db.jobs.find(query, proj).limit(limit).to_list(limit)
    return [
        {
            "id": d.get("id"),
            "primary": d.get("title") or "(untitled job)",
            "secondary": d.get("customer_name") or d.get("status") or "",
        }
        for d in docs
        if d.get("id")
    ]


async def _search_invoices(tenant_id: str, q: str, limit: int) -> List[dict]:
    query = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "$and": [
            _not_deleted(),
            {"$or": _build_or_regex(
                q, ["invoice_number", "customer_name", "title"],
            )},
        ],
    }
    proj = {
        "_id": 0, "id": 1,
        "invoice_number": 1, "customer_name": 1,
        "title": 1, "total": 1,
    }
    docs = await db.quotes.find(query, proj).limit(limit).to_list(limit)
    out: List[dict] = []
    for d in docs:
        rid = d.get("id")
        if not rid:
            continue
        num = d.get("invoice_number") or ""
        primary = f"Invoice {num}" if num else (d.get("title") or "(untitled invoice)")
        total = d.get("total")
        total_str = ""
        try:
            if total is not None:
                total_str = f"${float(total):,.2f}"
        except (TypeError, ValueError):
            total_str = ""
        secondary = " · ".join(
            [x for x in (d.get("customer_name") or "", total_str) if x]
        )
        out.append({"id": rid, "primary": primary, "secondary": secondary})
    return out


async def _search_leads(tenant_id: str, q: str, limit: int) -> List[dict]:
    query = _tenant_filter(tenant_id, q, ["name", "email", "phone"])
    proj = {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "status": 1}
    docs = await db.leads.find(query, proj).limit(limit).to_list(limit)
    return [
        {
            "id": d.get("id"),
            "primary": d.get("name") or "(unnamed lead)",
            "secondary": d.get("email") or d.get("phone") or d.get("status") or "",
        }
        for d in docs
        if d.get("id")
    ]


_ENTITY_HANDLERS = {
    "customers": _search_customers,
    "jobs": _search_jobs,
    "invoices": _search_invoices,
    "leads": _search_leads,
}


@router.get("/search")
async def global_search(
    q: str = Query("", description="Search string; empty returns empty groups"),
    limit: int = Query(5, ge=1, le=25),
    entities: str = Query(
        "customers,jobs,invoices,leads",
        description="Comma-separated entity list to search",
    ),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, List[dict]]:
    _require_dashboard_role(user)

    # Parse + validate entity filter. Unknown names are silently
    # dropped so the frontend can pass future entities without a
    # backend deploy racing ahead.
    requested = [e.strip().lower() for e in (entities or "").split(",")]
    active = [e for e in requested if e in _VALID_ENTITIES]
    if not active:
        active = list(_VALID_ENTITIES)

    # Empty-query short-circuit — return empty groups for every
    # requested entity so the caller can render skeletons/empty
    # states without a second render. Keeps typing latency snappy.
    stripped = (q or "").strip()
    if not stripped:
        return {e: [] for e in active}

    tenant_id = tenant.get("id") or ""
    if not tenant_id:
        return {e: [] for e in active}

    out: Dict[str, List[dict]] = {}
    for name in active:
        handler = _ENTITY_HANDLERS.get(name)
        if not handler:
            out[name] = []
            continue
        try:
            out[name] = await handler(tenant_id, stripped, limit)
        except Exception:
            # Fail-open per entity so a broken index on one collection
            # doesn't kill the whole search response.
            out[name] = []
    return out
