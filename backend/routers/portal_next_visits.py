"""Feb-2026 · Pool Service PS-D — Smart Portal Tiles endpoint.

``GET /api/portal/dashboard/next-visits`` — returns the SOONEST
future scheduled job per service-type category.  Eligibility is
derived from the customer's own job history: any job (past,
present, future, any status) in a given canonical category marks
that category as "eligible".  Future scheduled jobs populate the
tile; eligible categories without a future job surface a
placeholder with ``next_visit_at: null``.

Service-type categories (canonical set — new to PS-D, not tied
to any existing enum since ``billing_plans.service`` and
``jobs.service_type`` are both free-text strings across the
codebase):
    * ``pool``            → matches services containing "pool"
    * ``landscape``       → matches "landscape" / "landscaping"
    * ``filter_cleaning`` → matches "filter" / "cartridge"

Eligibility rules (Feb-2026 · simplified jobs-driven gate — SHA
to be inserted by caller; this comment preserves the audit trail
noting that the previous ``billing_plans.active`` + ``customers
.service_category`` hybrid gate was retired here):
    1. Eligible category — ANY row in ``db.jobs`` for this
       (tenant_id, customer_id) with a ``service_type`` /
       ``job_type`` / ``service_title`` matching a canonical
       category keyword.  Status + schedule are IGNORED at
       this step; a draft or long-past job still marks the
       category as eligible.
    2. Future scheduled job (populates the tile) — a row in
       ``db.jobs`` with ``scheduled_at`` (or ``scheduled_date``)
       >= now AND status in {scheduled, active, in_progress}
       whose category matches an eligible key.  When no future
       job exists for an eligible category, a placeholder tile
       with ``next_visit_at: null`` is emitted.

Output is filtered to the three canonical categories and returned
in the display order Pool → Landscape → Filter Cleaning.  Empty
list when the customer has no jobs matching ANY canonical
category — the portal hides the tile row entirely.

Tenant + customer isolation is enforced via the customer_id
derived from the JWT session (never from body / query).  Cross-
customer read attempts hit the 403 in ``_require_customer``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from utils import get_current_user
from routers.tenants import get_current_tenant


router = APIRouter()


# Canonical category set + substring matchers.  Order in this
# dict is the DISPLAY ORDER the endpoint returns rows in.
_CATEGORY_MATCHERS: List[Tuple[str, Tuple[str, ...]]] = [
    ("pool",            ("pool",)),
    ("landscape",       ("landscape", "landscaping")),
    ("filter_cleaning", ("filter cleaning", "filter clean",
                          "cartridge cleaning", "cartridge clean",
                          "filter", "cartridge")),
]


def _match_category(text: Optional[str]) -> Optional[str]:
    """Substring-match a free-text service label against the
    canonical category set.  Returns the category key or None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for key, hits in _CATEGORY_MATCHERS:
        for h in hits:
            if h in t:
                return key
    return None


def _job_category(job: Dict[str, Any]) -> Optional[str]:
    """Resolve a job's canonical category via the shipped
    service_type / job_type / service_title fallback chain."""
    return (_match_category(job.get("service_type"))
              or _match_category(job.get("job_type"))
              or _match_category(job.get("service_title")))


def _require_customer(user: dict) -> str:
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    return user["customer_id"]


async def _resolve_tech_name(tenant_id: str,
                              tech_id: Optional[str]) -> Optional[str]:
    """Look up a technician's display name for the tile subline.
    Tries ``db.technicians`` (the canonical field-tech directory
    seeded across the codebase) then falls back to ``db.users``.
    Returns None so the frontend can render its "Tech to be
    assigned" fallback."""
    if not tech_id:
        return None
    row = await db.technicians.find_one(
        {"id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "display_name": 1},
    )
    if row:
        return (row.get("name") or row.get("display_name")
                  or None)
    row = await db.users.find_one(
        {"id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "display_name": 1, "email": 1},
    )
    if row:
        return (row.get("name") or row.get("display_name")
                  or row.get("email") or None)
    return None


def _job_scheduled_iso(job: Dict[str, Any]) -> Optional[str]:
    """Prefer ``scheduled_at`` (full ISO with tz).  Fall back to
    ``scheduled_date`` (date-only) so a legacy row without a tz
    still lands on the tile."""
    return (job.get("scheduled_at")
              or job.get("scheduled_date")
              or None)


@router.get("/portal/dashboard/next-visits")
async def portal_next_visits(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    tid = tenant["id"]

    # ── (1) Jobs-driven eligibility · Feb-2026 — ANY job on this
    # (tenant, customer) marks its canonical category as eligible,
    # regardless of status or schedule.  Replaces the retired
    # ``billing_plans.active`` + ``customers.service_category``
    # hybrid gate so a customer whose plans haven't been seeded
    # (but whose jobs have been scheduled) still sees tiles.
    eligible_keys: set = set()
    try:
        async for job in db.jobs.find(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "service_type": 1, "job_type": 1,
             "service_title": 1},
        ):
            k = _job_category(job)
            if k:
                eligible_keys.add(k)
    except Exception as exc:                                     # pragma: no cover
        logger.warning(
            "[ps-d] jobs eligibility read failed for tenant=%s "
            "cid=%s: %s", tid, cid, exc,
        )
        # Fail-quietly per portal UX standard — return empty and
        # the frontend hides the tile row.
        return {"next_visits": []}

    if not eligible_keys:
        return {"next_visits": []}

    # ── (2) Future scheduled jobs (soonest-first).
    now_iso = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )
    today_iso = datetime.now(timezone.utc).date().isoformat()
    # ``scheduled_at`` may be null on some rows; ``scheduled_date``
    # is date-only.  We query for EITHER field being in the future
    # so both shapes qualify.
    future_query: Dict[str, Any] = {
        "tenant_id": tid,
        "customer_id": cid,
        "status": {"$in": ["scheduled", "active", "in_progress"]},
        "$or": [
            {"scheduled_at":   {"$gte": now_iso}},
            {"scheduled_date": {"$gte": today_iso}},
        ],
    }
    try:
        cursor = db.jobs.find(future_query, {
            "_id": 0, "id": 1, "service_type": 1, "service_title": 1,
            "job_type": 1, "scheduled_at": 1, "scheduled_date": 1,
            "scheduled_time": 1, "technician_id": 1,
        }).sort([("scheduled_at", 1), ("scheduled_date", 1)])
        future_jobs = await cursor.to_list(200)
    except Exception as exc:                                     # pragma: no cover
        logger.warning(
            "[ps-d] jobs read failed for tenant=%s cid=%s: %s",
            tid, cid, exc,
        )
        return {"next_visits": []}

    # ── (3) Group by category → keep only the soonest job per
    # eligible category.  Rows already sorted ascending, so the
    # first hit is the winner.
    by_key: Dict[str, Dict[str, Any]] = {}
    for job in future_jobs:
        k = _job_category(job)
        if not k or k not in eligible_keys:
            continue
        if k not in by_key:
            by_key[k] = job

    # ── (4) Resolve tech names + emit in canonical display order.
    # Placeholder rows (eligible category, no future job) emit
    # null datetime + null tech + null visit_id so the FE can
    # distinguish real vs empty tiles — β1 render-path contract
    # preserved byte-identical.
    out: List[Dict[str, Any]] = []
    for key, _hits in _CATEGORY_MATCHERS:
        if key not in eligible_keys:
            continue
        job = by_key.get(key)
        if job is None:
            out.append({
                "service_type":  key,
                "next_visit_at": None,
                "tech_name":     None,
                "visit_id":      None,
            })
            continue
        tech_name = await _resolve_tech_name(
            tid, job.get("technician_id"),
        )
        out.append({
            "service_type":  key,
            "next_visit_at": _job_scheduled_iso(job),
            "tech_name":     tech_name,
            "visit_id":      job.get("id"),
        })
    return {"next_visits": out}
