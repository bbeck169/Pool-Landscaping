"""Phase SEO-B · Feb-2026 — Backlink outreach CRM.

Admin+/manager only. Tenant-scoped. Reuses ``services.comms_email_adapter``
for Resend sends — no new email SDK, no new API keys.

Collections written:
  * ``outreach_prospects``   — one row per (site, contact)
  * ``outreach_templates``   — reusable email templates
  * ``outreach_messages``    — one row per send attempt

All endpoints validate ``tenant_id`` from the caller's JWT before any
read/write. Cross-tenant access is impossible by construction.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import (APIRouter, Depends, File, HTTPException, Query,
                        UploadFile)
from pydantic import BaseModel, EmailStr, Field

from config import db, logger
from services.comms_email_adapter import send_email
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_MOD_ROLES = {"admin", "super_admin", "manager", "owner"}
_STATUSES = {"pending", "contacted", "replied", "link_placed",
             "declined", "unsubscribed"}
_TERMINAL_STATUSES = {"replied", "link_placed", "declined", "unsubscribed"}


def _require_mod(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


def _normalize_domain(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.rstrip("/")
    if s.startswith("www."):
        s = s[4:]
    # Strip path/query.
    s = s.split("/", 1)[0].split("?", 1)[0]
    return s


# ═════════════════════════ Prospect models ══════════════════════════

class ProspectCreateBody(BaseModel):
    domain: str = Field(..., min_length=1)
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_role: Optional[str] = None
    target_page_url: Optional[str] = None
    desired_anchor: Optional[str] = None
    our_page_url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: str = ""
    status: str = "pending"


class ProspectPatchBody(BaseModel):
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_role: Optional[str] = None
    target_page_url: Optional[str] = None
    desired_anchor: Optional[str] = None
    our_page_url: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    next_followup_at: Optional[str] = None


class ProspectStatusBody(BaseModel):
    status: str = Field(..., min_length=1)


# ═════════════════════════ Prospect CRUD ════════════════════════════

@router.post("/outreach/prospects", operation_id="outreach.createProspect")
async def create_prospect(body: ProspectCreateBody,
                             caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    domain = _normalize_domain(body.domain)
    if not domain:
        raise HTTPException(400, {"error": "invalid_domain"})
    if body.status not in _STATUSES:
        raise HTTPException(422, {"error": "invalid_status"})
    now_ts = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "created_by_user_id": caller["id"],
        "created_at": now_ts,
        "domain": domain,
        "contact_name": body.contact_name,
        "contact_email": (body.contact_email or "").lower() or None,
        "contact_role": body.contact_role,
        "target_page_url": body.target_page_url,
        "desired_anchor": body.desired_anchor,
        "our_page_url": body.our_page_url,
        "tags": body.tags or [],
        "notes": body.notes or "",
        "status": body.status,
        "last_activity_at": None,
        "next_followup_at": None,
        "updated_at": now_ts,
        "deleted_at": None,
    }
    await db.outreach_prospects.insert_one({**doc})
    doc.pop("_id", None)
    return doc


@router.get("/outreach/prospects", operation_id="outreach.listProspects")
async def list_prospects(
    status: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    q: Dict[str, Any] = {"tenant_id": tenant_id, "deleted_at": None}
    if status and status != "all":
        if status not in _STATUSES:
            raise HTTPException(422, {"error": "invalid_status"})
        q["status"] = status
    if tag:
        q["tags"] = tag
    if search:
        safe = re.escape(search.strip())
        q["$or"] = [
            {"domain": {"$regex": safe, "$options": "i"}},
            {"contact_name": {"$regex": safe, "$options": "i"}},
            {"contact_email": {"$regex": safe, "$options": "i"}},
            {"notes": {"$regex": safe, "$options": "i"}},
        ]
    total = await db.outreach_prospects.count_documents(q)
    items: List[Dict[str, Any]] = []
    async for r in db.outreach_prospects.find(q, {"_id": 0}) \
                                            .sort("updated_at", -1) \
                                            .skip(offset).limit(limit):
        items.append(r)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def _load_prospect(tenant_id: str, pid: str) -> Dict[str, Any]:
    row = await db.outreach_prospects.find_one(
        {"id": pid, "tenant_id": tenant_id, "deleted_at": None},
        {"_id": 0})
    if not row:
        raise HTTPException(404, {"error": "not_found"})
    return row


@router.get("/outreach/prospects/{pid}",
             operation_id="outreach.getProspect")
async def get_prospect(pid: str,
                          caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    row = await _load_prospect(tenant_id, pid)
    # Attach message history.
    messages: List[Dict[str, Any]] = []
    async for m in db.outreach_messages.find(
            {"tenant_id": tenant_id, "prospect_id": pid},
            {"_id": 0}).sort("sent_at", -1).limit(50):
        messages.append(m)
    row["messages"] = messages
    return row


@router.patch("/outreach/prospects/{pid}",
               operation_id="outreach.patchProspect")
async def patch_prospect(pid: str, body: ProspectPatchBody,
                            caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    await _load_prospect(tenant_id, pid)
    updates: Dict[str, Any] = {}
    for field in ("contact_name", "contact_role", "target_page_url",
                   "desired_anchor", "our_page_url", "tags", "notes",
                   "next_followup_at"):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val
    if body.contact_email is not None:
        updates["contact_email"] = body.contact_email.lower() or None
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(422, {"error": "invalid_status"})
        updates["status"] = body.status
    if not updates:
        return await _load_prospect(tenant_id, pid)
    updates["updated_at"] = now_iso()
    await db.outreach_prospects.update_one(
        {"id": pid, "tenant_id": tenant_id}, {"$set": updates})
    return await _load_prospect(tenant_id, pid)


@router.delete("/outreach/prospects/{pid}",
                operation_id="outreach.deleteProspect")
async def delete_prospect(pid: str,
                             caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    await _load_prospect(tenant_id, pid)
    await db.outreach_prospects.update_one(
        {"id": pid, "tenant_id": tenant_id},
        {"$set": {"deleted_at": now_iso(),
                    "updated_at": now_iso()}})
    return {"deleted": True, "id": pid}


@router.post("/outreach/prospects/{pid}/status",
              operation_id="outreach.setProspectStatus")
async def set_prospect_status(
    pid: str, body: ProspectStatusBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    await _load_prospect(tenant_id, pid)
    if body.status not in _STATUSES:
        raise HTTPException(422, {"error": "invalid_status"})
    await db.outreach_prospects.update_one(
        {"id": pid, "tenant_id": tenant_id},
        {"$set": {"status": body.status,
                    "last_activity_at": now_iso(),
                    "updated_at": now_iso()}})
    return await _load_prospect(tenant_id, pid)


# ═════════════════════════ CSV bulk-import ══════════════════════════

@router.post("/outreach/prospects/bulk-import",
              operation_id="outreach.bulkImportProspects")
async def bulk_import_prospects(
    file: UploadFile = File(...),
    dry_run: bool = Query(False),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    try:
        raw = (await file.read()).decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(400, {"error": "invalid_file"})
    reader = csv.DictReader(io.StringIO(raw))
    created = 0
    updated = 0
    skipped = 0
    preview: List[Dict[str, Any]] = []
    for row in reader:
        domain = _normalize_domain(row.get("domain") or "")
        email = ((row.get("contact_email") or "").strip().lower()) or None
        if not domain:
            skipped += 1
            continue
        tags_raw = (row.get("tags") or "").strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        existing = await db.outreach_prospects.find_one(
            {"tenant_id": tenant_id, "domain": domain,
              "contact_email": email, "deleted_at": None},
            {"_id": 0, "id": 1})
        if existing:
            preview.append({"domain": domain, "email": email,
                              "action": "update"})
            if not dry_run:
                await db.outreach_prospects.update_one(
                    {"id": existing["id"]},
                    {"$set": {
                        "contact_name": row.get("contact_name") or None,
                        "contact_role": row.get("contact_role") or None,
                        "tags": tags,
                        "notes": row.get("notes") or "",
                        "updated_at": now_iso(),
                    }})
            updated += 1
        else:
            preview.append({"domain": domain, "email": email,
                              "action": "create"})
            if not dry_run:
                await db.outreach_prospects.insert_one({
                    "id": new_id(),
                    "tenant_id": tenant_id,
                    "created_by_user_id": caller["id"],
                    "created_at": now_iso(),
                    "domain": domain,
                    "contact_name": row.get("contact_name") or None,
                    "contact_email": email,
                    "contact_role": row.get("contact_role") or None,
                    "target_page_url": None,
                    "desired_anchor": None,
                    "our_page_url": None,
                    "tags": tags,
                    "notes": row.get("notes") or "",
                    "status": "pending",
                    "last_activity_at": None,
                    "next_followup_at": None,
                    "updated_at": now_iso(),
                    "deleted_at": None,
                })
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped,
             "dry_run": dry_run, "preview": preview[:20]}


# ═════════════════════════ Templates ════════════════════════════════

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class TemplateCreateBody(BaseModel):
    name: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    body_html: str = Field(..., min_length=1)
    body_text: Optional[str] = None


class TemplatePatchBody(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    archived: Optional[bool] = None


def _extract_variables(text: str) -> List[str]:
    return sorted(set(_VAR_RE.findall(text or "")))


@router.get("/outreach/templates", operation_id="outreach.listTemplates")
async def list_templates(
    include_archived: bool = Query(False),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if not include_archived:
        q["archived"] = {"$ne": True}
    items: List[Dict[str, Any]] = []
    async for r in db.outreach_templates.find(q, {"_id": 0}) \
                                            .sort("updated_at", -1):
        items.append(r)
    return {"items": items, "total": len(items)}


@router.post("/outreach/templates", operation_id="outreach.createTemplate")
async def create_template(body: TemplateCreateBody,
                             caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    now_ts = now_iso()
    variables = _extract_variables(
        (body.subject or "") + " " + (body.body_html or ""))
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "created_by_user_id": caller["id"],
        "name": body.name,
        "subject": body.subject,
        "body_html": body.body_html,
        "body_text": body.body_text,
        "variables": variables,
        "archived": False,
        "created_at": now_ts,
        "updated_at": now_ts,
    }
    await db.outreach_templates.insert_one({**doc})
    doc.pop("_id", None)
    return doc


@router.patch("/outreach/templates/{tid}",
               operation_id="outreach.patchTemplate")
async def patch_template(tid: str, body: TemplatePatchBody,
                            caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    row = await db.outreach_templates.find_one(
        {"id": tid, "tenant_id": tenant_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, {"error": "not_found"})
    updates: Dict[str, Any] = {}
    for f in ("name", "subject", "body_html", "body_text", "archived"):
        v = getattr(body, f)
        if v is not None:
            updates[f] = v
    if not updates:
        return row
    if "subject" in updates or "body_html" in updates:
        updates["variables"] = _extract_variables(
            (updates.get("subject", row.get("subject"))) + " "
            + (updates.get("body_html", row.get("body_html"))))
    updates["updated_at"] = now_iso()
    await db.outreach_templates.update_one(
        {"id": tid, "tenant_id": tenant_id}, {"$set": updates})
    fresh = await db.outreach_templates.find_one(
        {"id": tid, "tenant_id": tenant_id}, {"_id": 0})
    return fresh


@router.delete("/outreach/templates/{tid}",
                operation_id="outreach.deleteTemplate")
async def archive_template(tid: str,
                              caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    r = await db.outreach_templates.update_one(
        {"id": tid, "tenant_id": tenant_id},
        {"$set": {"archived": True, "updated_at": now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404, {"error": "not_found"})
    return {"archived": True, "id": tid}


# ═════════════════════════ Send flow ════════════════════════════════

class SendEmailBody(BaseModel):
    template_id: str
    override_subject: Optional[str] = None
    override_body_html: Optional[str] = None


def _render_variables(text: str, prospect: Dict[str, Any]) -> str:
    if not text:
        return ""
    values = {
        "contact_name": prospect.get("contact_name") or "there",
        "their_domain": prospect.get("domain") or "",
        "our_page_url": prospect.get("our_page_url") or "",
        "desired_anchor": prospect.get("desired_anchor") or "",
        "target_page_url": prospect.get("target_page_url") or "",
    }

    def _sub(m: re.Match) -> str:
        return str(values.get(m.group(1), m.group(0)))
    return _VAR_RE.sub(_sub, text)


@router.post("/outreach/prospects/{pid}/send",
              operation_id="outreach.sendProspect")
async def send_to_prospect(
    pid: str, body: SendEmailBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    prospect = await _load_prospect(tenant_id, pid)
    if not prospect.get("contact_email"):
        raise HTTPException(400, {"error": "no_contact_email"})

    tpl = await db.outreach_templates.find_one(
        {"id": body.template_id, "tenant_id": tenant_id}, {"_id": 0})
    if not tpl:
        raise HTTPException(404, {"error": "template_not_found"})

    subject_raw = body.override_subject or tpl["subject"]
    body_raw = body.override_body_html or tpl["body_html"]
    subject = _render_variables(subject_raw, prospect)
    html = _render_variables(body_raw, prospect)

    result = await send_email(
        tenant_id=tenant_id,
        to_email=prospect["contact_email"],
        subject=subject,
        html=html,
        from_name="Outreach")

    status = "sent" if result.get("status") == "sent" else "failed"
    msg_doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "prospect_id": pid,
        "template_id": tpl["id"],
        "sent_by_user_id": caller["id"],
        "subject_rendered": subject,
        "body_rendered": html,
        "to_email": prospect["contact_email"],
        "sent_at": now_iso(),
        "resend_id": result.get("provider_id"),
        "status": status,
        "error": result.get("error"),
    }
    await db.outreach_messages.insert_one({**msg_doc})
    msg_doc.pop("_id", None)

    # Auto-update prospect (unless in a terminal state).
    if prospect["status"] not in _TERMINAL_STATUSES:
        p_updates: Dict[str, Any] = {
            "last_activity_at": now_iso(),
            "updated_at": now_iso(),
        }
        if prospect["status"] == "pending":
            p_updates["status"] = "contacted"
        if not prospect.get("next_followup_at"):
            p_updates["next_followup_at"] = (
                (datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
        await db.outreach_prospects.update_one(
            {"id": pid, "tenant_id": tenant_id}, {"$set": p_updates})

    return {"message": msg_doc, "status": status,
             "error": result.get("error")}


@router.get("/outreach/prospects/{pid}/messages",
             operation_id="outreach.prospectMessages")
async def prospect_messages(pid: str,
                                caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    await _load_prospect(tenant_id, pid)
    items: List[Dict[str, Any]] = []
    async for m in db.outreach_messages.find(
            {"tenant_id": tenant_id, "prospect_id": pid},
            {"_id": 0}).sort("sent_at", -1).limit(200):
        items.append(m)
    return {"items": items, "total": len(items)}


# ═════════════════════════ Followups ════════════════════════════════

@router.get("/outreach/followups", operation_id="outreach.listFollowups")
async def list_followups(
    due_before: Optional[str] = Query(None),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    cutoff = due_before or now_iso()
    q = {
        "tenant_id": tenant_id,
        "deleted_at": None,
        "status": {"$in": ["contacted", "pending"]},
        "next_followup_at": {"$ne": None, "$lte": cutoff},
    }
    items: List[Dict[str, Any]] = []
    async for r in db.outreach_prospects.find(q, {"_id": 0}) \
                                            .sort("next_followup_at", 1):
        items.append(r)
    return {"items": items, "total": len(items),
             "due_before": cutoff}


# ═════════════════════════ Pipeline counts ═════════════════════════

@router.get("/outreach/pipeline", operation_id="outreach.pipelineCounts")
async def pipeline_counts(
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    base = {"tenant_id": tenant_id, "deleted_at": None}
    out: Dict[str, int] = {}
    total = 0
    for s in _STATUSES:
        n = await db.outreach_prospects.count_documents(
            {**base, "status": s})
        out[s] = n
        total += n
    out["total"] = total
    return out


# ═════════════════════════ Manual cron trigger ═════════════════════

@router.post("/outreach/cron/followup-digest",
              operation_id="outreach.runFollowupDigest")
async def run_followup_digest_manual(
    caller: Dict[str, Any] = Depends(get_current_user),
):
    """Admin-triggered same-effect version of the daily 08:00 UTC cron.
    Useful for smoke tests and one-off catch-ups."""
    _require_mod(caller)
    from services.outreach_followups import run_outreach_followup_digest
    result = await run_outreach_followup_digest(
        tenant_id=_tenant_or_400(caller))
    return result
