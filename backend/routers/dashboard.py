from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
# Bucket A2 · Feb-2026 — wildcard removed; dashboard.py does not reference
# any symbol from ``models`` (verified via AST diff against models exports).

router = APIRouter()


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    tid = tenant["id"]
    if user.get("role") == "technician":
        techn_id = user.get("technician_id")
        base = {"technician_id": techn_id, "tenant_id": tid}
        pending = await db.jobs.count_documents({**base, "status": "pending"})
        active = await db.jobs.count_documents({**base, "status": "active"})
        completed = await db.jobs.count_documents({**base, "status": "completed"})
        from utils import not_deleted_filter as _nd
        upcoming = await db.jobs.find(
            {**base, "status": {"$in": ["pending", "active"]}, **_nd()}, {"_id": 0}
        ).sort("scheduled_date", 1).to_list(10)
        return {
            "role": "technician",
            "pending_jobs": pending,
            "active_jobs": active,
            "completed_jobs": completed,
            "upcoming_jobs": upcoming,
        }

    if user.get("role") == "customer":
        cid = user.get("customer_id")
        base = {"customer_id": cid, "tenant_id": tid}
        active = await db.jobs.count_documents({**base, "status": {"$in": ["pending", "active"]}})
        completed = await db.jobs.count_documents({**base, "status": "completed"})
        unpaid_docs = await db.quotes.find(
            {**base, "doc_type": "invoice", "payment_status": "unpaid"}, {"_id": 0}
        ).to_list(1000)
        outstanding = round(sum(q["total"] for q in unpaid_docs), 2)
        pending_estimates = await db.quotes.count_documents(
            {**base, "doc_type": "quote", "status": {"$nin": ["accepted", "declined"]}}
        )
        upcoming = await db.jobs.find(
            {**base, "status": {"$in": ["pending", "active", "requested"]}, **_nd()}, {"_id": 0}
        ).sort("scheduled_date", 1).to_list(20)
        next_service = upcoming[0] if upcoming else None
        recent = await db.jobs.find(base, {"_id": 0}).sort("created_at", -1).to_list(5)
        cust = await db.customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0}) or {}
        unread_messages = await db.messages.count_documents(
            {**base, "sender": "business", "read_by_customer": False}
        )
        documents_count = await db.documents.count_documents(base)
        return {
            "role": "customer",
            "active_jobs": active,
            "completed_jobs": completed,
            "outstanding": outstanding,
            "unpaid_invoices": len(unpaid_docs),
            "pending_estimates": pending_estimates,
            "account_credit": round(cust.get("account_credit", 0.0), 2),
            "unread_messages": unread_messages,
            "documents_count": documents_count,
            "next_service": next_service,
            "recent_jobs": recent,
        }

    # Admin / super_admin
    tenant_q = {"tenant_id": tid}
    paid = await db.quotes.find({**tenant_q, "payment_status": "paid"}, {"_id": 0}).to_list(1000)
    revenue = round(sum(q["total"] for q in paid), 2)
    outstanding_docs = await db.quotes.find(
        {**tenant_q, "doc_type": "invoice", "payment_status": "unpaid"}, {"_id": 0}
    ).to_list(1000)
    outstanding = round(sum(q["total"] for q in outstanding_docs), 2)
    active = await db.jobs.count_documents({**tenant_q, "status": "active"})
    pending = await db.jobs.count_documents({**tenant_q, "status": "pending"})
    completed = await db.jobs.count_documents({**tenant_q, "status": "completed"})
    requested = await db.jobs.count_documents({**tenant_q, "status": "requested"})
    total_customers = await db.customers.count_documents(tenant_q)
    total_techs = await db.technicians.count_documents(tenant_q)
    recent = await db.jobs.find(tenant_q, {"_id": 0}).sort("created_at", -1).to_list(6)

    now = datetime.now(timezone.utc)
    seq = []
    yy, mm = now.year, now.month
    for i in range(5, -1, -1):
        m = mm - i
        y = yy
        while m <= 0:
            m += 12
            y -= 1
        seq.append((y, m))
    buckets = {f"{y}-{m:02d}": 0.0 for (y, m) in seq}
    for qd in paid:
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

    svc: dict = {}
    alljobs = await db.jobs.find({**tenant_q, **_nd()}, {"_id": 0}).to_list(2000)
    for j in alljobs:
        k = j.get("service_type") or "Other"
        svc[k] = svc.get(k, 0.0) + (j.get("price") or 0.0)
    revenue_by_service = sorted(
        [{"label": k, "value": round(v, 2)} for k, v in svc.items() if v > 0], key=lambda x: -x["value"]
    )[:6]

    recurring = round(sum(q["total"] for q in paid if any(w in (q.get("title", "").lower()) for w in ["monthly", "weekly", "recurring"])), 2)
    project = round(max(0.0, revenue - recurring), 2)

    total_leads = await db.leads.count_documents(tenant_q)
    open_leads = await db.leads.count_documents({**tenant_q, "status": {"$in": ["new", "contacted", "quoted"]}})

    return {
        "role": user.get("role", "admin"),
        "revenue": revenue,
        "outstanding": outstanding,
        "active_jobs": active,
        "pending_jobs": pending,
        "completed_jobs": completed,
        "requested_jobs": requested,
        "total_customers": total_customers,
        "total_technicians": total_techs,
        "total_leads": total_leads,
        "open_leads": open_leads,
        "recent_jobs": recent,
        "revenue_series": revenue_series,
        "revenue_by_service": revenue_by_service,
        "recurring_vs_project": {"recurring": recurring, "project": project},
    }
