"""Phase 2 · Feb-2026 · Quote-to-Lead Recipient — unified picker API."""
from __future__ import annotations
import re
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query
from config import db
from utils import require_admin_or_manager
from routers.tenants import get_current_tenant

router = APIRouter()


# P2 #4 · Feb-2026 — closed-lead statuses the search endpoint excludes
# by default. Mirrors the canonical status normalizer in routers/leads.py
# (``closed_won`` / ``closed_lost`` are the archive terminals). Operators
# can opt in to the full history via ``?include_closed=true``.
_CLOSED_LEAD_STATUSES = ["closed_won", "closed_lost"]


@router.get("/quote-recipients/search")
async def search_quote_recipients(
    q: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    include_closed: bool = Query(
        False,
        description=(
            "When False (default) lead rows with status closed_won / "
            "closed_lost are hidden. P2 #4 · Feb-2026."
        ),
    ),
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
) -> List[Dict[str, Any]]:
    term = (q or "").strip()
    tenant_id = tenant["id"]
    results: List[Dict[str, Any]] = []

    def _term_filter(base):
        if not term:
            return base
        rx = {"$regex": re.escape(term), "$options": "i"}
        return {"$and": [base, {"$or": [{"name": rx}, {"email": rx}, {"phone": rx}]}]}

    half = max(1, limit // 2) if term else limit
    async for row in db.customers.find(
        _term_filter({"tenant_id": tenant_id}),
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
    ).sort("name", 1).limit(half):
        results.append({
            "id": row.get("id"), "kind": "customer",
            "display_name": row.get("name") or "",
            "email": row.get("email") or "", "phone": row.get("phone") or "",
        })
    remaining = max(0, limit - len(results))
    if remaining <= 0:
        return results
    # P2 #4 · Feb-2026 — leads base filter + optional closed-status
    # exclusion. The guard is a predicate on the raw ``status`` field;
    # legacy docs with missing/null status fall through as "open" and
    # remain pickable (matches existing attribute flow where blank
    # status defaults to "new" on first write).
    _leads_filter: Dict[str, Any] = {"tenant_id": tenant_id}
    if not include_closed:
        _leads_filter["status"] = {"$nin": _CLOSED_LEAD_STATUSES}
    async for row in db.leads.find(
        _term_filter(_leads_filter),
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
    ).sort("name", 1).limit(remaining):
        results.append({
            "id": row.get("id"), "kind": "lead",
            "display_name": row.get("name") or "",
            "email": row.get("email") or "", "phone": row.get("phone") or "",
        })
    return results
