"""Feb-2026 · Pool Service PS-D — Smart Portal Tiles endpoint.

``GET /api/portal/dashboard/next-visits`` — returns the SOONEST
future scheduled job per service-type category, gated by the
customer having an active recurring subscription for that
category.

Service-type categories (canonical set — new to PS-D, not tied
to any existing enum since ``billing_plans.service`` and
``jobs.service_type`` are both free-text strings across the
codebase):
    * ``pool``            → matches services containing "pool"
    * ``landscape``       → matches "landscape" / "landscaping"
    * ``filter_cleaning`` → matches "filter" / "cartridge"

Eligibility rules (BOTH must hold per service type):
    1. Active subscription — a row in ``db.billing_plans`` with
       ``active: True`` whose ``service`` contains a category
       keyword.
    2. Future scheduled job — a row in ``db.jobs`` with
       ``scheduled_at`` (or ``scheduled_date``) >= now AND
       status in {scheduled, active, in_progress} whose
       ``service_type`` / ``job_type`` / ``service_title``
       contains a category keyword.

Output is filtered to the three canonical categories and returned
in the display order Pool → Landscape → Filter Cleaning.  Empty
list if no category qualifies — the portal hides the tile row.

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

    # ── (1) Active subscriptions → set of eligible category keys.
    active_keys: set = set()
    try:
        async for plan in db.billing_plans.find(
            {"tenant_id": tid, "customer_id": cid, "active": True},
            {"_id": 0, "service": 1},
        ):
            k = _match_category(plan.get("service"))
            if k:
                active_keys.add(k)
    except Exception as exc:                                     # pragma: no cover
        logger.warning(
            "[ps-d] billing_plans read failed for tenant=%s cid=%s"
            ": %s", tid, cid, exc,
        )
        # Fail-quietly per portal UX standard — return empty and
        # the frontend hides the tile row.
        return {"next_visits": []}

    if not active_keys:
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
    # category.  Rows already sorted ascending, so the first hit
    # is the winner.
    by_key: Dict[str, Dict[str, Any]] = {}
    for job in future_jobs:
        k = (_match_category(job.get("service_type"))
                or _match_category(job.get("job_type"))
                or _match_category(job.get("service_title")))
        if not k or k not in active_keys:
            continue
        if k not in by_key:
            by_key[k] = job

    # Feb-2026 · Portal β1 — operator ruling reversal on PS-D #8:
    # we no longer fail-quietly when a subscribed service has no
    # upcoming job.  Emit a placeholder tile (``next_visit_at=null``)
    # so the FE can render a "No visit scheduled" state per
    # eligible service.  Non-subscribed services still never surface
    # here — ``active_keys`` remains the eligibility gate.

    # ── (4) Resolve tech names + emit in canonical display order.
    # Placeholder rows (no future job) emit null datetime + null
    # tech + null visit_id so the FE can distinguish real vs
    # empty tiles.
    out: List[Dict[str, Any]] = []
    for key, _hits in _CATEGORY_MATCHERS:
        if key not in active_keys:
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
