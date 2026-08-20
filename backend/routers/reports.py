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


def _paid_amt(q: dict) -> float:
    paid = q.get("amount_paid")
    if not paid:
        paid = q.get("total", 0) if q.get("payment_status") == "paid" else 0
    return float(paid or 0)


def _extract_city(addr: str) -> str:
    if not addr:
        return "Unknown"
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else "Unknown"


async def _fetch_paid(dfrom: Optional[str], dto: Optional[str]) -> list:
    docs = await db.quotes.find(
        {"doc_type": "invoice", "$or": [{"amount_paid": {"$gt": 0}}, {"payment_status": "paid"}]},
        {"_id": 0},
    ).to_list(10000)
    return [q for q in docs if _in_range(q.get("paid_at") or q.get("created_at"), dfrom, dto)]


async def _fetch_all_invoices(dfrom: Optional[str], dto: Optional[str]) -> list:
    docs = await db.quotes.find({"doc_type": "invoice"}, {"_id": 0}).to_list(10000)
    return [q for q in docs if _in_range(q.get("created_at"), dfrom, dto)]


# ─── revenue slices ───────────────────────────────────────────────────────────
@router.get("/reports/revenue-by-city")
async def revenue_by_city(start: Optional[str] = None, end: Optional[str] = None,
                          user: dict = Depends(require_admin)):
    paid = await _fetch_paid(start, end)
    customers = await db.customers.find({}, {"_id": 0}).to_list(5000)
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
                          user: dict = Depends(require_admin)):
    paid = await _fetch_paid(start, end)
    jobs = await db.jobs.find({}, {"_id": 0}).to_list(10000)
    job_crew = {j["id"]: j.get("crew_id") for j in jobs}
    crews = await db.crews.find({}, {"_id": 0}).to_list(500)
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
                              user: dict = Depends(require_admin)):
    paid = await _fetch_paid(start, end)
    buckets: dict = {}
    counts: dict = {}
    for q in paid:
        cid = q.get("customer_id") or "unknown"
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
    return {"rows": rows, "summary": {"total": total, "customers": len(rows), "invoices": len(paid)}}


@router.get("/reports/gross-sales")
async def gross_sales(start: Optional[str] = None, end: Optional[str] = None,
                      user: dict = Depends(require_admin)):
    """Sum of ALL invoices created in the window — paid + unpaid."""
    invs = await _fetch_all_invoices(start, end)
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
                         user: dict = Depends(require_admin)):
    """Per-line-item aggregation across invoices in window."""
    invs = await _fetch_all_invoices(start, end)
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


async def _forecast_series(days_ahead: int = 90) -> list:
    """Return weekly buckets of projected revenue from active billing plans + weighted quotes."""
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=days_ahead)
    return await _forecast_series_between(today, horizon)


async def _forecast_series_between(start_date, end_date) -> list:
    """Feb-2026 · daily buckets between an inclusive [start_date, end_date]
    window. Reuses the same billing-plan + weighted-quote projection but
    keys each row by ISO date rather than week-start so short windows
    (today / tomorrow) still render meaningful bars.
    """
    plans = await db.billing_plans.find({"active": {"$ne": False}}, {"_id": 0}).to_list(2000)
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
    quotes = await db.quotes.find({"doc_type": "quote"}, {"_id": 0}).to_list(3000)
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
        series = await _forecast_series_between(start_local, end_local)
        total = round(sum(x["amount"] for x in series), 2)
        return {"series": series, "total": total,
                "range": preset,
                "date_from": start_local.isoformat(),
                "date_to": end_local.isoformat()}
    series = await _forecast_series(days)
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
    unpaid = await db.quotes.find({"doc_type": "invoice", "payment_status": "unpaid"}, {"_id": 0}).to_list(3000)
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
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    q: dict = {"doc_type": "invoice"}
    if status:
        q["payment_status"] = status
    else:
        q["$or"] = [{"amount_paid": {"$gt": 0}}, {"payment_status": {"$in": ["paid", "processing", "partial"]}}]
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
                      start: Optional[str] = None, end: Optional[str] = None):
    rows = await db.jobs.find({}, {"_id": 0}).sort("scheduled_date", -1).to_list(10000)
    if start or end:
        rows = [r for r in rows if _in_range(r.get("scheduled_date") or r.get("created_at"), start, end)]
    return {"filename": "jobs.csv", "content": _to_csv(rows, JOB_COLS), "count": len(rows)}


@router.get("/export/invoices")
async def export_invoices(user: dict = Depends(require_admin),
                          start: Optional[str] = None, end: Optional[str] = None):
    rows = await db.quotes.find({"doc_type": "invoice"}, {"_id": 0}).sort("created_at", -1).to_list(10000)
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
    """Customers created in [s, e). `created_at` is stored as ISO strings."""
    n = await db.customers.count_documents({
        "tenant_id": tenant_id,
        "created_at": {"$gte": s, "$lt": e},
    })
    return int(n)


async def _count_lost(tenant_id: str, s: str, e: str) -> int:
    """Deactivation events (active→inactive) in [s, e)."""
    n = await db.customer_activation_events.count_documents({
        "tenant_id": tenant_id,
        "to_status": "inactive",
        "changed_at": {"$gte": s, "$lt": e},
    })
    return int(n)


async def _totals_for_range(tenant_id: str, s: str, e: str) -> dict:
    g = await _count_gained(tenant_id, s, e)
    l = await _count_lost(tenant_id, s, e)
    return {"gained": g, "lost": l, "net": g - l}


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


# ─── Phase 39 · Algae-risk auto-flag ────────────────────────────────────────
# When a customer's last two submitted service reports both show free
# chlorine ≤ 0.5 ppm the pool is at meaningful algae-bloom risk. We record
# the fact in `algae_risk_flags` so the office can prompt a shock visit
# before things turn green (algae remediation costs the customer real money
# and the biz loses trust). The threshold is deliberate: 0.5 ppm mirrors the
# lower bound of the AI-dosing recommender.
ALGAE_RISK_CHLORINE_PPM = 0.5


def _chlorine_ppm(readings) -> float | None:
    """Extract the free-chlorine value from a `chemical_readings` list.

    Falls back to `chlorine` (single-column pools) if `free_chlorine`
    isn't present. Returns None if nothing usable is stored.
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
    for k in ("free_chlorine", "free chlorine", "chlorine"):
        if k in by_key:
            return by_key[k]
    return None


async def evaluate_algae_risk(tenant_id: str, customer_id: str | None):
    """Called from service_reports.submit. Idempotent — one open flag per
    customer at a time. Writes `{tenant_id, customer_id, flagged_at,
    evidence, resolved:False}` when the last two submitted reports both
    show free_chlorine ≤ 0.5 ppm."""
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
            "free_chlorine": cl,
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
