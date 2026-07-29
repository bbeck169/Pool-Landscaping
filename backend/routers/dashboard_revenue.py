"""Admin dashboard revenue tiles · Feb-2026.

Two endpoints:

* ``GET /api/admin/dashboard/revenue-by-category``  — sum invoiced
  revenue per invoice-line-item ``category`` within a date range.
* ``GET /api/admin/dashboard/revenue-forecast``  — booked (upcoming
  scheduled jobs) + recurring (billing_plans × cycles in range).

Category source of truth: **invoice line-items** (``db.quotes[]`` with
``doc_type=="invoice"``, ``line_items[].category``).  Service reports
do NOT carry a category field today; jobs carry ``service_type`` but
not the invoiced amount, so this is the only source that ties directly
to actual paid/invoiced revenue.

Recurring source of truth: **``db.billing_plans``** (``active=true``,
``frequency`` ∈ ``weekly|biweekly|monthly|quarterly|yearly``).
"""
from __future__ import annotations

import colorsys
import hashlib
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()

_UNCATEGORISED = "Uncategorised"


def _require_admin(user: dict) -> None:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


def _parse_range(start: str, end: str) -> tuple[str, str]:
    """Return normalized ISO strings for the range.  Accepts YYYY-MM-DD
    or full ISO timestamps; treats ``end`` as end-of-day inclusive."""
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "invalid start date")
    try:
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "invalid end date")
    # If end is midnight (date only), expand to end-of-day.
    if e.hour == 0 and e.minute == 0 and e.second == 0 and " " not in end:
        e = e.replace(hour=23, minute=59, second=59)
    if s > e:
        raise HTTPException(400, "start after end")
    return s.isoformat(), e.isoformat()


def _color_for(label: str) -> str:
    """Stable pastel hex derived from a hash of the category name."""
    h = int(hashlib.md5(label.encode("utf-8")).hexdigest()[:8], 16)  # noqa: S324 — non-security
    hue = (h % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.68)
    return "#" + "".join(f"{int(round(x * 255)):02x}" for x in (r, g, b))


# ═════════════════════════════════════════════════════════════════════
# Revenue by category
# ═════════════════════════════════════════════════════════════════════
@router.get("/admin/dashboard/revenue-by-category")
async def revenue_by_category(
    start: str = Query(..., description="ISO date (YYYY-MM-DD or full ISO)"),
    end: str = Query(..., description="ISO date (YYYY-MM-DD or full ISO)"),
    service_category_id: Optional[str] = Query(
        None,
        description=("Optional filter: only include revenue from line "
                      "items whose source pricebook item has this "
                      "service_category_id."),
    ),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    s_iso, e_iso = _parse_range(start, end)
    tenant_id = tenant["id"]

    # If a service_category_id filter is set, first resolve which
    # pricebook item ids belong to that business unit — line_items
    # carry the ``item_id`` field, so we can gate on membership.
    allowed_item_ids: Optional[set] = None
    if service_category_id:
        cur = db.items.find(
            {"tenant_id": tenant_id,
              "service_category_id": service_category_id},
            {"_id": 0, "id": 1},
        )
        allowed_item_ids = {row["id"] async for row in cur}
        if not allowed_item_ids:
            # No pricebook items match → guaranteed empty result.
            return {"items": [], "total": 0, "currency": "USD",
                    "range": {"start": s_iso, "end": e_iso},
                    "service_category_id": service_category_id}

    # Query: invoices in this tenant, dated inside the range. Match both
    # legacy ``created_at`` (which most seed data uses) and modern
    # ``issue_date`` / ``invoice_date``.  Docs are strings ISO-sortable.
    q = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "$or": [
            {"created_at": {"$gte": s_iso, "$lte": e_iso}},
            {"issue_date": {"$gte": s_iso, "$lte": e_iso}},
            {"invoice_date": {"$gte": s_iso, "$lte": e_iso}},
        ],
    }
    cur = db.quotes.find(q, {
        "_id": 0, "id": 1, "line_items": 1, "total": 1,
        "currency": 1, "status": 1,
    })

    totals: Dict[str, Dict[str, Any]] = {}
    currency = "USD"
    async for inv in cur:
        if inv.get("currency"):
            currency = inv["currency"]
        items = inv.get("line_items") or []
        for li in items:
            # Feb-2026 · Optional service-category filter — skip any
            # line whose source pricebook item is outside the set.
            if allowed_item_ids is not None:
                iid = li.get("item_id")
                if not iid or iid not in allowed_item_ids:
                    continue
            cat = (li.get("category") or "").strip() or _UNCATEGORISED
            amt = (float(li.get("quantity") or 0)
                    * float(li.get("unit_price") or 0))
            bucket = totals.setdefault(cat, {"amount": 0.0, "count": 0})
            bucket["amount"] += amt
            bucket["count"] += 1

    items_out: List[Dict[str, Any]] = []
    grand_total = 0.0
    for cat, b in sorted(totals.items(), key=lambda kv: kv[1]["amount"], reverse=True):
        items_out.append({
            "category": cat,
            "amount": round(b["amount"], 2),
            "count": b["count"],
            "color": _color_for(cat),
        })
        grand_total += b["amount"]

    return {
        "items": items_out,
        "total": round(grand_total, 2),
        "currency": currency,
        "range": {"start": s_iso, "end": e_iso},
    }


# ═════════════════════════════════════════════════════════════════════
# Income by SERVICE category — pricebook business-unit taxonomy.
# ═════════════════════════════════════════════════════════════════════
@router.get("/admin/dashboard/income-by-service-category")
async def income_by_service_category(
    start: str = Query(...),
    end: str = Query(...),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Group invoiced revenue by service-category (Pool, Landscaping,
    …) via the invoice line item's ``item_id`` → pricebook item
    (``db.items.service_category_id``) → ``db.service_categories``
    lookup chain.  Lines without an item_id, or whose item has no
    service_category_id, bucket into ``"Uncategorized"``."""
    _require_admin(user)
    s_iso, e_iso = _parse_range(start, end)
    tenant_id = tenant["id"]

    # Build item_id → service_category_id map (all items in this tenant).
    item_to_svc: Dict[str, str] = {}
    async for r in db.items.find(
        {"tenant_id": tenant_id, "service_category_id": {"$ne": None}},
        {"_id": 0, "id": 1, "service_category_id": 1},
    ):
        if r.get("service_category_id"):
            item_to_svc[r["id"]] = r["service_category_id"]

    # Build service_category_id → name map.
    svc_id_to_name: Dict[str, str] = {}
    async for c in db.service_categories.find(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1, "name": 1},
    ):
        svc_id_to_name[c["id"]] = c["name"]

    totals: Dict[str, Dict[str, Any]] = {}
    currency = "USD"
    cur = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice",
          "$or": [
              {"created_at": {"$gte": s_iso, "$lte": e_iso}},
              {"issue_date": {"$gte": s_iso, "$lte": e_iso}},
              {"invoice_date": {"$gte": s_iso, "$lte": e_iso}},
          ]},
        {"_id": 0, "id": 1, "line_items": 1, "currency": 1},
    )
    async for inv in cur:
        if inv.get("currency"):
            currency = inv["currency"]
        for li in (inv.get("line_items") or []):
            iid = li.get("item_id")
            svc_id = item_to_svc.get(iid) if iid else None
            svc_name = svc_id_to_name.get(svc_id) if svc_id else None
            bucket_key = svc_name or "Uncategorized"
            amt = (float(li.get("quantity") or 0)
                    * float(li.get("unit_price") or 0))
            b = totals.setdefault(bucket_key, {"amount": 0.0, "count": 0})
            b["amount"] += amt
            b["count"] += 1

    items_out: List[Dict[str, Any]] = []
    grand_total = 0.0
    for name, b in sorted(totals.items(),
                            key=lambda kv: kv[1]["amount"], reverse=True):
        color = "#94A3B8" if name == "Uncategorized" else _color_for(name)
        items_out.append({
            "category": name,
            "amount": round(b["amount"], 2),
            "count": b["count"],
            "color": color,
        })
        grand_total += b["amount"]

    return {
        "items": items_out,
        "total": round(grand_total, 2),
        "currency": currency,
        "range": {"start": s_iso, "end": e_iso},
    }


# ═════════════════════════════════════════════════════════════════════
# Revenue forecast (booked + recurring)
# ═════════════════════════════════════════════════════════════════════
_FREQ_DAYS = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 14,
    "bi-weekly": 14,
    "fortnightly": 14,
    "monthly": 30,
    "quarterly": 91,
    "yearly": 365,
    "annually": 365,
    "annual": 365,
}


def _cycles_in_range(freq: Optional[str], start_dt: datetime,
                      end_dt: datetime) -> int:
    """Approximate number of billing cycles that fall in the range.

    Uses inclusive day count divided by the cadence in days:
      • 30-day range at monthly (30-day freq) → 1 cycle
      • 60-day range at monthly              → 2 cycles
      • 90-day range at monthly              → 3 cycles
    """
    days = _FREQ_DAYS.get((freq or "").strip().lower())
    if not days:
        return 0
    # Inclusive day count — both endpoints belong to the window.
    inclusive_days = int((end_dt.date() - start_dt.date()).days) + 1
    if inclusive_days <= 0:
        return 0
    return inclusive_days // days


@router.get("/admin/dashboard/revenue-forecast")
async def revenue_forecast(
    start: str = Query(...),
    end: str = Query(...),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    s_iso, e_iso = _parse_range(start, end)
    tenant_id = tenant["id"]
    s_dt = datetime.fromisoformat(s_iso)
    e_dt = datetime.fromisoformat(e_iso)

    # ── Booked: upcoming jobs in the window ─────────────────────
    booked_q = {
        "tenant_id": tenant_id,
        "status": {"$in": ["scheduled", "confirmed"]},
        "scheduled_date": {"$gte": s_iso, "$lte": e_iso},
    }
    cur = db.jobs.find(booked_q, {
        "_id": 0, "id": 1, "price": 1, "total": 1, "quote_total": 1,
    })
    booked_amount = 0.0
    booked_count = 0
    async for j in cur:
        booked_count += 1
        # Prefer explicit ``price``; fall back to ``total`` / ``quote_total``.
        for key in ("price", "total", "quote_total"):
            v = j.get(key)
            if v is not None:
                try:
                    booked_amount += float(v)
                    break
                except (TypeError, ValueError):
                    continue

    # ── Recurring: active billing plans × cycles in range ───────
    rec_q = {"tenant_id": tenant_id, "active": True}
    cur = db.billing_plans.find(rec_q, {
        "_id": 0, "id": 1, "amount": 1, "frequency": 1,
    })
    recurring_amount = 0.0
    recurring_cycles_total = 0
    recurring_count = 0
    async for p in cur:
        recurring_count += 1
        cycles = _cycles_in_range(p.get("frequency"), s_dt, e_dt)
        recurring_cycles_total += cycles
        try:
            amt = float(p.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        recurring_amount += amt * cycles

    combined = round(booked_amount + recurring_amount, 2)

    return {
        "booked": {
            "amount": round(booked_amount, 2),
            "job_count": booked_count,
        },
        "recurring": {
            "amount": round(recurring_amount, 2),
            "subscription_count": recurring_count,
            "cycle_count": recurring_cycles_total,
        },
        "combined_total": combined,
        "currency": "USD",
        "range": {"start": s_iso, "end": e_iso},
    }
