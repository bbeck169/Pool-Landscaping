"""Task N Round 2 · Phase N.6 · Feb-2026 — shared archive query builder.

Extracted from ``routers/service_reports.notes_archive`` so both the
tenant-wide archive endpoint and the per-customer notes-history
endpoint can share the exact same aggregation shape, filter surface,
and row-projection semantics.

Only the initial ``$match`` differs between the two callers:

- Tenant-wide archive: ``{tenant_id, submitted_at $type string,
  <note-existence $or>}`` + optional filters.
- Per-customer notes-history: adds ``customer_id`` constraint via
  the joined ``job_doc.customer_id`` (post-lookup match).

Everything else — joins, sort, facet paginate — is identical.  A
future change to the row shape or the join semantics lands in one
file and both endpoints inherit.

Pure functions.  No DB call inside; caller owns the ``aggregate``
execution.  This keeps the module trivially unit-testable and
avoids importing the mongo motor client at module scope.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


TEMPLATE_INDUSTRY_MAP: Dict[str, str] = {
    "pool": "Pool",
    "landscape": "Landscaping",
    "generic": "Service",
}
NOTES_ARCHIVE_MAX_PAGE_SIZE = 100


def map_industry(template: Optional[str]) -> str:
    """Locked mapping per Phase N.1 audit.  ``None`` / missing falls
    through to ``Service`` — in current production data that branch
    only fires against test rows tagged ``TEST_p37_j_*``."""
    return TEMPLATE_INDUSTRY_MAP.get((template or "").lower(), "Service")


def parse_date_range_iso(
    date_from: Optional[str], date_to: Optional[str],
) -> Dict[str, str]:
    """Convert ``YYYY-MM-DD`` inputs to a ``$gte`` / ``$lte`` fragment
    covering the full UTC day range (inclusive both ends).  Raises
    ``ValueError`` on any drift so the router can 400 with a
    field-specific error payload."""
    out: Dict[str, str] = {}
    if date_from:
        try:
            datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"date_from:{exc}")
        out["$gte"] = f"{date_from}T00:00:00Z"
    if date_to:
        try:
            datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"date_to:{exc}")
        out["$lte"] = f"{date_to}T23:59:59.999Z"
    return out


def build_initial_match(
    *, tenant_id: str,
    tech_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    industry: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build the pipeline's first-stage ``$match`` document.

    Returns ``None`` when the caller passed an ``industry`` string
    the map doesn't recognise — the router should short-circuit
    with an empty response (stale dropdown values shouldn't crash
    the archive).
    """
    match_stage: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "submitted_at": {"$type": "string"},
        "$or": [
            {"notes": {"$type": "string", "$ne": ""}},
            {"internal_notes": {"$type": "string", "$ne": ""}},
            {"customer_notes": {"$type": "string", "$ne": ""}},
        ],
    }
    if tech_id:
        match_stage["tech_id"] = tech_id
    _date_frag = parse_date_range_iso(date_from, date_to)
    if _date_frag:
        match_stage["submitted_at"] = {"$type": "string", **_date_frag}
    if industry:
        _wanted = [k for k, v in TEMPLATE_INDUSTRY_MAP.items()
                    if v.lower() == industry.lower()]
        if industry.lower() == "service":
            match_stage["$and"] = [
                {"$or": [
                    {"template": "generic"},
                    {"template": None},
                    {"template": {"$exists": False}},
                ]}
            ]
        elif _wanted:
            match_stage["template"] = _wanted[0]
        else:
            return None
    return match_stage


def build_joins_stages() -> List[Dict[str, Any]]:
    """Lookup + unwind stages that join ``jobs``, ``customers``, and
    ``users`` onto the SR row.  Shared by both callers verbatim."""
    return [
        {"$lookup": {
            "from": "jobs", "localField": "job_id",
            "foreignField": "id", "as": "job_doc",
        }},
        {"$unwind": {"path": "$job_doc", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from": "customers", "localField": "job_doc.customer_id",
            "foreignField": "id", "as": "cust_doc",
        }},
        {"$unwind": {"path": "$cust_doc", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from": "users",
            "let": {"tid": "$tech_id"},
            "pipeline": [
                {"$match": {"$expr": {"$or": [
                    {"$eq": ["$id", "$$tid"]},
                    {"$eq": ["$technician_id", "$$tid"]},
                ]}}},
                {"$limit": 1},
                {"$project": {"_id": 0, "name": 1, "id": 1}},
            ],
            "as": "tech_doc",
        }},
        {"$unwind": {"path": "$tech_doc", "preserveNullAndEmptyArrays": True}},
    ]


def build_facet_stage(page: int, page_size: int) -> Dict[str, Any]:
    """The final ``$facet`` — rows + count."""
    skip = (page - 1) * page_size
    return {"$facet": {
        "rows": [
            {"$skip": skip},
            {"$limit": page_size},
            {"$project": {
                "_id": 0,
                "sr_id": "$id",
                "job_id": 1,
                "submitted_at": 1,
                "customer_id": "$cust_doc.id",
                "customer_name": "$cust_doc.name",
                "tech_id": 1,
                "tech_name": "$tech_doc.name",
                "template": 1,
                "notes": 1,
                "internal_notes": 1,
                "customer_notes": 1,
            }},
        ],
        "total_count": [{"$count": "n"}],
    }}


def build_archive_pipeline(
    *, tenant_id: str, page: int, page_size: int,
    customer_search: Optional[str] = None,
    tech_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    industry: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Full tenant-wide archive pipeline OR customer-scoped
    notes-history pipeline (when ``customer_id`` is supplied).

    Returns ``None`` when the caller's ``industry`` filter doesn't
    map to a known template value (short-circuit → empty response).
    """
    match_stage = build_initial_match(
        tenant_id=tenant_id, tech_id=tech_id,
        date_from=date_from, date_to=date_to, industry=industry,
    )
    if match_stage is None:
        return None

    pipeline: List[Dict[str, Any]] = [
        {"$match": match_stage},
        {"$sort": {"submitted_at": -1}},
        *build_joins_stages(),
    ]

    # Customer scope — applied AFTER the jobs $lookup so we can
    # filter on ``job_doc.customer_id`` cleanly.  Same stage
    # position as the customer_search regex.
    if customer_id:
        pipeline.append({"$match": {
            "job_doc.customer_id": customer_id,
        }})

    if customer_search:
        _pattern = re.escape(customer_search.strip())
        if _pattern:
            pipeline.append({"$match": {
                "cust_doc.name": {"$regex": _pattern, "$options": "i"},
            }})

    pipeline.append(build_facet_stage(page, page_size))
    return pipeline


def normalise_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the industry mapping + null-safe defaults to a single
    projected row from the pipeline.  Both endpoints emit rows in
    this identical shape so the frontend can render them with the
    same ``<NotesHistoryList>`` component."""
    return {
        "sr_id": row.get("sr_id"),
        "job_id": row.get("job_id"),
        "submitted_at": row.get("submitted_at"),
        "customer_id": row.get("customer_id"),
        "customer_name": row.get("customer_name") or "",
        "tech_id": row.get("tech_id"),
        "tech_name": row.get("tech_name") or "",
        "industry": map_industry(row.get("template")),
        "notes": row.get("notes") or "",
        "internal_notes": row.get("internal_notes") or "",
        "customer_notes": row.get("customer_notes") or "",
    }
