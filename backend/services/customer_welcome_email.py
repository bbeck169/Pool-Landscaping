"""WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 — one-off welcome
email sent when a customer accepts their first-ever quote.

Public API:
    await maybe_fire_welcome_on_first_accepted_quote(
        tenant_id=..., customer_id=..., quote_id=..., source="portal",
    )

The helper is role-agnostic by design — role gating is at the caller
(``routers/estimate_viewer.py``).  Customer-facing accept paths call
it; admin ``bulk-accept`` does NOT.

Idempotency:
    * Pre-check — ``customer.welcome_email_sent_at is None``.
    * Trigger-check — zero other ``status == "accepted"`` quotes for
      ``(customer_id, tenant_id)``, excluding ``quote_id``.
    * Tenant-toggle — ``tenant.welcome_email_on_first_accepted_quote_enabled``
      defaults True; False short-circuits with no send.
    * Atomic stamp — ``customers.update_one`` with
      ``welcome_email_sent_at: None`` guard.  If the stamp returns
      ``modified_count == 0`` AFTER a successful Resend, log a
      WARNING ``customer_welcome_email.race_detected`` — ops signal
      so we can measure whether to add a lock-first pattern.
    * Resend failure — do NOT stamp.  Next accept retries.

Follow-up (documented in commit body, not shipped here):
    * DB template seed migration
      ``migrations/seed_welcome_on_first_accepted_quote_template.py``
      mirroring ``seed_lead_conversion_welcome_template.py`` so
      tenants can override the hardcoded fallback via
      ``marketing_templates``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from config import db, logger
from services.email_urls import absolute_portal_url
from utils import new_id, now_iso


_TEMPLATE_NAME = "welcome_on_first_accepted_quote"


def _hardcoded_body(*, name: str, company_name: str,
                       company_phone: str, portal_link: str) -> str:
    """Hardcoded HTML fallback — DB template seed is a follow-up.

    Mirrors the ``lead_conversion_notifications._send_welcome_email``
    chrome so tenants without a seeded template still get a branded
    body.
    """
    cta = (
        f'<p><a href="{portal_link}" '
        f'style="background:#0891b2;color:#fff;padding:12px 20px;'
        f'border-radius:8px;text-decoration:none;display:inline-block">'
        f'Open your customer portal</a></p>'
    ) if portal_link else ""
    phone_bit = (
        f" or call <b>{company_phone}</b>" if company_phone else ""
    )
    return (
        f'<div style="font-family:sans-serif;max-width:560px;margin:auto">'
        f"<h2>Thanks for choosing {company_name}, {name}!</h2>"
        f"<p>We're thrilled to have you on board.  One of our team "
        f"will reach out shortly to schedule your first service.</p>"
        f"<h3>What happens next</h3>"
        f"<ul>"
        f"<li>We'll call or text you within one business day to "
        f"confirm your service start date.</li>"
        f"<li>Future invoices, service reports, and appointment "
        f"reminders will land in your inbox.</li>"
        f"<li>You can review and pay invoices, approve future "
        f"estimates, and manage your account from the customer "
        f"portal below.</li>"
        f"</ul>"
        + cta
        + f'<p style="color:#666;font-size:12px">You received this '
        f"because you accepted a quote with us.  Reply to this "
        f"email" + phone_bit + " anytime.</p>"
        f"</div>"
    )


async def _customer_display_name(customer: Dict[str, Any]) -> str:
    return (
        customer.get("name")
        or customer.get("contact_name")
        or "there"
    )


async def maybe_fire_welcome_on_first_accepted_quote(
    *, tenant_id: str, customer_id: str, quote_id: str,
    source: str,
) -> None:
    """Fire-and-forget helper.  All failures are swallowed and
    logged; the caller (quote accept flow) must never block on
    this notification.
    """
    try:
        # Feb-2026 · Automation suppression gate — if the
        # triggering quote came from the PDF importer (or any
        # future suppressed path), bail before sending.  Keep
        # cheap: lookup first, then run the rest of the pipeline.
        try:
            from services.automations.eligibility import (
                is_invoice_eligible_for_automation,
            )
            _trigger_doc = await db.quotes.find_one(
                {"id": quote_id, "tenant_id": tenant_id},
                {"_id": 0, "automations_suppressed": 1,
                 "deleted_at": 1, "status": 1,
                 "payment_status": 1},
            ) or {}
            _elig_w, _reason_w = is_invoice_eligible_for_automation(
                _trigger_doc, automation_kind="welcome_email",
            )
            if not _elig_w:
                logger.info(
                    "automation.skipped kind=welcome_email "
                    "invoice_id=%s reason=%s",
                    quote_id, _reason_w,
                )
                return
        except Exception:  # noqa: BLE001 — defensive
            # Gate failure must not block a legitimate welcome send;
            # fall through to the existing precheck ladder.
            pass
        # ── Step 1 · pre-check (fast short-circuit) ───────────────
        customer = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "email": 1,
               "welcome_email_sent_at": 1},
        )
        if not customer:
            return
        if customer.get("welcome_email_sent_at"):
            return
        email = (customer.get("email") or "").strip()
        if not email:
            logger.warning(
                "[customer-welcome-email] no email on customer; "
                "skipping tenant=%s customer=%s",
                tenant_id[:8], customer_id[:8],
            )
            return

        # ── Step 2 · trigger-check (count prior accepts) ──────────
        prior_accepts = await db.quotes.count_documents({
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "status": "accepted",
            "id": {"$ne": quote_id},
        })
        if prior_accepts > 0:
            return

        # ── Step 3 · tenant toggle ────────────────────────────────
        tenant = await db.tenants.find_one(
            {"id": tenant_id}, {"_id": 0},
        ) or {}
        toggle = tenant.get(
            "welcome_email_on_first_accepted_quote_enabled", True,
        )
        if toggle is False:
            logger.info(
                "[customer-welcome-email] disabled by tenant toggle "
                "— tenant=%s customer=%s", tenant_id[:8],
                customer_id[:8],
            )
            return

        # ── Step 4 · render ────────────────────────────────────────
        business_card = (tenant.get("settings") or {}).get(
            "business_card") or {}
        company_name = (
            business_card.get("company_name")
            or tenant.get("name")
            or "your service provider"
        )
        company_phone = business_card.get("phone") or ""
        name = await _customer_display_name(customer)
        portal_link = absolute_portal_url(
            "/portal/login", template_name=_TEMPLATE_NAME,
        ) or ""
        # Hardcoded fallback — remains the source of truth when no
        # tenant override exists. Admins who want to customize edit
        # the ``marketing_templates`` row with code
        # ``welcome_on_first_accept_email``; otherwise this body
        # ships as the sent copy.
        subject = (
            f"Thanks for choosing {company_name} — welcome aboard"
        )
        body_html = _hardcoded_body(
            name=name, company_name=company_name,
            company_phone=company_phone, portal_link=portal_link,
        )

        # ── Step 4b · P2 #10b · tenant override lookup ────────────
        # If the admin has an active DB row for this slug, replace
        # the subject + body with the rendered DB template. Missing
        # / inactive row → fall through to the hardcoded fallback
        # above. Catches any lookup/render failure to protect the
        # send path (never block a welcome email on a template
        # editing mistake — the hardcoded fallback saves it).
        try:
            from services.marketing_template_lookup import (
                get_template_by_code,
            )
            from services.marketing.merge_tags import render_template
            tpl = await get_template_by_code(
                "welcome_on_first_accept_email", tenant_id,
            )
            if tpl and tpl.get("body"):
                _ctx = {
                    "company_name": company_name,
                    "customer_first_name": (name or "").split(" ")[0] or name,
                    "customer_name": name,
                    "portal_url": portal_link,
                    "company_phone": company_phone,
                }
                _rendered_body, _ = render_template(
                    tpl["body"], _ctx, missing="empty",
                )
                _rendered_subject = (tpl.get("subject") or "").strip()
                if _rendered_body:
                    body_html = _rendered_body
                if _rendered_subject:
                    _rendered_subject, _ = render_template(
                        _rendered_subject, _ctx, missing="empty",
                    )
                    if _rendered_subject:
                        subject = _rendered_subject
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "[customer-welcome-email] DB template render failed "
                "— using hardcoded fallback: %s", exc,
            )

        # ── Step 5 · Resend send ──────────────────────────────────
        message_id: Optional[str] = None
        provider_status = "failed"
        try:
            from services.email.resend_adapter import send as _send
            provider_res = await _send(
                to=email, subject=subject, html=body_html,
                category="transactional", tenant_id=tenant_id,
            ) or {}
            provider_status = provider_res.get(
                "provider_status") or "sent"
            message_id = provider_res.get("provider_response_id")
        except Exception as exc:
            logger.error(
                "[customer-welcome-email] send failed — "
                "tenant=%s customer=%s quote=%s: %s",
                tenant_id[:8], customer_id[:8], quote_id[:8], exc,
            )
            return  # DO NOT stamp — next accept will retry

        if provider_status not in ("sent", "queued", "ok"):
            logger.error(
                "[customer-welcome-email] provider refused — "
                "tenant=%s customer=%s quote=%s status=%s",
                tenant_id[:8], customer_id[:8], quote_id[:8],
                provider_status,
            )
            return  # DO NOT stamp

        sent_at = now_iso()

        # ── Step 6 · atomic stamp ─────────────────────────────────
        res = await db.customers.update_one(
            {
                "id": customer_id, "tenant_id": tenant_id,
                "welcome_email_sent_at": None,
            },
            {"$set": {
                "welcome_email_sent_at": sent_at,
                "welcome_email_message_id": message_id,
                "welcome_email_trigger_quote_id": quote_id,
            }},
        )
        if res.modified_count == 0:
            # ── Step 7 · race detection ───────────────────────────
            # Another concurrent accept beat us to the stamp AFTER
            # we successfully sent.  The customer received two
            # welcome emails.  Ops signal.
            logger.warning(
                "customer_welcome_email.race_detected "
                "tenant=%s customer=%s quote=%s message_id=%s",
                tenant_id[:8], customer_id[:8], quote_id[:8],
                message_id or "",
            )
            return

        # ── Step 8 · audit log ────────────────────────────────────
        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "event": "customer.welcome_email_sent",
                "entity_kind": "customer",
                "entity_id": customer_id,
                "customer_id": customer_id,
                "trigger_quote_id": quote_id,
                "message_id": message_id,
                "trigger": "first_accepted_quote",
                "source": source,
                "created_at": sent_at,
            })
        except Exception as exc:  # pragma: no cover — never block
            logger.warning(
                "[customer-welcome-email] audit_logs insert failed: %s",
                exc,
            )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[customer-welcome-email] unexpected failure — "
            "tenant=%s customer=%s quote=%s: %s (%s)",
            tenant_id[:8], customer_id[:8], quote_id[:8], exc,
            type(exc).__name__,
        )
