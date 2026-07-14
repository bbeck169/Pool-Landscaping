from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from models import *

router = APIRouter()


# ----------------------- Operations: Dispatch -----------------------
@router.get("/dispatch")
async def dispatch(user: dict = Depends(require_admin),
                   tenant: dict = Depends(get_current_tenant),
                   date: Optional[str] = None):
    """Technicians with their jobs for a given day, plus an unassigned bucket."""
    day = (date or now_iso())[:10]
    jobs = await db.jobs.find(
        {"tenant_id": tenant["id"], "status": {"$in": ["pending", "active", "requested", "completed"]}},
        {"_id": 0},
    ).to_list(2000)
    day_jobs = [j for j in jobs if (j.get("scheduled_date") or "")[:10] == day]
    techs = await db.technicians.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("name", 1).to_list(1000)
    columns = []
    for t in techs:
        tjobs = [j for j in day_jobs if j.get("technician_id") == t["id"]]
        tjobs.sort(key=lambda j: j.get("scheduled_date") or "")
        columns.append({
            "technician_id": t["id"],
            "technician_name": t["name"],
            "avatar": t.get("avatar", ""),
            "specialty": t.get("specialty", ""),
            "jobs": tjobs,
        })
    unassigned = [j for j in day_jobs if not j.get("technician_id")]
    unassigned.sort(key=lambda j: j.get("scheduled_date") or "")
    return {"date": day, "columns": columns, "unassigned": unassigned}


# ----------------------- Operations: Work Stream -----------------------
@router.get("/activity")
async def activity(user: dict = Depends(require_admin),
                   tenant: dict = Depends(get_current_tenant),
                   limit: int = 40):
    """Unified reverse-chronological activity feed across the CRM."""
    tid = tenant["id"]
    events = []
    jobs = await db.jobs.find({"tenant_id": tid}, {"_id": 0}).sort("created_at", -1).to_list(60)
    for j in jobs:
        ref = {"type": "job", "id": j.get("id")}
        if j.get("status") == "requested":
            events.append({"type": "request", "icon": "help-buoy", "title": "Service requested",
                           "detail": f"{j.get('customer_name', 'Customer')} · {j.get('service_type', j.get('title', ''))}",
                           "at": j.get("created_at"), "related_ref": ref})
        elif j.get("status") == "completed":
            events.append({"type": "job_done", "icon": "checkmark-done-circle", "title": "Job completed",
                           "detail": f"{j.get('title', '')} · {j.get('technician_name') or 'Unassigned'}",
                           "at": j.get("completed_at") or j.get("created_at"), "related_ref": ref})
        else:
            events.append({"type": "job", "icon": "briefcase", "title": "Job created",
                           "detail": f"{j.get('title', '')} · {j.get('customer_name', '')}",
                           "at": j.get("created_at"), "related_ref": ref})
    paid = await db.quotes.find(
        {"tenant_id": tid, "payment_status": "paid"}, {"_id": 0}
    ).sort("paid_at", -1).to_list(30)
    for q in paid:
        ref_type = "invoice" if q.get("doc_type") == "invoice" else "quote"
        events.append({"type": "payment", "icon": "card", "title": "Payment received",
                       "detail": f"{q.get('customer_name', '')} · ${q.get('total', 0):,.2f}",
                       "at": q.get("paid_at") or q.get("created_at"),
                       "related_ref": {"type": ref_type, "id": q.get("id")}})
    leads = await db.leads.find({"tenant_id": tid}, {"_id": 0}).sort("created_at", -1).to_list(30)
    for l in leads:
        events.append({"type": "lead", "icon": "magnet", "title": "New lead",
                       "detail": f"{l.get('name', '')} · {l.get('source', '')}",
                       "at": l.get("created_at"),
                       "related_ref": {"type": "lead", "id": l.get("id")}})
    events = [e for e in events if e.get("at")]
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


# ----------------------- Operations: Reports -----------------------
@router.get("/reports")
async def reports(user: dict = Depends(require_admin),
                  tenant: dict = Depends(get_current_tenant)):
    return await _compute_reports(tenant["id"])


def _in_range(iso: str | None, date_from: str | None, date_to: str | None) -> bool:
    if not (date_from or date_to):
        return True
    if not iso:
        return False
    d = iso[:10]
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


async def _compute_reports(tenant_id: str, date_from: str | None = None, date_to: str | None = None):
    tq = {"tenant_id": tenant_id}
    paid_all = await db.quotes.find({**tq, "payment_status": "paid"}, {"_id": 0}).to_list(2000)
    paid = [q for q in paid_all if _in_range(q.get("paid_at") or q.get("created_at"), date_from, date_to)]
    revenue = round(sum(q["total"] for q in paid), 2)
    outstanding_docs = await db.quotes.find(
        {**tq, "doc_type": "invoice", "payment_status": "unpaid"}, {"_id": 0}
    ).to_list(2000)
    outstanding_docs = [q for q in outstanding_docs if _in_range(q.get("created_at"), date_from, date_to)]
    outstanding = round(sum(q["total"] for q in outstanding_docs), 2)

    now = datetime.now(timezone.utc)
    seq = []
    yy, mm = now.year, now.month
    for i in range(5, -1, -1):
        m, y = mm - i, yy
        while m <= 0:
            m += 12
            y -= 1
        seq.append((y, m))
    buckets = {f"{y}-{m:02d}": 0.0 for (y, m) in seq}
    for qd in paid_all:
        ds = qd.get("paid_at") or qd.get("created_at")
        try:
            dt = datetime.fromisoformat(ds)
            key = f"{dt.year}-{dt.month:02d}"
            if key in buckets:
                buckets[key] += qd["total"]
        except Exception:
            pass
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    revenue_series = [{"label": month_names[m - 1], "value": round(buckets[f"{y}-{m:02d}"], 2)} for (y, m) in seq]

    all_jobs = await db.jobs.find(tq, {"_id": 0}).to_list(3000)
    all_jobs = [j for j in all_jobs if _in_range(j.get("scheduled_date") or j.get("created_at"), date_from, date_to)]
    status_counts: dict = {}
    for j in all_jobs:
        s = j.get("status", "pending")
        status_counts[s] = status_counts.get(s, 0) + 1
    jobs_by_status = [{"label": k, "value": v} for k, v in status_counts.items()]

    svc: dict = {}
    for j in all_jobs:
        k = j.get("service_type") or "Other"
        svc[k] = svc.get(k, 0.0) + (j.get("price") or 0.0)
    revenue_by_service = sorted(
        [{"label": k, "value": round(v, 2)} for k, v in svc.items() if v > 0], key=lambda x: -x["value"]
    )[:6]

    cust_rev: dict = {}
    for q in paid:
        name = q.get("customer_name", "Unknown")
        cust_rev[name] = cust_rev.get(name, 0.0) + q["total"]
    top_customers = sorted(
        [{"label": k, "value": round(v, 2)} for k, v in cust_rev.items()], key=lambda x: -x["value"]
    )[:5]

    techs = await db.technicians.find(tq, {"_id": 0}).to_list(1000)
    tech_perf = []
    for t in techs:
        completed = sum(1 for j in all_jobs if j.get("technician_id") == t["id"] and j.get("status") == "completed")
        active = sum(1 for j in all_jobs if j.get("technician_id") == t["id"] and j.get("status") in ("pending", "active"))
        tech_perf.append({"label": t["name"], "completed": completed, "active": active})
    tech_perf.sort(key=lambda x: -x["completed"])

    total_jobs = len(all_jobs)
    completed_jobs = status_counts.get("completed", 0)
    completion_rate = round((completed_jobs / total_jobs) * 100) if total_jobs else 0
    avg_ticket = round(revenue / len(paid), 2) if paid else 0.0

    return {
        "revenue": revenue,
        "outstanding": outstanding,
        "collected_count": len(paid),
        "avg_ticket": avg_ticket,
        "completion_rate": completion_rate,
        "total_jobs": total_jobs,
        "revenue_series": revenue_series,
        "jobs_by_status": jobs_by_status,
        "revenue_by_service": revenue_by_service,
        "top_customers": top_customers,
        "technician_performance": tech_perf,
    }




@router.get("/reports/business-summary")
async def business_summary(date_from: Optional[str] = Query(None),
                           date_to: Optional[str] = Query(None),
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """One-call aggregate of all key business metrics for the reporting hub + export."""
    from routers.finances import compute_income_by_category
    from routers.jobs import compute_pool_service
    from routers.card import _company

    tid = tenant["id"]
    core = await _compute_reports(tid, date_from, date_to)
    income = await compute_income_by_category(tid, date_from, date_to)
    pool = await compute_pool_service(tid, date_from, date_to) if (date_from and date_to) else await compute_pool_service(tid)

    now = datetime.now(timezone.utc).date()
    if date_from and date_to:
        lo, hi = date_from, date_to
    else:
        lo = (now - timedelta(days=now.weekday())).isoformat()
        hi = (now - timedelta(days=now.weekday()) + timedelta(days=6)).isoformat()
    ts = await db.timesheets.find(
        {"tenant_id": tid, "date": {"$gte": lo, "$lte": hi}}, {"_id": 0}
    ).to_list(2000)
    hours_by_tech: dict = {}
    for t in ts:
        hours_by_tech[t.get("technician_name", "?")] = round(hours_by_tech.get(t.get("technician_name", "?"), 0.0) + float(t.get("hours") or 0), 2)
    labor_rows = [{"label": k, "value": v} for k, v in sorted(hours_by_tech.items(), key=lambda x: -x[1])]

    open_leads = await db.leads.count_documents({"tenant_id": tid, "status": {"$nin": ["won", "lost"]}})
    active_coverage = await db.route_coverage.count_documents({"tenant_id": tid, "active": True})
    total_customers = await db.customers.count_documents({"tenant_id": tid})

    return {
        "generated_at": now_iso(),
        "company": await _company(tid),
        "date_from": date_from,
        "date_to": date_to,
        "kpis": {
            "revenue": core["revenue"],
            "outstanding": core["outstanding"],
            "avg_ticket": core["avg_ticket"],
            "completion_rate": core["completion_rate"],
            "total_jobs": core["total_jobs"],
            "total_customers": total_customers,
            "open_leads": open_leads,
            "active_coverage": active_coverage,
            "labor_hours_week": round(sum(hours_by_tech.values()), 2),
        },
        "revenue_series": core["revenue_series"],
        "revenue_by_service": core["revenue_by_service"],
        "top_customers": core["top_customers"],
        "jobs_by_status": core["jobs_by_status"],
        "technician_performance": core["technician_performance"],
        "income_by_category": income["rows"],
        "income_total": income["total"],
        "pool_service": pool,
        "labor_hours": labor_rows,
    }
