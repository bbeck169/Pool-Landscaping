"""P2 #6 · Feb-2026 · Service-category dashboard breakdown.

Serves ``GET /api/dashboard/service-category-breakdown`` — the data
source for the admin Dashboard "By Service Category" tile row.

Returns a 4-bucket aggregate keyed on ``customers.service_category``:

  * ``pool``, ``landscaping``, ``both`` buckets each carry
    ``{customers, active_jobs, mtd_revenue}``.
  * ``unset`` bucket carries only ``{customers}`` (ops signal — if
    this count is high, the backfill script needs to run).

Behavior correction (Feb-2026, user ticket): a customer tagged
``service_category = "both"`` is counted in the **pool AND
landscaping AND both** tiles — not just the ``both`` tile.  The
union semantics apply to all three dimensions (customer count,
active jobs, MTD revenue).  Rationale: a customer whose services
include pool should appear in "Pool" counts (and clicking the
Pool tile deep-links to the Pool customer list, which has the
matching union-filter semantic at
``routers/customers.py::list_customers``).

Bucket membership tuples per customer:
    service_category == "pool"        -> ("pool",)
    service_category == "landscaping" -> ("landscaping",)
    service_category == "both"        -> ("pool", "landscaping", "both")
    unset (null / missing / invalid)  -> ()   (only ``unset`` tile)

RBAC: admin + manager only.  Technicians / customers get 403.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends

from config import db
from utils import require_admin_or_manager
from routers.tenants import get_current_tenant

router = APIRouter()


# Mirrors the active-job predicate used by customer_portal.py and
# dashboard_action_cards.py.  Kept narrow so a job that was flipped
# back to ``requested`` (pre-triage) still counts as active work.
_ACTIVE_JOB_STATUSES = ("scheduled", "pending", "in_progress", "active")

# Mirrors routers/payments_summary.py `_LIVE_STATUSES` discipline —
# only ``paid_at`` within the current calendar month contributes to
# MTD revenue, and the invoice doc_type gate is enforced below.
_PAID_PROJECTION = {
    "_id": 0, "customer_id": 1, "amount_paid": 1,
    "paid_at": 1, "doc_type": 1, "deleted_at": 1,
}

# Bucket-membership tuples per raw ``service_category`` value.  The
# empty tuple for ``unset`` means the customer increments only the
# ``unset`` tile's ``customers`` count (handled explicitly below);
# their jobs + MTD revenue are suppressed from the enum tiles (same
# as the original disjoint-count behavior for unset customers).
_CATEGORY_BUCKETS: Dict[str, Tuple[str, ...]] = {
    "pool":        ("pool",),
    "landscaping": ("landscaping",),
    "both":        ("pool", "landscaping", "both"),
}


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_iso(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


@router.get("/dashboard/service-category-breakdown")
async def service_category_breakdown(
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    tenant_id = tenant["id"]

    # ─── Step 1 · customer count per bucket.  "unset" matches
    # service_category == null OR missing — mirrors the list
    # filter at routers/customers.py.  A ``both`` customer
    # increments pool + landscaping + both via the union-tuple
    # lookup in ``_CATEGORY_BUCKETS``.
    buckets = {
        "pool": {"customers": 0, "active_jobs": 0, "mtd_revenue": 0.0},
        "landscaping": {"customers": 0, "active_jobs": 0, "mtd_revenue": 0.0},
        "both": {"customers": 0, "active_jobs": 0, "mtd_revenue": 0.0},
        "unset": {"customers": 0},
    }

    # Map customer_id → tuple of buckets they count in.  Each
    # downstream increment iterates the tuple so a single
    # ``both`` customer unions into three tiles.
    cust_buckets: Dict[str, Tuple[str, ...]] = {}
    async for row in db.customers.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "service_category": 1},
    ):
        cat = row.get("service_category")
        cid = row.get("id")
        tup = _CATEGORY_BUCKETS.get(cat, ())
        cust_buckets[cid] = tup
        if tup:
            for b in tup:
                buckets[b]["customers"] += 1
        else:
            buckets["unset"]["customers"] += 1

    # ─── Step 2 · active-job counts per bucket.  Union-counted
    # via ``cust_buckets``: a job owned by a ``both`` customer
    # increments pool + landscaping + both; a job owned by an
    # unset customer increments nothing (its tuple is empty).
    async for job in db.jobs.find(
        {"tenant_id": tenant_id,
         "status": {"$in": list(_ACTIVE_JOB_STATUSES)}},
        {"_id": 0, "customer_id": 1},
    ):
        for b in cust_buckets.get(job.get("customer_id"), ()):
            buckets[b]["active_jobs"] += 1

    # ─── Step 3 · MTD revenue per bucket.  Mirrors
    # payments_summary.collected_this_month contract: invoice docs
    # (doc_type=="invoice") whose paid_at ≥ month_start.  Same
    # union semantics as Step 2 — a both-customer's payment
    # contributes to pool + landscaping + both tile revenue.
    now_dt = datetime.now(timezone.utc)
    month_start = datetime(now_dt.year, now_dt.month, 1,
                              tzinfo=timezone.utc)
    async for inv in db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        _PAID_PROJECTION,
    ):
        if inv.get("deleted_at"):
            continue
        paid_dt = _parse_iso(inv.get("paid_at"))
        if not paid_dt or paid_dt < month_start:
            continue
        delta = _num(inv.get("amount_paid"))
        for b in cust_buckets.get(inv.get("customer_id"), ()):
            buckets[b]["mtd_revenue"] = round(
                buckets[b]["mtd_revenue"] + delta, 2,
            )

    return buckets
