from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    if user.get("role") == "technician":
        tid = user.get("technician_id")
        pending = await db.jobs.count_documents({"technician_id": tid, "status": "pending"})
        active = await db.jobs.count_documents({"technician_id": tid, "status": "active"})
        completed = await db.jobs.count_documents({"technician_id": tid, "status": "completed"})
        upcoming = await db.jobs.find(
            {"technician_id": tid, "status": {"$in": ["pending", "active"]}}, {"_id": 0}
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
        active = await db.jobs.count_documents({"customer_id": cid, "status": {"$in": ["pending", "active"]}})
        completed = await db.jobs.count_documents({"customer_id": cid, "status": "completed"})
        unpaid_docs = await db.quotes.find(
            {"customer_id": cid, "doc_type": "invoice", "payment_status": "unpaid"}, {"_id": 0}
        ).to_list(1000)
        outstanding = round(sum(q["total"] for q in unpaid_docs), 2)
        pending_estimates = await db.quotes.count_documents(
            {"customer_id": cid, "doc_type": "quote", "status": {"$nin": ["accepted", "declined"]}}
        )
        upcoming = await db.jobs.find(
            {"customer_id": cid, "status": {"$in": ["pending", "active", "requested"]}}, {"_id": 0}
        ).sort("scheduled_date", 1).to_list(20)
        next_service = upcoming[0] if upcoming else None
        recent = await db.jobs.find(
            {"customer_id": cid}, {"_id": 0}
        ).sort("created_at", -1).to_list(5)
        cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
        unread_messages = await db.messages.count_documents({"customer_id": cid, "sender": "business", "read_by_customer": False})
        documents_count = await db.documents.count_documents({"customer_id": cid})
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

    paid = await db.quotes.find({"payment_status": "paid"}, {"_id": 0}).to_list(1000)
    revenue = round(sum(q["total"] for q in paid), 2)
    outstanding_docs = await db.quotes.find(
        {"doc_type": "invoice", "payment_status": "unpaid"}, {"_id": 0}
    ).to_list(1000)
    outstanding = round(sum(q["total"] for q in outstanding_docs), 2)
    active = await db.jobs.count_documents({"status": "active"})
    pending = await db.jobs.count_documents({"status": "pending"})
    completed = await db.jobs.count_documents({"status": "completed"})
    requested = await db.jobs.count_documents({"status": "requested"})
    total_customers = await db.customers.count_documents({})
    total_techs = await db.technicians.count_documents({})
    recent = await db.jobs.find({}, {"_id": 0}).sort("created_at", -1).to_list(6)

    # Revenue trend — last 6 months
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

    # Revenue by service (from all jobs)
    svc: dict = {}
    alljobs = await db.jobs.find({}, {"_id": 0}).to_list(2000)
    for j in alljobs:
        k = j.get("service_type") or "Other"
        svc[k] = svc.get(k, 0.0) + (j.get("price") or 0.0)
    revenue_by_service = sorted(
        [{"label": k, "value": round(v, 2)} for k, v in svc.items() if v > 0], key=lambda x: -x["value"]
    )[:6]

    # Recurring vs project revenue (from paid invoices)
    recurring = round(sum(q["total"] for q in paid if any(w in (q.get("title", "").lower()) for w in ["monthly", "weekly", "recurring"])), 2)
    project = round(max(0.0, revenue - recurring), 2)

    total_leads = await db.leads.count_documents({})
    open_leads = await db.leads.count_documents({"status": {"$in": ["new", "contacted", "quoted"]}})

    return {
        "role": "admin",
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


