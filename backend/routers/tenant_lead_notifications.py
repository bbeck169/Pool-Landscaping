"""Phase K63 · Feb-2026 — Per-tenant "Lead Alert" recipient CRUD.

Rich recipient shape (stored on the tenant document under
``lead_notification_recipients``):

    [
      {
        "id": "<uuid>",
        "name": "Brian",
        "email": "brian@plofv.com",
        "phone": "+16028874400",
        "sms_opt_in": true,
        "email_opt_in": true,
      },
      ...
    ]

* Admin-only role gate (``require_admin``). Tenant-scoped —
  callers can only touch settings for the tenant their auth
  token was minted against.
* Phone numbers are normalized to E.164 on PUT. Email is
  case-folded + trimmed.
* Lazy migration on GET — if the tenant only carries the
  legacy P18 flat lists (``lead_alert_sms_recipients`` +
  ``lead_alert_email_recipients``), we synthesize the rich
  shape one-time and persist it so the Settings UI has a
  populated table to render.
* The dispatcher (see ``services/lead_notifications.py``) reads
  the rich list first and falls back to the legacy fields only
  when the rich list is absent, so this endpoint's writes never
  break in-flight submissions.
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant


router = APIRouter(tags=["settings"])


# ─── Models ─────────────────────────────────────────────────────────

class LeadRecipient(BaseModel):
    id: Optional[str] = None
    name: str = Field("", max_length=120)
    email: str = Field("", max_length=254)
    phone: str = Field("", max_length=32)
    sms_opt_in: bool = False
    email_opt_in: bool = False


class LeadRecipientsPayload(BaseModel):
    recipients: list[LeadRecipient]


# ─── Helpers ────────────────────────────────────────────────────────

_E164 = re.compile(r"^\+[1-9]\d{9,14}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_phone(raw: str) -> str:
    """K63 · Feb-2026 — coerce phone into E.164.

    Accepts common US inputs like ``602-887-4400``,
    ``(602) 887-4400``, ``6028874400`` and returns
    ``+16028874400``. Anything already E.164 passes through.
    Empty / non-string inputs return the empty string.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    if _E164.match(s):
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return s  # let the validator flag it below


def _synthesize_from_legacy(tenant: dict) -> list[dict]:
    """One-time migration — build the rich recipient list from the
    legacy P18 flat lists so an admin opening the Settings UI for
    a pre-K63 tenant sees the current wiring populated.

    * Every phone becomes an SMS-opt-in-only recipient.
    * Every email becomes an email-opt-in-only recipient.
    * Where a phone + email share a recipient in the legacy
      layout we can't know — we err on the side of two rows and
      let the admin merge via the UI.
    """
    out: list[dict] = []
    for phone in (tenant.get("lead_alert_sms_recipients") or []):
        if not (isinstance(phone, str) and phone.strip()):
            continue
        out.append({
            "id": new_id(),
            "name": "",
            "email": "",
            "phone": _normalize_phone(phone),
            "sms_opt_in": True,
            "email_opt_in": False,
        })
    for email in (tenant.get("lead_alert_email_recipients") or []):
        if not (isinstance(email, str) and email.strip()):
            continue
        out.append({
            "id": new_id(),
            "name": "",
            "email": email.strip().lower(),
            "phone": "",
            "sms_opt_in": False,
            "email_opt_in": True,
        })
    return out


# ─── Endpoints ──────────────────────────────────────────────────────

@router.get("/tenants/{tid}/settings/lead-notifications")
async def get_lead_notifications(tid: str,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """Return the current rich recipient list for the tenant.

    Also runs a lazy migration when the tenant only carries the
    legacy flat lists so the Settings UI has real data to render
    the first time an admin opens it.
    """
    if tid != tenant["id"]:
        raise HTTPException(403, "Tenant mismatch")
    doc = await db.tenants.find_one({"id": tid},
                                        {"_id": 0, "id": 1,
                                         "lead_notification_recipients": 1,
                                         "lead_alert_sms_recipients": 1,
                                         "lead_alert_email_recipients": 1})
    if not doc:
        raise HTTPException(404, "Tenant not found")
    recips = list(doc.get("lead_notification_recipients") or [])
    migrated = False
    if not recips and (
        doc.get("lead_alert_sms_recipients")
        or doc.get("lead_alert_email_recipients")
    ):
        recips = _synthesize_from_legacy(doc)
        await db.tenants.update_one(
            {"id": tid},
            {"$set": {"lead_notification_recipients": recips,
                       "lead_notification_recipients_migrated_at": now_iso()}},
        )
        migrated = True
    return {"recipients": recips, "migrated_from_legacy": migrated}


@router.put("/tenants/{tid}/settings/lead-notifications")
async def put_lead_notifications(tid: str,
                                    body: LeadRecipientsPayload,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """Replace the recipient list. Normalizes phone/email + assigns
    stable ids to any recipient added via the UI. Rejects the
    write when any row is malformed so the UI can surface a
    field-level error."""
    if tid != tenant["id"]:
        raise HTTPException(403, "Tenant mismatch")
    incoming = list(body.recipients or [])
    # K63 · Feb-2026 — hard cap enforced at the write boundary so
    # a rogue caller can't sidestep the FE counter. Ten covers every
    # observed tenant + leaves headroom for a small on-call rotation
    # without turning the alert list into a broadcast list.
    if len(incoming) > 10:
        raise HTTPException(400, "Maximum 10 recipients per tenant")
    normalized: list[dict] = []
    for i, r in enumerate(incoming):
        email = (r.email or "").strip().lower()
        phone = _normalize_phone(r.phone or "")
        if email and not _EMAIL.match(email):
            raise HTTPException(400,
                                    f"Recipient {i + 1}: invalid email address")
        if phone and not _E164.match(phone):
            raise HTTPException(400,
                                    f"Recipient {i + 1}: invalid phone "
                                    "(use E.164 like +16025551234)")
        if r.sms_opt_in and not phone:
            raise HTTPException(400,
                                    f"Recipient {i + 1}: SMS opt-in requires a phone number")
        if r.email_opt_in and not email:
            raise HTTPException(400,
                                    f"Recipient {i + 1}: Email opt-in requires an email address")
        normalized.append({
            "id": r.id or new_id(),
            "name": (r.name or "").strip()[:120],
            "email": email,
            "phone": phone,
            "sms_opt_in": bool(r.sms_opt_in),
            "email_opt_in": bool(r.email_opt_in),
        })
    await db.tenants.update_one(
        {"id": tid},
        {"$set": {"lead_notification_recipients": normalized,
                   "lead_notification_recipients_updated_at": now_iso(),
                   "lead_notification_recipients_updated_by": (user or {}).get("id")}},
    )
    return {"ok": True, "recipients": normalized}
