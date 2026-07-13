from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from emailer import send_invoice_reminder_email
from models import *

router = APIRouter()


# ----------------------- Quotes / Invoices -----------------------
def compute_totals(line_items: List[dict], tax_rate: float):
    subtotal = sum(li["quantity"] * li["unit_price"] for li in line_items)
    tax = round(subtotal * (tax_rate / 100.0), 2)
    return round(subtotal, 2), tax, round(subtotal + tax, 2)


@router.get("/quotes")
async def list_quotes(user: dict = Depends(get_current_user), doc_type: Optional[str] = None):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    q = {}
    if user.get("role") == "customer":
        q["customer_id"] = user.get("customer_id")
    if doc_type:
        q["doc_type"] = doc_type
    docs = await db.quotes.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.post("/quotes")
async def create_quote(body: QuoteIn, user: dict = Depends(require_admin)):
    customer = await db.customers.find_one({"id": body.customer_id}, {"_id": 0})
    if not customer:
        raise HTTPException(400, "Customer not found")
    items = [li.dict() for li in body.line_items]
    subtotal, tax, total = compute_totals(items, body.tax_rate)
    due_date = body.due_date
    if body.doc_type == "invoice" and not due_date:
        due_date = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    doc = {
        "id": new_id(),
        "customer_id": body.customer_id,
        "customer_name": customer["name"],
        "title": body.title,
        "doc_type": body.doc_type,
        "line_items": items,
        "tax_rate": body.tax_rate,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "amount_paid": 0.0,
        "due_date": due_date,
        "status": "draft",
        "payment_status": "unpaid",
        "notes": body.notes,
        "created_at": now_iso(),
    }
    await db.quotes.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/quotes/{qid}")
async def get_quote(qid: str, user: dict = Depends(get_current_user)):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    doc = await db.quotes.find_one({"id": qid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quote not found")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")
    return doc


@router.post("/quotes/{qid}/decision")
async def customer_quote_decision(qid: str, decision: str = Query(...), user: dict = Depends(get_current_user)):
    """Customer approves or declines their own estimate."""
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    doc = await db.quotes.find_one({"id": qid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Estimate not found")
    if doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")
    if doc.get("doc_type") != "quote":
        raise HTTPException(400, "Only estimates can be approved or declined")
    status = "accepted" if decision == "approve" else "declined"
    upd = {"status": status}
    if status == "accepted":
        upd["accepted_at"] = now_iso()
    await db.quotes.update_one({"id": qid}, {"$set": upd})
    return await db.quotes.find_one({"id": qid}, {"_id": 0})


@router.get("/quotes/ready-to-schedule")
async def ready_to_schedule(admin: dict = Depends(require_admin)):
    """Approved online estimates not yet turned into a scheduled job."""
    docs = await db.quotes.find(
        {"doc_type": "quote", "status": "accepted", "scheduled_job_id": {"$in": [None, ""]}},
        {"_id": 0},
    ).sort("accepted_at", -1).to_list(500)
    # Include legacy accepted quotes that predate the scheduled_job_id field.
    extra = await db.quotes.find(
        {"doc_type": "quote", "status": "accepted", "scheduled_job_id": {"$exists": False}},
        {"_id": 0},
    ).to_list(500)
    seen = {d["id"] for d in docs}
    docs.extend([e for e in extra if e["id"] not in seen])
    return [{
        "id": d["id"], "title": d.get("title", ""), "customer_id": d.get("customer_id"),
        "customer_name": d.get("customer_name", ""), "total": d.get("total", 0),
        "accepted_at": d.get("accepted_at"),
    } for d in docs]


@router.post("/quotes/{qid}/schedule")
async def schedule_from_estimate(qid: str, body: MaintBulkIn, admin: dict = Depends(require_admin)):
    """Turn an approved estimate into a scheduled job in one tap."""
    try:
        datetime.fromisoformat(body.scheduled_date[:10])
    except (ValueError, TypeError):
        raise HTTPException(400, "scheduled_date must be YYYY-MM-DD")
    doc = await db.quotes.find_one({"id": qid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Estimate not found")
    if doc.get("doc_type") != "quote" or doc.get("status") != "accepted":
        raise HTTPException(400, "Only approved estimates can be scheduled")
    if doc.get("scheduled_job_id"):
        raise HTTPException(400, "This estimate is already scheduled")
    customer = await db.customers.find_one({"id": doc.get("customer_id")}, {"_id": 0})
    tech_name, tech_avatar = None, ""
    if body.technician_id:
        tech = await db.technicians.find_one({"id": body.technician_id}, {"_id": 0})
        tech_name = tech["name"] if tech else None
        tech_avatar = tech.get("avatar", "") if tech else ""
    job = {
        "id": new_id(), "title": doc.get("title", "Service"), "customer_id": doc.get("customer_id"),
        "customer_name": doc.get("customer_name", ""), "technician_id": body.technician_id,
        "technician_name": tech_name, "technician_avatar": tech_avatar,
        "address": (customer or {}).get("address", ""), "service_type": doc.get("title", "Service"),
        "scheduled_date": body.scheduled_date, "notes": doc.get("notes", ""),
        "price": float(doc.get("total") or 0), "status": "pending", "photos": [],
        "from_estimate_id": qid, "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    job.pop("_id", None)
    await db.quotes.update_one({"id": qid}, {"$set": {"scheduled_job_id": job["id"], "status": "scheduled"}})
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Service scheduled",
                              f"Your approved estimate '{doc.get('title')}' is scheduled for {body.scheduled_date}.", job_id=job["id"])
    return job


@router.put("/quotes/{qid}/status")
async def update_quote_status(qid: str, status: str = Query(...), user: dict = Depends(require_admin)):
    await db.quotes.update_one({"id": qid}, {"$set": {"status": status}})
    return await db.quotes.find_one({"id": qid}, {"_id": 0})


@router.post("/quotes/{qid}/send-reminder")
async def send_reminder(qid: str, user: dict = Depends(require_admin)):
    """One-tap payment reminder for an outstanding invoice: in-app + SMS + email."""
    inv = await db.quotes.find_one({"id": qid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if not inv.get("customer_id"):
        raise HTTPException(400, "This invoice has no linked customer.")
    if inv.get("payment_status") == "paid":
        raise HTTPException(400, "This invoice is already paid.")
    balance = round(float(inv.get("total") or 0) - float(inv.get("amount_paid") or 0), 2)
    title = "Payment reminder"
    body = f"'{inv.get('title', 'Your invoice')}' has an outstanding balance of ${balance:,.2f}. Please pay at your earliest convenience."
    # In-app + SMS (SMS only fires if Twilio is configured; otherwise in-app still delivered)
    await notify_customer(inv["customer_id"], title, body, sms=True)
    email_sent = await send_invoice_reminder_email(inv)
    count = int(inv.get("reminder_count") or 0) + 1
    await db.quotes.update_one({"id": qid}, {"$set": {"last_reminder_at": now_iso(), "reminder_count": count}})
    return {"ok": True, "email_sent": email_sent, "reminder_count": count, "last_reminder_at": now_iso()}


@router.get("/invoices/overview")
async def invoices_overview(user: dict = Depends(require_admin)):
    """Admin AR dashboard: all outstanding invoices tagged pending / past_due / partial."""
    docs = await db.quotes.find({"doc_type": "invoice"}, {"_id": 0}).sort("due_date", 1).to_list(2000)
    today = datetime.now(timezone.utc).date().isoformat()
    # Look up which customers have a saved card/ACH on file.
    cust_ids = list({d.get("customer_id") for d in docs if d.get("customer_id")})
    pm_map = {}
    if cust_ids:
        custs = await db.customers.find(
            {"id": {"$in": cust_ids}}, {"_id": 0, "id": 1, "default_payment_method_id": 1, "pm_brand": 1, "pm_last4": 1}
        ).to_list(2000)
        for c in custs:
            if c.get("default_payment_method_id"):
                last4 = c.get("pm_last4", "")
                pm_map[c["id"]] = f"{c.get('pm_brand', 'Card')} ••{last4}" if last4 else c.get("pm_brand", "On file")
    out = []
    summary = {
        "pending": {"count": 0, "amount": 0.0},
        "past_due": {"count": 0, "amount": 0.0},
        "partial": {"count": 0, "amount": 0.0},
        "outstanding": {"count": 0, "amount": 0.0},
        "failed": {"count": 0, "amount": 0.0},
    }
    for d in docs:
        total = float(d.get("total") or 0)
        paid = float(d.get("amount_paid") or 0)
        balance = round(total - paid, 2)
        is_paid = d.get("payment_status") == "paid" or balance <= 0.01
        if is_paid:
            continue  # AR view only shows money still owed
        due = d.get("due_date")
        past_due = bool(due and due < today)
        partial = paid > 0.009
        pending = (not past_due) and (not partial)
        charge_failed = bool(d.get("charge_failed"))
        row = {
            "id": d["id"], "title": d.get("title", ""), "customer_name": d.get("customer_name", ""),
            "customer_id": d.get("customer_id"), "total": total, "amount_paid": round(paid, 2),
            "balance": balance, "due_date": due, "status": d.get("status"),
            "payment_status": d.get("payment_status"), "created_at": d.get("created_at"),
            "past_due": past_due, "partial": partial, "pending": pending,
            "last_reminder_at": d.get("last_reminder_at"), "reminder_count": int(d.get("reminder_count") or 0),
            "has_payment_method": d.get("customer_id") in pm_map,
            "pm_label": pm_map.get(d.get("customer_id"), ""),
            "processing": d.get("payment_status") == "processing",
            "charge_failed": charge_failed,
            "charge_error": d.get("charge_error", "") if charge_failed else "",
            "charge_failed_at": d.get("charge_failed_at") if charge_failed else None,
        }
        out.append(row)
        summary["outstanding"]["count"] += 1
        summary["outstanding"]["amount"] += balance
        if past_due:
            summary["past_due"]["count"] += 1
            summary["past_due"]["amount"] += balance
        if partial:
            summary["partial"]["count"] += 1
            summary["partial"]["amount"] += balance
        if pending:
            summary["pending"]["count"] += 1
            summary["pending"]["amount"] += balance
        if charge_failed:
            summary["failed"]["count"] += 1
            summary["failed"]["amount"] += balance
    for k in summary:
        summary[k]["amount"] = round(summary[k]["amount"], 2)
    return {"summary": summary, "invoices": out}


@router.post("/quotes/{qid}/record-payment")
async def record_payment(qid: str, body: RecordPaymentIn, user: dict = Depends(require_admin)):
    """Admin records a full or PARTIAL offline payment against an invoice."""
    doc = await db.quotes.find_one({"id": qid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    total = float(doc.get("total") or 0)
    paid = round(float(doc.get("amount_paid") or 0) + body.amount, 2)
    fully_paid = paid >= total - 0.01
    update = {
        "amount_paid": min(paid, total),
        "payment_status": "paid" if fully_paid else "partial",
        "charge_failed": False, "charge_error": "",
    }
    if fully_paid:
        update.update({"status": "accepted", "paid_at": now_iso(), "payment_method": "manual"})
    await db.quotes.update_one({"id": qid}, {"$set": update})
    if doc.get("customer_id"):
        msg = ("Your payment was received in full. Thank you!" if fully_paid
               else f"A partial payment of ${body.amount:,.2f} was recorded. Remaining balance: ${max(total - paid, 0):,.2f}.")
        await notify_customer(doc["customer_id"], "Payment recorded", msg)
    return await db.quotes.find_one({"id": qid}, {"_id": 0})


@router.post("/quotes/{qid}/pay")
async def pay_quote(qid: str, user: dict = Depends(require_admin)):
    """Admin-only: record a manual/offline FULL payment (cash, check, external card)."""
    doc = await db.quotes.find_one({"id": qid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quote not found")
    await db.quotes.update_one(
        {"id": qid},
        {"$set": {"payment_status": "paid", "status": "accepted", "amount_paid": float(doc.get("total") or 0),
                  "paid_at": now_iso(), "payment_method": "manual", "charge_failed": False, "charge_error": ""}},
    )
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Payment received",
                              f"Your payment for '{doc.get('title', 'invoice')}' was recorded. Thank you!")
    return await db.quotes.find_one({"id": qid}, {"_id": 0})


