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
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()

_UNCATEGORISED = "Uncategorized"

# Feb-2026 · Backlog #1 Part 1 — RFC-4122 UUID-shape guard. Legacy
# ``line_items[].category`` values sometimes hold an income_categories
# id (instead of the display name); the tile handler resolves id→name
# via a per-tenant map and, when unresolved, coerces to the
# ``Uncategorized`` bucket with ``is_orphan=True`` so an operator can
# spot leftover legacy data at a glance.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


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
    h = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)  # non-security: stable label→color slot
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

    # Feb-2026 · Priority 6 (Bug 3) — pricebook fallback.
    # Line items may be missing an inline ``category`` (older
    # invoices, manual entries, quote-cloned items). Build a single
    # ``item_id → category`` map so the aggregation below can fall
    # back to the source pricebook item's category before dropping
    # the row into the ``Uncategorized`` bucket. One tenant-scoped
    # scan; no N+1.
    item_id_to_category: Dict[str, str] = {}
    async for row in db.items.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "category": 1},
    ):
        cat = (row.get("category") or "").strip()
        if cat and row.get("id"):
            item_id_to_category[row["id"]] = cat

    # Feb-2026 · Backlog #1 Part 1 — income_categories id → name map.
    # Line items sometimes carry a raw id in ``category`` (legacy
    # write path) or explicitly in ``income_category_id`` (newer
    # writes). Either way the tile must render the human-readable
    # name; unresolved ids collapse into an orphan-flagged
    # Uncategorized bucket.
    income_cat_by_id: Dict[str, str] = {}
    async for row in db.income_categories.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "is_archived": 1},
    ):
        rid = row.get("id")
        name = (row.get("name") or "").strip()
        if rid and name:
            income_cat_by_id[rid] = name

    # Query: invoices in this tenant, dated inside the range. Match both
    # legacy ``created_at`` (which most seed data uses) and modern
    # ``issue_date`` / ``invoice_date``.  Docs are strings ISO-sortable.
    # Feb-2026 · Dashboard consistency ship — restrict to PAID invoices
    # so this tile is comparable to the ``/api/dashboard`` top-card
    # (lifetime paid) number. Prior behavior counted unpaid + overdue
    # + draft invoices, making the two tiles arithmetically
    # incomparable.  See the phantom-revenue investigation writeup.
    q = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "payment_status": "paid",
        # Feb-2026 · P2 Item 2 — merge date-range $or + soft-delete
        # $or into an explicit $and so neither clobbers the other.
        "$and": [
            {"$or": [
                {"created_at": {"$gte": s_iso, "$lte": e_iso}},
                {"issue_date": {"$gte": s_iso, "$lte": e_iso}},
                {"invoice_date": {"$gte": s_iso, "$lte": e_iso}},
            ]},
            {"$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ]},
        ],
    }
    cur = db.quotes.find(q, {
        "_id": 0, "id": 1, "line_items": 1, "total": 1,
        "currency": 1, "status": 1,
    })

    totals: Dict[str, Dict[str, Any]] = {}
    # Feb-2026 · Backlog #1 Part 1 — orphan tracker. Buckets whose
    # keys are UUID-shaped strings that failed id→name resolution
    # get flagged so the tile response carries ``is_orphan=True``.
    orphan_flag: Dict[str, bool] = {}
    orphan_ids_seen: set = set()
    currency = "USD"
    async for inv in cur:
        if inv.get("currency"):
            currency = inv["currency"]
        items = inv.get("line_items") or []
        # Feb-2026 · Priority 6 (Bug 3) — track how much of the
        # invoice's revenue we recognised via line items. If NONE
        # of the lines contribute (empty ``line_items``, all
        # filtered out by the service-category gate, or all-zero
        # priced), fall back to the invoice ``total`` under
        # ``Uncategorized`` so the tile total stays consistent
        # with the top-card lifetime paid figure. Never silently
        # drop a paid invoice from the chart.
        recognised_amount = 0.0
        line_matched_any = False
        for li in items:
            # Optional service-category filter — skip any line whose
            # source pricebook item is outside the set. When a
            # filter is active we still want the "was any line
            # matched" signal to reflect only in-scope lines, since
            # falling through to the invoice total would leak
            # out-of-scope revenue into the filtered tile.
            if allowed_item_ids is not None:
                iid = li.get("item_id")
                if not iid or iid not in allowed_item_ids:
                    continue
            line_matched_any = True
            # Category resolution order (Feb-2026 · Backlog #1 Part 1
            # — extended to resolve income_category id → name):
            #   1. ``line_item.income_category_id`` → name (canonical
            #      new write path; wins even when ``category`` is
            #      also set, because the id lookup is authoritative).
            #   2. inline ``line_item.category`` — if the value is
            #      UUID-shaped, treat as an id and resolve; if it
            #      resolves, use the name; if it doesn't, coerce to
            #      Uncategorized + flag orphan. Non-UUID strings pass
            #      through verbatim (existing behaviour).
            #   3. source pricebook item's ``category`` via item_id.
            #   4. ``Uncategorized`` (visibility over silence).
            cat: Optional[str] = None
            hit_orphan_id = False
            ic_id = (li.get("income_category_id") or "").strip()
            if ic_id:
                resolved = income_cat_by_id.get(ic_id)
                if resolved:
                    cat = resolved
                else:
                    hit_orphan_id = True
                    orphan_ids_seen.add(ic_id)
            if cat is None:
                inline_cat = (li.get("category") or "").strip()
                if inline_cat:
                    if _UUID_RE.match(inline_cat):
                        resolved = income_cat_by_id.get(inline_cat)
                        if resolved:
                            cat = resolved
                        else:
                            hit_orphan_id = True
                            orphan_ids_seen.add(inline_cat)
                    else:
                        cat = inline_cat
            if cat is None:
                pb_cat = item_id_to_category.get(li.get("item_id"))
                cat = pb_cat or _UNCATEGORISED
            amt = (float(li.get("quantity") or 0)
                    * float(li.get("unit_price") or 0))
            recognised_amount += amt
            bucket = totals.setdefault(cat, {"amount": 0.0, "count": 0})
            bucket["amount"] += amt
            bucket["count"] += 1
            if hit_orphan_id and cat == _UNCATEGORISED:
                orphan_flag[_UNCATEGORISED] = True

        # Priority 6 fallback — invoice with no matched lines (or
        # all-zero priced lines) is still real revenue. Charge the
        # invoice ``total`` to ``Uncategorized`` so it shows up in
        # the pie. Skip when a service-category filter is active
        # and NO in-scope lines matched — that invoice is out of
        # scope for the current view.
        try:
            inv_total = float(inv.get("total") or 0)
        except (TypeError, ValueError):
            inv_total = 0.0
        needs_fallback = (
            inv_total > 0
            and recognised_amount == 0
            and (allowed_item_ids is None or line_matched_any)
        )
        if needs_fallback:
            bucket = totals.setdefault(
                _UNCATEGORISED, {"amount": 0.0, "count": 0},
            )
            bucket["amount"] += inv_total
            bucket["count"] += 1

    items_out: List[Dict[str, Any]] = []
    grand_total = 0.0
    # Reverse the id-map so we can populate ``category_id`` when the
    # bucket key IS a known income_categories name.
    name_to_id: Dict[str, str] = {}
    for _cid, _cname in income_cat_by_id.items():
        # Prefer the first-seen id per name (case-insensitive collision
        # is rare; deterministic order comes from Mongo cursor).
        name_to_id.setdefault(_cname.lower(), _cid)
    for cat, b in sorted(totals.items(), key=lambda kv: kv[1]["amount"], reverse=True):
        # Feb-2026 · Priority 6 — surface the fallback bucket with
        # a distinct neutral grey (matches the sibling
        # income-by-service-category tile) so operators can spot
        # uncategorized revenue at a glance without hunting
        # through the legend.
        color = "#94A3B8" if cat == _UNCATEGORISED else _color_for(cat)
        # Feb-2026 · Backlog #1 Part 1 — additive response shape:
        # ``category_id`` (resolved when the bucket name maps back to
        # a live income_categories row), ``category_name`` (the
        # display label; NEVER a UUID), ``is_orphan`` (True iff this
        # bucket was created by consolidating unresolved-UUID line
        # items). FE reads ``category_name`` first with ``category``
        # as backward-compat fallback.
        cat_id: Optional[str] = None
        if cat != _UNCATEGORISED:
            cat_id = name_to_id.get(cat.lower())
        items_out.append({
            "category":      cat,                       # legacy alias
            "category_id":   cat_id,
            "category_name": cat,
            "amount":        round(b["amount"], 2),
            "count":         b["count"],
            "color":         color,
            "is_orphan":     bool(orphan_flag.get(cat, False)),
        })
        grand_total += b["amount"]

    return {
        "items": items_out,
        "total": round(grand_total, 2),
        "currency": currency,
        "range": {"start": s_iso, "end": e_iso},
        # Feb-2026 · Backlog #1 Part 1 — surfaces the set of orphan
        # ids we consolidated into Uncategorized. Consumed by the
        # future "you have N orphan-category line items, reassign?"
        # CTA (this phase adds the field only; no CTA yet).
        "orphan_ids": sorted(orphan_ids_seen),
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
    # Feb-2026 · Dashboard consistency ship — same ``payment_status``
    # filter as ``revenue_by_category`` above so both tiles agree
    # with the top-card lifetime paid number.
    cur = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice",
          "payment_status": "paid",
          # Feb-2026 · P2 Item 2 — as above, keep both $or clauses via $and.
          "$and": [
              {"$or": [
                  {"created_at": {"$gte": s_iso, "$lte": e_iso}},
                  {"issue_date": {"$gte": s_iso, "$lte": e_iso}},
                  {"invoice_date": {"$gte": s_iso, "$lte": e_iso}},
              ]},
              {"$or": [
                  {"deleted_at": None},
                  {"deleted_at": {"$exists": False}},
              ]},
          ]},
        {"_id": 0, "id": 1, "line_items": 1, "currency": 1, "total": 1},
    )
    async for inv in cur:
        if inv.get("currency"):
            currency = inv["currency"]
        # Feb-2026 · Priority 6 (Bug 3) — mirror the fallback that
        # ``revenue_by_category`` now applies: recognise the
        # invoice ``total`` under ``Uncategorized`` when no line
        # items produced any revenue (empty ``line_items`` array
        # OR every line has zero qty × unit_price). Prevents the
        # sibling tile from silently under-counting paid revenue
        # relative to the top-card lifetime number.
        recognised_amount = 0.0
        for li in (inv.get("line_items") or []):
            iid = li.get("item_id")
            svc_id = item_to_svc.get(iid) if iid else None
            svc_name = svc_id_to_name.get(svc_id) if svc_id else None
            bucket_key = svc_name or "Uncategorized"
            amt = (float(li.get("quantity") or 0)
                    * float(li.get("unit_price") or 0))
            recognised_amount += amt
            b = totals.setdefault(bucket_key, {"amount": 0.0, "count": 0})
            b["amount"] += amt
            b["count"] += 1
        try:
            inv_total = float(inv.get("total") or 0)
        except (TypeError, ValueError):
            inv_total = 0.0
        if inv_total > 0 and recognised_amount == 0:
            b = totals.setdefault("Uncategorized", {"amount": 0.0, "count": 0})
            b["amount"] += inv_total
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
    from utils import not_deleted_filter as _nd
    cur = db.jobs.find({**booked_q, **_nd()}, {
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
