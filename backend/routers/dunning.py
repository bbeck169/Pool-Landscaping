"""Phase 22 · Automated invoice follow-ups (dunning).

Configurable per-tenant reminder cadence + AR aging analytics + manual
reminder trigger + pause/resume + scheduled scanner.

Channels:
 - Email via Resend (LIVE when RESEND_API_KEY is set)
 - SMS via RingCentral (returns `pending_sms` when RC creds absent — no
   silent mock)

Payment link:
 - Stripe hosted PaymentLink when `STRIPE_SECRET_KEY` is set (created
   lazily on first reminder, then cached on the invoice)
 - Otherwise in-app portal URL `{APP_PUBLIC_URL}/portal/invoices/{id}/pay`
"""
import asyncio
import base64
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import (
    db, logger, RESEND_API_KEY, EMAIL_FROM, APP_PUBLIC_URL,
)
from utils import now_iso, new_id, require_admin, get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# Defaults + settings
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_STAGES: List[Dict[str, Any]] = [
    {
        "id": "pre_due_3d", "name": "3-day heads-up",
        "offset_days": -3, "channels": ["email"],
        "subject_template": "Reminder: invoice {invoice_number} due in 3 days",
        "body_template": (
            "Hi {customer_name},\n\n"
            "Just a friendly reminder that invoice {invoice_number} for "
            "${invoice_total} is due on {due_date}.\n\n"
            "View invoice: {payment_link}\n\n"
            "Thanks,\n{tenant_name}"
        ),
        "sms_template": (
            "{tenant_name}: invoice {invoice_number} (${invoice_total}) "
            "due {due_date}. Pay: {payment_link}"
        ),
    },
    {
        "id": "on_due_day", "name": "Due today",
        "offset_days": 0, "channels": ["email"],
        "subject_template": "Invoice {invoice_number} is due today",
        "body_template": (
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} for ${invoice_total} is due today. "
            "View invoice: {payment_link}\n\n"
            "Thanks,\n{tenant_name}"
        ),
        "sms_template": (
            "{tenant_name}: invoice {invoice_number} (${invoice_total}) "
            "is due today. Pay: {payment_link}"
        ),
    },
    {
        "id": "past_due_7d", "name": "7 days past due",
        "offset_days": 7, "channels": ["email"],
        "subject_template": "Past due: invoice {invoice_number} ({days_past_due}d)",
        "body_template": (
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} for ${invoice_total} is now "
            "{days_past_due} days past due. Please settle at your "
            "earliest convenience.\n\nView invoice: {payment_link}\n\n"
            "Questions? Call {tenant_phone}.\n\n{tenant_name}"
        ),
        "sms_template": (
            "{tenant_name}: invoice {invoice_number} is {days_past_due}d "
            "past due (${invoice_total}). Pay: {payment_link}"
        ),
    },
    {
        "id": "past_due_14d", "name": "14 days past due",
        "offset_days": 14, "channels": ["email", "sms"],
        "subject_template": "Second notice: invoice {invoice_number}",
        "body_template": (
            "Hi {customer_name},\n\n"
            "This is a second reminder that invoice {invoice_number} for "
            "${invoice_total} is {days_past_due} days past due. Please "
            "pay to avoid further follow-up.\n\nView invoice: {payment_link}\n\n"
            "{tenant_name} · {tenant_phone}"
        ),
        "sms_template": (
            "{tenant_name}: SECOND NOTICE — invoice {invoice_number} is "
            "{days_past_due}d past due. Pay: {payment_link}"
        ),
    },
    {
        "id": "past_due_30d", "name": "30 days past due (final)",
        "offset_days": 30, "channels": ["email", "sms"],
        "subject_template": "Final notice: invoice {invoice_number}",
        "body_template": (
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} is now 30+ days past due. This is "
            "our final courtesy reminder before your account is flagged "
            "at risk. Please pay ${invoice_total} today.\n\n"
            "View invoice: {payment_link}\n\n{tenant_name} · {tenant_phone}"
        ),
        "sms_template": (
            "{tenant_name}: FINAL NOTICE — invoice {invoice_number} is 30d+ "
            "past due (${invoice_total}). Pay: {payment_link}"
        ),
    },
    {
        "id": "past_due_60d", "name": "60 days past due (collections)",
        "offset_days": 60, "channels": ["email", "sms"],
        "subject_template": "Collections notice: invoice {invoice_number}",
        "body_template": (
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} (${invoice_total}) is now 60+ days "
            "past due. Your account has been flagged for collections. "
            "Please contact us immediately at {tenant_phone}.\n\n"
            "View invoice: {payment_link}\n\n{tenant_name}"
        ),
        "sms_template": (
            "{tenant_name}: your account is flagged for collections. "
            "Invoice {invoice_number} 60d+ past due. Call {tenant_phone}."
        ),
    },
]

DEFAULT_ESCALATION = {"at_risk_days": 30, "in_collections_days": 60}


async def _get_settings(tenant_id: str) -> Dict[str, Any]:
    doc = await db.dunning_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        doc = {
            "tenant_id": tenant_id,
            "enabled": True,
            "stages": [dict(s) for s in DEFAULT_STAGES],
            "escalation": dict(DEFAULT_ESCALATION),
            "stripe_payment_link_enabled": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.dunning_settings.insert_one(dict(doc))
        doc.pop("_id", None)
    return doc


class Stage(BaseModel):
    id: str
    name: str
    offset_days: int = Field(..., ge=-90, le=365)
    channels: List[str]
    subject_template: str = ""
    body_template: str
    sms_template: str = ""


class Escalation(BaseModel):
    at_risk_days: int = Field(30, ge=1, le=365)
    in_collections_days: int = Field(60, ge=1, le=730)


class SettingsIn(BaseModel):
    enabled: Optional[bool] = None
    stages: Optional[List[Stage]] = None
    escalation: Optional[Escalation] = None
    stripe_payment_link_enabled: Optional[bool] = None


@router.get("/dunning/settings")
async def get_settings(user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    return await _get_settings(tenant["id"])


@router.put("/dunning/settings")
async def put_settings(body: SettingsIn,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    updates: Dict[str, Any] = {"updated_at": now_iso(),
                                 "updated_by": user["id"]}
    if body.enabled is not None: updates["enabled"] = body.enabled
    if body.stages is not None:
        stages = [s.model_dump() for s in body.stages]
        # Validate uniqueness
        ids = [s["id"] for s in stages]
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "Stage ids must be unique")
        offsets = [s["offset_days"] for s in stages]
        if len(set(offsets)) != len(offsets):
            raise HTTPException(400, "Stage offset_days must be unique")
        for s in stages:
            if not s["channels"]:
                raise HTTPException(400,
                    f"Stage {s['id']} must have at least one channel")
            for ch in s["channels"]:
                if ch not in {"email", "sms"}:
                    raise HTTPException(400, f"Bad channel {ch}")
        updates["stages"] = stages
    if body.escalation is not None:
        updates["escalation"] = body.escalation.model_dump()
    if body.stripe_payment_link_enabled is not None:
        updates["stripe_payment_link_enabled"] = body.stripe_payment_link_enabled
    await db.dunning_settings.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": updates,
         "$setOnInsert": {"tenant_id": tenant["id"],
                           "created_at": now_iso()}},
        upsert=True,
    )
    return await _get_settings(tenant["id"])


@router.post("/dunning/settings/reset-defaults")
async def reset_defaults(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    await db.dunning_settings.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": {"stages": [dict(s) for s in DEFAULT_STAGES],
                    "escalation": dict(DEFAULT_ESCALATION),
                    "enabled": True,
                    "stripe_payment_link_enabled": True,
                    "updated_at": now_iso()},
         "$setOnInsert": {"tenant_id": tenant["id"],
                           "created_at": now_iso()}},
        upsert=True,
    )
    return await _get_settings(tenant["id"])


# ═══════════════════════════════════════════════════════════════════════
# Send-reminder core (used by manual endpoint + scanner)
# ═══════════════════════════════════════════════════════════════════════

# Phase 9D · Feb 2026 — dunning templates were the last surviving
# ``str.format(**ctx)`` callsite. Now every render is unified through
# the canonical merge-tag engine. Legacy single-brace tokens like
# ``{invoice_number}`` are normalised in place to ``{{invoice_number}}``
# before delegation, so the six ``DEFAULT_STAGES`` payloads AND any
# tenant-customised copies keep rendering byte-identically.
_DUNNING_SINGLE_BRACE = re.compile(
    r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_.]*)\}(?!\})"
)

# Phase D6 · Feb-2026 — Stock stage_ids whose subject/body/sms
# copy is catalogued in ``services.email_body_i18n``. A stage
# whose ``id`` is in this set gets its subject/body/sms rendered
# from the i18n catalog for the resolved locale; any other
# ``stage.id`` (tenant-customised stages) keeps rendering from
# the stage's own ``*_template`` fields.
_STOCK_STAGE_IDS = frozenset({
    "pre_due_3d", "on_due_day",
    "past_due_7d", "past_due_14d", "past_due_30d", "past_due_60d",
})


def _render(template: str, ctx: Dict[str, Any]) -> str:
    if not template:
        return ""
    normalised = _DUNNING_SINGLE_BRACE.sub(lambda m: "{{" + m.group(1) + "}}",
                                              template)
    try:
        from services.marketing.merge_tags import render_template as _canonical
        rendered, _unresolved = _canonical(normalised, ctx or {}, missing="empty")
        return rendered
    except Exception:
        # Never break a dunning send because of a template render bug —
        # fall through with the original template so the operator can
        # see the raw payload in logs.
        return template


def _localised_stage_copy(
    stage: Dict[str, Any], ctx: Dict[str, Any], locale: str,
) -> Dict[str, str]:
    """Phase D6 · Feb-2026 — return ``{"subject", "body", "sms"}``
    for ``stage`` rendered in ``locale``.

    * For stock stages (``id`` ∈ :data:`_STOCK_STAGE_IDS`), the
      subject / body / sms copy is loaded from the i18n catalog
      under ``dunning.<stage_id>.<field>`` and rendered directly
      with :func:`str.format`-style substitution.
    * For tenant-customised stages (any other ``id``), the fields
      fall through to ``stage.<field>_template`` and go through
      the existing :func:`_render` merge-tag pipeline so mid-flight
      customisations continue to work exactly as before.
    """
    stage_id = str(stage.get("id") or "")
    if stage_id in _STOCK_STAGE_IDS:
        from services.email_body_i18n import t_email_body
        return {
            "subject": t_email_body(
                locale, f"dunning.{stage_id}.subject", **ctx,
            ),
            "body": t_email_body(
                locale, f"dunning.{stage_id}.body", **ctx,
            ),
            "sms": t_email_body(
                locale, f"dunning.{stage_id}.sms", **ctx,
            ),
        }
    return {
        "subject": _render(stage.get("subject_template") or "", ctx),
        "body": _render(stage.get("body_template") or "", ctx),
        "sms": _render(
            stage.get("sms_template") or stage.get("body_template") or "",
            ctx,
        ),
    }


async def _payment_link_for(invoice: Dict[str, Any],
                              settings: Dict[str, Any],
                              *, src: str = "link") -> str:
    """Return a hosted payment-link URL (created + cached on the
    invoice), or the public magic-link viewer as fallback.

    Phase LZ4 · Feb 2026 — the Stripe PaymentLink branch was removed
    when the Stripe SDK was retired. New links are dispatched via the
    LZ2 Zapier bridge to Lumino when the invoice is created/edited;
    any URL saved onto ``invoice.payment_link`` (or the legacy
    ``stripe_payment_link``) is returned as-is. The magic-link viewer
    stays the reliable fallback so a paying customer never sees a
    dead page even if the Lumino dispatch is still in-flight.

    Phase K47 · Feb 2026 — the ``src`` kwarg is forwarded onto the
    magic-link URL so the resulting ``invoice_views`` row is
    stamped with the send channel. Ignored when a cached
    ``payment_link`` is returned (those URLs are minted upstream
    by Lumino and have their own tracking).
    """
    cached = invoice.get("payment_link")
    if cached:
        return cached
    # Feb 2026 · Pay-Now hotfix — the previous fallback pointed at
    # ``/portal/invoices/{id}/pay`` which is BEHIND auth; customers
    # without an active session were bounced to the login page. Use
    # the public magic-link viewer instead so the fallback still
    # works for logged-out recipients.
    from services.pay_link_builder import build_pay_now_url
    return build_pay_now_url(
        invoice["id"], invoice.get("tenant_id") or "", src=src,
    )


async def _build_context(invoice: Dict[str, Any], tenant: Dict[str, Any],
                           settings: Dict[str, Any],
                           *, src: str = "link") -> Dict[str, Any]:
    customer = None
    if invoice.get("customer_id"):
        customer = await db.customers.find_one(
            {"id": invoice["customer_id"], "tenant_id": tenant["id"]},
            {"_id": 0},
        )
    due = invoice.get("due_date") or ""
    days_past_due = 0
    try:
        if due:
            d = datetime.fromisoformat(str(due)[:10]).date()
            days_past_due = max(0, (datetime.now(timezone.utc).date() - d).days)
    except Exception:
        pass
    return {
        "customer_name": (customer or {}).get("name") or "there",
        "invoice_number": invoice["id"][:8],
        "invoice_total": f"{float(invoice.get('total', 0)):.2f}",
        "due_date": due or "TBD",
        "days_past_due": days_past_due,
        "payment_link": await _payment_link_for(invoice, settings, src=src),
        "tenant_name": tenant.get("name") or "Your Business",
        "tenant_phone": (tenant.get("phone")
                           or (tenant.get("settings") or {}).get("phone")
                           or ""),
        "customer_email": (customer or {}).get("email") or "",
        "customer_phone": (customer or {}).get("phone") or "",
    }


async def _send_email(to: str, subject: str, body: str,
                       tenant_name: str) -> Dict[str, Any]:
    if not RESEND_API_KEY:
        return {"status": "pending_resend", "reason": "resend-not-configured"}
    if not to or "@" not in to:
        return {"status": "failed", "error": "no-recipient"}
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        html_body = "<p>" + body.replace("\n\n", "</p><p>").replace(
            "\n", "<br>") + "</p>"
        # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
        resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [to], "subject": subject or "Invoice reminder",
            "html": html_body,
        })
        return {"status": "sent"}
    except Exception as e:
        logger.warning(f"dunning email send failed: {e}")
        return {"status": "failed", "error": str(e)}


async def _send_sms(to: str, body: str, *, tenant_id: Optional[str] = None,
                     customer_id: Optional[str] = None) -> Dict[str, Any]:
    """Feb-2026 · Twilio→RC consolidation — delegates to the shipped
    RingCentral adapter. Adapter fails-closed when RC creds absent;
    caller receives ``status="pending_sms"``.
    """
    if not to:
        return {"status": "failed", "error": "no-recipient"}
    from services.sms.rc_adapter import send as _sms_send
    res = await _sms_send(to=to, body=body, category="transactional",
                            tenant_id=tenant_id, customer_id=customer_id)
    provider = res.get("provider")
    status = res.get("provider_status")
    if provider == "ringcentral" and status in ("queued", "sent", "delivered", "accepted"):
        return {"status": "sent"}
    if provider == "mock" or status == "dry_run":
        return {"status": "pending_sms",
                 "reason": "sms-not-configured"}
    return {"status": "failed",
             "error": res.get("error") or "sms-send-failed"}


async def _send_reminder(invoice: Dict[str, Any], stage: Dict[str, Any],
                            tenant: Dict[str, Any], settings: Dict[str, Any],
                            channels: Optional[List[str]] = None,
                            custom_message: Optional[str] = None,
                            triggered_by: str = "auto") -> List[Dict[str, Any]]:
    """Send a reminder on the given stage. Returns list of persisted
    `dunning_reminders` docs (one per channel actually attempted).

    Phase D6 · Feb-2026 — subject / body / sms copy is resolved
    through :func:`_localised_stage_copy` using the recipient's
    locale (customer → tenant default → ``en``). Tenant-customised
    stages fall through to the legacy render path so any UI-driven
    customisation keeps working exactly as before. A caller-supplied
    ``custom_message`` overrides the body but the subject + SMS
    still localise.
    """
    # Phase K47 · Feb-2026 — build per-channel contexts so the
    # ``payment_link`` embedded in the email vs SMS body carries
    # the correct ``?src=`` tag; the receiving magic-link viewer
    # uses this to stamp source on ``invoice_views``.
    ctx_email = await _build_context(invoice, tenant, settings, src="email")
    ctx_sms = await _build_context(invoice, tenant, settings, src="sms")
    # Phase D6 · Feb-2026 — resolve recipient locale for
    # subject/body/sms i18n. The customer doc lives on the ctx so
    # we look it up once here (best-effort, tenant default is the
    # fallback).
    customer = None
    if invoice.get("customer_id"):
        try:
            customer = await db.customers.find_one(
                {"id": invoice["customer_id"],
                 "tenant_id": tenant["id"]},
                {"_id": 0, "locale": 1},
            )
        except Exception:  # noqa: BLE001
            customer = None
    from services.i18n.email_locale import resolve_email_locale
    locale = resolve_email_locale(recipient=customer, tenant=tenant)
    copy_email = _localised_stage_copy(stage, ctx_email, locale)
    copy_sms = _localised_stage_copy(stage, ctx_sms, locale)
    chans = channels or stage["channels"]
    subject = copy_email["subject"]
    if custom_message:
        # Admin override — respect it verbatim but still substitute
        # merge tags via the legacy renderer so ``{customer_name}``
        # etc. behave the same as before.
        body_text = _render(custom_message, ctx_email)
    else:
        body_text = copy_email["body"]
    sms_text = copy_sms["sms"]
    persisted: List[Dict[str, Any]] = []

    for ch in chans:
        if ch == "email":
            result = await _send_email(
                ctx_email.get("customer_email") or "",
                subject, body_text, ctx_email["tenant_name"])
            doc = {
                "id": new_id(), "tenant_id": tenant["id"],
                "invoice_id": invoice["id"],
                "stage_id": stage["id"], "channel": "email",
                "recipient": ctx_email.get("customer_email") or "",
                "subject": subject, "body": body_text,
                "status": result["status"],
                "error": result.get("error") or result.get("reason"),
                "sent_at": now_iso(),
                "triggered_by": triggered_by,
            }
        elif ch == "sms":
            result = await _send_sms(
                ctx_sms.get("customer_phone") or "", sms_text,
                tenant_id=tenant["id"],
                customer_id=invoice.get("customer_id"),
            )
            doc = {
                "id": new_id(), "tenant_id": tenant["id"],
                "invoice_id": invoice["id"],
                "stage_id": stage["id"], "channel": "sms",
                "recipient": ctx_sms.get("customer_phone") or "",
                "subject": "", "body": sms_text,
                "status": result["status"],
                "error": result.get("error") or result.get("reason"),
                "sent_at": now_iso(),
                "triggered_by": triggered_by,
            }
        else:
            continue
        await db.dunning_reminders.insert_one(dict(doc))
        doc.pop("_id", None)
        persisted.append(doc)
    return persisted


# ═══════════════════════════════════════════════════════════════════════
# Manual send + history + pause/resume
# ═══════════════════════════════════════════════════════════════════════

class ManualSendIn(BaseModel):
    stage_id: Optional[str] = None
    channels: Optional[List[str]] = None
    custom_message: Optional[str] = None


async def _fetch_invoice(iid: str, tenant_id: str) -> Dict[str, Any]:
    inv = await db.quotes.find_one(
        {"id": iid, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0},
    )
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


@router.post("/dunning/invoices/{iid}/send-reminder")
async def manual_send(iid: str, body: ManualSendIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    inv = await _fetch_invoice(iid, tenant["id"])
    settings = await _get_settings(tenant["id"])
    stage_id = body.stage_id or "manual"
    stage = next((s for s in settings["stages"] if s["id"] == stage_id), None)
    if not stage:
        # Manual send with no stage → synthesize a minimal stage
        stage = {
            "id": "manual", "name": "Manual reminder", "offset_days": 0,
            "channels": body.channels or ["email"],
            "subject_template":
                "Reminder: invoice {invoice_number} — ${invoice_total}",
            "body_template": (body.custom_message
                or "Hi {customer_name},\n\nA reminder that invoice "
                "{invoice_number} for ${invoice_total} remains unpaid.\n\n"
                "View invoice: {payment_link}\n\nThanks,\n{tenant_name}"),
            "sms_template":
                "{tenant_name}: invoice {invoice_number} (${invoice_total}) "
                "unpaid. Pay: {payment_link}",
        }
    docs = await _send_reminder(inv, stage, tenant, settings,
                                  channels=body.channels,
                                  custom_message=body.custom_message,
                                  triggered_by=f"manual:{user['id']}")
    return {"reminders": docs, "count": len(docs)}


@router.get("/dunning/invoices/{iid}/history")
async def reminder_history(iid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    await _fetch_invoice(iid, tenant["id"])
    rows = await db.dunning_reminders.find(
        {"invoice_id": iid, "tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("sent_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.post("/dunning/pause/{iid}")
async def pause_invoice(iid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    inv = await _fetch_invoice(iid, tenant["id"])
    await db.quotes.update_one(
        {"id": iid, "tenant_id": tenant["id"]},
        {"$set": {"dunning_paused": True,
                    "dunning_paused_at": now_iso(),
                    "dunning_paused_by": user["id"]}},
    )
    return {"invoice_id": iid, "dunning_paused": True}


@router.post("/dunning/resume/{iid}")
async def resume_invoice(iid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    inv = await _fetch_invoice(iid, tenant["id"])
    await db.quotes.update_one(
        {"id": iid, "tenant_id": tenant["id"]},
        {"$set": {"dunning_paused": False,
                    "dunning_resumed_at": now_iso()}},
    )
    return {"invoice_id": iid, "dunning_paused": False}


# ═══════════════════════════════════════════════════════════════════════
# Scanner (called by APScheduler)
# ═══════════════════════════════════════════════════════════════════════

def _due_date_utc(inv: Dict[str, Any]) -> Optional[datetime]:
    due = inv.get("due_date")
    if not due: return None
    try:
        return datetime.fromisoformat(str(due)[:10]).replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _scan_tenant(tenant: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    settings = await _get_settings(tenant["id"])
    if not settings.get("enabled"):
        return {"tenant": tenant["id"], "skipped": "disabled",
                 "fired": 0, "escalated": 0}
    invoices = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "invoice",
          "status": {"$in": ["sent", "past_due", "draft"]},
          "payment_status": {"$ne": "paid"}},
        {"_id": 0},
    ).to_list(5000)
    esc = settings.get("escalation") or DEFAULT_ESCALATION
    stages = settings.get("stages") or []
    fired_total = 0
    escalated_total = 0
    for inv in invoices:
        if inv.get("dunning_paused"):
            continue
        due = _due_date_utc(inv)
        if not due:
            continue
        days_past = (now.date() - due.date()).days
        # Auto-flip sent → past_due once we're past due.
        if days_past > 0 and inv.get("status") == "sent":
            await db.quotes.update_one(
                {"id": inv["id"], "tenant_id": tenant["id"]},
                {"$set": {"status": "past_due"}},
            )
            inv["status"] = "past_due"
        # Escalation flags (soft label).
        new_risk = None
        if days_past >= esc.get("in_collections_days", 60):
            new_risk = "in_collections"
        elif days_past >= esc.get("at_risk_days", 30):
            new_risk = "at_risk"
        if new_risk and inv.get("risk_status") != new_risk:
            await db.quotes.update_one(
                {"id": inv["id"], "tenant_id": tenant["id"]},
                {"$set": {"risk_status": new_risk,
                            f"risk_status_{new_risk}_at": now_iso()}},
            )
            inv["risk_status"] = new_risk
            escalated_total += 1
        # Fire any stage that is due AND hasn't fired for this invoice yet.
        for stage in stages:
            offset = int(stage.get("offset_days", 0))
            if days_past < offset:
                continue
            # Idempotency: skip if already sent for (invoice, stage).
            already = await db.dunning_reminders.find_one({
                "tenant_id": tenant["id"], "invoice_id": inv["id"],
                "stage_id": stage["id"],
            }, {"_id": 0, "id": 1})
            if already:
                continue
            try:
                await _send_reminder(inv, stage, tenant, settings,
                                        triggered_by="auto")
                fired_total += 1
            except Exception as e:
                logger.warning(f"scanner reminder failed for "
                                f"{inv['id']}/{stage['id']}: {e}")
    return {"tenant": tenant["id"], "invoices": len(invoices),
             "fired": fired_total, "escalated": escalated_total}


async def run_dunning_scan() -> Dict[str, Any]:
    """Registered on APScheduler. Iterates every tenant that has an
    active dunning settings doc (or any tenant → we lazy-seed on first
    scan pass so a brand-new tenant automatically gets the defaults)."""
    now = datetime.now(timezone.utc)
    tenants = await db.tenants.find({}, {"_id": 0}).to_list(500)
    summary = []
    for t in tenants:
        try:
            summary.append(await _scan_tenant(t, now))
        except Exception as e:
            logger.warning(f"scan_tenant failed for {t.get('id')}: {e}")
            summary.append({"tenant": t.get("id"), "error": str(e),
                              "fired": 0, "escalated": 0})
    total_fired = sum(s.get("fired", 0) for s in summary)
    total_escalated = sum(s.get("escalated", 0) for s in summary)
    if total_fired:
        logger.info(f"dunning scan fired {total_fired} reminders "
                     f"across {len(tenants)} tenants")
    return {"scanned_at": now.isoformat(),
             "tenants": len(tenants),
             "total_fired": total_fired,
             "total_escalated": total_escalated,
             "summary": summary}


# ═══════════════════════════════════════════════════════════════════════
# Queue preview + AR aging analytics
# ═══════════════════════════════════════════════════════════════════════

@router.get("/dunning/queue")
async def get_queue(days: int = 7,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    """Return reminders scheduled to fire in the next N days.

    Response envelope: `{items, total, window_days}`. Each item includes
    both `fire_date` (canonical, ISO date) and `fire_at` (deprecated
    alias, ISO datetime at 00:00 UTC) — the alias is kept for one
    release to ease client migration.
    """
    settings = await _get_settings(tenant["id"])
    if not settings.get("enabled"):
        return {"items": [], "total": 0, "window_days": days,
                 "note": "dunning disabled"}
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days)
    invoices = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "invoice",
          "status": {"$in": ["sent", "past_due", "draft"]},
          "payment_status": {"$ne": "paid"},
          "dunning_paused": {"$ne": True}},
        {"_id": 0},
    ).to_list(2000)
    items: List[Dict[str, Any]] = []
    for inv in invoices:
        due = _due_date_utc(inv)
        if not due: continue
        for stage in settings.get("stages") or []:
            fire_date = (due + timedelta(days=int(stage["offset_days"]))).date()
            if not (now.date() <= fire_date <= horizon.date()):
                continue
            already = await db.dunning_reminders.find_one({
                "tenant_id": tenant["id"], "invoice_id": inv["id"],
                "stage_id": stage["id"]}, {"_id": 0, "id": 1})
            if already: continue
            fire_date_iso = fire_date.isoformat()
            items.append({
                "invoice_id": inv["id"],
                "invoice_title": inv.get("title") or "",
                "customer_id": inv.get("customer_id"),
                "customer_name": inv.get("customer_name") or "",
                "amount": float(inv.get("total", 0)),
                "due_date": inv.get("due_date"),
                "stage_id": stage["id"], "stage_name": stage["name"],
                "channels": stage["channels"],
                "fire_date": fire_date_iso,
                # Deprecated alias — kept for one release.
                "fire_at": f"{fire_date_iso}T00:00:00+00:00",
            })
    items.sort(key=lambda x: (x["fire_date"], x["stage_id"]))
    return {"items": items, "total": len(items),
             "window_days": days}


@router.get("/dunning/analytics/ar-aging")
async def ar_aging(user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    """DSO + collection-rate + 4-bucket AR aging."""
    now = datetime.now(timezone.utc)
    invoices = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "invoice"},
        {"_id": 0},
    ).to_list(10000)
    buckets = {"current": 0.0, "aging_30": 0.0,
                "aging_60": 0.0, "aging_90": 0.0}
    total_outstanding = 0.0
    at_risk_count = 0
    in_collections_count = 0
    dso_num = 0.0  # Σ (days_outstanding × total) for unpaid
    dso_den = 0.0
    paid_last_30 = 0.0
    invoiced_last_30 = 0.0
    for inv in invoices:
        total = float(inv.get("total", 0) or 0)
        paid = float(inv.get("amount_paid", 0) or 0)
        balance = max(0.0, total - paid)
        pay_status = inv.get("payment_status") or "unpaid"
        due = _due_date_utc(inv)
        # DSO + collection rate windows.
        created_dt = None
        try:
            if inv.get("created_at"):
                created_dt = datetime.fromisoformat(
                    str(inv["created_at"]).replace("Z", "+00:00"))
        except Exception:
            pass
        if created_dt and (now - created_dt).days <= 30:
            invoiced_last_30 += total
        if pay_status == "paid" and created_dt \
                and (now - created_dt).days <= 30:
            paid_last_30 += paid or total
        if pay_status == "paid" or balance <= 0:
            continue
        total_outstanding += balance
        days_past = 0
        if due:
            days_past = max(0, (now.date() - due.date()).days)
            dso_num += balance * days_past
            dso_den += balance
        if days_past <= 0:
            buckets["current"] += balance
        elif days_past <= 30:
            buckets["aging_30"] += balance
        elif days_past <= 60:
            buckets["aging_60"] += balance
        else:
            buckets["aging_90"] += balance
        rs = inv.get("risk_status")
        if rs == "at_risk":
            at_risk_count += 1
        elif rs == "in_collections":
            in_collections_count += 1
    dso_days = round(dso_num / dso_den, 1) if dso_den > 0 else 0.0
    collection_rate = (
        round(100 * paid_last_30 / invoiced_last_30, 1)
        if invoiced_last_30 > 0 else 0.0
    )
    return {
        "current": round(buckets["current"], 2),
        "aging_30": round(buckets["aging_30"], 2),
        "aging_60": round(buckets["aging_60"], 2),
        "aging_90": round(buckets["aging_90"], 2),
        "aging_total": round(total_outstanding, 2),
        "dso_days": dso_days,
        "collection_rate_30d": collection_rate,
        "at_risk_count": at_risk_count,
        "in_collections_count": in_collections_count,
        "invoiced_last_30d": round(invoiced_last_30, 2),
        "paid_last_30d": round(paid_last_30, 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# Test hook — gated by ALLOW_TEST_HOOKS=1
# ═══════════════════════════════════════════════════════════════════════

@router.post("/dunning/_test/run-scan-now")
async def _test_run_scan_now(user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Dev-only synchronous scanner trigger. Invokes the same
    `run_dunning_scan` the APScheduler cron calls; returns the exact
    counts of reminders created and invoices whose `risk_status` was
    escalated during this pass. Gated by `ALLOW_TEST_HOOKS=1`.
    """
    if not os.environ.get("ALLOW_TEST_HOOKS"):
        raise HTTPException(403, "test hooks are disabled")
    result = await run_dunning_scan()
    return {
        "ran": True,
        "reminders_created": int(result.get("total_fired", 0)),
        "invoices_escalated": int(result.get("total_escalated", 0)),
        "scanned_at": result.get("scanned_at"),
        "tenants": result.get("tenants", 0),
    }
