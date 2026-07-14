"""Phase 15B — Advanced analytics + predictions.

Rule-based (no ML libs). Numbers are derived from real seed data:
- Customer LTV: cumulative paid-invoice revenue per customer with tier chips.
- Churn risk: 0-100 heuristic combining recency, payment lag, negative CSAT,
  complaint count in comms, cancelled plans.
- Tech productivity: technicians × weekdays matrix of completed jobs / duration / on-time %.
- Revenue anomalies: daily paid revenue, flags = |x - rolling_mean_30| > 2 * rolling_std_30.
- Forecast v2: extends Phase 6 forecast with seasonality + weather adjustment + P10/P50/P90.
"""
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from config import db
from utils import require_admin, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()


# ─── helpers ────────────────────────────────────────────────────────────────
def _to_iso_date(v) -> Optional[str]:
    if not v:
        return None
    s = str(v)
    return s[:10] if len(s) >= 10 else None


def _paid_iso(inv: dict) -> Optional[str]:
    return _to_iso_date(inv.get("paid_at") or inv.get("created_at"))


def _lifetime_revenue_by_customer(invoices: List[dict]) -> dict:
    tot = defaultdict(float)
    for inv in invoices:
        if inv.get("payment_status") != "paid":
            continue
        cid = inv.get("customer_id")
        if not cid:
            continue
        tot[cid] += float(inv.get("total") or 0)
    return dict(tot)


def _tier(v: float) -> str:
    if v >= 5000:
        return "platinum"
    if v >= 2000:
        return "gold"
    if v >= 500:
        return "silver"
    return "bronze"


# ─── Overview ───────────────────────────────────────────────────────────────
@router.get("/analytics/overview")
async def overview(user: dict = Depends(require_admin),
                   tenant: dict = Depends(get_current_tenant)):
    tid = tenant["id"]
    now = datetime.now(timezone.utc)
    this_month_key = now.strftime("%Y-%m")
    last_month = (now.replace(day=1) - timedelta(days=1))
    last_month_key = last_month.strftime("%Y-%m")

    invoices = await db.quotes.find(
        {"tenant_id": tid, "doc_type": "invoice", "payment_status": "paid"}, {"_id": 0}
    ).to_list(3000)
    this_mo = sum(float(i.get("total") or 0) for i in invoices if (i.get("paid_at") or "").startswith(this_month_key))
    last_mo = sum(float(i.get("total") or 0) for i in invoices if (i.get("paid_at") or "").startswith(last_month_key))

    pct = round(((this_mo - last_mo) / last_mo) * 100, 1) if last_mo else 0.0

    d2d_spend = 0.0
    campaigns = await db.marketing_campaigns.find({"tenant_id": tid}, {"_id": 0}).to_list(500)
    marketing_spend = sum(float(c.get("spend") or 0) for c in campaigns)
    new_customers = await db.customers.count_documents(
        {"tenant_id": tid, "created_at": {"$gte": now.replace(day=1).isoformat()}}
    )
    cac = round((d2d_spend + marketing_spend) / max(1, new_customers), 2)

    ltv_by_cust = _lifetime_revenue_by_customer(invoices)
    avg_ltv = round(sum(ltv_by_cust.values()) / max(1, len(ltv_by_cust)), 2) if ltv_by_cust else 0.0

    return {
        "this_month_revenue": round(this_mo, 2),
        "last_month_revenue": round(last_mo, 2),
        "mom_change_pct": pct,
        "cac": cac,
        "avg_ltv": avg_ltv,
        "active_customers": len(ltv_by_cust),
        "new_customers_this_month": new_customers,
    }


# ─── Customer LTV ───────────────────────────────────────────────────────────
@router.get("/analytics/customer-ltv")
async def customer_ltv(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    tid = tenant["id"]
    customers = await db.customers.find({"tenant_id": tid}, {"_id": 0}).to_list(2000)
    invoices = await db.quotes.find(
        {"tenant_id": tid, "doc_type": "invoice", "payment_status": "paid"}, {"_id": 0}
    ).to_list(5000)

    per_cust = defaultdict(lambda: {"revenue": 0.0, "invoice_count": 0, "last_paid": None})
    for inv in invoices:
        cid = inv.get("customer_id")
        if not cid:
            continue
        per_cust[cid]["revenue"] += float(inv.get("total") or 0)
        per_cust[cid]["invoice_count"] += 1
        pd = _paid_iso(inv)
        if pd and (not per_cust[cid]["last_paid"] or pd > per_cust[cid]["last_paid"]):
            per_cust[cid]["last_paid"] = pd

    rows = []
    for c in customers:
        agg = per_cust.get(c["id"], {"revenue": 0.0, "invoice_count": 0, "last_paid": None})
        rev = round(agg["revenue"], 2)
        rows.append({
            "customer_id": c["id"],
            "customer_name": c.get("name") or c.get("customer_name") or "—",
            "email": c.get("email"),
            "revenue": rev,
            "invoice_count": agg["invoice_count"],
            "last_paid": agg["last_paid"],
            "tier": _tier(rev),
            "vip": bool(c.get("vip") or c.get("is_vip")),
        })
    rows.sort(key=lambda r: r["revenue"], reverse=True)

    # Tier distribution summary
    tiers = {"platinum": 0, "gold": 0, "silver": 0, "bronze": 0}
    for r in rows:
        tiers[r["tier"]] += 1
    return {"rows": rows, "tier_counts": tiers, "total_revenue": round(sum(r["revenue"] for r in rows), 2)}


# ─── Churn Risk ─────────────────────────────────────────────────────────────
@router.get("/analytics/churn-risk")
async def churn_risk(user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    tid = tenant["id"]
    now = datetime.now(timezone.utc)
    customers = await db.customers.find({"tenant_id": tid}, {"_id": 0}).to_list(2000)
    jobs = await db.jobs.find({"tenant_id": tid}, {"_id": 0}).to_list(5000)
    invoices = await db.quotes.find({"tenant_id": tid, "doc_type": "invoice"}, {"_id": 0}).to_list(5000)
    csats = await db.csat_surveys.find({"tenant_id": tid, "nps_score": {"$ne": None}}, {"_id": 0}).to_list(2000)
    comms = await db.communications.find({"tenant_id": tid}, {"_id": 0}).to_list(5000)
    plans = await db.billing_plans.find({"tenant_id": tid}, {"_id": 0}).to_list(2000)

    # Index by customer.
    last_visit_by_cust = {}
    for j in jobs:
        cid = j.get("customer_id")
        if not cid:
            continue
        when = j.get("completed_at") or j.get("scheduled_start") or j.get("created_at")
        if when and (not last_visit_by_cust.get(cid) or when > last_visit_by_cust[cid]):
            last_visit_by_cust[cid] = when

    lag_by_cust = defaultdict(list)  # payment lag in days
    for inv in invoices:
        cid = inv.get("customer_id")
        if not cid:
            continue
        created = inv.get("created_at")
        paid = inv.get("paid_at")
        if inv.get("payment_status") == "paid" and created and paid:
            try:
                a = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                b = datetime.fromisoformat(str(paid).replace("Z", "+00:00"))
                lag_by_cust[cid].append((b - a).days)
            except Exception:
                pass
        elif inv.get("payment_status") != "paid" and created:
            try:
                a = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                lag_by_cust[cid].append((now - a).days)  # unpaid = ongoing lag
            except Exception:
                pass

    detractor_count_by_cust = defaultdict(int)
    for s in csats:
        if s.get("nps_score") is not None and s["nps_score"] <= 6 and s.get("customer_id"):
            detractor_count_by_cust[s["customer_id"]] += 1

    complaint_by_cust = defaultdict(int)
    for c in comms:
        text = (c.get("body") or c.get("last_message") or "").lower()
        if any(k in text for k in ("complaint", "unhappy", "cancel", "refund", "terrible", "awful")):
            cid = c.get("customer_id")
            if cid:
                complaint_by_cust[cid] += 1

    cancelled_plans_by_cust = defaultdict(int)
    for p in plans:
        if p.get("active") is False or p.get("status") == "cancelled":
            cid = p.get("customer_id")
            if cid:
                cancelled_plans_by_cust[cid] += 1

    rows = []
    for c in customers:
        cid = c["id"]
        last = last_visit_by_cust.get(cid)
        if last:
            try:
                days_since = (now - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).days
            except Exception:
                days_since = 365
        else:
            days_since = 365

        avg_lag = statistics.mean(lag_by_cust[cid]) if lag_by_cust.get(cid) else 0
        det_ct = detractor_count_by_cust[cid]
        complaint_ct = complaint_by_cust[cid]
        cancel_ct = cancelled_plans_by_cust[cid]

        # Weighted rule-based score, capped at 100.
        recency_score = min(40, max(0, (days_since - 30) * 0.6))  # 0-40
        lag_score = min(20, max(0, (avg_lag - 15) * 0.8))  # 0-20 after 15d avg
        detractor_score = min(20, det_ct * 15)  # 0-20
        complaint_score = min(10, complaint_ct * 5)  # 0-10
        cancel_score = min(10, cancel_ct * 10)  # 0-10
        score = round(recency_score + lag_score + detractor_score + complaint_score + cancel_score)
        score = max(0, min(100, score))

        band = "high" if score >= 70 else "medium" if score >= 40 else "low"

        rows.append({
            "customer_id": cid,
            "customer_name": c.get("name") or "—",
            "risk_score": score,
            "band": band,
            "days_since_last_visit": days_since,
            "avg_payment_lag_days": round(avg_lag, 1),
            "detractor_count": det_ct,
            "complaint_count": complaint_ct,
            "cancelled_plans": cancel_ct,
            "factors": {
                "recency": recency_score,
                "payment_lag": lag_score,
                "nps_detractor": detractor_score,
                "complaints": complaint_score,
                "cancellations": cancel_score,
            },
        })
    rows.sort(key=lambda r: r["risk_score"], reverse=True)
    bands = {"high": 0, "medium": 0, "low": 0}
    for r in rows:
        bands[r["band"]] += 1
    return {"rows": rows, "band_counts": bands}


# ─── Tech Productivity Heatmap ──────────────────────────────────────────────
@router.get("/analytics/tech-productivity")
async def tech_productivity(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant),
                            start: Optional[str] = Query(None),
                            end: Optional[str] = Query(None)):
    """Matrix: techs × weekdays (Mon..Sun) with jobs completed / avg duration / on-time %."""
    tid_ = tenant["id"]
    now = datetime.now(timezone.utc)
    if not start:
        start = (now - timedelta(days=30)).date().isoformat()
    if not end:
        end = now.date().isoformat()

    techs = await db.technicians.find({"tenant_id": tid_}, {"_id": 0}).to_list(500)
    jobs = await db.jobs.find({
        "tenant_id": tid_,
        "status": "completed",
        "completed_at": {"$gte": start, "$lte": end + "T23:59:59+00:00"},
    }, {"_id": 0}).to_list(5000)

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    # cells[tech_id][weekday_idx] = {jobs: n, total_min: 0, on_time: 0}
    cells: dict = defaultdict(lambda: defaultdict(lambda: {"jobs": 0, "total_min": 0, "on_time": 0}))

    for j in jobs:
        tid = j.get("technician_id")
        if not tid:
            continue
        try:
            when = datetime.fromisoformat(str(j.get("completed_at") or j.get("created_at")).replace("Z", "+00:00"))
        except Exception:
            continue
        widx = when.weekday()  # 0=Mon
        cells[tid][widx]["jobs"] += 1
        # Duration = completed_at - scheduled_start (best effort)
        try:
            if j.get("scheduled_start") and j.get("completed_at"):
                a = datetime.fromisoformat(str(j["scheduled_start"]).replace("Z", "+00:00"))
                b = datetime.fromisoformat(str(j["completed_at"]).replace("Z", "+00:00"))
                mins = max(1, int((b - a).total_seconds() / 60))
                cells[tid][widx]["total_min"] += mins
                # on-time = completed within 30 min of scheduled_end
                if j.get("scheduled_end"):
                    end_planned = datetime.fromisoformat(str(j["scheduled_end"]).replace("Z", "+00:00"))
                    if b <= end_planned + timedelta(minutes=30):
                        cells[tid][widx]["on_time"] += 1
        except Exception:
            pass

    matrix = []
    for t in techs:
        tid = t["id"]
        row = {
            "technician_id": tid,
            "technician_name": t.get("name") or "—",
            "cells": [],
            "total_jobs": 0,
        }
        for widx in range(7):
            c = cells[tid][widx]
            avg_dur = round(c["total_min"] / c["jobs"], 1) if c["jobs"] else 0
            on_time_pct = round((c["on_time"] / c["jobs"]) * 100, 1) if c["jobs"] else 0
            row["cells"].append({
                "day": weekdays[widx],
                "jobs": c["jobs"],
                "avg_duration_min": avg_dur,
                "on_time_pct": on_time_pct,
            })
            row["total_jobs"] += c["jobs"]
        matrix.append(row)
    matrix.sort(key=lambda r: r["total_jobs"], reverse=True)

    return {"start": start, "end": end, "weekdays": weekdays, "matrix": matrix}


# ─── Revenue Anomalies ──────────────────────────────────────────────────────
@router.get("/analytics/revenue-anomalies")
async def revenue_anomalies(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant),
                            days: int = Query(120, ge=30, le=730)):
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).date().isoformat()
    invoices = await db.quotes.find({
        "tenant_id": tenant["id"],
        "doc_type": "invoice",
        "payment_status": "paid",
        "paid_at": {"$gte": start},
    }, {"_id": 0}).to_list(10000)

    by_day = defaultdict(float)
    for inv in invoices:
        d = _paid_iso(inv)
        if d:
            by_day[d] += float(inv.get("total") or 0)

    # Fill missing days with 0 to keep the series contiguous.
    series = []
    cur = datetime.now(timezone.utc).date() - timedelta(days=days)
    end_d = datetime.now(timezone.utc).date()
    while cur <= end_d:
        series.append({"date": cur.isoformat(), "revenue": round(by_day.get(cur.isoformat(), 0.0), 2), "anomaly": False, "score": 0.0})
        cur += timedelta(days=1)

    # 30-day rolling mean + std, flag |x - mean| > 2 * std (skip windows w/ <10 datapoints).
    WINDOW = 30
    for i, pt in enumerate(series):
        if i < WINDOW:
            continue
        window = [s["revenue"] for s in series[i - WINDOW:i]]
        if len(window) < 10:
            continue
        mu = statistics.mean(window)
        sd = statistics.pstdev(window) or 1e-9
        z = (pt["revenue"] - mu) / sd
        pt["score"] = round(z, 2)
        if abs(z) >= 2.0 and pt["revenue"] > 0:
            pt["anomaly"] = True
            pt["mean"] = round(mu, 2)
            pt["stdev"] = round(sd, 2)

    anomalies = [p for p in series if p["anomaly"]]
    return {
        "days": days,
        "series": series,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies[-20:],
    }


# ─── Forecast v2 ────────────────────────────────────────────────────────────
_SEASONALITY = {  # month index (1..12) → multiplier
    1: 0.80, 2: 0.85, 3: 0.95, 4: 1.10, 5: 1.20, 6: 1.25,
    7: 1.25, 8: 1.20, 9: 1.15, 10: 1.05, 11: 0.90, 12: 0.80,
}


@router.get("/analytics/forecast-v2")
async def forecast_v2(user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant),
                      days: int = Query(90, ge=30, le=365)):
    """P10/P50/P90 daily revenue projection built on trailing 90-day mean × seasonality
    and a weather-adjustment factor (rainy days ≈ 15% fewer visits, approximated as flat 3%)."""
    now = datetime.now(timezone.utc)
    lookback = 90
    start = (now - timedelta(days=lookback)).date().isoformat()
    invoices = await db.quotes.find({
        "tenant_id": tenant["id"],
        "doc_type": "invoice",
        "payment_status": "paid",
        "paid_at": {"$gte": start},
    }, {"_id": 0}).to_list(10000)

    by_day = defaultdict(float)
    for inv in invoices:
        d = _paid_iso(inv)
        if d:
            by_day[d] += float(inv.get("total") or 0)

    daily = [by_day.get((now.date() - timedelta(days=i)).isoformat(), 0.0)
             for i in range(1, lookback + 1)]
    baseline = statistics.mean(daily) if daily else 0.0
    volatility = statistics.pstdev(daily) if len(daily) > 1 else baseline * 0.3
    weather_adj = 0.97  # flat 3% drag for rainy days across horizon

    series = []
    cur = now.date() + timedelta(days=1)
    for i in range(days):
        month_mult = _SEASONALITY.get(cur.month, 1.0)
        p50 = baseline * month_mult * weather_adj
        p10 = max(0.0, p50 - 1.28 * volatility)
        p90 = p50 + 1.28 * volatility
        series.append({
            "date": cur.isoformat(),
            "p10": round(p10, 2),
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "season_mult": round(month_mult, 2),
        })
        cur += timedelta(days=1)

    return {
        "days": days,
        "baseline_daily": round(baseline, 2),
        "volatility": round(volatility, 2),
        "weather_adjustment": weather_adj,
        "series": series,
        "totals": {
            "p10": round(sum(s["p10"] for s in series), 2),
            "p50": round(sum(s["p50"] for s in series), 2),
            "p90": round(sum(s["p90"] for s in series), 2),
        },
    }
