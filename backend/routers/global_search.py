"""Feb 2026 · Dashboard global-search endpoint.

`GET /api/search?q=<query>&limit=5&entities=customers,jobs,invoices,quotes,leads`

Returns a compact grouped result set so the Dashboard's quick-find
search bar can render "Customers · N / Jobs · N / Invoices · N /
Quotes · N / Leads · N" without hitting five separate endpoints
(and without duplicating tenant/soft-delete scoping in the frontend).

Scope:
  * Tenant-scoped via ``get_current_tenant``.
  * Role gate: ``admin | super_admin | manager`` — matches Dashboard
    visibility. Techs / customers get 403.
  * Skips soft-deleted rows (customers.deleted_at, jobs.deleted_at,
    quotes.deleted_at, leads.deleted_at).
  * Case-insensitive substring match across:
      - customers → name, email, phone (with digit-normalized
        matching so "555-1234" stored matches "5551234" typed), and
        address / billing_address
      - jobs → title, customer_name
      - invoices (db.quotes where doc_type=="invoice") →
        invoice_number, customer_name, title
      - quotes (db.quotes where doc_type=="quote") →
        quote_number, customer_name, title
      - leads → name, email, phone; filtered to ACTIVE statuses only
        (``new``, ``contacted``, ``quoted``).  Closed-won / closed-lost
        leads are excluded so the drop-down doesn't surface dead deals.
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


_VALID_ENTITIES = ("customers", "jobs", "invoices", "quotes", "leads")

# Canonical lead statuses that count as "active" for the drop-down —
# mirrors ``routers.leads._CANONICAL_STATUSES`` minus the closed
# terminals.  Closed-won / closed-lost leads are excluded so
# quick-find only surfaces deals still worth working.
_ACTIVE_LEAD_STATUSES = ["new", "contacted", "quoted"]


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


def _phone_digit_regex(needle: str) -> Optional[str]:
    """Return a regex that matches ``needle``'s digit sequence with
    ANY non-digit separators between adjacent digits, or ``None`` if
    the needle carries no digits at all.

    Example: ``needle="555-1234"`` → digits ``"5551234"`` → regex
    ``5\\D*5\\D*5\\D*1\\D*2\\D*3\\D*4`` which matches stored values
    like ``"(555) 123-4"``, ``"555.1234"``, ``"5551234"`` alike.
    Requires at least 3 digits so a single-letter typo like ``"a1"``
    doesn't produce a broad-brush regex on the phone index.
    """
    digits = re.sub(r"\D", "", needle or "")
    if len(digits) < 3:
        return None
    return r"\D*".join(re.escape(d) for d in digits)


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
    # INCOME-DRILLDOWN follow-up · Feb-2026 — search covers
    # name / email / phone plus the two persisted address strings
    # (service ``address`` + ``billing_address``).  Phone matching
    # additionally tries a digit-normalized regex so a user typing
    # ``5551234`` finds ``(555) 123-4`` and vice-versa.
    fields = ["name", "email", "phone", "address", "billing_address"]
    or_clauses = _build_or_regex(q, fields)
    phone_re = _phone_digit_regex(q)
    if phone_re:
        or_clauses.append({"phone": {"$regex": phone_re, "$options": "i"}})
    query = {
        "tenant_id": tenant_id,
        "$and": [_not_deleted(), {"$or": or_clauses}],
    }
    proj = {
        "_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
        "address": 1, "billing_address": 1,
    }
    docs = await db.customers.find(query, proj).limit(limit).to_list(limit)
    return [
        {
            "id": d.get("id"),
            "primary": d.get("name") or "(unnamed)",
            "secondary": (
                d.get("email")
                or d.get("phone")
                or d.get("address")
                or d.get("billing_address")
                or ""
            ),
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


async def _search_docs_by_doc_type(
    tenant_id: str, q: str, limit: int, *, doc_type: str, kind_label: str,
    number_field: str,
) -> List[dict]:
    """Shared code path for invoices + quotes — both live in
    ``db.quotes`` and are discriminated by ``doc_type``.  The two
    entities differ only in the number field (``invoice_number`` vs
    ``quote_number``) and the ``kind_label`` used to build the
    primary display string."""
    query = {
        "tenant_id": tenant_id,
        "doc_type": doc_type,
        "$and": [
            _not_deleted(),
            {"$or": _build_or_regex(
                q, [number_field, "customer_name", "title"],
            )},
        ],
    }
    proj = {
        "_id": 0, "id": 1,
        number_field: 1, "customer_name": 1,
        "title": 1, "total": 1,
    }
    docs = await db.quotes.find(query, proj).limit(limit).to_list(limit)
    out: List[dict] = []
    for d in docs:
        rid = d.get("id")
        if not rid:
            continue
        num = d.get(number_field) or ""
        primary = (
            f"{kind_label} {num}" if num
            else (d.get("title") or f"(untitled {kind_label.lower()})")
        )
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


async def _search_invoices(tenant_id: str, q: str, limit: int) -> List[dict]:
    return await _search_docs_by_doc_type(
        tenant_id, q, limit,
        doc_type="invoice", kind_label="Invoice",
        number_field="invoice_number",
    )


async def _search_quotes(tenant_id: str, q: str, limit: int) -> List[dict]:
    return await _search_docs_by_doc_type(
        tenant_id, q, limit,
        doc_type="quote", kind_label="Quote",
        number_field="quote_number",
    )


async def _search_leads(tenant_id: str, q: str, limit: int) -> List[dict]:
    # INCOME-DRILLDOWN follow-up · Feb-2026 — active statuses only.
    # Closed leads (``closed_won`` / ``closed_lost``) don't surface
    # in quick-find so the operator sees only in-flight deals.
    query = {
        "tenant_id": tenant_id,
        "status": {"$in": _ACTIVE_LEAD_STATUSES},
        "$and": [
            _not_deleted(),
            {"$or": _build_or_regex(q, ["name", "email", "phone"])},
        ],
    }
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
    "quotes": _search_quotes,
    "leads": _search_leads,
}


@router.get("/search")
async def global_search(
    q: str = Query("", description="Search string; empty returns empty groups"),
    limit: int = Query(5, ge=1, le=25),
    entities: str = Query(
        "customers,jobs,invoices,quotes,leads",
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
