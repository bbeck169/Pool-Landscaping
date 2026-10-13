"""Phase 8 · Feb 2026 — Lead-to-customer welcome bundle.

Fires when ``POST /api/leads/{id}/close-won`` (or ``/convert-to-customer``)
completes the conversion pipeline. Sends:

  1. Welcome email via Resend (``cs@plofv.com`` → customer.email).
  2. Welcome SMS via the RC adapter (``+16028874400`` → customer.phone).
     Bypasses marketing suppression because the send is transactional
     — a legitimate follow-up on an intent the customer expressed.
  3. Enrollment into the tenant-scoped ``Sales Won → Welcome Sequence``
     M5c drip (auto-seeded if missing).

Every send lands in ``marketing_deliveries`` with
``trigger_entity.kind="lead_conversion"``. Failures are logged and the
delivery row records the provider error — the pipeline never blocks
the conversion itself on notification issues.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from config import db, logger
from services.pay_link_builder import build_pay_now_url  # (unused but re-exportable)
from services.sms.rc_adapter import send as _rc_sms_send
from utils import new_id, now_iso

_M5C_KEY = "sales_won_welcome"
_APP_BASE = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")


async def _record_delivery(*, tenant_id: str, channel: str,
                              recipient: str, subject: Optional[str],
                              body: str, provider_res: Dict[str, Any],
                              trigger_lead_id: str,
                              trigger_customer_id: str) -> str:
    row_id = new_id()
    await db.marketing_deliveries.insert_one({
        "id": row_id,
        "tenant_id": tenant_id,
        "channel": channel,
        "recipient_email": recipient if channel == "email" else None,
        "recipient_phone": recipient if channel == "sms" else None,
        "subject_rendered": subject,
        "body_rendered": body,
        "provider": provider_res.get("provider") or "unknown",
        "provider_status": provider_res.get("provider_status"),
        "provider_response_id": provider_res.get("provider_response_id"),
        "provider_last_event_at": now_iso(),
        "sent_at": now_iso(),
        "trigger_entity": {
            "kind": "lead_conversion",
            "lead_id": trigger_lead_id,
            "customer_id": trigger_customer_id,
        },
        "mock": (provider_res.get("provider") == "mock"),
    })
    return row_id


async def _send_welcome_email(*, tenant_id: str, customer: Dict[str, Any],
                                 lead_id: str) -> Optional[str]:
    # P2 #10d · Feb-2026 — tenant-wide kill switch. Default True on
    # unset; admin opts out via ``PATCH /tenants/mine/settings``.
    from services.tenant_automation_gates import automation_enabled
    if not await automation_enabled(tenant_id, "lead_conversion_welcome_enabled"):
        return None
    # Feb-2026 · Multi-Contact Phase 2 · fan-out (manual).
    # Admin-initiated lead conversion — bypasses customer-level mute
    # (the customer just expressed intent; admin action confirms).
    from services.customer_multi_contact import active_email_recipients
    recipients = active_email_recipients(customer, context="manual")
    if not recipients:
        return None
    name = customer.get("name") or "there"
    # Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — DB-first render.
    # Prefer the ``lead_conversion_welcome_email`` row in
    # ``marketing_templates`` (tenant-specific > global default);
    # fall through to the hardcoded body below when the row is
    # absent OR the render fails.
    #
    # BUGFIX (part of the migration): the pre-migration body/subject
    # both hardcoded ``"Pool & Landscaping of Vistancia"`` and a
    # ``+1 (602) 887-4400`` phone number in the footer.  The DB body
    # renders these through ``{{COMPANY_NAME}}`` / ``{{COMPANY_PHONE}}``
    # so non-plofv tenants sign off correctly.  The hardcoded
    # fallback below is retained for defense-in-depth (a DB blip
    # shouldn't fail conversion emails) but should never fire for a
    # tenant that has run the seed migration.
    tenant_doc: Dict[str, Any] = {}
    try:
        import config as _cfg
        tenant_doc = await _cfg.db.tenants.find_one(
            {"id": tenant_id}, {"_id": 0},
        ) or {}
    except Exception:
        tenant_doc = {}
    company_name = (
        (tenant_doc.get("settings") or {}).get("business_card", {})
            .get("company_name")
        or tenant_doc.get("name")
        or "Pool & Landscaping of Vistancia"
    )
    company_phone = (
        (tenant_doc.get("settings") or {}).get("business_card", {})
            .get("phone")
        or ""
    )
    fallback_subject = f"Welcome to {company_name} — your account is ready"
    subject = fallback_subject
    rendered_body: Optional[str] = None
    try:
        from services.marketing_template_lookup import (
            get_template_with_global_fallback,
        )
        from services.marketing.merge_tags import render_template
        tpl = await get_template_with_global_fallback(
            "lead_conversion_welcome_email", tenant_id or None,
        )
        if tpl and tpl.get("body"):
            for _email_probe in recipients:
                portal_probe = (
                    f"{_APP_BASE}/portal/login?email={_email_probe}"
                    if _APP_BASE else ""
                )
                ctx = {
                    "tenant": tenant_doc,
                    "customer": customer,
                    "customer_name": name,
                    "portal_link": portal_probe,
                }
                rs, _ = render_template(
                    tpl.get("subject") or fallback_subject, ctx,
                    missing="empty",
                )
                rb, _ = render_template(
                    tpl["body"], ctx, missing="empty",
                )
                if rb:
                    subject = rs or fallback_subject
                    rendered_body = rb
                break
    except Exception as exc:  # noqa: BLE001 — defensive
        # Silent — caller wraps in try/except.
        logger.warning(
            "[lead-conversion-welcome] template render failed — "
            "using hardcoded fallback: %s", exc,
        )
    last_row_id: Optional[str] = None
    for email in recipients:
        portal_link = f"{_APP_BASE}/portal/login?email={email}" if _APP_BASE else ""
        if rendered_body is not None:
            body = rendered_body
        else:
            body = (
                f'<div style="font-family:sans-serif;max-width:560px;margin:auto">'
                f"<h2>Welcome aboard, {name}!</h2>"
                f"<p>Thanks for choosing <b>{company_name}</b>. "
                f"We've set up your account and one of our team will reach out shortly "
                f"to schedule your first service.</p>"
                f"<h3>What happens next</h3>"
                f"<ul>"
                f"<li>We'll call or text you within one business day to confirm a start date.</li>"
                f"<li>You'll receive service reports, invoices, and appointment reminders here.</li>"
                f"<li>Refer a neighbor and you both save $55 on your next service.</li>"
                f"</ul>"
                + (f'<p><a href="{portal_link}" style="background:#0891b2;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">Open your customer portal</a></p>' if portal_link else "")
                + f'<p style="color:#666;font-size:12px">You are receiving this because you '
                f"requested service from us. Reply to this email"
                + (f" or call <b>{company_phone}</b>" if company_phone else "")
                + " anytime.</p>"
                f"</div>"
            )
        try:
            from services.marketing_email.resend_adapter import send as _send_email
        except Exception:
            try:
                from services.marketing.email_adapter import send as _send_email  # type: ignore
            except Exception:
                _send_email = None  # type: ignore
        if _send_email is None:
            try:
                from emailer import send_transactional_email
                provider_res = await send_transactional_email(
                    to=email, subject=subject, html=body,
                )
            except Exception as exc:
                provider_res = {"provider": "mock",
                                 "provider_status": "failed",
                                 "provider_response_id": None,
                                 "error": str(exc)}
        else:
            try:
                provider_res = await _send_email(
                    to=email, subject=subject, html=body,
                    category="transactional", tenant_id=tenant_id,
                )
            except Exception as exc:
                provider_res = {"provider": "resend",
                                 "provider_status": "failed",
                                 "provider_response_id": None,
                                 "error": str(exc)}
        last_row_id = await _record_delivery(
            tenant_id=tenant_id, channel="email",
            recipient=email, subject=subject, body=body,
            provider_res=provider_res, trigger_lead_id=lead_id,
            trigger_customer_id=customer["id"],
        )
    return last_row_id


async def _send_welcome_sms(*, tenant_id: str, customer: Dict[str, Any],
                               lead_id: str) -> Optional[str]:
    # P2 #10d · Feb-2026 — same tenant kill switch gates the SMS half
    # of the lead-conversion automation (email + SMS share one flag
    # per audit Flag 2 approved shape).
    from services.tenant_automation_gates import automation_enabled
    if not await automation_enabled(tenant_id, "lead_conversion_welcome_enabled"):
        return None
    # Feb-2026 · Multi-Contact Phase 2 · fan-out (manual).
    from services.customer_multi_contact import active_phone_recipients
    recipients = active_phone_recipients(customer, context="manual")
    if not recipients:
        return None
    name = (customer.get("name") or "").split(" ", 1)[0] or "there"
    body = (
        f"Hi {name} — thanks for choosing Pool & Landscaping of Vistancia. "
        "We'll be in touch to schedule your first service. Reply STOP to opt out."
    )
    last_row_id: Optional[str] = None
    for phone in recipients:
        try:
            provider_res = await _rc_sms_send(
                to=phone, body=body,
                category="transactional",  # bypass marketing suppression
                tenant_id=tenant_id,
                idempotency_key=f"lead-conversion:{lead_id}:sms:{phone}",
            )
        except Exception as exc:  # pragma: no cover
            provider_res = {"provider": "ringcentral",
                             "provider_status": "failed",
                             "provider_response_id": None,
                             "error": str(exc)}
        last_row_id = await _record_delivery(
            tenant_id=tenant_id, channel="sms",
            recipient=phone, subject=None, body=body,
            provider_res=provider_res, trigger_lead_id=lead_id,
            trigger_customer_id=customer["id"],
        )
    return last_row_id


async def _ensure_m5c_drip(tenant_id: str) -> Optional[str]:
    """Seed the canonical Sales Won drip if it doesn't exist for this
    tenant. Returns the drip campaign id."""
    existing = await db.marketing_campaigns.find_one(
        {"tenant_id": tenant_id, "key": _M5C_KEY, "deleted_at": {"$in": [None, ""]}},
        {"_id": 0, "id": 1},
    )
    if existing:
        return existing["id"]
    cid = new_id()
    now = now_iso()
    doc = {
        "id": cid, "tenant_id": tenant_id, "key": _M5C_KEY,
        "name": "Sales Won → Welcome Sequence",
        "kind": "drip", "channel": "mixed", "status": "active",
        "trigger": "lead_conversion",
        "steps": [
            {"day": 0, "channel": "email",
             "subject": "Welcome to Pool & Landscaping of Vistancia",
             "body": "Day-0 welcome — customer just converted.",
             "category": "transactional"},
            {"day": 3, "channel": "email",
             "subject": "Your portal + services overview",
             "body": "Day-3 nudge — login link + service catalog.",
             "category": "marketing"},
            {"day": 10, "channel": "email",
             "subject": "Refer a neighbor and save $55",
             "body": "Day-10 referral reminder with promo code.",
             "category": "marketing"},
        ],
        "created_at": now, "updated_at": now,
        "created_by": "phase8_seeder",
    }
    await db.marketing_campaigns.insert_one(doc)
    logger.info(f"[phase8] seeded M5c drip {cid} for tenant {tenant_id[:8]}")
    return cid


async def _enroll_in_drip(*, tenant_id: str, customer: Dict[str, Any],
                            lead_id: str) -> Optional[str]:
    drip_id = await _ensure_m5c_drip(tenant_id)
    if not drip_id:
        return None
    enrollment_id = new_id()
    now = now_iso()
    await db.marketing_enrollments.insert_one({
        "id": enrollment_id,
        "tenant_id": tenant_id,
        "campaign_id": drip_id,
        "campaign_key": _M5C_KEY,
        "customer_id": customer["id"],
        "customer_email": customer.get("email"),
        "customer_phone": customer.get("phone"),
        "trigger_entity": {"kind": "lead_conversion",
                            "lead_id": lead_id,
                            "customer_id": customer["id"]},
        "current_step": 0,
        "next_run_at": now,
        "enrolled_at": now,
        "status": "active",
    })
    return enrollment_id


async def fire_welcome_bundle(*, tenant_id: str, lead: Dict[str, Any],
                                 customer: Dict[str, Any],
                                 actor_user_id: Optional[str]) -> Dict[str, Any]:
    """Public API — best-effort fire of all three welcome sends.

    Never raises. Each sub-send catches its own errors so a failed SMS
    doesn't prevent the drip from enrolling."""
    email_id, sms_id, drip_id = None, None, None
    try:
        email_id = await _send_welcome_email(
            tenant_id=tenant_id, customer=customer, lead_id=lead["id"],
        )
    except Exception as exc:
        logger.warning(f"[phase8] welcome email failed: {exc}")
    try:
        sms_id = await _send_welcome_sms(
            tenant_id=tenant_id, customer=customer, lead_id=lead["id"],
        )
    except Exception as exc:
        logger.warning(f"[phase8] welcome sms failed: {exc}")
    try:
        drip_id = await _enroll_in_drip(
            tenant_id=tenant_id, customer=customer, lead_id=lead["id"],
        )
    except Exception as exc:
        logger.warning(f"[phase8] drip enrollment failed: {exc}")
    return {"email_id": email_id, "sms_id": sms_id,
             "drip_enrollment_id": drip_id}
