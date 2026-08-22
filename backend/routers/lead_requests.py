"""Phase 15B slot-in — Lead Request Distributor.

Admin generates a magic-link URL that a prospect fills out; the submission
creates a Lead document + notifies the admin in real time.
"""
import base64
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel, Field

from config import db, logger, APP_PUBLIC_URL, RESEND_API_KEY, EMAIL_FROM
from utils import now_iso, new_id, require_admin, get_current_user, send_sms
from routers.tenants import get_current_tenant

router = APIRouter()

MAX_FILES = 10
MAX_FILE_MB = 20


def _mk_token() -> str:
    return secrets.token_urlsafe(24)


def _public_url(token: str) -> str:
    base = (APP_PUBLIC_URL or "").rstrip("/")
    return f"{base}/lead-request/{token}"


async def _get_branding() -> dict:
    """Aggregate brand info from marketing.brand + settings.tenant_profile."""
    brand = await db.marketing_brand.find_one({"id": "singleton"}, {"_id": 0}) or {}
    tenant = await db.settings.find_one({"key": "tenant_profile"}, {"_id": 0}) or {}
    tp = tenant.get("value") or {}
    address_lines = []
    addr = brand.get("address") or tp.get("address")
    city = brand.get("city") or tp.get("city")
    state = brand.get("state") or tp.get("state")
    zipc = brand.get("zip") or tp.get("zip")
    if addr:
        address_lines.append(addr)
    csz = ", ".join(x for x in [city, state] if x)
    if csz or zipc:
        address_lines.append(f"{csz} {zipc or ''}".strip())
    return {
        "business_name": brand.get("business_name") or tp.get("business_name") or "Pool & Landscaping",
        "logo_url": brand.get("logo_url"),
        "address_lines": [l for l in address_lines if l],
        "phone": brand.get("phone") or tp.get("phone") or "",
        "email": brand.get("email") or tp.get("email") or "",
        "primary_color": brand.get("primary_color") or "#0284C7",
        "secondary_color": brand.get("secondary_color") or "#16A34A",
    }


def _sms_body(business_name: str, url: str, expiry_hours: int, custom: str = "") -> str:
    base = f"You have received a request from {business_name} at {url}\nPlease complete within {expiry_hours}hrs, thank you"
    if custom and custom.strip():
        return f"{custom.strip()}\n\n{base}"
    return base


async def _seed_lead_request_form() -> None:
    existing = await db.forms.find_one({"slug": "lead-request"}, {"_id": 0})
    if existing:
        return
    doc = {
        "id": new_id(),
        "slug": "lead-request",
        "title": "Customer Form",
        "status": "published",
        "target_destination": "leads",
        "fields": [
            {"key": "company_name", "label": "Company Name",   "type": "text",   "required": False},
            {"key": "first_name",   "label": "First Name",     "type": "text",   "required": True},
            {"key": "last_name",    "label": "Last Name",      "type": "text",   "required": True},
            {"key": "cell_phone",   "label": "Cell Phone",     "type": "phone",  "required": True},
            {"key": "email",        "label": "Email",          "type": "email",  "required": True},
            {"key": "address",      "label": "Service Location", "type": "text", "required": True},
            {"key": "city",         "label": "City",           "type": "text",   "required": True},
            {"key": "state",        "label": "State",          "type": "text",   "required": True},
            {"key": "zip",          "label": "Zip",            "type": "text",   "required": True},
            {"key": "budget",       "label": "Budget",         "type": "number", "required": False},
            {"key": "notes",        "label": "Notes / Questions for us", "type": "textarea", "required": True},
        ],
        "created_at": now_iso(),
    }
    await db.forms.insert_one(doc)


class GenerateIn(BaseModel):
    method: str = Field(..., pattern="^(link|sms|email)$")
    to: Optional[str] = None
    custom_message: Optional[str] = ""
    expiry_hours: Optional[int] = 48  # null = never expires


async def _send_email(to: str, url: str, business_name: str, expiry_hours: int, custom: str = "") -> bool:
    if not RESEND_API_KEY or not to:
        return False
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        html = ""
        if custom:
            html += f"<p>{custom}</p>"
        html += (
            f"<p>You have received a request from <b>{business_name}</b>.</p>"
            f"<p><a href='{url}' style='background:#0284C7;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;'>Complete request</a></p>"
            f"<p style='color:#64748B;font-size:12px;'>Please complete within {expiry_hours}hrs, thank you.</p>"
        )
        resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [to],
            "subject": f"Info request from {business_name}",
            "html": html,
        })
        return True
    except Exception as e:
        logger.warning(f"lead-request email failed: {e}")
        return False


# ─── Admin endpoints ────────────────────────────────────────────────────────
@router.post("/lead-requests/generate")
async def generate(body: GenerateIn,
                   admin: dict = Depends(require_admin),
                   tenant: dict = Depends(get_current_tenant)):
    branding = await _get_branding()
    token = _mk_token()
    now = datetime.now(timezone.utc)
    expires_at = None
    if body.expiry_hours:
        expires_at = (now + timedelta(hours=body.expiry_hours)).isoformat()

    dispatch = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "admin_id": admin["id"],
        "admin_name": admin.get("name") or admin.get("email"),
        "method": body.method,
        "to": (body.to or "").strip() or None,
        "custom_message": (body.custom_message or "").strip(),
        "generated_token": token,
        "url": _public_url(token),
        "sent_at": now_iso(),
        "expires_at": expires_at,
        "expiry_hours": body.expiry_hours,
        "opened_at": None,
        "submitted_at": None,
        "resulting_lead_id": None,
        "revoked": False,
        "created_at": now_iso(),
    }
    await db.lead_request_dispatches.insert_one(dispatch)
    dispatch.pop("_id", None)

    sent = False
    reason = None
    if body.method == "link":
        sent = True
    elif body.method == "sms":
        if not body.to:
            raise HTTPException(400, "Phone number required for SMS")
        body_txt = _sms_body(branding["business_name"], dispatch["url"], body.expiry_hours or 48, body.custom_message)
        try:
            ok = send_sms(body.to, body_txt)
            if ok:
                sent = True
            else:
                reason = "sms-not-configured"
        except Exception as e:
            logger.warning(f"lead-request SMS failed: {e}")
            reason = str(e)[:120]
    elif body.method == "email":
        if not body.to:
            raise HTTPException(400, "Email required for Email send")
        sent = await _send_email(body.to, dispatch["url"], branding["business_name"],
                                  body.expiry_hours or 48, body.custom_message)
        if not sent:
            reason = "resend-not-configured-or-failed"

    return {"ok": True, "sent": sent, "reason": reason,
            "url": dispatch["url"], "token": token, "dispatch": dispatch}


@router.get("/lead-requests")
async def list_dispatches(admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant),
                          method: Optional[str] = None,
                          status: Optional[str] = None):
    q: dict = {"tenant_id": tenant["id"]}
    if method and method != "all":
        q["method"] = method
    rows = await db.lead_request_dispatches.find(q, {"_id": 0}).sort("sent_at", -1).to_list(500)
    if status == "submitted":
        rows = [r for r in rows if r.get("submitted_at")]
    elif status == "opened":
        rows = [r for r in rows if r.get("opened_at") and not r.get("submitted_at")]
    elif status == "pending":
        rows = [r for r in rows if not r.get("opened_at") and not r.get("submitted_at") and not r.get("revoked")]
    return rows


@router.get("/lead-requests/{did}")
async def get_dispatch(did: str,
                       admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    d = await db.lead_request_dispatches.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not d:
        raise HTTPException(404, "Dispatch not found")
    lead = None
    if d.get("resulting_lead_id"):
        lead = await db.leads.find_one(
            {"id": d["resulting_lead_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        )
    return {"dispatch": d, "lead": lead}


@router.post("/lead-requests/{did}/revoke")
async def revoke(did: str,
                 admin: dict = Depends(require_admin),
                 tenant: dict = Depends(get_current_tenant)):
    r = await db.lead_request_dispatches.update_one(
        {"id": did, "tenant_id": tenant["id"]},
        {"$set": {"revoked": True, "revoked_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Dispatch not found")
    return {"ok": True}


@router.post("/lead-requests/{did}/resend")
async def resend(did: str,
                 admin: dict = Depends(require_admin),
                 tenant: dict = Depends(get_current_tenant)):
    d = await db.lead_request_dispatches.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not d:
        raise HTTPException(404, "Dispatch not found")
    if d.get("submitted_at"):
        raise HTTPException(400, "Already submitted — regenerate a new link instead")

    branding = await _get_branding()
    sent = False
    reason = None
    if d["method"] == "sms" and d.get("to"):
        try:
            ok = send_sms(d["to"], _sms_body(branding["business_name"], d["url"],
                                             d.get("expiry_hours") or 48, d.get("custom_message", "")))
            sent = bool(ok)
            if not sent:
                reason = "sms-not-configured"
        except Exception as e:
            reason = str(e)[:120]
    elif d["method"] == "email" and d.get("to"):
        sent = await _send_email(d["to"], d["url"], branding["business_name"],
                                  d.get("expiry_hours") or 48, d.get("custom_message", ""))
        if not sent:
            reason = "resend-not-configured-or-failed"
    else:
        sent = True

    await db.lead_request_dispatches.update_one(
        {"id": did, "tenant_id": tenant["id"]},
        {"$set": {"sent_at": now_iso()}},
    )
    return {"ok": True, "sent": sent, "reason": reason}


# ─── Public endpoints ───────────────────────────────────────────────────────
def _expired(d: dict) -> bool:
    exp = d.get("expires_at")
    if not exp:
        return False
    try:
        return datetime.now(timezone.utc) > datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except Exception:
        return False


@router.get("/public/lead-request/{token}")
async def public_get(token: str):
    d = await db.lead_request_dispatches.find_one({"generated_token": token}, {"_id": 0})
    if not d or d.get("revoked"):
        raise HTTPException(404, "This request link is no longer active.")
    if _expired(d):
        branding = await _get_branding()
        raise HTTPException(410, f"This request link has expired. Please contact us at {branding.get('phone') or branding.get('email') or 'the business directly'}.")
    if d.get("submitted_at"):
        raise HTTPException(410, "This request has already been submitted.")

    form = await db.forms.find_one({"slug": "lead-request"}, {"_id": 0}) or {}
    branding = await _get_branding()

    # Mark opened_at (first view only).
    if not d.get("opened_at"):
        await db.lead_request_dispatches.update_one({"id": d["id"]}, {"$set": {"opened_at": now_iso()}})

    return {
        "personal_message": d.get("custom_message") or "",
        "expires_at": d.get("expires_at"),
        "expiry_hours": d.get("expiry_hours"),
        "form": {
            "title": form.get("title", "Customer Form"),
            "fields": form.get("fields", []),
        },
        "branding": branding,
    }


async def _create_lead_from_payload(dispatch: dict, payload: dict, files_meta: list) -> str:
    lead_id = new_id()
    lead = {
        "id": lead_id,
        "tenant_id": dispatch.get("tenant_id"),
        "name": f"{(payload.get('first_name') or '').strip()} {(payload.get('last_name') or '').strip()}".strip() or (payload.get("company_name") or "Prospect"),
        "email": payload.get("email"),
        "phone": payload.get("cell_phone"),
        "address": payload.get("address"),
        "city": payload.get("city"),
        "state": payload.get("state"),
        "zip": payload.get("zip"),
        "budget": payload.get("budget"),
        "notes": payload.get("notes"),
        "company_name": payload.get("company_name"),
        "status": "new",
        "source": f"lead-request-{dispatch.get('method', 'link')}",
        "dispatched_by": dispatch.get("admin_id"),
        "dispatch_id": dispatch["id"],
        "attachments": files_meta,
        "created_at": now_iso(),
    }
    await db.leads.insert_one(lead)
    _create_lead_from_payload._last_created = {                 # type: ignore[attr-defined]
        "lead": lead, "tenant_id": dispatch.get("tenant_id"),
    }
    return lead_id


@router.post("/public/lead-request/{token}/submit")
async def public_submit(token: str, request: Request,
                          background_tasks: BackgroundTasks):
    """Multipart-friendly submit. Fields land in the form-data body plus
    optional `files` uploads (up to 10 x 20MB)."""
    d = await db.lead_request_dispatches.find_one({"generated_token": token}, {"_id": 0})
    if not d or d.get("revoked"):
        raise HTTPException(404, "This request link is no longer active.")
    if _expired(d):
        raise HTTPException(410, "This request link has expired.")
    if d.get("submitted_at"):
        raise HTTPException(410, "This request has already been submitted.")

    content_type = (request.headers.get("content-type") or "").lower()
    payload: dict = {}
    files_meta: list = []

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        for k, v in form.multi_items():
            if hasattr(v, "filename") and v.filename:
                data = await v.read()
                if len(data) > MAX_FILE_MB * 1024 * 1024:
                    raise HTTPException(400, f"File {v.filename} exceeds {MAX_FILE_MB}MB")
                b64 = base64.b64encode(data).decode()
                mt = v.content_type or "application/octet-stream"
                files_meta.append({
                    "name": v.filename,
                    "content_type": mt,
                    "size": len(data),
                    "data_url": f"data:{mt};base64,{b64}",
                })
            else:
                payload[k] = str(v)
        if len(files_meta) > MAX_FILES:
            raise HTTPException(400, f"Too many files (max {MAX_FILES})")
    else:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid request body")

    required = ["first_name", "last_name", "cell_phone", "email", "address", "city", "state", "zip", "notes"]
    missing = [k for k in required if not str(payload.get(k) or "").strip()]
    if missing:
        raise HTTPException(400, f"Missing required fields: {', '.join(missing)}")

    lead_id = await _create_lead_from_payload(d, payload, files_meta)
    # Feb-2026 · P18 — dispatch tenant-configured lead alerts.
    _created = getattr(_create_lead_from_payload, "_last_created", None)
    if _created and _created.get("lead", {}).get("id") == lead_id:
        try:
            tenant_doc = await db.tenants.find_one(
                {"id": _created["tenant_id"]}, {"_id": 0}) or {}
            from services.lead_notifications import send_lead_alert_notifications
            send_lead_alert_notifications(
                lead=_created["lead"], tenant=tenant_doc,
                background_tasks=background_tasks,
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"[p18] lead-request alert dispatch failed: {_e}")
        _create_lead_from_payload._last_created = None              # type: ignore[attr-defined]
    await db.lead_request_dispatches.update_one(
        {"id": d["id"]},
        {"$set": {"submitted_at": now_iso(), "resulting_lead_id": lead_id}}
    )
    try:
        await db.activity_log.insert_one({
            "id": new_id(),
            "tenant_id": d.get("tenant_id"),
            "kind": "lead_request_submitted",
            "dispatch_id": d["id"],
            "lead_id": lead_id,
            "method": d.get("method"),
            "created_at": now_iso(),
        })
    except Exception:
        pass
    # Realtime push to the dispatching admin.
    try:
        from routers.realtime import bus
        await bus.broadcast(d["admin_id"], {
            "type": "lead_request_submitted",
            "payload": {
                "dispatch_id": d["id"],
                "lead_id": lead_id,
                "method": d.get("method"),
                "prospect_name": payload.get("first_name", "") + " " + payload.get("last_name", ""),
            },
        })
    except Exception:
        pass

    return {"ok": True, "lead_id": lead_id}
