"""Communications Subsystem · Phase 1 — Admin API + delivery endpoints.

Prefix: ``/api/comms/``. All endpoints require an admin/super_admin
role unless explicitly noted (``opt-out POST`` is public, signed).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso, new_id
from routers.tenants import get_current_tenant

from services.comm_tokens import (
    AVAILABLE_TOKENS, extract_tokens, resolve_tokens, resolve_email_blocks,
    resolve_email_subject, render_email_html, render_sms_text,
    sample_tokens_context, build_context_for_customer,
)
from services.comms_email_adapter import send_email
from services.comms_sms_adapter import send_sms, sms_length_stats


router = APIRouter(prefix="/comms", tags=["Communications"])


# --- helpers -----------------------------------------------------------

def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


_ALLOWED_TRIGGERS = {
    "customer.created", "job.scheduled", "job.completed",
    "invoice.created", "invoice.paid", "invoice.overdue",
    "service_report.finalized", "onboarding.milestone",
    "customer.birthday", "customer.anniversary",
    "route.seasonal_open", "route.seasonal_close", "manual",
}
_ALLOWED_CHANNELS = {"email", "sms"}
_ALLOWED_BLOCK_TYPES = {
    "text", "heading", "image", "button", "divider", "spacer",
    "columns_2", "columns_3", "social", "video", "product_card", "footer",
}


def _validate_blocks_json(blocks: list) -> None:
    if not isinstance(blocks, list):
        raise HTTPException(422, "blocks_json must be a list")
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            raise HTTPException(422, f"block[{i}] is not an object")
        t = b.get("type")
        if t not in _ALLOWED_BLOCK_TYPES:
            raise HTTPException(422, f"block[{i}].type {t!r} not in allowed set")
        if not isinstance(b.get("props") or {}, dict):
            raise HTTPException(422, f"block[{i}].props must be an object")
        # Columns require a `children` shape of [[...], ...].
        if t in ("columns_2", "columns_3"):
            need = 2 if t == "columns_2" else 3
            ch = b.get("children")
            if not (isinstance(ch, list) and len(ch) == need and all(isinstance(c, list) for c in ch)):
                raise HTTPException(422, f"block[{i}] columns require exactly {need} child arrays")


def _load_company(tenant: dict) -> Dict[str, Any]:
    return {
        "name": tenant.get("name") or "",
        "phone": tenant.get("phone") or "",
        "email": tenant.get("email") or tenant.get("support_email") or "",
        "website": tenant.get("website") or "",
        "logo_url": tenant.get("logo_url") or "",
        "portal_link": tenant.get("portal_link") or tenant.get("portal_url") or "",
        "address": tenant.get("address") or "",
    }


def _clean_doc(d: dict) -> dict:
    out = dict(d or {})
    out.pop("_id", None)
    return out


def _sign_unsubscribe(tenant_id: str, contact: str, channel: str) -> str:
    secret = os.environ.get("JWT_SECRET") or "dev"
    payload = f"{tenant_id}|{contact}|{channel}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def _verify_unsubscribe(tenant_id: str, contact: str, channel: str, token: str) -> bool:
    return hmac.compare_digest(token, _sign_unsubscribe(tenant_id, contact, channel))


# --- Pydantic bodies ---------------------------------------------------

class EmailTemplateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = ""
    subject: str
    blocks_json: List[Dict[str, Any]]
    is_customer_facing: bool = True


class EmailTemplatePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    subject: Optional[str] = None
    blocks_json: Optional[List[Dict[str, Any]]] = None
    is_customer_facing: Optional[bool] = None


class SmsTemplateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=1600)
    mms_image_url: Optional[str] = None


class SmsTemplatePatch(BaseModel):
    name: Optional[str] = None
    body: Optional[str] = None
    mms_image_url: Optional[str] = None


class AutomationIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=120)
    name: str
    description: Optional[str] = ""
    trigger_event: str
    trigger_conditions: Optional[Dict[str, Any]] = None
    channel: str
    template_code: str
    send_delay_minutes: int = 0
    active: bool = True


class AutomationPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_conditions: Optional[Dict[str, Any]] = None
    send_delay_minutes: Optional[int] = None
    active: Optional[bool] = None


class PreviewIn(BaseModel):
    recipient_id: Optional[str] = None
    sample_data: Optional[Dict[str, Any]] = None


class SendNowIn(BaseModel):
    channel: str
    template_code: str
    recipient_ids: List[str] = Field(default_factory=list, max_length=500)
    schedule_at: Optional[str] = None


# --- shared query helpers ---------------------------------------------

async def _find_email_template(tenant_id: str, code: str) -> Optional[dict]:
    return await db.email_templates.find_one({
        "code": code,
        "$or": [{"tenant_id": tenant_id}, {"tenant_id": None, "is_system": True}],
    })


async def _find_sms_template(tenant_id: str, code: str) -> Optional[dict]:
    return await db.sms_templates.find_one({
        "code": code,
        "$or": [{"tenant_id": tenant_id}, {"tenant_id": None, "is_system": True}],
    })


async def _find_automation(tenant_id: str, code: str) -> Optional[dict]:
    return await db.automation_rules.find_one({
        "code": code,
        "$or": [{"tenant_id": tenant_id}, {"tenant_id": None, "is_system": True}],
    })


async def _load_customer(tenant_id: str, recipient_id: str) -> Optional[dict]:
    return await db.customers.find_one({"id": recipient_id, "tenant_id": tenant_id})


# --- Email template endpoints -----------------------------------------

@router.get("/email-templates")
async def list_email_templates(user: dict = Depends(_require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    q = {"$or": [{"tenant_id": tenant["id"]}, {"tenant_id": None, "is_system": True}]}
    rows = await db.email_templates.find(q).to_list(500)
    return [_clean_doc(r) for r in rows]


@router.get("/email-templates/{code}")
async def get_email_template(code: str,
                              user: dict = Depends(_require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    row = await _find_email_template(tenant["id"], code)
    if not row:
        raise HTTPException(404, "Not found")
    return _clean_doc(row)


@router.post("/email-templates", status_code=201)
async def create_email_template(body: EmailTemplateIn,
                                 user: dict = Depends(_require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    _validate_blocks_json(body.blocks_json)
    if body.code.startswith("system."):
        raise HTTPException(400, "'system.' prefix is reserved")
    existing = await db.email_templates.find_one(
        {"tenant_id": tenant["id"], "code": body.code})
    if existing:
        raise HTTPException(409, "template code already exists in tenant")
    doc = {
        "tenant_id": tenant["id"],
        "code": body.code,
        "name": body.name,
        "description": body.description or "",
        "subject": body.subject,
        "blocks_json": body.blocks_json,
        "is_system": False,
        "is_customer_facing": bool(body.is_customer_facing),
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        "updated_by": user["id"],
    }
    await db.email_templates.insert_one(doc)
    return _clean_doc(doc)


@router.patch("/email-templates/{code}")
async def patch_email_template(code: str, body: EmailTemplatePatch,
                                user: dict = Depends(_require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    existing = await db.email_templates.find_one({"tenant_id": tenant["id"], "code": code})
    if not existing:
        raise HTTPException(404, "Not found (only tenant-custom templates are editable)")
    updates: Dict[str, Any] = {}
    if body.name is not None: updates["name"] = body.name
    if body.description is not None: updates["description"] = body.description
    if body.subject is not None: updates["subject"] = body.subject
    if body.blocks_json is not None:
        _validate_blocks_json(body.blocks_json)
        updates["blocks_json"] = body.blocks_json
    if body.is_customer_facing is not None:
        updates["is_customer_facing"] = bool(body.is_customer_facing)
    if not updates:
        return _clean_doc(existing)
    updates["updated_at"] = now_iso()
    updates["updated_by"] = user["id"]
    updates["version"] = int(existing.get("version") or 1) + 1
    await db.email_templates.update_one({"_id": existing["_id"]}, {"$set": updates})
    return _clean_doc({**existing, **updates})


@router.delete("/email-templates/{code}", status_code=204)
async def delete_email_template(code: str,
                                 user: dict = Depends(_require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    existing = await db.email_templates.find_one({"tenant_id": tenant["id"], "code": code})
    if not existing:
        raise HTTPException(404, "Not found (system templates cannot be deleted)")
    await db.email_templates.delete_one({"_id": existing["_id"]})
    return None


@router.post("/email-templates/{code}/duplicate")
async def duplicate_email_template(code: str,
                                    user: dict = Depends(_require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    src = await _find_email_template(tenant["id"], code)
    if not src:
        raise HTTPException(404, "Not found")
    new_code = f"copy.{code}.{str(uuid.uuid4())[:8]}"
    doc = {
        "tenant_id": tenant["id"],
        "code": new_code,
        "name": f"{src.get('name') or code} (copy)",
        "description": src.get("description") or "",
        "subject": src.get("subject") or "",
        "blocks_json": src.get("blocks_json") or [],
        "is_system": False,
        "is_customer_facing": bool(src.get("is_customer_facing", True)),
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        "updated_by": user["id"],
    }
    await db.email_templates.insert_one(doc)
    return _clean_doc(doc)


@router.post("/email-templates/{code}/preview")
async def preview_email_template(code: str, body: PreviewIn,
                                  user: dict = Depends(_require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    tpl = await _find_email_template(tenant["id"], code)
    if not tpl:
        raise HTTPException(404, "Not found")
    # Build context: sample defaults, then customer overrides (if given),
    # then explicit sample_data overrides.
    ctx = sample_tokens_context()
    ctx.update({k: v for k, v in build_context_for_customer(
        {}, {}, {}, _load_company(tenant),
        unsubscribe_url=ctx.get("unsubscribe_url", "")).items() if v})
    if body.recipient_id:
        cust = await _load_customer(tenant["id"], body.recipient_id)
        if not cust:
            raise HTTPException(404, "recipient customer not found")
        contact = cust.get("email") or cust.get("phone") or ""
        unsub = f"{tenant.get('portal_link','')}/unsubscribe?token={_sign_unsubscribe(tenant['id'], contact, 'email')}"
        ctx.update(build_context_for_customer(cust, {}, {}, _load_company(tenant), unsub))
    if body.sample_data:
        ctx.update(body.sample_data)
    subject = resolve_email_subject(tpl.get("subject") or "", ctx)
    html = render_email_html(tpl.get("blocks_json") or [], ctx)
    return {
        "subject": subject,
        "html": html,
        "tokens_resolved": {k: v for k, v in ctx.items() if v},
    }


# --- SMS template endpoints --------------------------------------------

@router.get("/sms-templates")
async def list_sms_templates(user: dict = Depends(_require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    q = {"$or": [{"tenant_id": tenant["id"]}, {"tenant_id": None, "is_system": True}]}
    rows = await db.sms_templates.find(q).to_list(500)
    return [_clean_doc(r) for r in rows]


@router.get("/sms-templates/{code}")
async def get_sms_template(code: str,
                            user: dict = Depends(_require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await _find_sms_template(tenant["id"], code)
    if not row:
        raise HTTPException(404, "Not found")
    return _clean_doc(row)


@router.post("/sms-templates", status_code=201)
async def create_sms_template(body: SmsTemplateIn,
                               user: dict = Depends(_require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    if body.code.startswith("system."):
        raise HTTPException(400, "'system.' prefix is reserved")
    existing = await db.sms_templates.find_one({"tenant_id": tenant["id"], "code": body.code})
    if existing:
        raise HTTPException(409, "template code already exists in tenant")
    doc = {
        "tenant_id": tenant["id"],
        "code": body.code,
        "name": body.name,
        "body": body.body,
        "mms_image_url": body.mms_image_url,
        "tokens_referenced": extract_tokens(body.body),
        "is_system": False,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
    }
    await db.sms_templates.insert_one(doc)
    return _clean_doc(doc)


@router.patch("/sms-templates/{code}")
async def patch_sms_template(code: str, body: SmsTemplatePatch,
                              user: dict = Depends(_require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    existing = await db.sms_templates.find_one({"tenant_id": tenant["id"], "code": code})
    if not existing:
        raise HTTPException(404, "Not found")
    updates: Dict[str, Any] = {}
    if body.name is not None: updates["name"] = body.name
    if body.body is not None:
        updates["body"] = body.body
        updates["tokens_referenced"] = extract_tokens(body.body)
    if body.mms_image_url is not None: updates["mms_image_url"] = body.mms_image_url
    if not updates:
        return _clean_doc(existing)
    updates["updated_at"] = now_iso()
    updates["version"] = int(existing.get("version") or 1) + 1
    await db.sms_templates.update_one({"_id": existing["_id"]}, {"$set": updates})
    return _clean_doc({**existing, **updates})


@router.delete("/sms-templates/{code}", status_code=204)
async def delete_sms_template(code: str,
                               user: dict = Depends(_require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    existing = await db.sms_templates.find_one({"tenant_id": tenant["id"], "code": code})
    if not existing:
        raise HTTPException(404, "Not found (system templates cannot be deleted)")
    await db.sms_templates.delete_one({"_id": existing["_id"]})
    return None


@router.post("/sms-templates/{code}/duplicate")
async def duplicate_sms_template(code: str,
                                  user: dict = Depends(_require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    src = await _find_sms_template(tenant["id"], code)
    if not src:
        raise HTTPException(404, "Not found")
    new_code = f"copy.{code}.{str(uuid.uuid4())[:8]}"
    doc = {
        "tenant_id": tenant["id"],
        "code": new_code,
        "name": f"{src.get('name') or code} (copy)",
        "body": src.get("body") or "",
        "mms_image_url": src.get("mms_image_url"),
        "tokens_referenced": extract_tokens(src.get("body") or ""),
        "is_system": False,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
    }
    await db.sms_templates.insert_one(doc)
    return _clean_doc(doc)


@router.post("/sms-templates/{code}/preview")
async def preview_sms_template(code: str, body: PreviewIn,
                                user: dict = Depends(_require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    tpl = await _find_sms_template(tenant["id"], code)
    if not tpl:
        raise HTTPException(404, "Not found")
    ctx = sample_tokens_context()
    if body.recipient_id:
        cust = await _load_customer(tenant["id"], body.recipient_id)
        if not cust:
            raise HTTPException(404, "recipient customer not found")
        ctx.update(build_context_for_customer(cust, {}, {}, _load_company(tenant), ""))
    if body.sample_data:
        ctx.update(body.sample_data)
    rendered = render_sms_text(tpl.get("body") or "", ctx)
    return {
        "rendered_body": rendered,
        "tokens_resolved": {k: v for k, v in ctx.items() if v},
        **sms_length_stats(rendered),
    }


# --- Automation rule endpoints -----------------------------------------

@router.get("/automations")
async def list_automations(user: dict = Depends(_require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    q = {"$or": [{"tenant_id": tenant["id"]}, {"tenant_id": None, "is_system": True}]}
    rows = await db.automation_rules.find(q).to_list(500)
    return [_clean_doc(r) for r in rows]


@router.get("/automations/{code}")
async def get_automation(code: str,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    row = await _find_automation(tenant["id"], code)
    if not row:
        raise HTTPException(404, "Not found")
    return _clean_doc(row)


@router.post("/automations", status_code=201)
async def create_automation(body: AutomationIn,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    if body.trigger_event not in _ALLOWED_TRIGGERS:
        raise HTTPException(422, f"trigger_event must be one of {sorted(_ALLOWED_TRIGGERS)}")
    if body.channel not in _ALLOWED_CHANNELS:
        raise HTTPException(422, "channel must be 'email' or 'sms'")
    existing = await db.automation_rules.find_one({"tenant_id": tenant["id"], "code": body.code})
    if existing:
        raise HTTPException(409, "automation code already exists in tenant")
    doc = {
        "tenant_id": tenant["id"],
        "code": body.code,
        "name": body.name,
        "description": body.description or "",
        "trigger_event": body.trigger_event,
        "trigger_conditions": body.trigger_conditions or {},
        "channel": body.channel,
        "template_code": body.template_code,
        "send_delay_minutes": int(body.send_delay_minutes or 0),
        "active": bool(body.active),
        "is_system": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "last_fired_at": None,
        "fire_count": 0,
    }
    await db.automation_rules.insert_one(doc)
    try:
        from services.automation_engine import re_index_rules
        await re_index_rules(tenant["id"])
    except Exception as e:
        logger.warning(f"[comms] automation re-index failed after create: {e}")
    return _clean_doc(doc)


@router.patch("/automations/{code}")
async def patch_automation(code: str, body: AutomationPatch,
                            user: dict = Depends(_require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    existing = await db.automation_rules.find_one({"tenant_id": tenant["id"], "code": code})
    if not existing:
        raise HTTPException(404, "Not found (only tenant-custom automations are editable)")
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        return _clean_doc(existing)
    updates["updated_at"] = now_iso()
    await db.automation_rules.update_one({"_id": existing["_id"]}, {"$set": updates})
    try:
        from services.automation_engine import re_index_rules
        # System rules also carry `is_system=True` with tenant_id=None,
        # but PATCH only reaches tenant-custom docs, so tenant-scoped
        # re-index is sufficient. Re-run a full index if the toggle
        # flipped ``active`` on a system rule via a future endpoint.
        await re_index_rules(tenant["id"])
    except Exception as e:
        logger.warning(f"[comms] automation re-index failed after patch: {e}")
    return _clean_doc({**existing, **updates})


@router.delete("/automations/{code}", status_code=204)
async def delete_automation(code: str,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    existing = await db.automation_rules.find_one({"tenant_id": tenant["id"], "code": code})
    if not existing:
        raise HTTPException(404, "Not found (system automations cannot be deleted)")
    await db.automation_rules.delete_one({"_id": existing["_id"]})
    try:
        from services.automation_engine import re_index_rules
        await re_index_rules(tenant["id"])
    except Exception as e:
        logger.warning(f"[comms] automation re-index failed after delete: {e}")
    return None


@router.post("/automations/{code}/test-fire")
async def test_fire_automation(code: str, body: PreviewIn,
                                user: dict = Depends(_require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    rule = await _find_automation(tenant["id"], code)
    if not rule:
        raise HTTPException(404, "Not found")
    if not body.recipient_id:
        raise HTTPException(422, "recipient_id is required")
    cust = await _load_customer(tenant["id"], body.recipient_id)
    if not cust:
        raise HTTPException(404, "recipient customer not found")
    return await _deliver_one(
        tenant=tenant, user=user, customer=cust,
        channel=rule["channel"], template_code=rule["template_code"],
        automation_code=rule["code"],
    )


# --- QuoteIQ Phase Q3-B · AI Autopilot copy generator -----------------

AUTOPILOT_COPY_COST = 3
AUTOPILOT_HISTORY_MAX = 5


class GenerateCopyIn(BaseModel):
    """QuoteIQ Q3-B request body.

    Fields:
        channel: "email"|"sms" — override the rule's default channel (optional).
        tone: friendly|professional|urgent|casual — copy voice tone (default friendly).
        use_case: seasonal|invoice_followup|generic — steers scenario framing (default generic).
        brand_voice_snippet: short reference paragraph that pins voice/style.
        extra_context: any additional context (audience, offer, constraints).
    """
    channel: Optional[str] = Field(default=None, description="'email' or 'sms' — overrides the rule's channel when set.")
    tone: Optional[str] = Field(default="friendly", max_length=32, description="Voice tone: friendly | professional | urgent | casual.")
    use_case: Optional[str] = Field(default="generic", max_length=32, description="Scenario: seasonal | invoice_followup | generic.")
    brand_voice_snippet: Optional[str] = Field(default=None, max_length=2000, description="Short reference paragraph that pins voice / style.")
    extra_context: Optional[str] = Field(default="", max_length=2000, description="Extra context to steer the copy (audience, offer, constraints).")


@router.post("/automations/{code}/generate-copy")
async def generate_automation_copy(code: str, body: GenerateCopyIn,
                                     user: dict = Depends(_require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    """QuoteIQ Q3-B — generate AI copy suggestions for an automation
    rule. Debits ``AUTOPILOT_COPY_COST`` credits (feature=autopilot).
    Attaches the generated copy under ``ai_generated_copy`` on the rule
    — does NOT silently overwrite the linked template.

    Tenant-custom rules are updated in place (with a history entry
    prepended to ``ai_generated_history``, capped at ``AUTOPILOT_HISTORY_MAX``).
    System rules only get the copy in the response (a tenant would need
    to clone the rule first to persist the copy).
    """
    rule = await _find_automation(tenant["id"], code)
    if not rule:
        raise HTTPException(404, "automation not found")
    from services.autopilot_copy import generate_copy
    from services.ai_credits import debit_credits
    from services.ai.cap_http import raise_if_ai_cap_exceeded

    channel = (body.channel or rule.get("channel") or "email").lower().strip()
    if channel not in ("email", "sms"):
        raise HTTPException(422, "channel must be 'email' or 'sms'")

    debit = await debit_credits(
        tenant["id"], AUTOPILOT_COPY_COST, feature="autopilot",
        ref_id=rule.get("code") or (rule.get("_id") and str(rule["_id"])),
        ref_type="automation_rule",
        reason="autopilot_generate_copy", actor_user_id=user.get("id"),
    )
    copy = await generate_copy(
        trigger_event=str(rule.get("trigger_event") or ""),
        channel=channel,
        tone=(body.tone or "friendly"),
        use_case=(body.use_case or "generic"),
        brand_voice_snippet=(body.brand_voice_snippet or ""),
        company_name=(tenant.get("name") or "Your Service Team"),
        extra_context=(body.extra_context or ""),
        tenant_id=tenant["id"],
    )
    # Phase I1.7.e · chunk 2.c · Feb-2026 — surface tenant BYO AI
    # cap-exceeded as HTTP 429 before persisting the automation copy.
    raise_if_ai_cap_exceeded(copy)
    generated_at = now_iso()
    ai_copy_doc = {
        **{k: copy.get(k) for k in ("subject", "body_text", "body_sms")},
        "channel": channel,
        "tone": (body.tone or "friendly").lower(),
        "use_case": (body.use_case or "generic").lower(),
        "brand_voice_snippet": body.brand_voice_snippet or "",
        "extra_context": body.extra_context or "",
        "generated_at": generated_at,
        "generated_by": user.get("id"),
        "model": "claude-sonnet-4-5" if not copy.get("error") else "mock-fallback",
        "credits_debited": AUTOPILOT_COPY_COST,
        "error": copy.get("error"),
    }
    # Persist onto the rule doc so the UI can retrieve the last
    # suggestion — but only for tenant-custom rules. System rules stay
    # read-only; the copy is still returned in the response.
    persisted = False
    if rule.get("tenant_id") == tenant["id"]:
        # Prepend to history + keep last N.
        history = [ai_copy_doc] + list(rule.get("ai_generated_history") or [])
        history = history[:AUTOPILOT_HISTORY_MAX]
        await db.automation_rules.update_one(
            {"_id": rule["_id"]},
            {"$set": {"ai_generated_copy": ai_copy_doc,
                       "ai_generated_history": history,
                       "ai_generated_copy_at": generated_at,
                       "updated_at": generated_at}},
        )
        persisted = True
    fresh = await _find_automation(tenant["id"], code)
    return {
        "automation": _clean_doc(fresh),
        "ai_generated_copy": ai_copy_doc,
        "persisted": persisted,
        "credits_balance_after": debit.get("balance_after"),
        "credit_warning": bool(debit.get("warning")),
    }


# --- QuoteIQ Phase Q3-B · AI Autopilot planners -----------------------
#
# The planners draft a whole ladder of automation steps in one shot
# (seasonal open/close for a service, or an N-step invoice follow-up).
# Each drafted step debits ``AUTOPILOT_COPY_COST`` credits. Nothing is
# persisted at draft-time — the admin reviews the steps + calls the
# ``/approve`` endpoint to spawn real ``automation_rules`` (each with
# a freshly-created template).

SEASONAL_TRIGGERS = {
    "spring": "route.seasonal_open",
    "summer": "route.seasonal_open",
    "fall": "route.seasonal_close",
    "winter": "route.seasonal_close",
}
SEASONAL_STEP_OFFSETS_DAYS = [-14, 0, 7]  # heads-up · day-of · thank-you
INVOICE_FOLLOWUP_DEFAULT_DAYS = [7, 14, 30]


class SeasonalDraftIn(BaseModel):
    season: str = Field(..., description="spring | summer | fall | winter")
    service_types: List[str] = Field(default_factory=list,
                                        description="Optional list of service types this ladder targets.")
    channel: str = Field(default="email", description="'email' or 'sms'.")
    tone: str = Field(default="friendly")
    brand_voice_snippet: Optional[str] = None


class InvoiceFollowupDraftIn(BaseModel):
    days_ladder: List[int] = Field(default_factory=lambda: list(INVOICE_FOLLOWUP_DEFAULT_DAYS),
                                     description="Days-past-due for each follow-up step.")
    channel: str = Field(default="email")
    tone: str = Field(default="professional")
    brand_voice_snippet: Optional[str] = None


class ApproveStepIn(BaseModel):
    """Client-shaped step returned by a draft. Kept minimal — the
    approve endpoint re-hydrates the persistent doc."""
    code: str = Field(..., min_length=1, max_length=120)
    name: str
    description: Optional[str] = ""
    trigger_event: str
    channel: str
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_sms: Optional[str] = None
    send_delay_minutes: int = 0
    active: bool = True


class ApproveIn(BaseModel):
    steps: List[ApproveStepIn]


def _minutes_from_days(d: int) -> int:
    return int(max(0, d) * 24 * 60)


async def _draft_step(*, tenant: dict, code: str, name: str,
                        description: str, trigger_event: str, channel: str,
                        tone: str, use_case: str, brand_voice_snippet: str,
                        delay_days: int, extra_context: str) -> Dict[str, Any]:
    from services.autopilot_copy import generate_copy
    copy = await generate_copy(
        trigger_event=trigger_event, channel=channel, tone=tone,
        use_case=use_case, brand_voice_snippet=brand_voice_snippet or "",
        company_name=(tenant.get("name") or "Your Service Team"),
        extra_context=extra_context,
        tenant_id=tenant.get("id"),
    )
    return {
        "code": code, "name": name, "description": description,
        "trigger_event": trigger_event, "channel": channel,
        "subject": copy.get("subject"),
        "body_text": copy.get("body_text"),
        "body_sms": copy.get("body_sms"),
        "send_delay_minutes": _minutes_from_days(delay_days),
        "delay_days": delay_days,
        "active": True,
        "error": copy.get("error"),
        "cap_exceeded": bool(copy.get("cap_exceeded")),
    }


@router.post("/planners/seasonal/draft")
async def seasonal_draft(body: SeasonalDraftIn,
                           user: dict = Depends(_require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Draft a seasonal-open (or -close) ladder for one or more service
    types. Debits ``AUTOPILOT_COPY_COST`` credits per drafted step."""
    from services.ai_credits import debit_credits
    season = (body.season or "").lower()
    if season not in SEASONAL_TRIGGERS:
        raise HTTPException(422,
                              f"season must be one of {sorted(SEASONAL_TRIGGERS.keys())}")
    if body.channel not in _ALLOWED_CHANNELS:
        raise HTTPException(422, "channel must be 'email' or 'sms'")
    services = body.service_types or ["general"]
    steps: List[Dict[str, Any]] = []
    stamp = int(datetime.now(timezone.utc).timestamp())
    for svc in services:
        for offset in SEASONAL_STEP_OFFSETS_DAYS:
            label = ("heads_up" if offset < 0
                       else "day_of" if offset == 0
                       else "follow_up")
            code = f"ai_seasonal_{season}_{svc}_{label}_{stamp}"[:110]
            step = await _draft_step(
                tenant=tenant, code=code,
                name=f"{season.title()} {svc.replace('_', ' ').title()} · {label.replace('_', ' ')}",
                description=f"AI-drafted seasonal {season} step for {svc}.",
                trigger_event=SEASONAL_TRIGGERS[season],
                channel=body.channel,
                tone=body.tone, use_case="seasonal",
                brand_voice_snippet=body.brand_voice_snippet or "",
                delay_days=offset,
                extra_context=f"Season={season}. Service type={svc}. "
                                f"Offset from event={offset} days.",
            )
            steps.append(step)
    # Phase I1.7.e · chunk 2.c · Feb-2026 — if any drafted step hit
    # the tenant BYO AI monthly cap, surface HTTP 429 before we
    # debit credits. Later steps in the same tick will keep hitting
    # the cap too, so short-circuiting is safe.
    from services.ai.cap_http import raise_if_ai_cap_exceeded
    for _s in steps:
        raise_if_ai_cap_exceeded(_s)
    total = len(steps) * AUTOPILOT_COPY_COST
    debit = await debit_credits(
        tenant["id"], total, feature="autopilot",
        ref_id=f"seasonal_{season}_{stamp}",
        ref_type="autopilot_planner",
        reason="autopilot_seasonal_draft",
        actor_user_id=user.get("id"),
    )
    return {
        "planner": "seasonal", "season": season,
        "channel": body.channel, "tone": body.tone,
        "service_types": services, "steps": steps,
        "total_credits_debited": total,
        "credits_balance_after": debit.get("balance_after"),
        "credit_warning": bool(debit.get("warning")),
    }


@router.post("/planners/invoice-followup/draft")
async def invoice_followup_draft(body: InvoiceFollowupDraftIn,
                                    user: dict = Depends(_require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """Draft an N-step invoice follow-up ladder. Debits
    ``AUTOPILOT_COPY_COST`` credits per drafted step."""
    from services.ai_credits import debit_credits
    ladder = list(body.days_ladder or INVOICE_FOLLOWUP_DEFAULT_DAYS)
    ladder = [int(d) for d in ladder if isinstance(d, (int, float))]
    ladder = sorted({d for d in ladder if d >= 0})
    if not ladder:
        raise HTTPException(422, "days_ladder must contain at least one non-negative integer")
    if body.channel not in _ALLOWED_CHANNELS:
        raise HTTPException(422, "channel must be 'email' or 'sms'")
    steps: List[Dict[str, Any]] = []
    stamp = int(datetime.now(timezone.utc).timestamp())
    for d in ladder:
        code = f"ai_invoice_followup_d{d}_{stamp}"[:110]
        step = await _draft_step(
            tenant=tenant, code=code,
            name=f"Invoice follow-up · day {d}",
            description=f"AI-drafted invoice follow-up at day {d} past due.",
            trigger_event="invoice.overdue",
            channel=body.channel,
            tone=body.tone or "professional",
            use_case="invoice_followup",
            brand_voice_snippet=body.brand_voice_snippet or "",
            delay_days=d,
            extra_context=f"Days past due: {d}. Reference invoice.number "
                            "and provide a clear pay-now action.",
        )
        steps.append(step)
    # Phase I1.7.e · chunk 2.c · Feb-2026 — cap-exceeded → HTTP 429.
    from services.ai.cap_http import raise_if_ai_cap_exceeded
    for _s in steps:
        raise_if_ai_cap_exceeded(_s)
    total = len(steps) * AUTOPILOT_COPY_COST
    debit = await debit_credits(
        tenant["id"], total, feature="autopilot",
        ref_id=f"invoice_followup_{stamp}",
        ref_type="autopilot_planner",
        reason="autopilot_invoice_followup_draft",
        actor_user_id=user.get("id"),
    )
    return {
        "planner": "invoice_followup",
        "channel": body.channel, "tone": body.tone,
        "days_ladder": ladder, "steps": steps,
        "total_credits_debited": total,
        "credits_balance_after": debit.get("balance_after"),
        "credit_warning": bool(debit.get("warning")),
    }


async def _persist_step_as_rule(*, tenant: dict, user: dict,
                                  step: ApproveStepIn) -> Dict[str, Any]:
    """Create a template (email or sms) from the step's copy, then a
    rule pointing at it. Idempotent by rule code — re-approving with
    the same code overwrites the previously-created template."""
    if step.channel not in _ALLOWED_CHANNELS:
        raise HTTPException(422, f"step {step.code}: channel must be email or sms")
    if step.trigger_event not in _ALLOWED_TRIGGERS:
        raise HTTPException(422, f"step {step.code}: trigger_event {step.trigger_event!r} not allowed")
    tmpl_code = f"tpl_{step.code}"[:120]
    now = now_iso()
    if step.channel == "email":
        subject = step.subject or "Update from your service team"
        body_text = step.body_text or ""
        blocks = [
            {"type": "heading", "props": {"text": subject}},
            {"type": "text", "props": {"text": body_text}},
        ]
        tpl_doc = {
            "tenant_id": tenant["id"],
            "code": tmpl_code,
            "name": step.name or tmpl_code,
            "description": step.description or "",
            "subject": subject,
            "blocks_json": blocks,
            "is_system": False,
            "is_customer_facing": True,
            "version": 1,
            "created_at": now, "updated_at": now,
            "created_by": user["id"], "updated_by": user["id"],
        }
        await db.email_templates.update_one(
            {"tenant_id": tenant["id"], "code": tmpl_code},
            {"$set": tpl_doc}, upsert=True,
        )
    else:
        body = step.body_sms or step.body_text or ""
        tpl_doc = {
            "tenant_id": tenant["id"],
            "code": tmpl_code,
            "name": step.name or tmpl_code,
            "body": body,
            "mms_image_url": None,
            "is_system": False,
            "created_at": now, "updated_at": now,
            "created_by": user["id"], "updated_by": user["id"],
        }
        await db.sms_templates.update_one(
            {"tenant_id": tenant["id"], "code": tmpl_code},
            {"$set": tpl_doc}, upsert=True,
        )
    rule_doc = {
        "tenant_id": tenant["id"],
        "code": step.code,
        "name": step.name,
        "description": step.description or "",
        "trigger_event": step.trigger_event,
        "trigger_conditions": {},
        "channel": step.channel,
        "template_code": tmpl_code,
        "send_delay_minutes": int(max(0, step.send_delay_minutes or 0)),
        "active": bool(step.active),
        "is_system": False,
        "source": "ai_planner",
        "created_at": now, "updated_at": now,
        "last_fired_at": None, "fire_count": 0,
    }
    await db.automation_rules.update_one(
        {"tenant_id": tenant["id"], "code": step.code},
        {"$set": rule_doc}, upsert=True,
    )
    return {"code": step.code, "template_code": tmpl_code}


async def _finalize_approval(tenant_id: str) -> None:
    try:
        from services.automation_engine import re_index_rules
        await re_index_rules(tenant_id)
    except Exception as e:
        logger.warning(f"[comms] automation re-index failed after planner approve: {e}")


@router.post("/planners/seasonal/approve", status_code=201)
async def seasonal_approve(body: ApproveIn,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    if not body.steps:
        raise HTTPException(422, "no steps to approve")
    created = [await _persist_step_as_rule(tenant=tenant, user=user, step=s)
                for s in body.steps]
    await _finalize_approval(tenant["id"])
    return {"created": created, "count": len(created)}


@router.post("/planners/invoice-followup/approve", status_code=201)
async def invoice_followup_approve(body: ApproveIn,
                                      user: dict = Depends(_require_admin),
                                      tenant: dict = Depends(get_current_tenant)):
    if not body.steps:
        raise HTTPException(422, "no steps to approve")
    created = [await _persist_step_as_rule(tenant=tenant, user=user, step=s)
                for s in body.steps]
    await _finalize_approval(tenant["id"])
    return {"created": created, "count": len(created)}


# --- Send-now + sends log endpoints ------------------------------------

async def deliver_one_by_ids(*, tenant_id: str, template_code: str,
                              channel: str, recipient_id: str,
                              extras: Optional[Dict[str, Any]] = None,
                              automation_code: Optional[str] = None
                              ) -> Optional[Dict[str, Any]]:
    """Phase 3 · automation-engine entry point.

    Same delivery mechanics as ``_deliver_one`` but callable purely by
    IDs — the engine has no ``tenant``/``user`` dict on hand when a
    domain event fires. Returns the ``communication_sends`` row on
    success, ``None`` if the recipient/template is missing. Never
    raises: dispatch failures land in the send row as ``status="failed"``.
    """
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        return None
    customer = await _load_customer(tenant_id, recipient_id)
    if not customer:
        return None
    company = _load_company(tenant)
    extras = extras or {}

    if channel == "email":
        tpl = await _find_email_template(tenant_id, template_code)
        if not tpl:
            return None
        contact = customer.get("email") or ""
        unsub_token = _sign_unsubscribe(tenant_id, contact, "email") if contact else ""
        unsub_url = f"{company.get('portal_link','')}/unsubscribe?token={unsub_token}&e={contact}" if contact else ""
        ctx = sample_tokens_context()
        ctx.update(build_context_for_customer(
            customer, extras.get("job") or {}, extras.get("invoice") or {},
            company, unsub_url, extras=extras,
        ))
        subject = resolve_email_subject(tpl.get("subject") or "", ctx)
        html = render_email_html(tpl.get("blocks_json") or [], ctx)
        try:
            deliver = await send_email(tenant_id, contact, subject, html,
                                         from_name=company.get("name") or None)
        except Exception as e:
            deliver = {"status": "failed", "provider_id": None, "error": str(e)[:400]}
        doc = {
            "id": new_id(), "tenant_id": tenant_id, "kind": "email",
            "template_code": template_code, "automation_code": automation_code,
            "recipient_id": customer.get("id"),
            "recipient_email": contact, "recipient_phone": None,
            "subject": subject, "rendered_body": html,
            "tokens_resolved": {k: v for k, v in ctx.items() if v},
            "status": deliver.get("status"),
            "provider_message_id": deliver.get("provider_id"),
            "error": deliver.get("error"),
            "queued_at": now_iso(),
            "sent_at": now_iso() if deliver.get("status") in ("sent", "mocked") else None,
            "retry_count": 0,
        }
        await db.communication_sends.insert_one(doc)
        return _clean_doc(doc)

    if channel == "sms":
        tpl = await _find_sms_template(tenant_id, template_code)
        if not tpl:
            return None
        contact = customer.get("phone") or ""
        ctx = sample_tokens_context()
        ctx.update(build_context_for_customer(
            customer, extras.get("job") or {}, extras.get("invoice") or {},
            company, "", extras=extras,
        ))
        rendered = render_sms_text(tpl.get("body") or "", ctx)
        try:
            deliver = await send_sms(tenant_id, contact, rendered,
                                       mms_url=tpl.get("mms_image_url"))
        except Exception as e:
            deliver = {"status": "failed", "provider_id": None, "error": str(e)[:400]}
        doc = {
            "id": new_id(), "tenant_id": tenant_id, "kind": "sms",
            "template_code": template_code, "automation_code": automation_code,
            "recipient_id": customer.get("id"),
            "recipient_email": None, "recipient_phone": contact,
            "subject": None, "rendered_body": rendered,
            "tokens_resolved": {k: v for k, v in ctx.items() if v},
            "status": deliver.get("status"),
            "provider_message_id": deliver.get("provider_id"),
            "error": deliver.get("error"),
            "character_count": deliver.get("character_count"),
            "segment_count": deliver.get("segment_count"),
            "queued_at": now_iso(),
            "sent_at": now_iso() if deliver.get("status") in ("sent", "mocked") else None,
            "retry_count": 0,
        }
        await db.communication_sends.insert_one(doc)
        return _clean_doc(doc)

    return None


async def _deliver_one(*, tenant: dict, user: dict, customer: dict,
                        channel: str, template_code: str,
                        automation_code: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = tenant["id"]
    company = _load_company(tenant)
    if channel == "email":
        tpl = await _find_email_template(tenant_id, template_code)
        if not tpl:
            raise HTTPException(404, f"email template {template_code!r} not found")
        contact = customer.get("email") or ""
        unsub_token = _sign_unsubscribe(tenant_id, contact, "email") if contact else ""
        unsub_url = f"{company.get('portal_link','')}/unsubscribe?token={unsub_token}&e={contact}"
        ctx = sample_tokens_context()
        ctx.update(build_context_for_customer(customer, {}, {}, company, unsub_url))
        subject = resolve_email_subject(tpl.get("subject") or "", ctx)
        html = render_email_html(tpl.get("blocks_json") or [], ctx)
        deliver = await send_email(tenant_id, contact, subject, html,
                                     from_name=company.get("name") or None)
        # Phase I1.7.e · chunk 1 · Feb-2026 — transactional cap-exceeded
        # semantic: persist the audit row THEN 429 the caller. This
        # endpoint is a synchronous admin-triggered send, so surfacing
        # the tenant's monthly cap as an HTTP 429 is the correct signal.
        doc = {
            "id": new_id(), "tenant_id": tenant_id, "kind": "email",
            "template_code": template_code, "automation_code": automation_code,
            "recipient_id": customer.get("id"),
            "recipient_email": contact, "recipient_phone": None,
            "subject": subject, "rendered_body": html,
            "tokens_resolved": {k: v for k, v in ctx.items() if v},
            "status": deliver["status"],
            "provider_message_id": deliver.get("provider_id"),
            "error": deliver.get("error"),
            "queued_at": now_iso(),
            "sent_at": now_iso() if deliver["status"] in ("sent", "mocked") else None,
            "retry_count": 0,
        }
        await db.communication_sends.insert_one(doc)
        from services.messaging.byo_passthrough import raise_if_cap_exceeded
        raise_if_cap_exceeded(
            deliver,
            detail=(f"Monthly messaging cap exceeded for tenant {tenant_id} "
                    f"(channel=email, template={template_code})"),
        )
        return _clean_doc(doc)
    elif channel == "sms":
        tpl = await _find_sms_template(tenant_id, template_code)
        if not tpl:
            raise HTTPException(404, f"sms template {template_code!r} not found")
        contact = customer.get("phone") or ""
        ctx = sample_tokens_context()
        ctx.update(build_context_for_customer(customer, {}, {}, company, ""))
        rendered = render_sms_text(tpl.get("body") or "", ctx)
        deliver = await send_sms(tenant_id, contact, rendered,
                                   mms_url=tpl.get("mms_image_url"))
        doc = {
            "id": new_id(), "tenant_id": tenant_id, "kind": "sms",
            "template_code": template_code, "automation_code": automation_code,
            "recipient_id": customer.get("id"),
            "recipient_email": None, "recipient_phone": contact,
            "subject": None, "rendered_body": rendered,
            "tokens_resolved": {k: v for k, v in ctx.items() if v},
            "status": deliver["status"],
            "provider_message_id": deliver.get("provider_id"),
            "error": deliver.get("error"),
            "character_count": deliver.get("character_count"),
            "segment_count": deliver.get("segment_count"),
            "queued_at": now_iso(),
            "sent_at": now_iso() if deliver["status"] in ("sent", "mocked") else None,
            "retry_count": 0,
        }
        await db.communication_sends.insert_one(doc)
        # Phase I1.7.e · chunk 1 · Feb-2026 — transactional cap-exceeded
        # semantic: persist the audit row THEN 429 the caller. Mirrors
        # the email branch above.
        from services.messaging.byo_passthrough import raise_if_cap_exceeded
        raise_if_cap_exceeded(
            deliver,
            detail=(f"Monthly messaging cap exceeded for tenant {tenant_id} "
                    f"(channel=sms, template={template_code})"),
        )
        return _clean_doc(doc)
    else:
        raise HTTPException(422, "channel must be 'email' or 'sms'")


@router.post("/send-now")
async def send_now(body: SendNowIn,
                    user: dict = Depends(_require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    if body.channel not in _ALLOWED_CHANNELS:
        raise HTTPException(422, "channel must be 'email' or 'sms'")
    if not body.recipient_ids:
        raise HTTPException(422, "recipient_ids required")
    results = []
    for rid in body.recipient_ids:
        cust = await _load_customer(tenant["id"], rid)
        if not cust:
            results.append({"recipient_id": rid, "status": "failed",
                              "error": "recipient not found"})
            continue
        res = await _deliver_one(
            tenant=tenant, user=user, customer=cust,
            channel=body.channel, template_code=body.template_code,
            automation_code=None,
        )
        results.append({"recipient_id": rid, "status": res.get("status"),
                          "send_id": res.get("id")})
    return {"results": results, "count": len(results)}


@router.get("/sends")
async def list_sends(user: dict = Depends(_require_admin),
                      tenant: dict = Depends(get_current_tenant),
                      kind: Optional[str] = Query(None),
                      status: Optional[str] = Query(None),
                      recipient_id: Optional[str] = Query(None),
                      limit: int = Query(50, ge=1, le=500)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if kind: q["kind"] = kind
    if status: q["status"] = status
    if recipient_id: q["recipient_id"] = recipient_id
    rows = await db.communication_sends.find(q).sort("queued_at", -1).to_list(limit)
    return [_clean_doc(r) for r in rows]


@router.get("/sends/{send_id}")
async def get_send(send_id: str,
                    user: dict = Depends(_require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    row = await db.communication_sends.find_one(
        {"id": send_id, "tenant_id": tenant["id"]})
    if not row:
        raise HTTPException(404, "Not found")
    return _clean_doc(row)


# --- Automation events (Phase 3) --------------------------------------

@router.get("/automation-events")
async def list_automation_events(user: dict = Depends(_require_admin),
                                   tenant: dict = Depends(get_current_tenant),
                                   automation_code: Optional[str] = Query(None),
                                   trigger_event: Optional[str] = Query(None),
                                   status: Optional[str] = Query(None),
                                   since: Optional[str] = Query(
                                       None, description="ISO timestamp; "
                                       "returns rows fired at or after this instant"),
                                   limit: int = Query(100, ge=1, le=500)):
    """Phase 3 · engine journal. Returns dispatch events with rule +
    outcome so admins can audit exactly which triggers fired and why
    others were skipped (dedup / conditions / no-customer)."""
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if automation_code:
        q["automation_code"] = automation_code
    if trigger_event:
        q["trigger_event"] = trigger_event
    if status:
        q["status"] = status
    if since:
        q["fired_at"] = {"$gte": since}
    rows = await (db.automation_engine_events
                    .find(q, {"_id": 0, "fired_at_dt": 0})
                    .sort("fired_at", -1)
                    .to_list(limit))
    return {"count": len(rows), "events": rows}


# --- Tokens catalog ----------------------------------------------------

@router.get("/tokens")
async def list_tokens(user: dict = Depends(_require_admin)):
    """Return the flat token catalog with sample resolved values."""
    return {
        "count": len(AVAILABLE_TOKENS),
        "tokens": [{"name": k, **v} for k, v in AVAILABLE_TOKENS.items()],
        "sample_context": sample_tokens_context(),
    }


# --- Opt-out endpoints -------------------------------------------------

class OptOutIn(BaseModel):
    tenant_id: str
    channel: str  # 'email' | 'sms'
    contact: str  # email address or phone number
    token: str    # signed unsubscribe token


@router.post("/opt-out")
async def opt_out(body: OptOutIn):
    """Public endpoint — verified via signed unsubscribe token."""
    if body.channel not in _ALLOWED_CHANNELS:
        raise HTTPException(422, "channel must be 'email' or 'sms'")
    if not _verify_unsubscribe(body.tenant_id, body.contact, body.channel, body.token):
        raise HTTPException(403, "invalid unsubscribe token")
    doc: Dict[str, Any] = {
        "tenant_id": body.tenant_id,
        "channel": body.channel,
        "opted_out_at": now_iso(),
    }
    if body.channel == "email":
        doc["contact_email"] = body.contact.lower()
    else:
        doc["contact_phone"] = body.contact
    # Upsert to keep index-unique constraint happy on repeated opt-outs.
    key = {k: v for k, v in doc.items() if k in
             ("tenant_id", "contact_email", "contact_phone", "channel")}
    await db.communication_opt_outs.update_one(key, {"$set": doc}, upsert=True)
    return {"ok": True}


@router.get("/opt-outs")
async def list_opt_outs(user: dict = Depends(_require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    rows = await db.communication_opt_outs.find({"tenant_id": tenant["id"]}).to_list(500)
    return [_clean_doc(r) for r in rows]
