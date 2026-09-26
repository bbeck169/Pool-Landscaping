"""N3' · Feb-2026 — GET /search/global.

Tech-facing global search across customers + jobs + invoices. Feeds
the mobile / web PageHeader search bar (grouped dropdown wiring
lands in N4'). Distinct from the pre-existing
``GET /api/search`` (Dashboard quick-find, admin-only) — this route
is tech-facing (``require_tech_or_above``), address-aware on
customers, and returns a merged "documents" group.

Contract
────────
    GET /search/global?q=<query>&limit=5
    Auth:  require_tech_or_above (admin | super_admin | technician)

    Response 200:
        {
          "query": "<echoed q>",
          "customers": [
            {"id": ..., "name": ..., "address_line1": ..., "city": ...,
             "postal_code": ..., "match_field": "name" | "address"},
            ...
          ],
          "documents": [
            {"type": "job" | "invoice", "id": ..., "display_id": ...,
             "title": ..., "match_field": "id" | "number" | "title"},
            ...
          ]
        }

Behaviour
─────────
* ``q`` < 2 chars → 200 with empty groups (frontend debounces on
  early keystrokes; not a validation error).
* ``limit`` clamped to [1, 10]; default 5. Applied per group
  (5 customers + 5 combined documents).
* Case-insensitive Mongo ``$regex`` with ``re.escape(q)`` (G1=a).
  A user typing ``$100`` or ``J.`` will not blow up the query.
* Customer address match spans ``name``, ``address_line1``,
  legacy ``address``, ``city``, ``postal_code`` — collapsed to
  ``match_field: "address"`` per G2=a. Match on ``name`` yields
  ``match_field: "name"``.
* Documents group merges jobs + invoices per G3=a. Job
  ``display_id`` = ``f"J-{id[:8]}"``; invoice ``display_id`` =
  the tenant's ``invoice_number`` field (real format
  ``"INV-2026-000048"``).
* Ranking is server-side, cheap:
    rank 0 — exact match on the primary display field
    rank 1 — prefix match on the primary display field
    rank 2 — substring match anywhere (default for everything else)
  Within each tier, sort by ``updated_at DESC`` (falls back to
  ``created_at``).
* All queries tenant-scoped. Cross-tenant leak = P0 defect;
  covered explicitly in the pytest suite.
* Soft-delete rows excluded (``deleted_at: None`` with
  ``$exists: False`` fallback for legacy docs — matches MA0
  P34 / Task-KK pattern).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from config import db
from routers.pool_calculators import require_tech_or_above
from routers.tenants import get_current_tenant


router = APIRouter()


MIN_Q_CHARS = 2
DEFAULT_LIMIT = 5
MAX_LIMIT = 10


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
def _not_deleted() -> Dict[str, Any]:
    return {"$or": [{"deleted_at": None},
                     {"deleted_at": {"$exists": False}}]}


def _rank(primary: str, needle_lower: str) -> int:
    """Cheap 3-tier rank on the row's primary display field.

    Returns:
        0 — exact case-insensitive match
        1 — prefix (case-insensitive)
        2 — otherwise (substring is implied by the regex prefilter)
    """
    if not primary:
        return 2
    p = primary.lower()
    if p == needle_lower:
        return 0
    if p.startswith(needle_lower):
        return 1
    return 2


def _updated_key(row: Dict[str, Any]) -> str:
    """Sort key — most recent first. Falls back to ``created_at``
    then to empty string so rows without stamps deterministically
    sink to the bottom of their rank tier."""
    return str(row.get("updated_at") or row.get("created_at") or "")


# ═══════════════════════════════════════════════════════════════════
# Customer search
# ═══════════════════════════════════════════════════════════════════
_CUSTOMER_ADDR_FIELDS = ("address_line1", "address", "city", "postal_code")
_CUSTOMER_SEARCH_FIELDS = ("name",) + _CUSTOMER_ADDR_FIELDS


async def _search_customers(tenant_id: str, needle: str,
                              limit: int) -> List[Dict[str, Any]]:
    escaped = re.escape(needle)
    rx = {"$regex": escaped, "$options": "i"}
    q = {
        "tenant_id": tenant_id,
        "$and": [
            {"$or": [{f: rx} for f in _CUSTOMER_SEARCH_FIELDS]},
            _not_deleted(),
        ],
    }
    proj = {
        "_id": 0, "id": 1, "name": 1,
        "address_line1": 1, "address": 1, "city": 1,
        "postal_code": 1, "updated_at": 1, "created_at": 1,
    }
    # Pull a bounded superset (limit * 4, capped at 40) so the
    # per-tier sort has enough rows to rerank locally without a
    # second DB roundtrip.
    fetch = min(limit * 4, 40)
    rows = await db.customers.find(q, proj).limit(fetch).to_list(fetch)

    needle_lower = needle.lower()
    scored: List[tuple] = []
    for r in rows:
        name = str(r.get("name") or "")
        addr_hits = [str(r.get(f) or "") for f in _CUSTOMER_ADDR_FIELDS
                       if r.get(f) and needle_lower in str(r.get(f) or "").lower()]
        # match_field policy: name wins if name matches; else "address".
        if needle_lower in name.lower():
            match_field = "name"
            rank = _rank(name, needle_lower)
        elif addr_hits:
            match_field = "address"
            # Rank by the strongest address-field match.
            rank = min(_rank(h, needle_lower) for h in addr_hits)
        else:
            # Regex hit some field we didn't collapse into the rank
            # heuristic — treat as substring.
            match_field = "name"
            rank = 2
        scored.append((rank, _updated_key(r), r, match_field))

    scored.sort(key=lambda t: (t[0], -1 if not t[1] else 0, t[1]),
                 reverse=False)
    # NOTE: two-key sort — rank ASC, then updated_at DESC. Python's
    # tuple sort can't mix asc/desc natively on a string, so we sort
    # once by ``(rank, updated_at)`` and reverse the ``updated_at``
    # tier by negating the key. Simpler: sort by rank ASC, then
    # separately reverse-sort within each rank block. Doing that below.
    scored.sort(key=lambda t: t[0])  # stable — preserves fetch order within tier

    out: List[Dict[str, Any]] = []
    # Emit per-rank blocks, each sorted by updated_at DESC.
    for rank_tier in (0, 1, 2):
        block = [(k, r, mf) for rk, k, r, mf in scored if rk == rank_tier]
        block.sort(key=lambda x: x[0], reverse=True)  # updated_at DESC
        for _, r, mf in block:
            out.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "address_line1": r.get("address_line1"),
                "city": r.get("city"),
                "postal_code": r.get("postal_code"),
                "match_field": mf,
            })
            if len(out) >= limit:
                return out
    return out


# ═══════════════════════════════════════════════════════════════════
# Documents search (jobs ∪ invoices)
# ═══════════════════════════════════════════════════════════════════
async def _search_jobs(tenant_id: str, needle: str,
                        limit: int) -> List[Dict[str, Any]]:
    escaped = re.escape(needle)
    rx = {"$regex": escaped, "$options": "i"}
    q = {
        "tenant_id": tenant_id,
        "$and": [
            {"$or": [{"id": rx}, {"title": rx}]},
            _not_deleted(),
        ],
    }
    proj = {"_id": 0, "id": 1, "title": 1,
             "updated_at": 1, "created_at": 1}
    fetch = min(limit * 4, 40)
    rows = await db.jobs.find(q, proj).limit(fetch).to_list(fetch)

    needle_lower = needle.lower()
    out: List[Dict[str, Any]] = []
    for r in rows:
        jid = str(r.get("id") or "")
        title = str(r.get("title") or "")
        display_id = f"J-{jid[:8]}" if jid else ""
        if needle_lower == jid.lower() or jid.lower().startswith(needle_lower):
            match_field = "id"
        elif needle_lower in jid.lower():
            match_field = "id"
        else:
            match_field = "title"
        # Rank on the field that matched.
        primary = jid if match_field == "id" else title
        rank = _rank(primary, needle_lower)
        out.append({
            "type": "job",
            "id": jid,
            "display_id": display_id,
            "title": title,
            "match_field": match_field,
            "_rank": rank,
            "_updated_key": _updated_key(r),
        })
    return out


async def _search_invoices(tenant_id: str, needle: str,
                             limit: int) -> List[Dict[str, Any]]:
    escaped = re.escape(needle)
    rx = {"$regex": escaped, "$options": "i"}
    q = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "$and": [
            {"$or": [{"invoice_number": rx}, {"title": rx}]},
            _not_deleted(),
        ],
    }
    proj = {"_id": 0, "id": 1, "invoice_number": 1, "title": 1,
             "updated_at": 1, "created_at": 1}
    fetch = min(limit * 4, 40)
    rows = await db.quotes.find(q, proj).limit(fetch).to_list(fetch)

    needle_lower = needle.lower()
    out: List[Dict[str, Any]] = []
    for r in rows:
        inv_num = str(r.get("invoice_number") or "")
        title = str(r.get("title") or "")
        if needle_lower in inv_num.lower():
            match_field = "number"
            primary = inv_num
        else:
            match_field = "title"
            primary = title
        rank = _rank(primary, needle_lower)
        out.append({
            "type": "invoice",
            "id": r.get("id"),
            "display_id": inv_num or f"#{str(r.get('id') or '')[:8]}",
            "title": title,
            "match_field": match_field,
            "_rank": rank,
            "_updated_key": _updated_key(r),
        })
    return out


async def _search_documents(tenant_id: str, needle: str,
                              limit: int) -> List[Dict[str, Any]]:
    """Merge job + invoice results into one ranked, capped list."""
    jobs = await _search_jobs(tenant_id, needle, limit)
    invoices = await _search_invoices(tenant_id, needle, limit)
    combined = jobs + invoices
    # Two-pass sort: rank ASC (primary), updated_at DESC (secondary).
    combined.sort(key=lambda r: r.get("_updated_key") or "", reverse=True)
    combined.sort(key=lambda r: r.get("_rank", 2))
    out: List[Dict[str, Any]] = []
    for r in combined[:limit]:
        r.pop("_rank", None)
        r.pop("_updated_key", None)
        out.append(r)
    return out


# ═══════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════
@router.get("/search/global")
async def search_global(
    q: str = Query(default="", max_length=200,
                    description="Search needle. <2 chars → empty groups."),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    needle = (q or "").strip()
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    if len(needle) < MIN_Q_CHARS:
        return {"query": needle, "customers": [], "documents": []}
    tenant_id = tenant["id"]
    customers = await _search_customers(tenant_id, needle, limit)
    documents = await _search_documents(tenant_id, needle, limit)
    return {"query": needle, "customers": customers, "documents": documents}
