# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from models import *  # noqa: F403,F405

router = APIRouter()


# ----------------------- Leads -----------------------
@router.get("/leads")
async def list_leads(user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant),
                     status: Optional[str] = None):
    q: dict = {"tenant_id": tenant["id"]}
    if status and status != "all":
        q["status"] = status
    return await db.leads.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.post("/leads")
async def create_lead(body: LeadIn,
                      user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "technician", "super_admin"):
        raise HTTPException(403, "Not allowed")
    doc = body.dict()
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_at": now_iso(),
        "created_by": user.get("id"),
    })
    await db.leads.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/leads/{lid}")
async def update_lead(lid: str, body: LeadUpdate,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd:
        await db.leads.update_one(
            {"id": lid, "tenant_id": tenant["id"]}, {"$set": upd}
        )
    return await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.post("/leads/{lid}/convert")
async def convert_lead(lid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "technician", "super_admin"):
        raise HTTPException(403, "Not allowed")
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    cust = await _ensure_customer_from_lead(lead, tenant["id"])
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"status": "won", "converted": {"type": "customer", "id": cust["id"]}}},
    )
    # Slice O.2 · Referral reward hook — safe no-op when the lead
    # isn't referral-sourced. Never raises; hook enforces idempotency.
    try:
        from routers.referral_rewards import fire_referral_conversion_hook
        await fire_referral_conversion_hook(
            tenant_id=tenant["id"], lead=lead, new_customer_id=cust["id"],
        )
    except Exception as exc:
        logger.warning("[leads] referral hook failed: %s", exc)
    return cust


async def _ensure_customer_from_lead(lead: dict, tenant_id: str) -> dict:
    """Find an existing customer within the tenant matching the lead
    (by phone, else name) or create one."""
    existing = None
    if lead.get("phone"):
        existing = await db.customers.find_one(
            {"phone": lead["phone"], "tenant_id": tenant_id}, {"_id": 0}
        )
    if not existing:
        existing = await db.customers.find_one(
            {"name": lead["name"], "tenant_id": tenant_id}, {"_id": 0}
        )
    if existing:
        return existing
    cust = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "name": lead["name"],
        "email": lead.get("email", ""),
        "phone": lead.get("phone", ""),
        "address": lead.get("address", ""),
        "gate_code": "",
        "lat": lead.get("lat"),
        "lng": lead.get("lng"),
        "notes": lead.get("notes", ""),
        "created_at": now_iso(),
    }
    await db.customers.insert_one(cust)
    cust.pop("_id", None)
    return cust


@router.post("/leads/{lid}/convert-to-job")
async def convert_lead_to_job(lid: str, body: ConvertJobIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    cust = await _ensure_customer_from_lead(lead, tenant["id"])
    price = body.price if body.price is not None else float(lead.get("est_value") or 0)
    tech_name = tech_avatar = None
    if body.technician_id:
        tech = await db.technicians.find_one(
            {"id": body.technician_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        tech_name = tech["name"] if tech else None
        tech_avatar = tech.get("avatar", "") if tech else ""
    job = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cust["id"], "customer_name": cust["name"],
        "address": cust.get("address", ""), "service_type": body.service_type or "Pool Service",
        "scheduled_date": body.scheduled_date, "notes": lead.get("notes", ""),
        "technician_id": body.technician_id, "technician_name": tech_name,
        "technician_avatar": tech_avatar, "price": price,
        "status": "pending", "photos": [], "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"status": "won", "converted": {"type": "job", "id": job["id"]}}},
    )
    job.pop("_id", None)
    return job


@router.post("/leads/{lid}/convert-to-quote")
async def convert_lead_to_quote(lid: str, body: ConvertQuoteIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    cust = await _ensure_customer_from_lead(lead, tenant["id"])
    up = body.unit_price if body.unit_price is not None else float(lead.get("est_value") or 0)
    title = body.title or f"Estimate for {lead['name']}"
    line_items = [{"description": lead.get("notes") or title, "quantity": 1, "unit_price": up}]
    subtotal = round(up, 2)
    tax = round(subtotal * ((body.tax_rate or 0) / 100.0), 2)
    total = round(subtotal + tax, 2)
    quote = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cust["id"], "customer_name": cust["name"],
        "title": title, "doc_type": "quote", "line_items": line_items,
        "tax_rate": body.tax_rate or 0, "subtotal": subtotal, "tax": tax, "total": total,
        "status": "sent", "payment_status": "unpaid", "notes": lead.get("notes", ""),
        "created_at": now_iso(),
    }
    await db.quotes.insert_one(quote)
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"status": "quoted", "converted": {"type": "quote", "id": quote["id"]}}},
    )
    quote.pop("_id", None)
    return quote


@router.delete("/leads/{lid}")
async def delete_lead(lid: str,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    res = await db.leads.delete_one({"id": lid, "tenant_id": tenant["id"]})
    return {"ok": True, "deleted": res.deleted_count}
