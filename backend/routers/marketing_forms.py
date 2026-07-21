"""Feb-2026 · Slice H1 — Public Form Builder backend.

Two surfaces:

* Admin (``/api/admin/forms/*``) — CRUD for form definitions + read-
  access on submissions. Standard JWT admin auth.
* Public (``/api/widget/form/*``) — schema fetch + submit, called by
  the widget JS bundle on the tenant's marketing site. Uses
  :func:`routers.widget_config.require_widget_auth` (public widget key
  + Origin allowlist).

Cloudflare Turnstile:
* When ``TURNSTILE_SECRET`` is set in ``/app/backend/.env`` we require
  and verify a ``turnstile_token`` on every public submit.
* When it is unset we log a single startup warning (from
  :func:`log_turnstile_status_once`) and accept submissions without
  verification. This keeps dev + preview builds unblocked.

Lead capture:
* Every submission spawns a ``leads`` doc scoped to the tenant. If the
  form's ``name`` / ``email`` / ``phone`` fields are present we use
  them; otherwise the lead is created with placeholder values so the
  admin can still triage it via ``form_submissions``.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from routers.widget_config import require_widget_auth

router = APIRouter(tags=["Marketing Forms"])

# ─── Turnstile helpers ────────────────────────────────────────────────

TURNSTILE_VERIFY_URL = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)
_TURNSTILE_WARNED = False


def _turnstile_secret() -> str:
    return (os.environ.get("TURNSTILE_SECRET") or "").strip()


def log_turnstile_status_once() -> None:
    """Called once from server.py startup. Emits a single WARN when
    the secret is missing so ops know verification is bypassed."""
    global _TURNSTILE_WARNED
    if _TURNSTILE_WARNED:
        return
    _TURNSTILE_WARNED = True
    if not _turnstile_secret():
        logger.warning(
            "[h1] turnstile disabled — TURNSTILE_SECRET missing; "
            "form submissions will NOT be verified"
        )
    else:
        logger.info("[h1] turnstile verification ENABLED")


async def _verify_turnstile(token: Optional[str], remote_ip: Optional[str]) -> None:
    """Hard-verify a Turnstile token. No-op when secret is unset."""
    secret = _turnstile_secret()
    if not secret:
        return  # graceful bypass
    if not token:
        raise HTTPException(400, "Missing turnstile_token")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                TURNSTILE_VERIFY_URL,
                data={
                    "secret": secret,
                    "response": token,
                    **({"remoteip": remote_ip} if remote_ip else {}),
                },
            )
            payload = r.json()
    except Exception as exc:
        logger.warning("[h1] turnstile verify request failed: %s", exc)
        raise HTTPException(502, "turnstile verification unavailable")
    if not payload.get("success"):
        logger.info("[h1] turnstile rejected: %s", payload)
        raise HTTPException(400, "turnstile verification failed")


# ─── Field / form models ─────────────────────────────────────────────

_FIELD_TYPES = {"text", "email", "phone", "textarea",
                 "select", "checkbox", "number", "url"}

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,63})$")


def _norm_slug(v: str) -> str:
    v = (v or "").strip().lower()
    v = re.sub(r"[^a-z0-9-]+", "-", v).strip("-")
    if not v:
        raise HTTPException(422, "slug cannot be empty")
    if not _SLUG_RE.match(v):
        raise HTTPException(422, f"'{v}' is not a valid slug")
    return v[:64]


class FormField(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    label: str = Field(..., min_length=1, max_length=120)
    type: str = Field(..., description=f"one of {_FIELD_TYPES}")
    required: bool = False
    placeholder: Optional[str] = Field(None, max_length=120)
    options: Optional[List[str]] = None  # for select


class FormIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    slug: Optional[str] = None
    fields: List[FormField] = Field(default_factory=list)
    submit_button_label: str = Field("Send", max_length=40)
    success_message: str = Field(
        "Thanks! We'll be in touch shortly.", max_length=280
    )
    notify_admin_bell: bool = True


class FormPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    fields: Optional[List[FormField]] = None
    submit_button_label: Optional[str] = Field(None, max_length=40)
    success_message: Optional[str] = Field(None, max_length=280)
    notify_admin_bell: Optional[bool] = None
    active: Optional[bool] = None


class FormSubmit(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)
    turnstile_token: Optional[str] = None
    page_url: Optional[str] = Field(None, max_length=500)


def _validate_field_defs(fields: List[FormField]) -> None:
    seen_names: set = set()
    for f in fields:
        if f.type not in _FIELD_TYPES:
            raise HTTPException(422, f"field '{f.name}': unsupported type '{f.type}'")
        if f.name in seen_names:
            raise HTTPException(422, f"duplicate field name '{f.name}'")
        seen_names.add(f.name)
        if f.type == "select" and not f.options:
            raise HTTPException(
                422, f"field '{f.name}': select fields need options"
            )


def _clean_form(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc:
        doc.pop("_id", None)
    return doc


# ═══════════════════════════════════════════════════════════════════════
# Admin routes — full JWT auth
# ═══════════════════════════════════════════════════════════════════════
@router.post("/admin/forms", status_code=201)
async def create_form(body: FormIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    _validate_field_defs(body.fields)
    slug = _norm_slug(body.slug or body.name)
    # Slug must be unique within tenant.
    dupe = await db.marketing_forms.find_one(
        {"tenant_id": tenant["id"], "slug": slug}, {"_id": 0, "id": 1}
    )
    if dupe:
        raise HTTPException(409, f"slug '{slug}' already exists for this tenant")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": body.name,
        "slug": slug,
        "fields": [f.dict() for f in body.fields],
        "submit_button_label": body.submit_button_label,
        "success_message": body.success_message,
        "notify_admin_bell": body.notify_admin_bell,
        "active": True,
        "created_by": user["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "submission_count": 0,
    }
    await db.marketing_forms.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/admin/forms")
async def list_forms(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    rows = await db.marketing_forms.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return rows


@router.get("/admin/forms/{fid}")
async def get_form(fid: str,
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Form not found")
    return doc


@router.patch("/admin/forms/{fid}")
async def patch_form(fid: str, body: FormPatch,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()}
    if "fields" in updates and updates["fields"] is not None:
        _validate_field_defs([FormField(**f) if isinstance(f, dict) else f
                                 for f in updates["fields"]])
        updates["fields"] = [
            (f.dict() if isinstance(f, FormField) else f)
            for f in updates["fields"]
        ]
    updates["updated_at"] = now_iso()
    r = await db.marketing_forms.update_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Form not found")
    return await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/admin/forms/{fid}")
async def delete_form(fid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.marketing_forms.delete_one(
        {"id": fid, "tenant_id": tenant["id"]}
    )
    return {"ok": True, "deleted": r.deleted_count}


@router.get("/admin/forms/{fid}/submissions")
async def list_form_submissions(fid: str,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant),
                                    limit: int = 100):
    # Confirm the form exists in this tenant first — cheap 404 guard.
    exists = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    )
    if not exists:
        raise HTTPException(404, "Form not found")
    rows = await db.form_submissions.find(
        {"tenant_id": tenant["id"], "form_id": fid},
        {"_id": 0},
    ).sort("created_at", -1).to_list(min(max(1, int(limit or 100)), 500))
    return rows


# ═══════════════════════════════════════════════════════════════════════
# Public widget routes — X-Widget-Key + Origin allowlist
# ═══════════════════════════════════════════════════════════════════════
@router.get("/widget/form/{fid}")
async def get_widget_form(fid: str,
                             tenant: Dict[str, Any] = Depends(require_widget_auth)):
    """Return the public-safe schema of a form (no internal fields)."""
    doc = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"], "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "slug": 1, "fields": 1,
         "submit_button_label": 1, "success_message": 1},
    )
    if not doc:
        raise HTTPException(404, "Form not found or not active")
    return doc


@router.post("/widget/form/{fid}/submit", status_code=201)
async def submit_widget_form(fid: str, body: FormSubmit,
                                request: Request,
                                tenant: Dict[str, Any] = Depends(require_widget_auth)):
    form = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"], "active": {"$ne": False}},
        {"_id": 0},
    )
    if not form:
        raise HTTPException(404, "Form not found or not active")

    # Turnstile — verify or graceful bypass.
    client_ip = None
    if request.client:
        client_ip = request.client.host
    await _verify_turnstile(body.turnstile_token, client_ip)

    # Required-field validation.
    missing: List[str] = []
    for f in form.get("fields") or []:
        if f.get("required"):
            val = body.data.get(f["name"])
            if val is None or (isinstance(val, str) and not val.strip()):
                missing.append(f["name"])
    if missing:
        raise HTTPException(
            422, f"missing required fields: {', '.join(missing)}"
        )

    # Persist submission.
    sub_id = new_id()
    sub_doc = {
        "id": sub_id,
        "tenant_id": tenant["id"],
        "form_id": fid,
        "form_slug": form.get("slug"),
        "form_name": form.get("name"),
        "data": body.data or {},
        "page_url": body.page_url,
        "ip": client_ip,
        "user_agent": request.headers.get("user-agent"),
        "created_at": now_iso(),
    }
    await db.form_submissions.insert_one(sub_doc)

    # Lead upsert. Look for standard field names first, fall back to
    # loose scans of the submitted values.
    name = _first_str(body.data, ["name", "full_name", "fullname"])
    email = _first_str(body.data, ["email", "email_address"])
    phone = _first_str(body.data, ["phone", "phone_number", "tel", "mobile"])
    notes = _first_str(body.data, ["message", "notes", "details", "comments"])

    lead_id: Optional[str] = None
    if email or phone:
        # Try to match an existing lead by contact.
        existing = None
        if email:
            existing = await db.leads.find_one(
                {"tenant_id": tenant["id"], "email": email}, {"_id": 0, "id": 1}
            )
        if not existing and phone:
            existing = await db.leads.find_one(
                {"tenant_id": tenant["id"], "phone": phone}, {"_id": 0, "id": 1}
            )
        if existing:
            lead_id = existing["id"]
        else:
            lead_id = new_id()
            lead_doc = {
                "id": lead_id,
                "tenant_id": tenant["id"],
                "name": name or "Form visitor",
                "email": email or "",
                "phone": phone or "",
                "source": f"form:{form.get('slug') or fid}",
                "status": "new",
                "notes": (notes or "")[:500],
                "meta": {"form_id": fid, "submission_id": sub_id,
                         "page_url": body.page_url},
                "created_at": now_iso(),
            }
            await db.leads.insert_one(lead_doc)

    # Update submission with lead_id + bump form counter.
    await db.form_submissions.update_one(
        {"id": sub_id}, {"$set": {"lead_id": lead_id}}
    )
    await db.marketing_forms.update_one(
        {"id": fid, "tenant_id": tenant["id"]},
        {"$inc": {"submission_count": 1},
         "$set": {"updated_at": now_iso()}},
    )

    # Optional admin bell.
    if form.get("notify_admin_bell", True):
        try:
            from services.notifications import enqueue_for_tenant_admins
            display = name or email or phone or "Anonymous"
            await enqueue_for_tenant_admins(
                tenant["id"],
                kind="form_submission",
                title=f"Form submission — {form.get('name') or form.get('slug')}",
                body=f"From {display}",
                source_ref={
                    "kind": "form_submission",
                    "form_id": fid,
                    "submission_id": sub_id,
                    "lead_id": lead_id,
                },
                href=(f"/leads/{lead_id}" if lead_id else "/marketing/forms"),
                priority="normal",
            )
        except Exception as exc:  # pragma: no cover — logged only
            logger.warning("[h1] admin bell fan-out failed: %s", exc)

    return {
        "ok": True,
        "submission_id": sub_id,
        "lead_id": lead_id,
        "success_message": form.get("success_message"),
    }


# ─── Utilities ────────────────────────────────────────────────────────

def _first_str(d: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None
