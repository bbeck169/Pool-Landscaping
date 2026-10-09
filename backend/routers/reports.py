"""Phase 6 — Finance + Reports router.

Adds: revenue forecast, 5 revenue-slice reports, paginated payments ledger,
"run all due" billing-plans endpoint, and jobs/invoices CSV exports.
Existing /reports/business-summary lives in operations.py; income-by-category
lives in finances.py — this module only holds NEW endpoints for Phase 6.
"""
import csv
import io
from typing import Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException

from config import db, logger
from utils import now_iso, new_id, require_admin, notify_customer
from utils import require_admin_or_manager
# Feb-2026 · P3 — reuse the 4-rung tech-name cascade so exported
# rows carry the CURRENT display name, not the stale snapshot that
# job docs cache at write time.
from services.service_report_view import resolve_technician_names
from routers.tenants import get_current_tenant

router = APIRouter()


# ─── helpers ──────────────────────────────────────────────────────────────────
def _in_range(iso: str | None, dfrom: str | None, dto: str | None) -> bool:
    if not (dfrom or dto):
        return True
    if not iso:
        return False
    d = iso[:10]
    if dfrom and d < dfrom:
        return False
    if dto and d > dto:
        return False
    return True


# CUSTOMER-RETENTION-ACCOUNT-CORRECTION-PARITY · Feb-2026 — tenant-
# scoped excluded-customer-id lookup used by the four high-risk
# revenue routes patched in this phase.  Mirrors the shape used by
# ``_lost_customer_ids`` in the retention report so a flagged
# customer stops contributing to revenue-by-customer, forecasts,
# the dashboard tile, AND the KPI metric on the very next refresh
# (no cache invalidation needed).
async def _excluded_customer_ids(tenant_id: str) -> list:
    """Return the list of ``customer_id`` strings in this tenant that
    currently have ``account_correction=True``.  Empty list when
    the tenant has no flagged customers — callers should treat that
    as a no-op (no $nin clause to add)."""
    rows = await db.customers.find(
        {"tenant_id": tenant_id, "account_correction": True},
        {"_id": 0, "id": 1},
    ).to_list(length=None)
    return [r["id"] for r in rows if r.get("id")]


def _paid_amt(q: dict) -> float:
    # FIN-PARITY-C · Feb-2026 — legacy-fallback shim removed.
    # The ``recompute_amount_paid_v1`` migration guarantees every
    # historic invoice tagged ``payment_status="paid"`` also
    # carries a positive ``amount_paid`` (the migration flags any
    # row where that isn't true with a
    # ``paid_flag_without_payments`` audit for operator review;
    # such rows correctly report $0 collected until resolved).
    # Post-migration, ``amount_paid`` is the sole source of
    # truth for revenue aggregators — no ``payment_status``-
    # derived fallback needed.
    return float(q.get("amount_paid") or 0.0)


def _extract_city(addr: str) -> str:
    if not addr:
        return "Unknown"
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else "Unknown"


async def _fetch_paid(tenant_id: str, dfrom: Optional[str], dto: Optional[str]) -> list:
    # Feb-2026 · P2 Item 2 — revenue-slice fetch MUST exclude soft-
    # deleted invoices. Merge existing amount_paid/status $or with the
    # soft-delete guard via $and.
    # P59 · Feb-2026 — every read scoped to the caller's tenant.
    # Prior to this splice the helper ran with an unfiltered
    # ``doc_type=invoice`` query, letting any caller reach cross-
    # tenant invoice rows through the JSON /reports/* endpoints
    # (and, transitively, /export/*).  Callers MUST now pass
    # ``tenant_id``; empty-string tenant_id yields empty result.
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        return []
    docs = await db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice",
          "$and": [
              {"$or": [{"amount_paid": {"$gt": 0}}, {"payment_status": "paid"}]},
              {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
          ]},
        {"_id": 0},
    ).to_list(10000)
    return [q for q in docs if _in_range(q.get("paid_at") or q.get("created_at"), dfrom, dto)]


async def _fetch_all_invoices(tenant_id: str, dfrom: Optional[str], dto: Optional[str]) -> list:
    # Feb-2026 · P2 Item 2 — gross-sales / invoiced-items MUST exclude
    # soft-deleted invoices from the totals.
    # P59 · Feb-2026 — every read scoped to the caller's tenant.
    # Same rationale as ``_fetch_paid``; callers MUST pass
    # ``tenant_id``.
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        return []
    docs = await db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice",
          "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).to_list(10000)
    return [q for q in docs if _in_range(q.get("created_at"), dfrom, dto)]


# ─── revenue slices ───────────────────────────────────────────────────────────
@router.get("/reports/revenue-by-city")
async def revenue_by_city(start: Optional[str] = None, end: Optional[str] = None,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    # P59 · Feb-2026 — every read scoped to the caller's tenant.
    # Prior to this fix ``db.customers.find({}, ...)`` ran with an
    # empty filter, letting any admin token enumerate cross-tenant
    # customer rows (names + address strings) via the city bucket
    # side-channel.
    tenant_id = tenant["id"]
    paid = await _fetch_paid(tenant_id, start, end)
    customers = await db.customers.find(
        {"tenant_id": tenant_id}, {"_id": 0},
    ).to_list(5000)
    by_cid = {c["id"]: c for c in customers}
    buckets: dict = {}
    for q in paid:
        cid = q.get("customer_id")
        cust = by_cid.get(cid) if cid else None
        city = (cust or {}).get("city") if cust else None
        if not city:
            city = _extract_city((cust or {}).get("address", "") or q.get("customer_address", ""))
        buckets[city] = buckets.get(city, 0.0) + _paid_amt(q)
    rows = sorted(
        [{"city": k, "amount": round(v, 2)} for k, v in buckets.items()],
        key=lambda r: -r["amount"],
    )
    total = round(sum(r["amount"] for r in rows), 2)
    return {"rows": rows, "summary": {"total": total, "cities": len(rows), "invoices": len(paid)}}


@router.get("/reports/revenue-by-crew")
async def revenue_by_crew(start: Optional[str] = None, end: Optional[str] = None,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    # P59 · Feb-2026 — every read scoped to the caller's tenant.
    # Prior to this fix ``db.jobs.find({}, ...)`` and
    # ``db.crews.find({}, ...)`` both ran with empty filters, letting
    # any admin token enumerate cross-tenant job + crew rows through
    # the revenue-by-crew bucket side-channel.
    tenant_id = tenant["id"]
    paid = await _fetch_paid(tenant_id, start, end)
    jobs = await db.jobs.find(
        {"tenant_id": tenant_id}, {"_id": 0, "photos.data": 0},
    ).to_list(10000)
    job_crew = {j["id"]: j.get("crew_id") for j in jobs}
    crews = await db.crews.find(
        {"tenant_id": tenant_id}, {"_id": 0},
    ).to_list(500)
    crew_name = {c["id"]: c.get("name", "Crew") for c in crews}

    # Attribute invoice revenue to a crew via converted_job_id or matching customer's most recent job.
    jobs_by_customer: dict = {}
    for j in jobs:
        jobs_by_customer.setdefault(j.get("customer_id"), []).append(j)

    buckets: dict = {}
    for q in paid:
        crew_id = None
        # 1) If invoice tied to a converted job, follow that.
        for j in jobs:
            if j.get("quote_id") == q.get("id"):
                crew_id = j.get("crew_id")
                break
        # 2) Else, look at most recent job for the customer.
        if not crew_id and q.get("customer_id"):
            cjobs = jobs_by_customer.get(q["customer_id"], [])
            cjobs = sorted(cjobs, key=lambda j: j.get("scheduled_date") or j.get("created_at") or "", reverse=True)
            if cjobs:
                crew_id = cjobs[0].get("crew_id")
        label = crew_name.get(crew_id, "Solo tech") if crew_id else "Solo tech"
        buckets[label] = buckets.get(label, 0.0) + _paid_amt(q)
    rows = sorted([{"crew": k, "amount": round(v, 2)} for k, v in buckets.items()],
                  key=lambda r: -r["amount"])
    total = round(sum(r["amount"] for r in rows), 2)
    return {"rows": rows, "summary": {"total": total, "crews": len(rows), "invoices": len(paid)}}


@router.get("/reports/revenue-by-customer")
async def revenue_by_customer(start: Optional[str] = None, end: Optional[str] = None,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    # P59 · Feb-2026 — strict tenant scope via ``get_current_tenant``.
    # ``_fetch_paid`` already refuses empty-string tenant_id, so the
    # bucketing below can only see the caller's invoices.
    tenant_id = tenant["id"]
    paid = await _fetch_paid(tenant_id, start, end)
    # Phase 4a · Feb-2026 — strict ``payment_status == "paid"`` guard.
    # ``_fetch_paid`` applies the broader
    # ``{amount_paid>0 OR payment_status=="paid"}`` filter so other
    # revenue slices (city / service type) can include partial-paid
    # rows at their caller's option.  Revenue by Customer must NEVER
    # count partial / open / sent / draft / void / refunded /
    # overdue / unpaid / pending — the user-facing table showed
    # inflated totals when a customer had any non-``paid`` activity
    # in-window.  Post-filtering here keeps ``_fetch_paid`` shared
    # (no change to the other revenue reports) while enforcing the
    # exact Phase 4a semantic locally.
    paid = [
        q for q in paid
        if (q.get("payment_status") or "").strip().lower() == "paid"
    ]
    # CUSTOMER-RETENTION-ACCOUNT-CORRECTION-PARITY · Feb-2026 — skip
    # invoices whose ``customer_id`` is currently flagged as a
    # bookkeeping / test account so the revenue-by-customer table
    # matches the retention tile. Retroactive by design.
    excluded = set(await _excluded_customer_ids(tenant_id))
    buckets: dict = {}
    counts: dict = {}
    for q in paid:
        cid = q.get("customer_id") or "unknown"
        if cid in excluded:
            continue
        name = q.get("customer_name") or "Unknown"
        key = (cid, name)
        buckets[key] = buckets.get(key, 0.0) + _paid_amt(q)
        counts[key] = counts.get(key, 0) + 1
    rows = sorted(
        [{"customer_id": k[0], "customer_name": k[1], "amount": round(v, 2), "invoices": counts[k]}
         for k, v in buckets.items()],
        key=lambda r: -r["amount"],
    )
    total = round(sum(r["amount"] for r in rows), 2)
    return {"rows": rows, "summary": {"total": total, "customers": len(rows),
             "invoices": sum(counts.values())}}


@router.get("/reports/gross-sales")
async def gross_sales(start: Optional[str] = None, end: Optional[str] = None,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    """Sum of ALL invoices created in the window — paid + unpaid."""
    # P59 · Feb-2026 — strict tenant scope via ``get_current_tenant``.
    # ``_fetch_all_invoices`` already refuses empty-string tenant_id,
    # so the totals below reflect only the caller's tenant.
    tenant_id = tenant["id"]
    invs = await _fetch_all_invoices(tenant_id, start, end)
    total = round(sum(float(i.get("total") or 0) for i in invs), 2)
    paid_total = round(sum(_paid_amt(i) for i in invs), 2)
    outstanding = round(total - paid_total, 2)
    # Monthly breakdown (trend)
    monthly: dict = {}
    for i in invs:
        ds = (i.get("created_at") or "")[:7]
        if not ds:
            continue
        monthly[ds] = monthly.get(ds, 0.0) + float(i.get("total") or 0)
    trend = [{"month": k, "amount": round(v, 2)} for k, v in sorted(monthly.items())]
    rows = sorted(
        [
            {
                "id": i["id"],
                "created_at": i.get("created_at"),
                "customer_name": i.get("customer_name", ""),
                "title": i.get("title", ""),
                "total": float(i.get("total") or 0),
                "amount_paid": _paid_amt(i),
                "payment_status": i.get("payment_status") or "unpaid",
            }
            for i in invs
        ],
        key=lambda r: r["created_at"] or "",
        reverse=True,
    )
    return {
        "rows": rows,
        "trend": trend,
        "summary": {"gross": total, "collected": paid_total, "outstanding": outstanding, "count": len(invs)},
    }


@router.get("/reports/invoiced-items")
async def invoiced_items(start: Optional[str] = None, end: Optional[str] = None,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Per-line-item aggregation across invoices in window."""
    # P59 · Feb-2026 — strict tenant scope via ``get_current_tenant``.
    tenant_id = tenant["id"]
    invs = await _fetch_all_invoices(tenant_id, start, end)
    agg: dict = {}
    for inv in invs:
        for li in (inv.get("line_items") or []):
            key = (li.get("description") or "Item").strip()
            qty = float(li.get("quantity") or 0)
            price = float(li.get("unit_price") or 0)
            amt = qty * price
            row = agg.setdefault(key, {"description": key, "quantity": 0.0, "amount": 0.0, "invoices": 0,
                                        "category": li.get("category") or "Pool"})
            row["quantity"] += qty
            row["amount"] += amt
            row["invoices"] += 1
    rows = sorted(
        [{**r, "quantity": round(r["quantity"], 2), "amount": round(r["amount"], 2)} for r in agg.values()],
        key=lambda r: -r["amount"],
    )
    total = round(sum(r["amount"] for r in rows), 2)
    return {"rows": rows, "summary": {"total": total, "unique_items": len(rows), "invoices": len(invs)}}


# ─── revenue forecast ─────────────────────────────────────────────────────────
_FREQ_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 90}


def _quote_weight(q: dict) -> float:
    """Approved → 0.9 | sent ≤7d → 0.6 | sent >7d → 0.3 | else 0."""
    status = (q.get("status") or "").lower()
    decision = (q.get("decision") or "").lower()
    if decision == "approved" or status == "accepted":
        return 0.9
    if status == "sent":
        try:
            d = datetime.fromisoformat((q.get("created_at") or "")[:19])
            age = (datetime.now(timezone.utc).replace(tzinfo=None) - d.replace(tzinfo=None)).days
        except Exception:
            age = 99
        return 0.6 if age <= 7 else 0.3
    return 0.0


async def _forecast_series(days_ahead: int = 90, excluded_ids: Optional[list] = None) -> list:
    """Return weekly buckets of projected revenue from active billing plans + weighted quotes.

    CUSTOMER-RETENTION-ACCOUNT-CORRECTION-PARITY · Feb-2026 — the
    optional ``excluded_ids`` list is passed through to
    ``_forecast_series_between``; billing plans + quotes tied to any
    flagged customer are excluded from the projection.  ``None``
    (the legacy default) preserves pre-filter behavior for callers
    that haven't threaded through tenant context.
    """
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=days_ahead)
    return await _forecast_series_between(today, horizon, excluded_ids=excluded_ids)


async def _forecast_series_between(start_date, end_date, excluded_ids: Optional[list] = None) -> list:
    """Feb-2026 · daily buckets between an inclusive [start_date, end_date]
    window. Reuses the same billing-plan + weighted-quote projection but
    keys each row by ISO date rather than week-start so short windows
    (today / tomorrow) still render meaningful bars.

    CUSTOMER-RETENTION-ACCOUNT-CORRECTION-PARITY · Feb-2026 —
    plans + weighted quotes whose ``customer_id`` is in
    ``excluded_ids`` are dropped before the aggregation.  Known
    pre-existing cross-tenant leak on these two ``find`` calls
    (no ``tenant_id`` filter) is **not** addressed here; this
    phase only ensures a flagged customer in the caller's tenant
    doesn't contribute to the projection total.  Fixing the
    tenant leak is tracked as its own follow-up ticket.
    """
    _ex = set(excluded_ids or [])
    plan_q: dict = {"active": {"$ne": False}}
    if _ex:
        plan_q["customer_id"] = {"$nin": list(_ex)}
    plans = await db.billing_plans.find(plan_q, {"_id": 0}).to_list(2000)
    buckets: dict = {}
    for p in plans:
        try:
            nr = datetime.fromisoformat((p.get("next_run") or "")[:10]).date()
        except Exception:
            continue
        step = _FREQ_DAYS.get(p.get("frequency", "monthly"), 30)
        amt = float(p.get("amount") or 0) * 1.08
        while nr <= end_date:
            if start_date <= nr <= end_date:
                key = nr.isoformat()
                buckets[key] = buckets.get(key, 0.0) + amt
            nr = nr + timedelta(days=step)
    # Weighted open quotes — land 14 days out.
    quote_q: dict = {"doc_type": "quote"}
    if _ex:
        quote_q["customer_id"] = {"$nin": list(_ex)}
    quotes = await db.quotes.find(quote_q, {"_id": 0}).to_list(3000)
    today = datetime.now(timezone.utc).date()
    for q in quotes:
        w = _quote_weight(q)
        if w <= 0:
            continue
        landing = today + timedelta(days=14)
        if not (start_date <= landing <= end_date):
            continue
        key = landing.isoformat()
        buckets[key] = buckets.get(key, 0.0) + float(q.get("total") or 0) * w
    out = []
    cur = start_date
    while cur <= end_date:
        key = cur.isoformat()
        out.append({"week": key, "date": key,
                    "amount": round(buckets.get(key, 0.0), 2)})
        cur += timedelta(days=1)
    return out


async def _forecast_series_weekly_wrapper(days_ahead: int = 90) -> list:
    """Legacy weekly bucketing kept for the days= flow.

    Older callers may still expect week-start iso keys, so we build
    the same aggregate but rounded to Mon-anchored buckets.
    """
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=days_ahead)
    plans = await db.billing_plans.find({"active": {"$ne": False}}, {"_id": 0}).to_list(2000)
    weekly: dict = {}  # week_start iso → amount
    for p in plans:
        try:
            nr = datetime.fromisoformat((p.get("next_run") or "")[:10]).date()
        except Exception:
            continue
        step = _FREQ_DAYS.get(p.get("frequency", "monthly"), 30)
        amt = float(p.get("amount") or 0) * 1.08  # include tax like run_billing_plan
        while nr <= horizon:
            if nr >= today:
                wk = (nr - timedelta(days=nr.weekday())).isoformat()
                weekly[wk] = weekly.get(wk, 0.0) + amt
            nr = nr + timedelta(days=step)
    # Weighted open quotes (assume revenue landing 14 days out)
    quotes = await db.quotes.find({"doc_type": "quote"}, {"_id": 0}).to_list(3000)
    for q in quotes:
        w = _quote_weight(q)
        if w <= 0:
            continue
        landing = today + timedelta(days=14)
        if landing > horizon:
            continue
        wk = (landing - timedelta(days=landing.weekday())).isoformat()
        weekly[wk] = weekly.get(wk, 0.0) + float(q.get("total") or 0) * w
    # Build ordered series
    out = []
    cur = today - timedelta(days=today.weekday())
    while cur <= horizon:
        wk = cur.isoformat()
        out.append({"week": wk, "amount": round(weekly.get(wk, 0.0), 2)})
        cur += timedelta(days=7)
    return out


@router.get("/reports/forecast")
async def revenue_forecast(
    user: dict = Depends(require_admin),
    days: int = Query(90, ge=7, le=365),
    range: Optional[str] = Query(None,
        description="Feb-2026 · preset window: today|tomorrow|week|month|custom"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD (custom range)"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD (custom range)"),
    tenant: dict = Depends(get_current_tenant),
):
    # Feb-2026 · Enhancement 2 — preset ranges honored in tenant tz.
    if range:
        preset = (range or "").lower()
        tz_name = (tenant or {}).get("timezone") or "America/Phoenix"
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        now_local = datetime.now(tz)
        today_local = now_local.date()
        if preset == "today":
            start_local = today_local
            end_local = today_local
        elif preset == "tomorrow":
            start_local = today_local + timedelta(days=1)
            end_local = start_local
        elif preset == "week":
            # Mon–Sun window containing today.
            start_local = today_local - timedelta(days=today_local.weekday())
            end_local = start_local + timedelta(days=6)
        elif preset == "month":
            start_local = today_local.replace(day=1)
            # Last day of the month.
            if start_local.month == 12:
                next_month = start_local.replace(year=start_local.year + 1, month=1)
            else:
                next_month = start_local.replace(month=start_local.month + 1)
            end_local = next_month - timedelta(days=1)
        elif preset == "custom":
            if not (date_from and date_to):
                raise HTTPException(400, "custom range requires date_from + date_to")
            try:
                start_local = datetime.fromisoformat(date_from).date()
                end_local = datetime.fromisoformat(date_to).date()
            except ValueError:
                raise HTTPException(400, "invalid date format")
            if end_local < start_local:
                raise HTTPException(400, "date_to must be >= date_from")
        else:
            raise HTTPException(400,
                "range must be one of today|tomorrow|week|month|custom")
        series = await _forecast_series_between(
            start_local, end_local,
            excluded_ids=await _excluded_customer_ids(tenant["id"]),
        )
        total = round(sum(x["amount"] for x in series), 2)
        return {"series": series, "total": total,
                "range": preset,
                "date_from": start_local.isoformat(),
                "date_to": end_local.isoformat()}
    series = await _forecast_series(
        days, excluded_ids=await _excluded_customer_ids(tenant["id"]),
    )
    total = round(sum(x["amount"] for x in series), 2)
    return {"days": days, "series": series, "total": total}


@router.get("/reports/forecast-cards")
async def forecast_cards(user: dict = Depends(require_admin)):
    quotes = await db.quotes.find({"doc_type": "quote"}, {"_id": 0}).to_list(3000)
    pipeline = round(sum(float(q.get("total") or 0) for q in quotes if (q.get("status") or "").lower() in ("sent", "draft", "accepted") and (q.get("decision") or "").lower() != "declined"), 2)
    weighted = round(sum(float(q.get("total") or 0) * _quote_weight(q) for q in quotes), 2)

    plans = await db.billing_plans.find({"active": {"$ne": False}}, {"_id": 0}).to_list(2000)
    monthly_recurring = 0.0
    for p in plans:
        amt = float(p.get("amount") or 0) * 1.08
        step_days = _FREQ_DAYS.get(p.get("frequency", "monthly"), 30)
        monthly_recurring += amt * (30 / step_days)
    monthly_recurring = round(monthly_recurring, 2)

    now = datetime.now(timezone.utc)
    # Feb-2026 · P2 Item 2 — at-risk unpaid list MUST exclude
    # soft-deleted invoices.
    unpaid = await db.quotes.find(
        {"doc_type": "invoice", "payment_status": "unpaid",
          "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).to_list(3000)
    at_risk = 0.0
    for q in unpaid:
        try:
            created = datetime.fromisoformat(q.get("created_at"))
            if (now - created).days >= 30:
                at_risk += float(q.get("total") or 0)
        except Exception:
            pass
    at_risk = round(at_risk, 2)

    return {
        "pipeline_value": pipeline,
        "weighted_forecast": weighted,
        "monthly_recurring": monthly_recurring,
        "at_risk": at_risk,
        "active_plan_count": len(plans),
    }


# ─── payments ledger (paginated + filtered) ──────────────────────────────────
@router.get("/payments/list")
async def payments_list(
    user: dict = Depends(require_admin),
    start: Optional[str] = None,
    end: Optional[str] = None,
    method: Optional[str] = None,
    status: Optional[str] = None,
    # Feb-2026 · Item 2 — customer-scoped filter.
    customer_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    q: dict = {"doc_type": "invoice"}
    if status:
        q["payment_status"] = status
    else:
        q["$or"] = [{"amount_paid": {"$gt": 0}}, {"payment_status": {"$in": ["paid", "processing", "partial"]}}]
    if customer_id:
        q["customer_id"] = customer_id
    # Feb-2026 · P2 Item 2 — payments ledger MUST exclude soft-deleted
    # invoices. Compose via $and to preserve any $or already present.
    _deleted_guard = {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]}
    if "$or" in q:
        existing_or = q.pop("$or")
        q["$and"] = [{"$or": existing_or}, _deleted_guard]
    else:
        q.update(_deleted_guard)
    docs = await db.quotes.find(q, {"_id": 0}).sort("paid_at", -1).to_list(20000)
    rows = []
    for d in docs:
        ref = d.get("paid_at") or d.get("created_at")
        if not _in_range(ref, start, end):
            continue
        pm = d.get("payment_method") or ("Card" if d.get("payment_status") == "paid" else "")
        if method and method != "all" and (pm or "").lower() != method.lower():
            continue
        rows.append({
            "id": d["id"],
            # Payments Page · Invoice Link (Feb 2026) — expose both `invoice_id`
            # (an explicit alias of `id` since these ledger rows ARE the paid
            # invoice) and `invoice_number` (already stored on the quote doc)
            # so the frontend can render a clickable "INV-YYYY-NNNNNN" that
            # routes to /invoices/{invoice_id}. Existing `id` field kept for
            # backward compat.
            "invoice_id": d["id"],
            "invoice_number": d.get("invoice_number") or None,
            "customer_id": d.get("customer_id"),
            "customer_name": d.get("customer_name", ""),
            "invoice_title": d.get("title", ""),
            "amount": _paid_amt(d),
            "invoice_total": float(d.get("total") or 0),
            "method": pm or "—",
            "status": d.get("payment_status") or "unpaid",
            "paid_at": d.get("paid_at"),
            "created_at": d.get("created_at"),
            "stripe_pi_id": d.get("payment_intent_id"),
        })
    total = len(rows)
    total_amount = round(sum(r["amount"] for r in rows), 2)
    off = (page - 1) * page_size
    page_rows = rows[off: off + page_size]
    return {
        "rows": page_rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_amount": total_amount,
    }


# ─── billing-plans "run all due" ──────────────────────────────────────────────
@router.post("/billing-plans/run")
async def run_all_due_billing_plans(user: dict = Depends(require_admin)):
    """Fire every active plan whose next_run <= today (creates invoices, advances next_run)."""
    from routers.finances import advance_date
    today = datetime.now(timezone.utc).date().isoformat()
    plans = await db.billing_plans.find(
        {"active": {"$ne": False}, "next_run": {"$lte": today}}, {"_id": 0}
    ).to_list(1000)
    fired = []
    for p in plans:
        pid = p["id"]
        amount = float(p.get("amount") or 0)
        tax = round(amount * 0.08, 2)
        invoice = {
            "id": new_id(), "customer_id": p["customer_id"], "customer_name": p.get("customer_name", ""),
            "title": p.get("service", "Recurring Service"), "doc_type": "invoice",
            "line_items": [{"description": p.get("service", "Recurring Service"),
                             "quantity": 1, "unit_price": amount, "category": "Pool"}],
            "tax_rate": 8.0, "subtotal": amount, "tax": tax, "total": round(amount + tax, 2),
            "amount_paid": 0.0,
            "due_date": (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat(),
            "status": "sent", "payment_status": "unpaid",
            "notes": "Auto-generated from billing plan",
            "billing_plan_id": pid, "created_at": now_iso(),
        }
        # Task SS/RR Phase 2 · Feb 2026 — auto-apply available credits
        # BEFORE persisting. tenant_id lives on the billing_plan; when
        # missing we fall back to the customer doc. Failure is
        # non-fatal — legacy invoices still bill as before.
        try:
            tid = p.get("tenant_id")
            if not tid and p.get("customer_id"):
                _c = await db.customers.find_one(
                    {"id": p["customer_id"]}, {"_id": 0, "tenant_id": 1},
                )
                tid = (_c or {}).get("tenant_id")
            if tid:
                invoice["tenant_id"] = tid
                from services.credits_apply import apply_and_persist
                invoice = await apply_and_persist(db, tid, invoice)
        except Exception as _e:                                    # noqa: BLE001
            pass
        # Feb-2026 · P0 fix — route the legacy billing-plan runner
        # through the canonical helper so nightly runs don't emit
        # rows with ``invoice_number: null``. Fall back to a raw
        # ``insert_one`` if the tenant is somehow missing so a
        # numbering failure never silently drops the invoice.
        _tid = invoice.get("tenant_id")
        _tenant = None
        if _tid:
            _tenant = await db.tenants.find_one(
                {"id": _tid}, {"_id": 0, "id": 1, "timezone": 1},
            )
        if _tenant:
            try:
                from services.invoice_numbering import insert_invoice
                await insert_invoice(invoice, _tenant)
            except Exception as _num_exc:                          # noqa: BLE001
                logger.warning(
                    f"run_all_due_billing_plans number-assign failed: {_num_exc}"
                )
                await db.quotes.insert_one(invoice)
        else:
            await db.quotes.insert_one(invoice)
        new_next = advance_date(p.get("next_run") or now_iso(), p.get("frequency", "monthly"))
        await db.billing_plans.update_one(
            {"id": pid}, {"$set": {"next_run": new_next, "last_run": now_iso()}},
        )
        try:
            await notify_customer(p["customer_id"], "New invoice",
                                  f"An invoice for {p.get('service', 'your service')} was issued.")
        except Exception as e:
            logger.warning(f"notify_customer for billing-plan run failed: {e}")
        fired.append({"plan_id": pid, "invoice_id": invoice["id"], "next_run": new_next})
    return {"fired": len(fired), "runs": fired}


# ─── impexp: jobs & invoices exports ─────────────────────────────────────────
JOB_COLS = ["id", "title", "customer_name", "service_type", "status", "technician_name",
            "scheduled_date", "price", "created_at"]
INVOICE_COLS = ["id", "customer_name", "title", "total", "amount_paid", "payment_status",
                "created_at", "paid_at", "due_date"]


def _to_csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([("" if r.get(c) is None else r.get(c)) for c in cols])
    return buf.getvalue()


@router.get("/export/jobs")
async def export_jobs(user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant),
                      start: Optional[str] = None, end: Optional[str] = None):
    # P59 · Feb-2026 — every read scoped to the caller's tenant.
    # Prior to this fix ``db.jobs.find({}, ...)`` ran with an empty
    # filter, letting any admin token on any tenant enumerate
    # cross-tenant job rows (customer names, addresses, prices,
    # technician IDs) through a CSV download.
    tenant_id = tenant["id"]
    rows = await db.jobs.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "photos.data": 0},
    ).sort("scheduled_date", -1).to_list(10000)
    if start or end:
        rows = [r for r in rows if _in_range(r.get("scheduled_date") or r.get("created_at"), start, end)]
    # Feb-2026 · P3 — hydrate ``technician_name`` from the current
    # users / technicians display name, overwriting any stale snapshot
    # baked in at job-write time. Single ``$in`` query per request via
    # ``resolve_technician_names`` — no N+1.
    tech_ids = {r.get("technician_id") for r in rows if r.get("technician_id")}
    names_map = await resolve_technician_names(db, tenant_id, list(tech_ids)) if tech_ids else {}
    for r in rows:
        tid = r.get("technician_id")
        if tid:
            r["technician_name"] = names_map.get(tid) or r.get("technician_name") or tid
    return {"filename": "jobs.csv", "content": _to_csv(rows, JOB_COLS), "count": len(rows)}


@router.get("/export/invoices")
async def export_invoices(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant),
                          start: Optional[str] = None, end: Optional[str] = None):
    # Feb-2026 · P2 Item 2 — invoice CSV export MUST exclude
    # soft-deleted rows (a common revenue-reconciliation surface).
    # P59 · Feb-2026 — every read scoped to the caller's tenant.
    rows = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "invoice",
          "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(10000)
    if start or end:
        rows = [r for r in rows if _in_range(r.get("created_at"), start, end)]
    return {"filename": "invoices.csv", "content": _to_csv(rows, INVOICE_COLS), "count": len(rows)}


# ─── Phase 34g · Customer Retention Report ───────────────────────────────────
def _bucket_month(dt: datetime) -> tuple[str, str, str]:
    """Return (label='YYYY-MM', start_iso='YYYY-MM-01', end_exclusive_iso)."""
    from calendar import monthrange
    y, m = dt.year, dt.month
    _, last = monthrange(y, m)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return (f"{y:04d}-{m:02d}", f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01")


def _bucket_week(dt: datetime) -> tuple[str, str, str]:
    """ISO week bucket. Monday-start. Label 'YYYY-Www'."""
    monday = dt - timedelta(days=dt.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = monday + timedelta(days=7)
    year, week, _ = monday.isocalendar()
    return (f"{year:04d}-W{week:02d}",
            monday.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"))


def _bucket_year(dt: datetime) -> tuple[str, str, str]:
    y = dt.year
    return (f"{y:04d}", f"{y:04d}-01-01", f"{y + 1:04d}-01-01")


def _generate_buckets(period: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Return chronologically-ordered buckets covering [start_dt, end_dt]."""
    out: list[dict] = []
    seen: set[str] = set()
    if period == "week":
        cur = start_dt
        step = timedelta(days=7)
    elif period == "year":
        cur = start_dt.replace(month=1, day=1)
        step = None  # year uses replace
    else:  # month (default)
        cur = start_dt.replace(day=1)
        step = None
    guard = 0
    while cur < end_dt and guard < 400:
        guard += 1
        if period == "week":
            label, s, e = _bucket_week(cur)
        elif period == "year":
            label, s, e = _bucket_year(cur)
        else:
            label, s, e = _bucket_month(cur)
        if label not in seen:
            out.append({"label": label, "start": s, "end": e})
            seen.add(label)
        # advance
        if period == "week":
            cur = cur + step
        elif period == "year":
            cur = cur.replace(year=cur.year + 1)
        else:  # month
            cur = (cur.replace(day=28) + timedelta(days=5)).replace(day=1)
    return out


async def _count_gained(tenant_id: str, s: str, e: str) -> int:
    """Customers created in [s, e). `created_at` is stored as ISO strings.

    CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — the
    ``{account_correction: {$ne: true}}`` predicate excludes rows the
    office has flagged as bookkeeping / test accounts.  Retroactive by
    design: flipping the flag ON drops the customer from every past
    bucket on the very next refresh (no cache invalidation).
    """
    n = await db.customers.count_documents({
        "tenant_id": tenant_id,
        "created_at": {"$gte": s, "$lt": e},
        "account_correction": {"$ne": True},
    })
    return int(n)


async def _count_lost(tenant_id: str, s: str, e: str) -> int:
    """Deactivation events (active→inactive) in [s, e).

    CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — the lost tile
    joins the activation event with its customer row so flagged
    customers drop out.  We fetch the IDs of currently-flagged
    customers in-tenant, then subtract via ``customer_id: {$nin}``
    on the events query.  The flagged-ID set is small (hundreds at
    most) and this call fires at report time, not request time.
    """
    excluded = await db.customers.find(
        {"tenant_id": tenant_id, "account_correction": True},
        {"_id": 0, "id": 1},
    ).to_list(length=None)
    excluded_ids = [r["id"] for r in excluded if r.get("id")]
    q = {
        "tenant_id": tenant_id,
        "to_status": "inactive",
        "changed_at": {"$gte": s, "$lt": e},
    }
    if excluded_ids:
        q["customer_id"] = {"$nin": excluded_ids}
    n = await db.customer_activation_events.count_documents(q)
    return int(n)


# CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — MRR normalization.
# Mirrors the formula already used by ``dashboard_revenue.py`` +
# ``reports_recurring_vs_project.py`` so the recurring-revenue tile on
# the retention report is numerically consistent with the dashboard tile.
# Semantics: SUM each customer's CURRENT ``billing_plans`` snapshot —
# not a point-in-time replay of what the plans looked like at
# gained/lost moment.  Documented inline because "current snapshot vs
# historical replay" is the kind of subtle thing a future reader
# would otherwise rediscover painfully.
_FREQ_PER_MONTH = {"weekly": 4.333, "monthly": 1.0, "quarterly": 1 / 3.0}


def _customer_mrr_from_plans(plans: list) -> float:
    """Return MRR dollar amount for a list of billing_plans docs.

    Only ACTIVE plans contribute.  Unknown frequencies fall back to
    monthly (consistent with the write-side default on
    ``BillingPlanIn.frequency``).  Rounded to 2 decimals so sums
    stay commutative across callers.
    """
    total = 0.0
    for p in plans or []:
        if not p.get("active"):
            continue
        amt = float(p.get("amount") or 0.0)
        freq = (p.get("frequency") or "monthly").lower()
        total += amt * _FREQ_PER_MONTH.get(freq, 1.0)
    return round(total, 2)


async def _mrr_sum_for_customers(
    tenant_id: str, customer_ids: list,
) -> float:
    """Hydrate ``billing_plans`` for a list of customer_ids and return
    the aggregated MRR dollar sum (not per-row — grand total).  Empty
    input → 0.0 without hitting Mongo."""
    if not customer_ids:
        return 0.0
    plans = await db.billing_plans.find(
        {"tenant_id": tenant_id,
         "customer_id": {"$in": customer_ids},
         "active": True},
        {"_id": 0, "customer_id": 1, "amount": 1, "frequency": 1,
         "active": 1},
    ).to_list(length=None)
    # Group by customer so the per-customer MRR is intact (callers
    # that need per-row MRR use the drill-down endpoint which groups
    # explicitly).  Grand total is the same either way.
    return _customer_mrr_from_plans(plans)


async def _gained_customer_ids(tenant_id: str, s: str, e: str) -> list:
    """IDs of non-flagged customers created in [s, e)."""
    rows = await db.customers.find(
        {"tenant_id": tenant_id,
         "created_at": {"$gte": s, "$lt": e},
         "account_correction": {"$ne": True}},
        {"_id": 0, "id": 1},
    ).to_list(length=None)
    return [r["id"] for r in rows if r.get("id")]


async def _lost_customer_ids(tenant_id: str, s: str, e: str) -> list:
    """IDs of non-flagged customers whose activation flipped
    active→inactive in [s, e).  Join hop: look up each event's
    ``customer_id`` and filter out ones currently flagged."""
    excluded_rows = await db.customers.find(
        {"tenant_id": tenant_id, "account_correction": True},
        {"_id": 0, "id": 1},
    ).to_list(length=None)
    excluded_ids = {r["id"] for r in excluded_rows if r.get("id")}
    events = await db.customer_activation_events.find(
        {"tenant_id": tenant_id,
         "to_status": "inactive",
         "changed_at": {"$gte": s, "$lt": e}},
        {"_id": 0, "customer_id": 1},
    ).to_list(length=None)
    out = []
    seen: set = set()
    for ev in events:
        cid = ev.get("customer_id")
        if not cid or cid in excluded_ids or cid in seen:
            continue
        out.append(cid)
        seen.add(cid)
    return out


async def _totals_for_range(tenant_id: str, s: str, e: str) -> dict:
    """Return the full tile payload for [s, e).

    CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — the two new
    MRR tiles (``recurring_revenue_gained`` / ``_lost``) sum each
    non-flagged customer's CURRENT ``billing_plans`` snapshot.
    Documented inline (and in ``_customer_mrr_from_plans``) so a
    future reader doesn't assume this is a historical replay.
    """
    gained_ids = await _gained_customer_ids(tenant_id, s, e)
    lost_ids = await _lost_customer_ids(tenant_id, s, e)
    rr_gained = await _mrr_sum_for_customers(tenant_id, gained_ids)
    rr_lost = await _mrr_sum_for_customers(tenant_id, lost_ids)
    return {
        "gained": len(gained_ids),
        "lost": len(lost_ids),
        "net": len(gained_ids) - len(lost_ids),
        "recurring_revenue_gained": rr_gained,
        "recurring_revenue_lost": rr_lost,
    }


def _pct_change(cur: int, prev: int) -> Optional[float]:
    if prev == 0:
        return None if cur == 0 else 100.0  # arbitrary — flagged as N/A in UI
    return round(((cur - prev) / abs(prev)) * 100.0, 2)


async def _has_history_before(tenant_id: str, before_iso: str) -> bool:
    """Cheap probe: does this tenant have a customer created > 1 year before
    the current window's start? If not, YoY is meaningless."""
    n = await db.customers.count_documents({
        "tenant_id": tenant_id,
        "created_at": {"$lt": before_iso},
    }, limit=1)
    return n > 0


@router.get("/reports/customer-retention")
async def customer_retention_report(
    user: dict = Depends(require_admin),
    period: str = Query("month"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    if period not in ("week", "month", "year"):
        raise HTTPException(400, "period must be week|month|year")
    tenant_id = user["tenant_id"]
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Default windows.
    if not end:
        end_dt = today + timedelta(days=1)  # inclusive-of-today
    else:
        end_dt = datetime.fromisoformat(end + "T00:00:00").replace(tzinfo=timezone.utc)
    if not start:
        if period == "week":
            start_dt = end_dt - timedelta(weeks=52)
        elif period == "year":
            start_dt = end_dt.replace(year=end_dt.year - 4, month=1, day=1)
        else:  # month
            start_dt = (end_dt - timedelta(days=365)).replace(day=1)
    else:
        start_dt = datetime.fromisoformat(start + "T00:00:00").replace(tzinfo=timezone.utc)

    buckets_meta = _generate_buckets(period, start_dt, end_dt)
    buckets: list[dict] = []
    for b in buckets_meta:
        t = await _totals_for_range(tenant_id, b["start"], b["end"])
        buckets.append({**b, **t})

    totals = {
        "gained": sum(b["gained"] for b in buckets),
        "lost":   sum(b["lost"]   for b in buckets),
        "net":    sum(b["net"]    for b in buckets),
        # CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — new
        # MRR tiles.  Sum per-bucket so the number stays consistent
        # with the per-bucket counts rendered in the chart (same
        # dedupe semantics inside each bucket).  Rounded to 2 dp
        # since each bucket is already rounded — floats compose
        # into enough drift to see a half-penny delta without this
        # final round.
        "recurring_revenue_gained": round(
            sum(b.get("recurring_revenue_gained", 0.0) for b in buckets), 2,
        ),
        "recurring_revenue_lost": round(
            sum(b.get("recurring_revenue_lost", 0.0) for b in buckets), 2,
        ),
    }

    # YoY block — same window shifted back 1 year.
    prev_start = start_dt.replace(year=start_dt.year - 1)
    prev_end   = end_dt.replace(year=end_dt.year - 1)
    has_history = await _has_history_before(tenant_id, prev_start.strftime("%Y-%m-%d"))
    if not has_history:
        yoy = {
            "current_totals": totals,
            "previous_totals": None,
            "gained_pct_change": None,
            "lost_pct_change": None,
            "net_pct_change": None,
            "mocked": True,
            "reason": "insufficient history for YoY",
        }
    else:
        prev_totals = await _totals_for_range(
            tenant_id,
            prev_start.strftime("%Y-%m-%d"),
            prev_end.strftime("%Y-%m-%d"),
        )
        yoy = {
            "current_totals": totals,
            "previous_totals": prev_totals,
            "gained_pct_change": _pct_change(totals["gained"], prev_totals["gained"]),
            "lost_pct_change":   _pct_change(totals["lost"],   prev_totals["lost"]),
            "net_pct_change":    _pct_change(totals["net"],    prev_totals["net"]),
            "mocked": False,
            "reason": None,
        }

    return {
        "period": period,
        "start": start_dt.strftime("%Y-%m-%d"),
        "end":   end_dt.strftime("%Y-%m-%d"),
        "buckets": buckets,
        "totals": totals,
        "yoy": yoy,
    }


# ═════════════════════════════════════════════════════════════════════════
# CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — drill-down lists.
#
# Two sister endpoints feeding the Gained / Lost tile modals on
# ``/reports/customer-retention``.  Each returns a paginated list of
# {customer_id, name, date, mrr, account_correction} rows so the FE
# modal can render a sortable table + per-row Account Correction
# toggle without a second round-trip for every column.
#
# ``account_correction`` is included on the row so the FE can show
# the current toggle state inline (even though we filter them OUT of
# the list by default — a page REFRESH after a flag flip will drop
# them from the list; the row's own ``account_correction`` field
# supports the pre-refresh optimistic UI).
#
# Pagination: ``page`` (1-based) + ``limit`` (default 50, max 500).
# Response envelope: ``{items, total, has_more, page, limit}``.
# ═════════════════════════════════════════════════════════════════════════
async def _retention_drilldown_rows(
    tenant_id: str,
    kind: str,            # "gained" | "lost"
    start: str,
    end: str,
    page: int,
    limit: int,
) -> dict:
    """Shared pipeline for the two drill-down routes."""
    if kind == "gained":
        all_ids = await _gained_customer_ids(tenant_id, start, end)
    else:
        all_ids = await _lost_customer_ids(tenant_id, start, end)
    total = len(all_ids)
    if total == 0:
        return {"items": [], "total": 0, "has_more": False,
                "page": page, "limit": limit}
    off = max(0, (page - 1) * limit)
    page_ids = all_ids[off: off + limit]
    # Hydrate names + created_at per row (sparse — one Mongo call for
    # the WHOLE page).
    cust_rows = await db.customers.find(
        {"tenant_id": tenant_id, "id": {"$in": page_ids}},
        {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1,
         "created_at": 1, "account_correction": 1,
         "account_correction_at": 1, "account_correction_by": 1},
    ).to_list(length=len(page_ids))
    cust_map = {r["id"]: r for r in cust_rows if r.get("id")}
    # For "lost" we also need the activation event's ``changed_at``
    # (the "cancelled on" date rendered in the UI).  For "gained"
    # the ``created_at`` on the customer row IS the "added on" date.
    changed_at_map: dict = {}
    if kind == "lost" and page_ids:
        ev_rows = await db.customer_activation_events.find(
            {"tenant_id": tenant_id,
             "to_status": "inactive",
             "customer_id": {"$in": page_ids},
             "changed_at": {"$gte": start, "$lt": end}},
            {"_id": 0, "customer_id": 1, "changed_at": 1},
        ).sort("changed_at", -1).to_list(length=None)
        for ev in ev_rows:
            # Latest event wins (we sorted DESC above).
            changed_at_map.setdefault(ev["customer_id"], ev["changed_at"])
    # Per-customer MRR map — single aggregation call for the whole page.
    plan_rows: list = []
    if page_ids:
        plan_rows = await db.billing_plans.find(
            {"tenant_id": tenant_id,
             "customer_id": {"$in": page_ids},
             "active": True},
            {"_id": 0, "customer_id": 1, "amount": 1, "frequency": 1,
             "active": 1},
        ).to_list(length=None)
    mrr_by_cust: dict = {}
    for p in plan_rows:
        cid = p.get("customer_id")
        if not cid:
            continue
        mrr_by_cust.setdefault(cid, []).append(p)
    items: list = []
    for cid in page_ids:
        c = cust_map.get(cid)
        if not c:
            # Skip orphan — customer row deleted between the id
            # fetch and the hydrate.  Keeps the list truthful.
            continue
        name = (c.get("name")
                or " ".join(_x for _x in
                            (c.get("first_name"), c.get("last_name")) if _x)
                or "—")
        date_iso = (changed_at_map.get(cid) if kind == "lost"
                    else c.get("created_at"))
        items.append({
            "customer_id": cid,
            "name": name,
            "date": date_iso,
            "mrr": _customer_mrr_from_plans(mrr_by_cust.get(cid, [])),
            "account_correction": bool(c.get("account_correction") or False),
        })
    has_more = off + len(page_ids) < total
    return {"items": items, "total": total, "has_more": has_more,
            "page": page, "limit": limit}


@router.get("/reports/customer-retention/gained-list")
async def customer_retention_gained_list(
    user: dict = Depends(require_admin),
    period: str = Query("month"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    """Paginated drill-down of customers counted in Gained tile."""
    if period not in ("week", "month", "year"):
        raise HTTPException(400, "period must be week|month|year")
    tenant_id = user["tenant_id"]
    # Default to the same window the main report uses so the modal's
    # row count equals the tile's total.
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    end_dt = (
        today + timedelta(days=1) if not end else
        datetime.fromisoformat(end + "T00:00:00").replace(tzinfo=timezone.utc)
    )
    if not start:
        if period == "week":
            start_dt = end_dt - timedelta(weeks=52)
        elif period == "year":
            start_dt = end_dt.replace(year=end_dt.year - 4, month=1, day=1)
        else:
            start_dt = (end_dt - timedelta(days=365)).replace(day=1)
    else:
        start_dt = datetime.fromisoformat(
            start + "T00:00:00",
        ).replace(tzinfo=timezone.utc)
    return await _retention_drilldown_rows(
        tenant_id, "gained",
        start_dt.strftime("%Y-%m-%d"),
        end_dt.strftime("%Y-%m-%d"),
        page, limit,
    )


@router.get("/reports/customer-retention/lost-list")
async def customer_retention_lost_list(
    user: dict = Depends(require_admin),
    period: str = Query("month"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    """Paginated drill-down of customers counted in Lost tile."""
    if period not in ("week", "month", "year"):
        raise HTTPException(400, "period must be week|month|year")
    tenant_id = user["tenant_id"]
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    end_dt = (
        today + timedelta(days=1) if not end else
        datetime.fromisoformat(end + "T00:00:00").replace(tzinfo=timezone.utc)
    )
    if not start:
        if period == "week":
            start_dt = end_dt - timedelta(weeks=52)
        elif period == "year":
            start_dt = end_dt.replace(year=end_dt.year - 4, month=1, day=1)
        else:
            start_dt = (end_dt - timedelta(days=365)).replace(day=1)
    else:
        start_dt = datetime.fromisoformat(
            start + "T00:00:00",
        ).replace(tzinfo=timezone.utc)
    return await _retention_drilldown_rows(
        tenant_id, "lost",
        start_dt.strftime("%Y-%m-%d"),
        end_dt.strftime("%Y-%m-%d"),
        page, limit,
    )


# ─── Phase 39 · Algae-risk auto-flag ────────────────────────────────────────
# When a customer's last two submitted service reports both show free
# chlorine ≤ 0.5 ppm the pool is at meaningful algae-bloom risk. We record
# the fact in `algae_risk_flags` so the office can prompt a shock visit
# before things turn green (algae remediation costs the customer real money
# and the biz loses trust). The threshold is deliberate: 0.5 ppm mirrors the
# lower bound of the AI-dosing recommender.
ALGAE_RISK_CHLORINE_PPM = 0.5


def _chlorine_ppm(readings) -> float | None:
    """Extract the chlorine value from a `chemical_readings` list.

    Phase P17.1 · Feb-2026 — accepts the canonical ``chlorine`` key
    plus legacy spellings (``free_chlorine``, ``free chlorine``) so
    reports written before the rename still resolve.
    Returns None if nothing usable is stored.
    """
    if not readings:
        return None
    by_key = {}
    for r in readings or []:
        k = (r.get("key") or r.get("name") or "").lower().strip()
        v = r.get("value")
        if v in (None, ""):
            continue
        try:
            by_key[k] = float(v)
        except (TypeError, ValueError):
            continue
    for k in ("chlorine", "free_chlorine", "free chlorine"):
        if k in by_key:
            return by_key[k]
    return None


async def evaluate_algae_risk(tenant_id: str, customer_id: str | None):
    """Called from service_reports.submit. Idempotent — one open flag per
    customer at a time. Writes `{tenant_id, customer_id, flagged_at,
    evidence, resolved:False}` when the last two submitted reports both
    show chlorine ≤ 0.5 ppm."""
    if not customer_id:
        return None
    # Any already-open flag? Keep it open, just refresh evidence.
    from utils import not_deleted_filter as _nd
    jobs = await db.jobs.find(
        {"customer_id": customer_id, "tenant_id": tenant_id, **_nd()},
        {"_id": 0, "id": 1},
    ).to_list(2000)
    jids = [j["id"] for j in jobs]
    if not jids:
        return None
    reports = await db.service_reports.find(
        {"job_id": {"$in": jids}, "submitted_at": {"$ne": None},
         "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "job_id": 1, "chemical_readings": 1,
         "submitted_at": 1},
    ).sort("submitted_at", -1).to_list(2)
    if len(reports) < 2:
        return None
    evidence = []
    for rep in reports:
        cl = _chlorine_ppm(rep.get("chemical_readings"))
        if cl is None or cl > ALGAE_RISK_CHLORINE_PPM:
            return None  # streak broken
        evidence.append({
            "report_id": rep.get("id"),
            "chlorine": cl,
            "date": rep.get("submitted_at"),
        })
    now = now_iso()
    existing = await db.algae_risk_flags.find_one({
        "tenant_id": tenant_id, "customer_id": customer_id,
        "resolved": False,
    })
    if existing:
        # Refresh evidence but keep the original `flagged_at` — the office
        # wants to see "flagged 12d ago" as a persistent aging signal.
        await db.algae_risk_flags.update_one(
            {"id": existing["id"]},
            {"$set": {"evidence": evidence, "updated_at": now}},
        )
        return existing["id"]
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "flagged_at": now,
        "updated_at": now,
        "evidence": evidence,
        "resolved": False,
        "resolved_at": None,
        "resolved_by": None,
        "resolution_kind": None,
    }
    await db.algae_risk_flags.insert_one(doc)
    return doc["id"]


@router.get("/reports/algae-risk")
async def list_algae_risk(user: dict = Depends(require_admin)):
    """List all currently-flagged customers with their evidence + basic
    customer info so the retention-report panel can render them."""
    tenant_id = user["tenant_id"]
    flags = await db.algae_risk_flags.find(
        {"tenant_id": tenant_id, "resolved": False},
        {"_id": 0},
    ).sort("flagged_at", 1).to_list(200)
    if not flags:
        return {"items": [], "count": 0}
    cust_ids = list({f["customer_id"] for f in flags})
    customers = await db.customers.find(
        {"id": {"$in": cust_ids}, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
         "address": 1, "pool_gallons": 1, "is_vip": 1},
    ).to_list(len(cust_ids))
    cmap = {c["id"]: c for c in customers}
    for f in flags:
        f["customer"] = cmap.get(f["customer_id"])
    return {"items": flags, "count": len(flags)}


@router.post("/reports/algae-risk/{customer_id}/resolve")
async def resolve_algae_risk(customer_id: str,
                                user: dict = Depends(require_admin)):
    """Manual dismiss — office decided the customer is fine (e.g. just
    tested and confirmed chlorine is now normal)."""
    tenant_id = user["tenant_id"]
    now = now_iso()
    r = await db.algae_risk_flags.update_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "resolved": False},
        {"$set": {"resolved": True, "resolved_at": now,
                   "resolved_by": user["id"], "resolution_kind": "dismissed"}},
    )
    if r.modified_count == 0:
        raise HTTPException(404, "No open algae-risk flag for this customer")
    return {"ok": True, "resolved_at": now}


@router.post("/reports/algae-risk/{customer_id}/schedule-shock")
async def schedule_shock_algae_risk(customer_id: str,
                                        user: dict = Depends(require_admin)):
    """Auto-schedules a Shock Treatment job for the customer, then resolves
    the flag. Keeps the office one tap away from remediation."""
    tenant_id = user["tenant_id"]
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    # Simple new job — scheduling engine + tech assignment can be tweaked
    # from the schedule page after creation. Keep the shape aligned with
    # the existing jobs schema (id/name/customer_id/tenant_id/status/...).
    now = now_iso()
    job = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "customer_name": cust.get("name"),
        "address": cust.get("address"),
        "service_type": "Shock Treatment",
        "template": "pool",
        "status": "scheduled",
        "billable": True,
        "price": 65.0,   # baseline; office can edit
        "notes": "Auto-created from algae-risk flag — free chlorine ≤ 0.5 ppm on last 2 visits.",
        "scheduled_at": now,
        "created_at": now, "updated_at": now,
        "source": "algae_risk_auto",
    }
    await db.jobs.insert_one(job)
    await db.algae_risk_flags.update_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "resolved": False},
        {"$set": {"resolved": True, "resolved_at": now,
                   "resolved_by": user["id"],
                   "resolution_kind": "scheduled_shock",
                   "scheduled_job_id": job["id"]}},
    )
    return {"ok": True, "job_id": job["id"], "resolved_at": now}


# ═══════════════════════════════════════════════════════════════════
# Phase 10 · Feb-2026 — Labor cost report.
#
# Thin wrapper around ``services.labor_cost.compute_labor_cost``.
# Separate from the EBIT report so the Ops / Finance team can
# surface the per-tech breakdown independently (and so Phase 11
# can inject recurring labor costs into EBIT without changing
# this endpoint's response shape).
#
# Role gate:
#   * admin / super_admin / owner → full read (write-only roles are
#     out of scope here — this is a read-only report).
#   * manager                    → read-only parity (manager
#     equivalents already have read access to EBIT per Phase 53c).
#   * technician / customer      → 403.
#
# Response shape: see ``services.labor_cost.compute_labor_cost``.
# ═══════════════════════════════════════════════════════════════════
_LABOR_COST_VIEWER_ROLES = frozenset({
    "admin", "super_admin", "owner", "manager",
})


@router.get("/reports/labor-cost")
async def get_labor_cost_report(
    start: str = Query(..., description=(
        "Inclusive window start, ISO date (``YYYY-MM-DD``). "
        "Matches the EBIT convention — a job on this exact day is "
        "included if its ``scheduled_date`` equals ``start``.")),
    end: str = Query(..., description=(
        "Inclusive window end, ISO date (``YYYY-MM-DD``). "
        "Matches the EBIT convention — a job on this exact day is "
        "included if its ``scheduled_date`` equals ``end``.")),
    tech_id: Optional[str] = Query(
        None,
        description=(
            "When set, narrows the report to a single technician's "
            "``users.id`` (or equivalent ``technician_id``)."
        ),
    ),
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    role = ((user or {}).get("role") or "").lower()
    if role not in _LABOR_COST_VIEWER_ROLES:
        raise HTTPException(status_code=403, detail="forbidden")
    from services.labor_cost import compute_labor_cost
    return await compute_labor_cost(
        tenant["id"], start, end,
        tech_filter=(tech_id or None),
    )
