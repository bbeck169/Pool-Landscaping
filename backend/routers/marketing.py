# ruff: noqa: F403,F405
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Query, Request
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


# ── Feb-2026 · Phase F5 — Widget-lead field extraction ────────────
# The primary alias-tolerant extractor now lives in
# ``services/lead_extraction`` so both this router (public-form
# path) and ``routers/marketing_forms`` (widget path) share the
# exact same helper — see the identity assertion in
# ``tests/test_lead_extraction_single_source_of_truth.py``.  The
# ``_first_str`` + ``_lead_row_from_form_values`` names are kept
# as thin aliases so downstream imports don't need to change.
from services.lead_extraction import (
    first_str as _first_str,
    lead_row_from_form_values as _lead_row_from_form_values,
)


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
# TD-50 · Feb-2026 — System C deprecation.
#
# The ``/forms*`` endpoints below are the ORIGINAL public-form
# surface backed by ``db.forms``.  They are superseded by the
# Marketing Forms Builder path at ``routers/marketing_forms.py``
# (admin UI: ``/admin/marketing/forms``; public widget:
# ``/widget/form/{fid}``).  New forms SHOULD be authored through
# the Marketing Forms Builder.
#
# Operators migrating from System C should run::
#
#     python backend/scripts/migrate_system_c_forms_to_marketing_forms.py --audit
#     python backend/scripts/migrate_system_c_forms_to_marketing_forms.py
#
# which idempotently copies each ``db.forms`` row into
# ``db.marketing_forms`` preserving slug + submission linkage
# (``db.form_submissions.form_id`` is unchanged — both systems
# have always shared this collection).
#
# These endpoints are LEFT FUNCTIONAL for backward compatibility
# with any production tenant still using the old UI.  A follow-up
# atomic will physically remove them once operators confirm the
# migration ran clean on their tenants.
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
async def submit_public_form(slug: str, body: dict, request: Request,
                                background_tasks: BackgroundTasks):
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
        # Feb-2026 · K53.1 — Fix B: require an email OR phone before
        # we insert a lead row.  Prior behaviour was to unconditionally
        # save a ``{"name": "Website Visitor"}`` placeholder whenever
        # extraction failed to find a contact — matching the guard on
        # the modern widget path (``routers/marketing_forms.py:501``).
        # Raw submissions are still written to ``db.form_submissions``
        # above so nothing is truly lost.
        # Phase L2.5 · Feb-2026 — use the schema-aware extractor so
        # forms whose contact fields carry auto-generated ids
        # (``field_9`` / ``field_Service Address_5``) still resolve
        # to the canonical keys via label matching.  Falls back to
        # the pre-L2 behaviour when the form doc has no ``fields``
        # array (legacy).
        from services.lead_extraction import (
            extract_contact_fields_with_schema,
            lead_row_from_form_values_with_schema,
        )
        _schema_fields = form.get("fields") or []
        _extracted = extract_contact_fields_with_schema(vals, _schema_fields)
        if not (_extracted.get("email") or _extracted.get("phone")):
            logger.info(
                f"[k53.1] Path A guard-skip · tenant={tid} form={form.get('id')}"
                f" slug={slug} submission_id={sub['id']}"
                f" values_keys={list(vals.keys())[:20]}"
            )
            return {"ok": True, "redirect_url": form.get("redirect_url"),
                    "lead_created": False, "reason": "no_contact_captured"}
        lead = lead_row_from_form_values_with_schema(
            tid=tid, vals=vals,
            source_label=form.get("name") or "Web Form",
            schema_fields=_schema_fields,
        )
        lead["submission_id"] = sub["id"]
        await db.leads.insert_one(lead)
        # Feb-2026 · P18 — instant SMS+email alert to tenant-configured
        # recipients.  Deferred via BackgroundTasks; no-op when both
        # recipient lists are empty.
        try:
            tenant_doc = await db.tenants.find_one(
                {"id": tid}, {"_id": 0}) or {"id": tid}
            from services.lead_notifications import send_lead_alert_notifications
            await send_lead_alert_notifications(
                lead=lead, tenant=tenant_doc,
                background_tasks=background_tasks,
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"[p18] lead alert dispatch failed: {_e}")
    # Feb-2026 · K53.2 — happy-path response now surfaces
    # ``lead_created`` explicitly so Path A / Path B response shapes
    # stay consistent for future API consumers.
    return {"ok": True, "redirect_url": form.get("redirect_url"),
            "lead_created": dest == "lead"}


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
async def submit_form(fid: str, body: FormSubmitIn, request: Request,
                        background_tasks: BackgroundTasks):
    """Legacy public form submission — creates a submission record and a new lead."""
    form = await db.forms.find_one({"id": fid}, {"_id": 0})
    if not form:
        raise HTTPException(404, "Form not found")
    tid = form.get("tenant_id") or await _resolve_public_tenant(request, form)
    vals = body.values or {}
    sub = {"id": new_id(), "tenant_id": tid, "form_id": fid,
           "values": vals, "created_at": now_iso()}
    await db.form_submissions.insert_one(sub)
    # Feb-2026 · K53.1 — Fix B: require an email OR phone before
    # inserting a lead row.  Matches the widget path's guard so
    # ``"Website Visitor"`` placeholders cannot originate from
    # either Path A endpoint.  Raw submission remains persisted
    # above so nothing is truly lost.
    # Phase L2.5 · Feb-2026 — same wire-in for the legacy submit
    # endpoint (``/api/marketing/forms/{fid}/submit``).  Uses the
    # schema-aware extractor + lead-row builder so auto-generated
    # field ids resolve to canonical contact keys via label match.
    from services.lead_extraction import (
        extract_contact_fields_with_schema,
        lead_row_from_form_values_with_schema,
    )
    _schema_fields = form.get("fields") or []
    _extracted = extract_contact_fields_with_schema(vals, _schema_fields)
    if not (_extracted.get("email") or _extracted.get("phone")):
        logger.info(
            f"[k53.1] Path A guard-skip · tenant={tid} form={fid}"
            f" submission_id={sub['id']} values_keys={list(vals.keys())[:20]}"
        )
        return {"ok": True, "lead_created": False,
                "reason": "no_contact_captured"}
    lead = lead_row_from_form_values_with_schema(
        tid=tid, vals=vals,
        source_label=form.get("name", "Web Form"),
        schema_fields=_schema_fields,
    )
    lead["submission_id"] = sub["id"]
    await db.leads.insert_one(lead)
    # Feb-2026 · P18 — same lead-alert fan-out as the /public path.
    try:
        tenant_doc = await db.tenants.find_one(
            {"id": tid}, {"_id": 0}) or {"id": tid}
        from services.lead_notifications import send_lead_alert_notifications
        await send_lead_alert_notifications(
            lead=lead, tenant=tenant_doc,
            background_tasks=background_tasks,
        )
    except Exception as _e:  # noqa: BLE001
        logger.warning(f"[p18] lead alert dispatch failed: {_e}")
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

    # Feb-2026 · Technician Check-In flow — validate that each
    # ``photo_file_ids`` entry references a real, tenant-scoped
    # public_checkin upload. Bad ids surface as 422 with a payload
    # naming the offender so the mobile client can highlight the
    # broken photo tile.
    seen_ids = list(dict.fromkeys(body.photo_file_ids))
    if len(seen_ids) != len(body.photo_file_ids):
        raise HTTPException(422, detail={
            "code": "PHOTO_FILE_IDS_DUPLICATE",
            "message": "photo_file_ids must be unique",
        })
    file_docs = await db.files.find(
        {"id": {"$in": seen_ids},
         "tenant_id": tenant["id"],
         "is_deleted": {"$ne": True}},
        {"_id": 0, "id": 1, "purpose": 1, "linked_entity_type": 1,
         "storage_path": 1, "storage": 1},
    ).to_list(len(seen_ids) + 1)
    found_ids = {d["id"] for d in file_docs}
    missing = [fid for fid in seen_ids if fid not in found_ids]
    if missing:
        raise HTTPException(422, detail={
            "code": "PHOTO_FILE_IDS_INVALID",
            "message": "One or more photo_file_ids do not exist for this tenant",
            "missing": missing,
        })
    # Purpose gate — uploads have to be flagged as public_checkin so
    # a tech can't accidentally attach an invoice PDF or a customer
    # avatar as a check-in photo.
    wrong_purpose = [d["id"] for d in file_docs
                       if (d.get("purpose") or "") != "public_checkin"]
    if wrong_purpose:
        raise HTTPException(422, detail={
            "code": "PHOTO_FILE_IDS_WRONG_PURPOSE",
            "message": "Photos must be uploaded with purpose='public_checkin'",
            "wrong_purpose": wrong_purpose,
        })

    doc = body.model_dump()
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "technician_id": user.get("technician_id") or user.get("id"),
        "technician_name": user.get("name"),
        "status": "draft",
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
