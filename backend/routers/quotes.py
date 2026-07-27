# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from emailer import send_invoice_reminder_email
from models import *  # noqa: F403,F405

router = APIRouter()


# ----------------------- Quotes / Invoices -----------------------
def compute_totals(line_items: List[dict], tax_rate: float):
    subtotal = sum(li["quantity"] * li["unit_price"] for li in line_items)
    tax = round(subtotal * (tax_rate / 100.0), 2)
    return round(subtotal, 2), tax, round(subtotal + tax, 2)


@router.get("/quotes")
async def list_quotes(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant),
                      doc_type: Optional[str] = None,
                      include_deleted: bool = False):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    q: dict = {"tenant_id": tenant["id"]}
    if user.get("role") == "customer":
        q["customer_id"] = user.get("customer_id")
    if doc_type:
        q["doc_type"] = doc_type
    # Phase 34 · Task BB · Feb 2026 — bulk-select soft-delete.
    # Hide soft-deleted rows by default (`deleted_at` is None or
    # missing). Only super_admins can opt-in with ``include_deleted=1``.
    if not (include_deleted and (user.get("role") or "").lower() == "super_admin"):
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]
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
    # Feb-2026 MP1.5 — property_id validation. Same rules as
    # POST /jobs: if the customer has exactly 1 active property, auto-
    # assign; if the caller sent an explicit id, verify it belongs to
    # this customer + tenant AND is still active. Leaving the field
    # null when the customer has multiple properties is allowed — that's
    # the "consolidated across properties" case (master_billing_mode
    # ``consolidated``).
    property_id = body.property_id
    if property_id:
        prop = await db.properties.find_one(
            {"id": property_id, "tenant_id": tenant["id"],
              "customer_id": body.customer_id},
            {"_id": 0, "id": 1, "active": 1},
        )
        if not prop:
            raise HTTPException(400, "property_id not found for this customer")
        if prop.get("active") is False:
            raise HTTPException(400, "property_id refers to an inactive property")
    else:
        active_props = await db.properties.find(
            {"tenant_id": tenant["id"], "customer_id": body.customer_id,
              "active": {"$ne": False}},
            {"_id": 0, "id": 1},
        ).to_list(10)
        if len(active_props) == 1:
            property_id = active_props[0]["id"]
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
        "property_id": property_id,
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
    # Comms Phase 3 — invoice.created automation (only for docs that
    # actually landed as invoices; quotes stay quiet).
    try:
        if body.doc_type == "invoice":
            from services.automation_engine import emit as _emit
            await _emit(
                "invoice.created",
                {"invoice": doc, "customer": {"id": doc.get("customer_id"),
                                                 "name": doc.get("customer_name")}},
                tenant_id=tenant["id"],
                entity_kind="invoice", entity_id=doc["id"],
                customer_id=doc.get("customer_id"),
            )
    except Exception:
        pass
    # Feb-2026 · Marketing Slice M5c — drip event bus (invoice_sent).
    try:
        if body.doc_type == "invoice" and doc.get("customer_id"):
            from services.marketing.drip_events import on_event as _drip_on_event
            await _drip_on_event(
                "invoice_sent", tenant["id"], doc.get("customer_id"),
            )
    except Exception:
        pass
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
    # Feb-2026 MP1.5 — property_id patch validation. Must reference an
    # active property belonging to this quote's customer + tenant.
    if "property_id" in upd and upd["property_id"]:
        prop = await db.properties.find_one(
            {"id": upd["property_id"], "tenant_id": tenant["id"],
              "customer_id": existing.get("customer_id")},
            {"_id": 0, "id": 1, "active": 1},
        )
        if not prop:
            raise HTTPException(400, "property_id not found for this customer")
        if prop.get("active") is False:
            raise HTTPException(400, "property_id refers to an inactive property")
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
    # Comms Phase 3 — fire invoice.paid on the flip to fully-paid.
    if fully_paid:
        try:
            fresh = await db.quotes.find_one(
                {"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
            from services.automation_engine import emit as _emit
            await _emit(
                "invoice.paid",
                {"invoice": fresh or {}, "customer": {"id": (fresh or {}).get("customer_id"),
                                                          "name": (fresh or {}).get("customer_name")}},
                tenant_id=tenant["id"],
                entity_kind="invoice", entity_id=qid,
                customer_id=(fresh or {}).get("customer_id"),
            )
        except Exception:
            pass
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
    # Comms Phase 3 — invoice.paid on manual/offline full payment.
    try:
        fresh = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
        from services.automation_engine import emit as _emit
        await _emit(
            "invoice.paid",
            {"invoice": fresh or {}, "customer": {"id": (fresh or {}).get("customer_id"),
                                                      "name": (fresh or {}).get("customer_name")}},
            tenant_id=tenant["id"],
            entity_kind="invoice", entity_id=qid,
            customer_id=(fresh or {}).get("customer_id"),
        )
    except Exception:
        pass
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


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task BB · Feb 2026 — Invoice/Quote bulk-select soft-delete.
# Mirrors the Phase 28 `_perform_soft_delete_job` pattern in routers/jobs.py.
# The invoice list page + Estimator list page + Payments ledger all gained
# checkbox-select + mass-delete UX; each surface hits its own bulk endpoint.
# ═════════════════════════════════════════════════════════════════════════
from pydantic import BaseModel as _BaseModelBB  # local alias — avoid model.py * import shadow


class _InvoiceBulkDeleteIn(_BaseModelBB):
    # Phase 34 · Task EE (extension) — invoices/payments accept
    # either explicit ``ids`` or the filter-selector shape.
    ids: Optional[List[str]] = None
    query_selector: Optional[Dict[str, Any]] = None
    exclude_ids: Optional[List[str]] = None


# Phase 34 · Task DD · Feb 2026 — cap raised 100 → 400 across all four
# bulk-delete surfaces (invoices, estimates, payments, leads). Kept as
# a local constant per router so a bad import can't accidentally drop
# the guard entirely.
_BULK_DELETE_CAP = 400

_INVOICE_SELECTOR_KEYS = {"status", "search", "customer_id", "has_late_fee"}


async def _resolve_invoice_ids(selector: Dict[str, Any],
                                 exclude: List[str],
                                 tenant_id: str,
                                 doc_type: str = "invoice") -> List[str]:
    """Task EE — safely translate the invoices/payments frontend filter
    shape into a concrete list of quote ids. Whitelist-only. Always
    tenant-scoped, always excludes soft-deleted rows."""
    q: Dict[str, Any] = {"tenant_id": tenant_id, "doc_type": doc_type,
                            "$or": [{"deleted_at": None},
                                        {"deleted_at": {"$exists": False}}]}
    clean = {k: v for k, v in (selector or {}).items()
              if k in _INVOICE_SELECTOR_KEYS}
    if clean.get("status") and clean["status"] != "all":
        q["payment_status"] = clean["status"]
    if clean.get("customer_id"):
        q["customer_id"] = clean["customer_id"]
    if clean.get("has_late_fee"):
        q["line_items.is_late_fee"] = True
    if clean.get("search"):
        s = str(clean["search"]).strip()
        if s:
            q["$and"] = [{"$or": [
                {"title": {"$regex": s, "$options": "i"}},
                {"customer_name": {"$regex": s, "$options": "i"}},
                {"invoice_number": {"$regex": s, "$options": "i"}},
            ]}]
    excl = set(exclude or [])
    ids: List[str] = []
    async for row in db.quotes.find(q, {"_id": 0, "id": 1}).limit(_BULK_DELETE_CAP + 1):
        rid = row.get("id")
        if rid and rid not in excl:
            ids.append(rid)
    return ids


async def _perform_soft_delete_quote(qid: str, user: dict, tenant: dict) -> dict:
    """Shared soft-delete helper for quotes/invoices. Enforces:
    * tenant scoping (row must belong to caller's tenant).
    * no re-delete (already soft-deleted rows return ``already_deleted=True``
      instead of raising).
    * audit row written best-effort.
    Called by both the single-invoice soft-delete + the bulk endpoint so
    behavior is identical.
    """
    doc = await db.quotes.find_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1, "doc_type": 1,
         "payment_status": 1, "amount_paid": 1},
    )
    if not doc:
        raise HTTPException(404, "Invoice not found")
    if doc.get("deleted_at"):
        return {"ok": True, "id": qid, "already_deleted": True}
    deleted_at = now_iso()
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": deleted_at,
                    "deleted_by_user_id": user.get("id")}},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "invoice.soft_delete",
            "target_id": qid,
            "target_doc_type": doc.get("doc_type") or "invoice",
            "at": deleted_at,
        })
    except Exception as e:
        logger.warning(f"invoice.soft_delete audit failed: {e}")
    return {"ok": True, "id": qid, "deleted_at": deleted_at}


@router.post("/invoices/{qid}/soft-delete",
              operation_id="invoices.softDelete")
async def soft_delete_invoice(qid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    return await _perform_soft_delete_quote(qid, user, tenant)


@router.post("/invoices/bulk-delete",
              operation_id="invoices.bulkDelete")
async def bulk_delete_invoices(body: _InvoiceBulkDeleteIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Bulk soft-delete invoices. See Task EE (extension) for the
    ``query_selector`` shape."""
    if body.query_selector is not None:
        ids = await _resolve_invoice_ids(
            body.query_selector, body.exclude_ids or [],
            tenant["id"], doc_type="invoice",
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _BULK_DELETE_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_BULK_DELETE_CAP} rows per call")
    ids = list(dict.fromkeys(ids))  # idempotency — de-dupe payload
    deleted: List[str] = []
    failed: List[dict] = []
    for qid in ids:
        try:
            r = await _perform_soft_delete_quote(qid, user, tenant)
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": qid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                # noqa: BLE001
            failed.append({"id": qid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task BB · Feb 2026 — Payments bulk-select soft-delete.
# Payments are stored as quotes with ``payment_status in {paid, partial,
# processing}`` — there is no separate collection. "Deleting" a payment
# reverts the row back to ``unpaid`` and zeroes ``amount_paid``, while
# tagging ``payment_deleted_at`` for the archive view. Stripe-linked
# rows (``payment_intent_id`` set) refuse deletion — those payouts
# have already cleared to the bank and reversing them is a Stripe
# operation the admin must run through the dashboard.
# ═════════════════════════════════════════════════════════════════════════
_STRIPE_LOCKED_METHODS = {"stripe", "card"}


async def _perform_delete_payment(pid: str, user: dict, tenant: dict) -> dict:
    """Revert a paid invoice back to ``unpaid`` — the "delete a payment"
    semantics on this platform. Refuses if:
    * the row is not found in this tenant.
    * the row has a Stripe payment_intent_id (cleared to bank; reversal
      belongs in the Stripe dashboard, not here).
    * the row's payment method is a card/Stripe charge that has already
      succeeded (defense in depth for rows missing the PI id).
    """
    doc = await db.quotes.find_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "payment_status": 1, "amount_paid": 1,
         "payment_intent_id": 1, "payment_method": 1,
         "payment_deleted_at": 1},
    )
    if not doc:
        raise HTTPException(404, "Payment not found")
    if doc.get("payment_deleted_at"):
        return {"ok": True, "id": pid, "already_deleted": True}
    if doc.get("payment_intent_id"):
        raise HTTPException(
            409, "Payment is linked to a cleared Stripe charge — reverse via Stripe dashboard",
        )
    method = (doc.get("payment_method") or "").lower()
    if method in _STRIPE_LOCKED_METHODS and (doc.get("payment_status") or "").lower() == "paid":
        raise HTTPException(
            409, "Card/Stripe payments cannot be bulk-deleted — refund via the invoice detail page",
        )
    if (doc.get("payment_status") or "").lower() == "unpaid":
        raise HTTPException(400, "Nothing to delete — this invoice has no recorded payment")
    deleted_at = now_iso()
    await db.quotes.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {
            "payment_status": "unpaid",
            "amount_paid": 0.0,
            "paid_at": None,
            "payment_deleted_at": deleted_at,
            "payment_deleted_by_user_id": user.get("id"),
            "payment_deleted_prior_status": doc.get("payment_status"),
            "payment_deleted_prior_amount_paid": doc.get("amount_paid") or 0.0,
        }},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "payment.soft_delete",
            "target_id": pid,
            "prior_status": doc.get("payment_status"),
            "prior_amount_paid": doc.get("amount_paid") or 0.0,
            "at": deleted_at,
        })
    except Exception as e:
        logger.warning(f"payment.soft_delete audit failed: {e}")
    return {"ok": True, "id": pid, "deleted_at": deleted_at}


@router.post("/payments/bulk-delete",
              operation_id="payments.bulkDelete")
async def bulk_delete_payments(body: _InvoiceBulkDeleteIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Bulk-revert payment status on paid invoices. Financial-state
    guardrails match the single-record semantics — Stripe-linked
    payments refuse; the failures are surfaced in ``failed[]`` so
    admins see the count of "locked" rows without the whole batch
    aborting."""
    if body.query_selector is not None:
        ids = await _resolve_invoice_ids(
            body.query_selector, body.exclude_ids or [],
            tenant["id"], doc_type="invoice",
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _BULK_DELETE_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_BULK_DELETE_CAP} rows per call")
    ids = list(dict.fromkeys(ids))  # idempotency
    deleted: List[str] = []
    failed: List[dict] = []
    for pid in ids:
        try:
            r = await _perform_delete_payment(pid, user, tenant)
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": pid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                # noqa: BLE001
            failed.append({"id": pid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}
