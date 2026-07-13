from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()


# ----------------------- Marketing: Form Builder -----------------------
@router.get("/forms")
async def list_forms(user: dict = Depends(require_admin)):
    forms = await db.forms.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    for f in forms:
        f["submissions"] = await db.form_submissions.count_documents({"form_id": f["id"]})
    return forms


@router.post("/forms")
async def create_form(body: FormIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "created_at": now_iso()})
    if not doc.get("slug"):
        doc["slug"] = (doc.get("name") or "form").lower().replace(" ", "-") + "-" + new_id()[:6]
    await db.forms.insert_one(doc)
    doc.pop("_id", None)
    doc["submissions"] = 0
    return doc


@router.get("/forms/{fid}")
async def get_form(fid: str, user: dict = Depends(require_admin)):
    form = await db.forms.find_one({"$or": [{"id": fid}, {"slug": fid}]}, {"_id": 0})
    if not form:
        raise HTTPException(404, "Form not found")
    form["submissions"] = await db.form_submissions.count_documents({"form_id": form["id"]})
    return form


@router.patch("/forms/{fid}")
async def update_form(fid: str, body: dict, user: dict = Depends(require_admin)):
    upd = {k: v for k, v in (body or {}).items() if k != "id"}
    if upd:
        upd["updated_at"] = now_iso()
        await db.forms.update_one({"id": fid}, {"$set": upd})
    return await db.forms.find_one({"id": fid}, {"_id": 0})


@router.delete("/forms/{fid}")
async def delete_form(fid: str, user: dict = Depends(require_admin)):
    await db.forms.delete_one({"id": fid})
    return {"ok": True}


@router.get("/forms/{fid}/submissions")
async def list_form_submissions(fid: str, user: dict = Depends(require_admin)):
    return await db.form_submissions.find({"form_id": fid}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.get("/public/forms/{slug}")
async def get_public_form(slug: str):
    form = await db.forms.find_one({"$or": [{"slug": slug}, {"id": slug}]}, {"_id": 0})
    if not form or form.get("status") == "draft":
        raise HTTPException(404, "Form not found")
    # Never leak notification recipients in the public payload
    form.pop("notify_emails", None)
    return form


@router.post("/public/forms/{slug}/submit")
async def submit_public_form(slug: str, body: dict):
    form = await db.forms.find_one({"$or": [{"slug": slug}, {"id": slug}]}, {"_id": 0})
    if not form:
        raise HTTPException(404, "Form not found")
    vals = (body or {}).get("values") or body or {}
    sub = {"id": new_id(), "form_id": form["id"], "slug": slug, "values": vals, "created_at": now_iso()}
    await db.form_submissions.insert_one(sub)
    dest = (form.get("destination") or "lead").lower()
    if dest == "lead":
        await db.leads.insert_one({
            "id": new_id(), "name": vals.get("name", "Website Visitor"),
            "phone": vals.get("phone", ""), "email": vals.get("email", ""),
            "source": form.get("name") or "Web Form", "status": "new",
            "notes": vals.get("message") or vals.get("notes") or "",
            "created_at": now_iso(),
        })
    return {"ok": True, "redirect_url": form.get("redirect_url")}


@router.post("/forms/{fid}/submit")
async def submit_form(fid: str, body: FormSubmitIn):
    """Public form submission — creates a submission record and a new lead."""
    form = await db.forms.find_one({"id": fid}, {"_id": 0})
    if not form:
        raise HTTPException(404, "Form not found")
    vals = body.values or {}
    sub = {"id": new_id(), "form_id": fid, "values": vals, "created_at": now_iso()}
    await db.form_submissions.insert_one(sub)
    lead = {
        "id": new_id(), "name": vals.get("name", "Website Visitor"),
        "phone": vals.get("phone", ""), "email": vals.get("email", ""),
        "source": form.get("name", "Web Form"), "status": "new",
        "notes": vals.get("message", vals.get("notes", "")), "est_value": 0.0, "created_at": now_iso(),
    }
    await db.leads.insert_one(lead)
    return {"ok": True, "lead_created": True}


# ----------------------- Marketing: Automation -----------------------
@router.get("/automations")
async def list_automations(user: dict = Depends(require_admin)):
    return await db.automations.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.post("/automations")
async def create_automation(body: AutomationIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "runs": 0, "created_at": now_iso()})
    await db.automations.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/automations/{aid}")
async def update_automation(aid: str, body: AutomationUpdate, user: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd:
        await db.automations.update_one({"id": aid}, {"$set": upd})
    return await db.automations.find_one({"id": aid}, {"_id": 0})


# ----------------------- Marketing: Communication -----------------------
@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(require_admin)):
    return await db.campaigns.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.post("/campaigns")
async def create_campaign(body: CampaignIn, user: dict = Depends(require_admin)):
    total = await db.customers.count_documents({})
    doc = body.dict()
    doc.update({"id": new_id(), "status": "sent", "sent_count": total,
                "sent_at": now_iso(), "created_at": now_iso()})
    await db.campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ----------------------- Marketing: Reviews -----------------------
@router.get("/reviews")
async def list_reviews(user: dict = Depends(require_admin)):
    items = await db.reviews.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    count = len(items)
    average = round(sum(r.get("rating", 0) for r in items) / count, 1) if count else 0.0
    return {"items": items, "average": average, "count": count}


@router.post("/reviews")
async def create_review(body: ReviewIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "response": None, "created_at": now_iso()})
    await db.reviews.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/reviews/{rid}/respond")
async def respond_review(rid: str, body: ReviewRespond, user: dict = Depends(require_admin)):
    await db.reviews.update_one({"id": rid}, {"$set": {"response": body.response, "responded_at": now_iso()}})
    return await db.reviews.find_one({"id": rid}, {"_id": 0})


# ----------------------- Marketing: Map Check-ins -----------------------
@router.get("/checkins")
async def list_checkins(user: dict = Depends(require_admin)):
    return await db.checkins.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/checkins")
async def create_checkin(body: CheckinIn, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("technician", "admin"):
        raise HTTPException(403, "Not allowed")
    doc = body.dict()
    doc.update({
        "id": new_id(),
        "technician_id": user.get("technician_id"),
        "technician_name": user.get("name"),
        "created_at": now_iso(),
    })
    await db.checkins.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ----------------------- Marketing: Rank Grid (local SEO) -----------------------
@router.get("/rank-grid")
async def rank_grid(user: dict = Depends(require_admin)):
    kws = await db.rank_grid.find({}, {"_id": 0}).sort("keyword", 1).to_list(1000)
    for k in kws:
        grid = k.get("grid", [])
        flat = [v for row in grid for v in row]
        k["avg_rank"] = round(sum(flat) / len(flat), 1) if flat else 0
        k["top3_pct"] = round(100 * sum(1 for v in flat if v <= 3) / len(flat)) if flat else 0
    return kws


