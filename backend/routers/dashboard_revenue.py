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
from services.reports.service_category_bucketing import (
    bucket_service_category,
)
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

# ═════════════════════════════════════════════════════════════════════
# Shared category identity resolver (TD-revenue-by-category-id-grouping
# · Feb-2026)
#
# PRE-TICKET: ``revenue_by_category`` grouped the pie chart by the
# resolved NAME STRING (``totals.setdefault(cat, ...)``). Any
# spelling/casing drift ("Landscape" vs "Landscaping") split one real
# category into two tile rows; the sibling ``income_by_category_rows``
# drill-down also matched by name, so clicking "Hardscaping" could
# return Irrigation line items when the resolution ladder produced
# divergent names for the same semantic bucket.
#
# POST-TICKET: both routes resolve each line item to a stable
# ``(bucket_key, display_name)`` tuple. ``bucket_key`` is:
#
#   - ``f"id:{ic_id}"``   when the line has an ``income_category_id``
#     FK that resolves to a live ``income_categories`` row (OR an
#     inline ``category`` field that holds a UUID that resolves).
#     This is the authoritative identity — any two lines sharing an
#     FK bucket together regardless of inline-string drift.
#   - ``f"name:<lower>"`` when the line only carries an inline string
#     ``category`` (no FK, no UUID that resolves). Case-insensitive
#     normalization folds "Landscape" and "landscape" together;
#     "Landscape" and "Landscaping" still split, by design — a
#     migration (sibling ticket) is required to re-root those into
#     an id bucket.
#   - ``f"pb:<lower>"``   when the line has no FK AND no inline
#     ``category`` but its ``item_id`` resolves to a pricebook item
#     whose ``category`` field is set. Case-insensitive. Keeps the
#     Priority-6 (Bug 3) fallback path intact.
#   - ``"uncategorized"`` for the final catch-all.
#
# Grouping by ``bucket_key`` eliminates the name-string bug class
# while preserving a single human-readable ``display_name`` per
# bucket (first-seen wins; FK bucket's name comes from the id→name
# map so it stays canonical).
# ═════════════════════════════════════════════════════════════════════
_UNCATEGORISED_KEY = "uncategorized"


def _resolve_line_category_identity(
    li: Dict[str, Any],
    item_id_to_category: Dict[str, str],
    income_cat_by_id: Dict[str, str],
) -> tuple[str, str, bool]:
    """Return ``(bucket_key, display_name, hit_orphan_id)`` for a
    single invoice line item.

    ``hit_orphan_id`` is True when an ``income_category_id`` (or an
    inline-UUID ``category``) failed to resolve against the live
    ``income_categories`` map, so the caller can flag the resulting
    Uncategorized bucket with ``is_orphan=True`` (parity with the
    pre-ticket orphan-tracker behaviour)."""
    ic_id = (li.get("income_category_id") or "").strip()
    if ic_id:
        resolved = income_cat_by_id.get(ic_id)
        if resolved:
            return (f"id:{ic_id}", resolved, False)
        return (_UNCATEGORISED_KEY, _UNCATEGORISED, True)
    inline_cat = (li.get("category") or "").strip()
    if inline_cat:
        if _UUID_RE.match(inline_cat):
            resolved = income_cat_by_id.get(inline_cat)
            if resolved:
                return (f"id:{inline_cat}", resolved, False)
            return (_UNCATEGORISED_KEY, _UNCATEGORISED, True)
        return (f"name:{inline_cat.lower()}", inline_cat, False)
    pb_cat = item_id_to_category.get(li.get("item_id") or "")
    if pb_cat:
        pb_clean = pb_cat.strip()
        return (f"pb:{pb_clean.lower()}", pb_clean, False)
    return (_UNCATEGORISED_KEY, _UNCATEGORISED, False)


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
            # Feb-2026 · TD-revenue-by-category-id-grouping — group
            # by ``bucket_key`` (FK-rooted when possible) so
            # "Landscape" vs "Landscaping" never splits one real
            # category into two tile rows.  See the
            # ``_resolve_line_category_identity`` docstring for the
            # key semantics.
            bucket_key, cat_display, hit_orphan_id = \
                _resolve_line_category_identity(
                    li, item_id_to_category, income_cat_by_id,
                )
            if hit_orphan_id:
                ic_id = (li.get("income_category_id")
                           or li.get("category") or "").strip()
                if ic_id:
                    orphan_ids_seen.add(ic_id)
            amt = (float(li.get("quantity") or 0)
                    * float(li.get("unit_price") or 0))
            recognised_amount += amt
            bucket = totals.setdefault(bucket_key, {
                "amount": 0.0, "count": 0,
                "display_name": cat_display,
            })
            bucket["amount"] += amt
            bucket["count"] += 1
            if hit_orphan_id and bucket_key == _UNCATEGORISED_KEY:
                orphan_flag[_UNCATEGORISED_KEY] = True

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
                _UNCATEGORISED_KEY,
                {"amount": 0.0, "count": 0,
                 "display_name": _UNCATEGORISED},
            )
            bucket["amount"] += inv_total
            bucket["count"] += 1

    items_out: List[Dict[str, Any]] = []
    grand_total = 0.0
    for bucket_key, b in sorted(totals.items(),
                                     key=lambda kv: kv[1]["amount"],
                                     reverse=True):
        display_name = b.get("display_name") or _UNCATEGORISED
        # Feb-2026 · TD-revenue-by-category-id-grouping — surface
        # ``category_id`` directly from the bucket key when it is
        # FK-rooted (``id:<uuid>``); other key shapes (``name:``,
        # ``pb:``, ``uncategorized``) emit ``category_id = None`` so
        # the FE can route drill-down clicks via the fallback name
        # path for those buckets.
        cat_id: Optional[str] = None
        if bucket_key.startswith("id:"):
            cat_id = bucket_key[3:]
        color = ("#94A3B8" if bucket_key == _UNCATEGORISED_KEY
                   else _color_for(display_name))
        items_out.append({
            "category":      display_name,              # legacy alias
            "category_id":   cat_id,
            "category_name": display_name,
            # Feb-2026 · TD-revenue-by-category-id-grouping — the
            # tile legend click uses ``bucket_key`` as the stable
            # identity for the drill-down filter.  Non-FK buckets
            # (name:, pb:, uncategorized) still work via this key;
            # the drill-down endpoint accepts it under the
            # ``category_key`` query param.
            "bucket_key":    bucket_key,
            "amount":        round(b["amount"], 2),
            "count":         b["count"],
            "color":         color,
            "is_orphan":     bool(
                orphan_flag.get(bucket_key, False),
            ),
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
            # Feb-2026 · Income-by-service drill-down parity —
            # canonical bucketing lives in
            # ``services.reports.service_category_bucketing``
            # and is shared with the drill-down route.
            # Resolution precedence (unchanged):
            #   1. line.service_category_id
            #   2. pricebook item.service_category_id
            #   3. Uncategorized (empty / stale)
            _bucket_id, svc_name = bucket_service_category(
                li, item_to_svc, svc_id_to_name,
            )
            bucket_key = svc_name
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

    # CUSTOMER-RETENTION-ACCOUNT-CORRECTION-PARITY · Feb-2026 — fetch
    # the set of flagged customer ids ONCE and $nin-clamp it onto the
    # three customer-linked queries below (booked jobs, billing
    # plans, recurring job templates).  Empty set → no clause added,
    # preserves pre-flag behavior byte-for-byte.
    _excluded_cursor = db.customers.find(
        {"tenant_id": tenant_id, "account_correction": True},
        {"_id": 0, "id": 1},
    )
    _excluded_rows = await _excluded_cursor.to_list(length=None)
    _excluded_ids = [r["id"] for r in _excluded_rows if r.get("id")]

    # ── Booked: upcoming jobs in the window ─────────────────────
    # Feb-2026 · P1 Revenue Forecast under-count fix — expanded the
    # status filter from the legacy ``{scheduled, confirmed}`` pair
    # to include ``pending`` (``JobIn.status`` default per
    # ``models.py:275``), ``requested`` (job-request intake path in
    # ``routers/jobs.py::job_request`` L2201), and ``in_progress``
    # (post-arrival, pre-completion). Operator report: one-time
    # jobs created via the Edit Job modal with the DEFAULT status
    # (``pending``) carrying a price > 0 were being dropped from
    # the "Booked" sum. ``completed`` and ``cancelled`` continue to
    # be excluded (they're not forward-looking bookings).
    # The in-loop ``effective_price <= 0`` skip enforces the
    # product-locked ``price > 0`` filter so zero-price shells (no
    # revenue to forecast) don't inflate the booked job_count.
    booked_q = {
        "tenant_id": tenant_id,
        "status": {"$in": [
            "scheduled", "confirmed",
            "pending", "requested", "in_progress",
        ]},
        "scheduled_date": {"$gte": s_iso[:10], "$lte": e_iso},
    }
    if _excluded_ids:
        booked_q["customer_id"] = {"$nin": _excluded_ids}
    from utils import not_deleted_filter as _nd
    cur = db.jobs.find({**booked_q, **_nd()}, {
        "_id": 0, "id": 1, "price": 1, "total": 1, "quote_total": 1,
        "line_items": 1,
    })
    booked_amount = 0.0
    booked_count = 0
    async for j in cur:
        # TD-revenue-forecast-f7-defensive-hardening · Nov-2026 —
        # F7 priority branch.  Mirrors ``auto_invoice._build_line_
        # items`` at ``services/auto_invoice.py:60-104`` where
        # ``job.line_items[]`` wins over ``job.price`` when non-
        # empty.  Formula duplicated verbatim (NOT imported — the
        # auto-invoice helper is async + builds full invoice-
        # shaped rows with new ids, writeback flags, etc.; forecast
        # only needs the dollar sum).  Keep the two formulas in
        # lock-step: ``line_total_cents = round(qty * unit_price *
        # 100)``, sum across lines, convert back to dollars.
        job_lines = j.get("line_items") or []
        f7_price: Optional[float] = None
        if job_lines:
            total_cents = 0
            for src in job_lines:
                try:
                    qty = float(src.get("quantity") or 0)
                    unit_dollars = float(src.get("unit_price") or 0)
                except (TypeError, ValueError):
                    continue
                total_cents += int(round(qty * unit_dollars * 100))
            f7_price = total_cents / 100.0
        # Resolve effective price via the F7-first cascade:
        # ``line_items.sum → price → total → quote_total``.  Legacy
        # field-name fallback for records written by pre-Feb-2026
        # code paths is preserved verbatim.  Jobs with no non-null
        # numeric in the cascade OR a resolved value <= 0 are
        # SKIPPED entirely (not counted toward ``booked_count``
        # either) — zero-price jobs don't contribute to the
        # forward forecast.  The ``> 0`` gate at the bottom still
        # drops F7 jobs whose line_items sum to zero (e.g. a
        # single-row placeholder with ``unit_price=0``).
        effective_price: Optional[float] = None
        if f7_price is not None and f7_price > 0:
            effective_price = f7_price
        else:
            for key in ("price", "total", "quote_total"):
                v = j.get(key)
                if v is not None:
                    try:
                        effective_price = float(v)
                        break
                    except (TypeError, ValueError):
                        continue
        if effective_price is None or effective_price <= 0:
            continue
        booked_count += 1
        booked_amount += effective_price

    # ── Recurring: active billing plans × cycles in range ───────
    rec_q = {"tenant_id": tenant_id, "active": True}
    if _excluded_ids:
        rec_q["customer_id"] = {"$nin": _excluded_ids}
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

    # ── Phase H10 · Feb-2026 — recurring_jobs templates ─────────
    # Expected instances = enumerate next occurrences per template
    # in the window, MINUS dates already materialized in ``jobs``
    # (already counted under BOOKED).  Prevents double-counting.
    from routers.recurring_jobs import _next_occurrences
    tpls = await db.recurring_job_templates.find(
        {"tenant_id": tenant_id, "active": True},
        {"_id": 0, "id": 1, "frequency": 1, "day_of_week": 1,
         "day_of_month": 1, "interval_days": 1, "start_date": 1,
         "end_date": 1, "recurrence_never_ends": 1,
         "monthly_pattern": 1, "monthly_nth_week": 1,
         "monthly_weekday": 1, "allow_sunday": 1,
         "price_cents": 1},
    ).to_list(2000)
    s_date = s_dt.date() if hasattr(s_dt, "date") else s_dt
    e_date = e_dt.date() if hasattr(e_dt, "date") else e_dt
    # Existing materialized template-linked jobs in the window —
    # dedupe against these to avoid double-count.
    materialized = await db.jobs.find(
        {"tenant_id": tenant_id,
         "scheduled_date": {"$gte": s_iso[:10], "$lte": e_iso},
         "recurring_template_id": {"$ne": None}},
        {"_id": 0, "recurring_template_id": 1, "scheduled_date": 1},
    ).to_list(5000)
    seen_key = {
        (m.get("recurring_template_id"),
         (m.get("scheduled_date") or "")[:10])
        for m in materialized
    }
    recurring_jobs_amount = 0.0
    recurring_jobs_count = 0
    recurring_jobs_active_templates = 0
    for tpl in tpls:
        recurring_jobs_active_templates += 1
        try:
            occ = _next_occurrences(tpl, s_date, e_date, max_count=200)
        except Exception:
            continue
        price = float(tpl.get("price_cents") or 0) / 100.0
        for d in occ:
            key = (tpl.get("id"), d.isoformat())
            if key in seen_key:
                continue
            recurring_jobs_count += 1
            recurring_jobs_amount += price
    recurring_amount = round(recurring_amount + recurring_jobs_amount, 2)

    combined = round(booked_amount + recurring_amount, 2)

    return {
        "booked": {
            "amount": round(booked_amount, 2),
            "job_count": booked_count,
        },
        "recurring": {
            "amount": recurring_amount,
            "subscription_count": recurring_count,
            "cycle_count": recurring_cycles_total,
            # Phase H10 · Feb-2026 — recurring_jobs contribution
            # exposed on its own axis so the tile footer can render
            # "N recurring jobs + M subscriptions" cleanly and
            # H10 tests can lock partitioning.
            "recurring_job_count": recurring_jobs_count,
            "recurring_job_amount": round(recurring_jobs_amount, 2),
            "active_template_count": recurring_jobs_active_templates,
        },
        "combined_total": combined,
        "currency": "USD",
        "range": {"start": s_iso, "end": e_iso},
    }
