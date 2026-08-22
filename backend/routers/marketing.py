# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant, _ensure_default_tenant
from models import (
    AutomationIn, AutomationUpdate, CampaignIn, CheckinIn,
    FormIn, FormSubmitIn, ReviewIn, ReviewRespond,
)

router = APIRouter()


# ── Feb-2026 · P17 — Widget-lead field extraction ─────────────────
# Legacy public-form endpoints (``/public/forms/{slug}/submit`` and
# ``/forms/{fid}/submit``) previously did a naive
# ``vals.get("phone", "")`` / ``vals.get("email", "")`` /
# ``vals.get("name", "Website Visitor")`` extraction, which silently
# dropped every submission whose form fields used the common
# ``full_name`` / ``email_address`` / ``phone_number`` aliases.
# The prod symptom (``app.plofv.com/leads``) was leads landing with
# empty contact columns + the hardcoded "Website Visitor" fallback
# name.  This helper mirrors the alias-tolerant extractor in
# ``routers/marketing_forms.py::_first_str`` so both intake paths
# now capture the same field-name universe.
def _first_str(d: dict, keys: List[str]) -> Optional[str]:
    for k in keys:
        v = (d or {}).get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _lead_row_from_form_values(*, tid: str, vals: dict, source_label: str) -> dict:
    """Build the ``leads`` insert doc from a form-submission ``vals``
    dict, tolerating every common field-name alias.  The returned
    doc is safe to insert directly into ``db.leads``."""
    name = _first_str(vals, ["name", "full_name", "fullname"])
    email = _first_str(vals, ["email", "email_address"])
    phone = _first_str(vals, ["phone", "phone_number", "tel", "mobile"])
    message = _first_str(vals, ["message", "notes", "details", "comments"])
    address = _first_str(vals, ["address", "street_address", "service_address"])
    service_interest = _first_str(
        vals, ["service_interest", "requested_service", "service", "interest"],
    )
    return {
        "id": new_id(),
        "tenant_id": tid,
        "name": name or "Website Visitor",
        "phone": phone or "",
        "email": email or "",
        "address": address or "",
        "service_address": address or "",
        "service_interest": service_interest or None,
        "message": message or "",
        "source": source_label or "Web Form",
        "status": "new",
        "notes": message or "",
        "est_value": 0.0,
        "created_at": now_iso(),
    }


async def _resolve_public_tenant(request: Request, form: dict | None = None) -> str:
    """Public endpoints: prefer the form's own tenant_id, else X-Tenant-Slug header,
    else custom domain, else default tenant."""
    if form and form.get("tenant_id"):
        return form["tenant_id"]
    slug = request.headers.get("x-tenant-slug")
    if slug:
        t = await db.tenants.find_one({"slug": slug, "active": True}, {"_id": 0})
        if t:
            return t["id"]
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host:
        t = await db.tenants.find_one({"custom_domain": host, "active": True}, {"_id": 0})
        if t:
            return t["id"]
    return (await _ensure_default_tenant())["id"]


# ----------------------- Marketing: Form Builder -----------------------
@router.get("/forms")
async def list_forms(user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    forms = await db.forms.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)
    for f in forms:
        f["submissions"] = await db.form_submissions.count_documents(
            {"form_id": f["id"], "tenant_id": tenant["id"]}
        )
    return forms


@router.post("/forms")
async def create_form(body: FormIn,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "created_at": now_iso()})
    if not doc.get("slug"):
        doc["slug"] = (doc.get("name") or "form").lower().replace(" ", "-") + "-" + new_id()[:6]
    await db.forms.insert_one(doc)
    doc.pop("_id", None)
    doc["submissions"] = 0
    return doc


@router.get("/forms/{fid}")
async def get_form(fid: str,
                   user: dict = Depends(require_admin),
                   tenant: dict = Depends(get_current_tenant)):
    form = await db.forms.find_one(
        {"tenant_id": tenant["id"], "$or": [{"id": fid}, {"slug": fid}]}, {"_id": 0}
    )
    if not form:
        raise HTTPException(404, "Form not found")
    form["submissions"] = await db.form_submissions.count_documents(
        {"form_id": form["id"], "tenant_id": tenant["id"]}
    )
    return form


@router.patch("/forms/{fid}")
async def update_form(fid: str, body: dict,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in (body or {}).items() if k != "id"}
    if upd:
        upd["updated_at"] = now_iso()
        await db.forms.update_one(
            {"id": fid, "tenant_id": tenant["id"]}, {"$set": upd}
        )
    return await db.forms.find_one({"id": fid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/forms/{fid}")
async def delete_form(fid: str,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    await db.forms.delete_one({"id": fid, "tenant_id": tenant["id"]})
    return {"ok": True}


@router.get("/forms/{fid}/submissions")
async def list_form_submissions(fid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    return await db.form_submissions.find(
        {"form_id": fid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)


@router.get("/public/forms/{slug}")
async def get_public_form(slug: str, request: Request):
    # Public: resolve by slug across all tenants; header/domain can disambiguate.
    tenant_id = await _resolve_public_tenant(request)
    form = await db.forms.find_one(
        {"tenant_id": tenant_id, "$or": [{"slug": slug}, {"id": slug}]}, {"_id": 0}
    )
    if not form:
        # Fallback for legacy pre-tenant forms + cross-tenant slug lookup.
        form = await db.forms.find_one({"$or": [{"slug": slug}, {"id": slug}]}, {"_id": 0})
    if not form or form.get("status") == "draft":
        raise HTTPException(404, "Form not found")
    form.pop("notify_emails", None)
    return form


@router.post("/public/forms/{slug}/submit")
async def submit_public_form(slug: str, body: dict, request: Request):
    form = await db.forms.find_one({"$or": [{"slug": slug}, {"id": slug}]}, {"_id": 0})
    if not form or form.get("status") != "published":
        raise HTTPException(404, "Form not found")
    # Use the form's tenant_id (already bound at create time) as ground truth.
    tid = form.get("tenant_id") or await _resolve_public_tenant(request, form)
    vals = (body or {}).get("values") or body or {}
    sub = {"id": new_id(), "tenant_id": tid, "form_id": form["id"], "slug": slug,
           "values": vals, "created_at": now_iso()}
    await db.form_submissions.insert_one(sub)
    dest = (form.get("destination") or "lead").lower()
    if dest == "lead":
        await db.leads.insert_one(_lead_row_from_form_values(
            tid=tid, vals=vals,
            source_label=form.get("name") or "Web Form",
        ))
    return {"ok": True, "redirect_url": form.get("redirect_url")}


@router.get("/forms/{fid}/preview")
async def preview_form(fid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    """Admin-only preview — returns the full form schema regardless of publish status."""
    form = await db.forms.find_one(
        {"tenant_id": tenant["id"], "$or": [{"id": fid}, {"slug": fid}]}, {"_id": 0}
    )
    if not form:
        raise HTTPException(404, "Form not found")
    form.pop("notify_emails", None)
    return form


@router.post("/forms/{fid}/submit")
async def submit_form(fid: str, body: FormSubmitIn, request: Request):
    """Legacy public form submission — creates a submission record and a new lead."""
    form = await db.forms.find_one({"id": fid}, {"_id": 0})
    if not form:
        raise HTTPException(404, "Form not found")
    tid = form.get("tenant_id") or await _resolve_public_tenant(request, form)
    vals = body.values or {}
    sub = {"id": new_id(), "tenant_id": tid, "form_id": fid,
           "values": vals, "created_at": now_iso()}
    await db.form_submissions.insert_one(sub)
    lead = _lead_row_from_form_values(
        tid=tid, vals=vals,
        source_label=form.get("name", "Web Form"),
    )
    await db.leads.insert_one(lead)
    return {"ok": True, "lead_created": True}


# ----------------------- Marketing: Automation -----------------------
@router.get("/automations")
async def list_automations(user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    return await db.automations.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)


@router.post("/automations")
async def create_automation(body: AutomationIn,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "runs": 0, "created_at": now_iso()})
    await db.automations.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/automations/{aid}")
async def update_automation(aid: str, body: AutomationUpdate,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd:
        await db.automations.update_one(
            {"id": aid, "tenant_id": tenant["id"]}, {"$set": upd}
        )
    return await db.automations.find_one({"id": aid, "tenant_id": tenant["id"]}, {"_id": 0})


# ----------------------- Marketing: Communication -----------------------
@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    return await db.campaigns.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)


@router.post("/campaigns")
async def create_campaign(body: CampaignIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    total = await db.customers.count_documents({"tenant_id": tenant["id"]})
    doc = body.dict()
    doc.update({"id": new_id(), "tenant_id": tenant["id"],
                "status": "sent", "sent_count": total,
                "sent_at": now_iso(), "created_at": now_iso()})
    await db.campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ----------------------- Marketing: Reviews -----------------------
@router.get("/reviews")
async def list_reviews(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    items = await db.reviews.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)
    count = len(items)
    average = round(sum(r.get("rating", 0) for r in items) / count, 1) if count else 0.0
    return {"items": items, "average": average, "count": count}


@router.post("/reviews")
async def create_review(body: ReviewIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    doc.update({"id": new_id(), "tenant_id": tenant["id"],
                "response": None, "created_at": now_iso()})
    await db.reviews.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/reviews/{rid}/respond")
async def respond_review(rid: str, body: ReviewRespond,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    await db.reviews.update_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"$set": {"response": body.response, "responded_at": now_iso()}},
    )
    return await db.reviews.find_one({"id": rid, "tenant_id": tenant["id"]}, {"_id": 0})


# ----------------------- Marketing: Map Check-ins -----------------------
@router.get("/checkins")
async def list_checkins(user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    return await db.checkins.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)


@router.post("/checkins")
async def create_checkin(body: CheckinIn,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("technician", "admin", "super_admin"):
        raise HTTPException(403, "Not allowed")
    doc = body.dict()
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "technician_id": user.get("technician_id"),
        "technician_name": user.get("name"),
        "created_at": now_iso(),
    })
    await db.checkins.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ----------------------- Marketing: Rank Grid (local SEO) -----------------------
@router.get("/rank-grid")
async def rank_grid(user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    kws = await db.rank_grid.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("keyword", 1).to_list(1000)
    for k in kws:
        grid = k.get("grid", [])
        flat = [v for row in grid for v in row]
        k["avg_rank"] = round(sum(flat) / len(flat), 1) if flat else 0
        k["top3_pct"] = round(100 * sum(1 for v in flat if v <= 3) / len(flat)) if flat else 0
    return kws
