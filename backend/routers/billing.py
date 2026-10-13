"""Phase 3 additions:
- Payment-handle settings (Venmo/Zelle/Cash App/PayPal + automatic-invoice-texting toggle)
- Master invoices (combine multiple regular invoices into one payable)
- Invoice SMS (RingCentral; graceful no-op when unconfigured)
- Quote → Job conversion
"""
import asyncio
import os
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, require_admin, get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()

SETTINGS_DOC_ID = "singleton"


# ─── Settings ───────────────────────────────────────────────────────────────
class PaymentHandlesIn(BaseModel):
    venmo: Optional[str] = ""
    zelle: Optional[str] = ""
    cashapp: Optional[str] = ""
    paypal: Optional[str] = ""
    automatic_invoice_texting: Optional[bool] = False


@router.get("/settings/payment-handles")
async def get_payment_handles(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    doc = await db.payment_handles.find_one(
        {"id": SETTINGS_DOC_ID, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    return doc or {
        "id": SETTINGS_DOC_ID,
        "tenant_id": tenant["id"],
        "venmo": "",
        "zelle": "",
        "cashapp": "",
        "paypal": "",
        "automatic_invoice_texting": False,
    }


@router.put("/settings/payment-handles")
async def put_payment_handles(body: PaymentHandlesIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    d = body.dict()
    d["id"] = SETTINGS_DOC_ID
    d["tenant_id"] = tenant["id"]
    d["updated_at"] = now_iso()
    await db.payment_handles.update_one(
        {"id": SETTINGS_DOC_ID, "tenant_id": tenant["id"]},
        {"$set": d},
        upsert=True,
    )
    return d


# ─── Invoice SMS ────────────────────────────────────────────────────────────
class InvoiceSmsIn(BaseModel):
    to: Optional[str] = None
    message: Optional[str] = None


@router.post("/invoices/{iid}/send-sms")
async def send_invoice_sms(iid: str, body: InvoiceSmsIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Text an invoice link via the shipped RingCentral SMS adapter.

    Feb-2026 · Twilio→RC consolidation — all SMS traffic funnels through
    ``services/sms/rc_adapter.send`` which handles E.164 normalization,
    retry, DRY-RUN allow-list guard, and never raises.
    """
    inv = await db.quotes.find_one({"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    to = (body.to or "").strip()
    if not to:
        cust = await db.customers.find_one(
            {"id": inv.get("customer_id"), "tenant_id": tenant["id"]}, {"_id": 0}
        ) or {}
        to = (cust.get("phone") or "").strip()
    if not to:
        raise HTTPException(400, "No SMS destination number available")

    body_txt = body.message or (
        f"Invoice {iid[:8].upper()} for {inv.get('customer_name', '')}: ${inv.get('total', 0):.2f}. "
        f"Pay online: {inv.get('payment_link') or 'link pending'}"
    )
    from services.sms.rc_adapter import send as _sms_send
    res = await _sms_send(
        to=to, body=body_txt,
        category="transactional", tenant_id=tenant["id"],
        customer_id=inv.get("customer_id"),
        idempotency_key=f"invoice-sms:{iid}",
    )
    provider = res.get("provider")
    status = res.get("provider_status")
    if provider == "ringcentral" and status in ("queued", "sent", "delivered", "accepted"):
        return {"sent": True, "to": to, "sid": res.get("provider_response_id")}
    if provider == "mock" or status == "dry_run":
        # Adapter is disabled at runtime (RC creds absent) OR the
        # comms_env_guard blocked the send (non-prod env, recipient
        # not on allow-list). Preserve the shape any existing UI keys
        # off — reason is now a neutral "sms-not-configured".
        return {"sent": False, "reason": "sms-not-configured", "to": to}
    return {"sent": False, "reason": res.get("error") or "sms-send-failed", "to": to}


# ─── Convert approved quote → job ───────────────────────────────────────────
@router.post("/quotes/{qid}/convert-to-job")
async def convert_quote_to_job(qid: str, body: dict,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    """body: { scheduled_date, technician_id?, notes? }"""
    q = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not q:
        raise HTTPException(404, "Quote not found")
    if q.get("decision") not in ("approved",) and q.get("status") not in ("approved",):
        # Allow anyway with a warning — some flows mark approval on status.
        pass
    # Phase K71 · Feb-2026 — Convert-to-job/invoice parity gate.
    #
    # Feb-2026 · invoice-category hard-block removal — convert no
    # longer rejects when K71 line-item category is missing. Fire
    # an audit log row so ops can grep for jobs that need
    # category cleanup; the amber chip in the admin editor still
    # surfaces the warning.
    from routers.income_categories import check_line_items_k71_gaps
    _gaps = check_line_items_k71_gaps(q.get("line_items") or [])
    if _gaps:
        import logging as _logging
        _logging.getLogger("quotes").info(
            "invoices.convert_with_category_warnings quote_id=%s "
            "tenant_id=%s line_indices=%s",
            qid, tenant["id"], _gaps,
        )
        try:
            from services.invoices.line_item_category_audit import (
                write_category_warnings_audit,
            )
            await write_category_warnings_audit(
                db, tenant_id=tenant["id"],
                actor_id=(user or {}).get("id"),
                invoice_id=qid,
                scan={
                    "uncategorized_count": len(_gaps),
                    "inactive_category_line_item_count": 0,
                    "uncategorized_line_indices": _gaps,
                    "inactive_category_line_indices": [],
                },
                source="quote_convert_to_job",
            )
        except Exception as _audit_exc:  # noqa: BLE001
            pass
    cust = await db.customers.find_one(
        {"id": q["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    ) or {}
    tech = None
    if body.get("technician_id"):
        tech = await db.technicians.find_one(
            {"id": body["technician_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        )

    line_summary = ", ".join(
        li.get("description", "") for li in (q.get("line_items") or [])
    )[:200]

    # Phase K71 · Feb-2026 — Copy quote line items into job.line_items[]
    # so the auto-invoice pipeline preserves K71 metadata (long
    # description, service_category_id, income_category_id) end-to-end
    # via ``services/auto_invoice.py::_build_line_items``.
    job_line_items = []
    for li in (q.get("line_items") or []):
        job_line_items.append({
            "description": li.get("description"),
            "long_description": li.get("long_description"),
            "quantity": li.get("quantity"),
            "unit_price": li.get("unit_price"),
            "category": li.get("category"),
            "income_category_id": li.get("income_category_id"),
            "service_category_id": li.get("service_category_id"),
            "item_id": li.get("item_id"),
            "pricebook_item_id": li.get("pricebook_item_id"),
        })

    job = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "title": q.get("title") or f"Quote {qid[:8]} · Work",
        "customer_id": q["customer_id"],
        "customer_name": cust.get("name"),
        "address": cust.get("address", ""),
        "service_type": "Pool Cleaning",
        "technician_id": body.get("technician_id"),
        "technician_name": tech["name"] if tech else None,
        "technician_avatar": tech.get("avatar", "") if tech else "",
        "scheduled_date": body.get("scheduled_date"),
        "notes": (body.get("notes") or "") + ("\n" + line_summary if line_summary else ""),
        "price": q.get("total", 0),
        "line_items": job_line_items,
        "status": "scheduled",
        "photos": [],
        "quote_id": qid,
        "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"converted_job_id": job["id"], "converted_at": now_iso()}},
    )
    job.pop("_id", None)
    return job


# ─── Master invoices ────────────────────────────────────────────────────────
class MasterInvoiceIn(BaseModel):
    label: Optional[str] = None
    customer_ids: List[str]              # one or many payer customers
    invoice_ids: List[str]               # child invoice IDs to roll up
    due_date: Optional[str] = None


@router.get("/invoices/master")
async def list_master_invoices(user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    docs = await db.master_invoices.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return docs


@router.post("/invoices/master")
async def create_master_invoice(body: MasterInvoiceIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    if not body.invoice_ids:
        raise HTTPException(400, "invoice_ids required")
    invs = await db.quotes.find(
        {"id": {"$in": body.invoice_ids}, "tenant_id": tenant["id"], "doc_type": "invoice"},
        {"_id": 0},
    ).to_list(2000)
    if not invs:
        raise HTTPException(404, "No matching invoices")
    total = sum((float(i.get("total") or 0)) for i in invs)
    balance = sum(
        max(0.0, float(i.get("total") or 0) - float(i.get("amount_paid") or 0))
        for i in invs
    )
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "label": body.label
        or f"Master · {len(invs)} invoices · {invs[0].get('customer_name', 'Multi-payer')}",
        "customer_ids": body.customer_ids,
        "invoice_ids": [i["id"] for i in invs],
        "invoice_snapshot": [
            {
                "id": i["id"],
                "title": i.get("title", ""),
                "customer_id": i.get("customer_id"),
                "customer_name": i.get("customer_name"),
                "total": float(i.get("total") or 0),
                "amount_paid": float(i.get("amount_paid") or 0),
                "payment_status": i.get("payment_status") or "unpaid",
                "due_date": i.get("due_date"),
            }
            for i in invs
        ],
        "total": total,
        "balance": balance,
        "amount_paid": 0.0,
        "due_date": body.due_date,
        "status": "open" if balance > 0 else "paid",
        "payment_status": "unpaid" if balance > 0 else "paid",
        "created_at": now_iso(),
    }
    # Phase 56.18 — master invoice number (MINV-YYYY-NNNNNN).
    from services.invoice_numbering import assign_invoice_number_if_missing
    await assign_invoice_number_if_missing(doc, tenant, master=True)
    await db.master_invoices.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/invoices/master/{mid}")
async def get_master_invoice(mid: str,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    doc = await db.master_invoices.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Master invoice not found")
    # refresh child snapshot totals lazily
    children = await db.quotes.find(
        {"id": {"$in": doc["invoice_ids"]}, "tenant_id": tenant["id"]},
        {"_id": 0},
    ).to_list(2000)
    by_id = {c["id"]: c for c in children}
    for s in doc.get("invoice_snapshot") or []:
        c = by_id.get(s["id"])
        if c:
            s["amount_paid"] = float(c.get("amount_paid") or 0)
            s["payment_status"] = c.get("payment_status") or "unpaid"
    return doc


@router.delete("/invoices/master/{mid}")
async def delete_master_invoice(mid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    res = await db.master_invoices.delete_one({"id": mid, "tenant_id": tenant["id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Master invoice not found")
    return {"ok": True}


class MasterPayIn(BaseModel):
    amount: float


@router.post("/invoices/master/{mid}/apply-payment")
async def apply_master_payment(mid: str, body: MasterPayIn,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    """Applies `amount` proportionally across every child invoice's remaining balance,
    then marks the master invoice's own totals + status."""
    doc = await db.master_invoices.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Master invoice not found")
    amount = max(0.0, float(body.amount or 0))
    children = await db.quotes.find(
        {"id": {"$in": doc["invoice_ids"]}, "tenant_id": tenant["id"]},
        {"_id": 0},
    ).to_list(2000)
    remaining = {
        c["id"]: max(0.0, float(c.get("total") or 0) - float(c.get("amount_paid") or 0))
        for c in children
    }
    total_remaining = sum(remaining.values()) or 1e-9
    applied_total = 0.0
    for c in children:
        share = (remaining.get(c["id"], 0) / total_remaining) * amount
        share = min(share, remaining.get(c["id"], 0))
        if share <= 0:
            continue
        new_paid = round(float(c.get("amount_paid") or 0) + share, 2)
        status = "paid" if new_paid + 0.005 >= float(c.get("total") or 0) else "partial"
        await db.quotes.update_one(
            {"id": c["id"], "tenant_id": tenant["id"]},
            {"$set": {"amount_paid": new_paid, "payment_status": status}},
        )
        applied_total += share
    new_master_paid = round(float(doc.get("amount_paid") or 0) + applied_total, 2)
    master_status = "paid" if new_master_paid + 0.005 >= float(doc["total"]) else (
        "partial" if new_master_paid > 0 else "unpaid"
    )
    await db.master_invoices.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {
            "$set": {
                "amount_paid": new_master_paid,
                "payment_status": master_status,
                "status": "paid" if master_status == "paid" else "open",
                "last_payment_at": now_iso(),
            }
        },
    )
    return {"ok": True, "applied": applied_total, "master_paid": new_master_paid}
