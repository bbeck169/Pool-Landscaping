from fastapi import APIRouter, HTTPException, Depends, Query, Response
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from emailer import send_invoice_reminder_email
from models import *

router = APIRouter()


# ----------------------- Quotes / Invoices -----------------------
def compute_totals(line_items: List[dict], tax_rate: float):
    subtotal = sum(li["quantity"] * li["unit_price"] for li in line_items)
    tax = round(subtotal * (tax_rate / 100.0), 2)
    return round(subtotal, 2), tax, round(subtotal + tax, 2)


@router.get("/quotes")
async def list_quotes(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant),
                      doc_type: Optional[str] = None):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    q: dict = {"tenant_id": tenant["id"]}
    if user.get("role") == "customer":
        q["customer_id"] = user.get("customer_id")
    if doc_type:
        q["doc_type"] = doc_type
    docs = await db.quotes.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.post("/quotes")
async def create_quote(body: QuoteIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(400, "Customer not found")
    items = [li.dict() for li in body.line_items]
    subtotal, tax, total = compute_totals(items, body.tax_rate)
    due_date = body.due_date
    if body.doc_type == "invoice" and not due_date:
        due_date = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    # Auto-fill terms from tenant defaults when the caller did not explicitly send one.
    terms = body.terms
    if terms is None:
        from routers.finances import get_terms_defaults
        defaults = await get_terms_defaults()
        terms = defaults["default_invoice_terms"] if body.doc_type == "invoice" else defaults["default_quote_terms"]
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
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
        "terms": terms,
        "created_at": now_iso(),
    }
    # Phase 56.18 — assign human-readable invoice number on birth for
    # docs typed as invoice (quotes don't get one; see routers/
    # billing.py for master invoices).
    if body.doc_type == "invoice":
        from services.invoice_numbering import assign_invoice_number_if_missing
        await assign_invoice_number_if_missing(doc, tenant)
    await db.quotes.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/quotes/{qid}")
async def update_quote(qid: str, body: QuoteUpdate,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    """Partial update of quote/invoice fields (title, notes, terms, tax_rate, due_date, line_items)."""
    existing = await db.quotes.find_one(
        {"id": qid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Not found")
    upd = {k: v for k, v in body.dict().items() if v is not None}
    # Phase 56.18 — invoice_number is IMMUTABLE once assigned. Reject
    # any attempt to overwrite (defensive; `QuoteUpdate` shouldn't
    # accept it, but guard anyway in case an admin sends raw JSON).
    if "invoice_number" in upd and upd["invoice_number"] != existing.get("invoice_number"):
        raise HTTPException(400, "invoice_number is immutable once assigned")
    upd.pop("invoice_number", None)
    if "line_items" in upd:
        upd["line_items"] = [li if isinstance(li, dict) else li.dict() for li in upd["line_items"]]
    if "line_items" in upd or "tax_rate" in upd:
        items = upd.get("line_items", existing.get("line_items", []))
        tax_rate = float(upd.get("tax_rate", existing.get("tax_rate", 0)) or 0)
        subtotal, tax, total = compute_totals(items, tax_rate)
        amount_paid = float(existing.get("amount_paid") or 0)
        upd.update({
            "tax_rate": tax_rate,
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "remaining_balance": round(max(total - amount_paid, 0.0), 2),
        })
    upd["updated_at"] = now_iso()
    await db.quotes.update_one({"id": qid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.get("/quotes/{qid}")
async def get_quote(qid: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quote not found")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")
    return doc


@router.post("/quotes/{qid}/decision")
async def customer_quote_decision(qid: str,
                                  decision: str = Query(...),
                                  user: dict = Depends(get_current_user),
                                  tenant: dict = Depends(get_current_tenant)):
    """Customer approves or declines their own estimate."""
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
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
    await db.quotes.update_one({"id": qid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.get("/quotes/ready-to-schedule")
async def ready_to_schedule(admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Approved online estimates not yet turned into a scheduled job."""
    docs = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "quote", "status": "accepted",
         "scheduled_job_id": {"$in": [None, ""]}},
        {"_id": 0},
    ).sort("accepted_at", -1).to_list(500)
    # Include legacy accepted quotes that predate the scheduled_job_id field.
    extra = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "quote", "status": "accepted",
         "scheduled_job_id": {"$exists": False}},
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
async def schedule_from_estimate(qid: str, body: MaintBulkIn,
                                 admin: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Turn an approved estimate into a scheduled job in one tap."""
    try:
        datetime.fromisoformat(body.scheduled_date[:10])
    except (ValueError, TypeError):
        raise HTTPException(400, "scheduled_date must be YYYY-MM-DD")
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Estimate not found")
    if doc.get("doc_type") != "quote" or doc.get("status") != "accepted":
        raise HTTPException(400, "Only approved estimates can be scheduled")
    if doc.get("scheduled_job_id"):
        raise HTTPException(400, "This estimate is already scheduled")
    customer = await db.customers.find_one(
        {"id": doc.get("customer_id"), "tenant_id": tenant["id"]}, {"_id": 0}
    )
    tech_name, tech_avatar = None, ""
    if body.technician_id:
        tech = await db.technicians.find_one(
            {"id": body.technician_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        tech_name = tech["name"] if tech else None
        tech_avatar = tech.get("avatar", "") if tech else ""
    job = {
        "id": new_id(), "tenant_id": tenant["id"],
        "title": doc.get("title", "Service"), "customer_id": doc.get("customer_id"),
        "customer_name": doc.get("customer_name", ""), "technician_id": body.technician_id,
        "technician_name": tech_name, "technician_avatar": tech_avatar,
        "address": (customer or {}).get("address", ""), "service_type": doc.get("title", "Service"),
        "scheduled_date": body.scheduled_date, "notes": doc.get("notes", ""),
        "price": float(doc.get("total") or 0), "status": "pending", "photos": [],
        "from_estimate_id": qid, "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    job.pop("_id", None)
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"scheduled_job_id": job["id"], "status": "scheduled"}},
    )
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Service scheduled",
                              f"Your approved estimate '{doc.get('title')}' is scheduled for {body.scheduled_date}.", job_id=job["id"])
    return job


@router.put("/quotes/{qid}/status")
async def update_quote_status(qid: str, status: str = Query(...),
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]}, {"$set": {"status": status}}
    )
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/quotes/{qid}/send-reminder")
async def send_reminder(qid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """One-tap payment reminder for an outstanding invoice: in-app + SMS + email."""
    inv = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if not inv.get("customer_id"):
        raise HTTPException(400, "This invoice has no linked customer.")
    if inv.get("payment_status") == "paid":
        raise HTTPException(400, "This invoice is already paid.")
    balance = round(float(inv.get("total") or 0) - float(inv.get("amount_paid") or 0), 2)
    title = "Payment reminder"
    body = f"'{inv.get('title', 'Your invoice')}' has an outstanding balance of ${balance:,.2f}. Please pay at your earliest convenience."
    await notify_customer(inv["customer_id"], title, body, sms=True)
    email_sent = await send_invoice_reminder_email(inv)
    count = int(inv.get("reminder_count") or 0) + 1
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"last_reminder_at": now_iso(), "reminder_count": count}},
    )
    return {"ok": True, "email_sent": email_sent, "reminder_count": count, "last_reminder_at": now_iso()}


@router.get("/invoices/overview")
async def invoices_overview(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Admin AR dashboard: all outstanding invoices tagged pending / past_due / partial."""
    docs = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "invoice"}, {"_id": 0}
    ).sort("due_date", 1).to_list(2000)
    today = datetime.now(timezone.utc).date().isoformat()
    cust_ids = list({d.get("customer_id") for d in docs if d.get("customer_id")})
    pm_map = {}
    if cust_ids:
        custs = await db.customers.find(
            {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "default_payment_method_id": 1, "pm_brand": 1, "pm_last4": 1},
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
            continue
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
async def record_payment(qid: str, body: RecordPaymentIn,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Admin records a full or PARTIAL offline payment against an invoice."""
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
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
    await db.quotes.update_one({"id": qid, "tenant_id": tenant["id"]}, {"$set": update})
    if doc.get("customer_id"):
        msg = ("Your payment was received in full. Thank you!" if fully_paid
               else f"A partial payment of ${body.amount:,.2f} was recorded. Remaining balance: ${max(total - paid, 0):,.2f}.")
        await notify_customer(doc["customer_id"], "Payment recorded", msg)
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/quotes/{qid}/pay")
async def pay_quote(qid: str,
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    """Admin-only: record a manual/offline FULL payment (cash, check, external card)."""
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quote not found")
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"payment_status": "paid", "status": "accepted",
                  "amount_paid": float(doc.get("total") or 0),
                  "paid_at": now_iso(), "payment_method": "manual",
                  "charge_failed": False, "charge_error": ""}},
    )
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Payment received",
                              f"Your payment for '{doc.get('title', 'invoice')}' was recorded. Thank you!")
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})



# ────────────────────────────── PDF export ───────────────────────────────────
@router.get("/quotes/{qid}/pdf")
async def quote_or_invoice_pdf(qid: str,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    """Streams a printable PDF for a quote or invoice, including the terms section."""
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")

    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlcolors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    is_invoice = doc.get("doc_type") == "invoice"
    label = "Invoice" if is_invoice else "Estimate"
    buf = BytesIO()
    pdf_doc = SimpleDocTemplate(buf, pagesize=letter, title=f"{label} {qid[:8]}")
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"<b>{label}</b>", styles["Title"]))
    story.append(Paragraph("Pool &amp; Landscaping of Vistancia", styles["Normal"]))
    story.append(Spacer(1, 12))

    header_rows = [
        [f"{label} #", qid[:8].upper()],
        ["Title", doc.get("title", "")],
        ["Customer", doc.get("customer_name", "")],
        ["Status", (doc.get("status") or "").title()],
    ]
    if is_invoice:
        header_rows.append(["Due", doc.get("due_date") or "—"])
        header_rows.append(["Payment", (doc.get("payment_status") or "unpaid").title()])
    header_rows.append(["Created", (doc.get("created_at") or "")[:10]])
    t = Table(header_rows, colWidths=[1.4 * inch, 5.0 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (0, -1), rlcolors.HexColor("#F4F4F5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    line_rows = [["Description", "Qty", "Unit", "Total"]]
    for li in (doc.get("line_items") or []):
        qty = float(li.get("quantity") or 0)
        unit = float(li.get("unit_price") or 0)
        line_rows.append([li.get("description", ""), f"{qty:g}", f"${unit:,.2f}", f"${qty * unit:,.2f}"])
    lt = Table(line_rows, colWidths=[3.6 * inch, 0.8 * inch, 1.1 * inch, 1.1 * inch])
    lt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, 0), rlcolors.HexColor("#F4F4F5")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(lt)
    story.append(Spacer(1, 8))

    subtotal = float(doc.get("subtotal") or 0)
    tax_amt = float(doc.get("tax") or 0)
    total = float(doc.get("total") or 0)
    tot_rows = [
        ["Subtotal", f"${subtotal:,.2f}"],
        [f"Tax ({doc.get('tax_rate', 0)}%)", f"${tax_amt:,.2f}"],
        ["Total", f"${total:,.2f}"],
    ]
    tt = Table(tot_rows, colWidths=[5.0 * inch, 1.4 * inch])
    tt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 11),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, rlcolors.HexColor("#0284C7")),
        ("TEXTCOLOR", (0, -1), (-1, -1), rlcolors.HexColor("#0284C7")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tt)
    story.append(Spacer(1, 14))

    notes = (doc.get("notes") or "").strip()
    if notes:
        story.append(Paragraph("<b>Notes</b>", styles["Heading3"]))
        story.append(Paragraph(notes.replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 10))

    terms_text = doc.get("terms")
    if not terms_text:
        try:
            from routers.finances import get_terms_defaults
            defaults = await get_terms_defaults()
            terms_text = defaults["default_invoice_terms"] if is_invoice else defaults["default_quote_terms"]
        except Exception:
            terms_text = ""
    if terms_text:
        story.append(Paragraph("<b>Terms &amp; Conditions</b>", styles["Heading3"]))
        story.append(Paragraph(terms_text.replace("\n", "<br/>"), styles["Normal"]))

    pdf_doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    filename = f"{label.lower()}-{qid[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
