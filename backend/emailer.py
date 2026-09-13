import resend
from typing import Optional

from config import db, logger, RESEND_API_KEY, EMAIL_FROM, APP_PUBLIC_URL
# Feb-2026 · Email Base Template Theming — shared brand shell.
# ``wrap_html_in_shell`` is a PURE function; callers must resolve
# ``branding`` via ``get_effective_business_settings(...)`` in their
# already-async context and reuse the dict across a fan-out loop
# so a multi-recipient send doesn't re-fetch the tenant N times.
from services.email.theming import wrap_html_in_shell
from services.tenants.business_settings import (
    get_effective_business_settings,
)


def _thumbs_html(job: dict) -> str:
    photos = job.get("photos") or []
    if not photos:
        return ""
    base = APP_PUBLIC_URL
    cells = ""
    for p in photos[:6]:
        src = f"{base}/api/public/job-photo/{job['id']}/{p['id']}"
        cells += (
            f'<td style="padding:4px;">'
            f'<img src="{src}" width="96" height="96" alt="Service photo" '
            f'style="border-radius:10px;display:block;object-fit:cover;border:1px solid #E2E8F0;" />'
            f"</td>"
        )
    return (
        '<p style="margin:20px 0 8px;font-family:Arial,sans-serif;font-size:14px;color:#334155;">'
        "Photos from your visit:</p>"
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0"><tr>'
        f"{cells}</tr></table>"
    )


def _completion_html(job: dict, customer_name: str) -> str:
    report_url = f"{APP_PUBLIC_URL}/job/{job['id']}"
    service = job.get("service_type", "service")
    when = (job.get("scheduled_date") or "")[:10]
    return f"""
    <div style="max-width:560px;margin:0 auto;font-family:Arial,sans-serif;color:#1A2B3C;">
      <div style="background:#003C5F;padding:24px;border-radius:12px 12px 0 0;">
        <h1 style="color:#fff;margin:0;font-size:20px;">Pool &amp; Landscaping of Vistancia</h1>
      </div>
      <div style="border:1px solid #E2E8F0;border-top:none;border-radius:0 0 12px 12px;padding:24px;">
        <h2 style="font-size:18px;margin:0 0 8px;">Your service is complete ✅</h2>
        <p style="font-size:14px;color:#334155;line-height:20px;margin:0 0 4px;">
          Hi {customer_name}, we've finished your <strong>{service}</strong>{f' on {when}' if when else ''}.
          Your full service report — checklist, water readings and chemicals added — is ready to view.
        </p>
        {_thumbs_html(job)}
        <div style="text-align:center;margin:28px 0 8px;">
          <a href="{report_url}"
             style="background:#0EA5B7;color:#fff;text-decoration:none;font-size:15px;font-weight:bold;
                    padding:14px 28px;border-radius:10px;display:inline-block;">
            View Your Service Report
          </a>
        </div>
        <p style="font-size:12px;color:#94A3B8;text-align:center;margin:12px 0 0;">
          Questions? Just reply in the app and our team (and Marina, our assistant) will help.
        </p>
      </div>
    </div>
    """


async def send_completion_email(job: dict) -> bool:
    """Email the customer that their job is complete, with photo thumbnails + a report link."""
    if not RESEND_API_KEY:
        logger.info("Resend not configured — skipping completion email.")
        return False
    cid = job.get("customer_id")
    if not cid:
        return False
    cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
    to_email = cust.get("email")
    if not to_email:
        user = await db.users.find_one({"customer_id": cid, "role": "customer"}, {"_id": 0})
        to_email = user.get("email") if user else None
    if not to_email:
        logger.info("No customer email — skipping completion email.")
        return False
    # Phase 34 · Task L · Feb-2026 — outbound safety guard. Same rule
    # as the shared resend adapter: block live sends in non-prod
    # unless the recipient is on the allow-list.
    from services.comms_env_guard import guard_outbound
    verdict = guard_outbound(kind="email", to=to_email)
    if verdict.blocked:
        logger.info(
            "[DRY-RUN] emailer.send_completion_email SKIPPED to=%s job=%s",
            to_email, job.get("id"),
        )
        return False
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": to_email,
            "subject": f"Your {job.get('service_type', 'service')} is complete",
            "html": _completion_html(job, cust.get("name", "there")),
        })
        return True
    except Exception as e:
        logger.warning(f"Completion email failed: {e}")
        return False


def _invoice_display_number(inv: dict) -> str:
    """Return a stable customer-facing identifier for an invoice.

    Preference order (all customer-visible today somewhere in the
    UI): explicit ``invoice_number`` → doc_number → id short-form.
    NEVER falls back to ``title`` (which for legacy rows is the
    doc-type label ``"Estimate"`` / ``"Invoice"`` — the exact string
    that produced the "invoice Estimate has an outstanding
    balance…" prod bug).
    """
    n = (inv.get("invoice_number") or inv.get("doc_number") or "").strip()
    if n:
        return n
    _id = str(inv.get("id") or "")
    return f"#{_id[:8]}" if _id else "#—"


def _reminder_html(inv: dict, name: str, attachment_count: int = 0,
                     portal_cta_url: str = "") -> str:
    balance = round(float(inv.get("total") or 0) - float(inv.get("amount_paid") or 0), 2)
    due = inv.get("due_date") or "now"
    # Feb-2026 · P0 Pay-link routing fix — always use the PUBLIC
    # pay-link URL (``/pay/invoice/{id}?token=…``) instead of the
    # portal auto-login URL (``/api/portal/auto-login?t=…``). The
    # portal path required the customer to have an active session
    # and 302'd to ``/portal/login?reason=link_expired`` once the
    # 72h portal-token TTL lapsed, blocking payment. The public
    # URL runs OUTSIDE ``<AppLayout>`` (see App.js) so no login is
    # ever required; the token there is a 30-day pay-only JWT tied
    # to the invoice + tenant.  ``portal_cta_url`` is retained for
    # backwards-compat callers but is now IGNORED for the Pay Now
    # button.  See DIAG_PAY_LINK_LOGIN_REDIRECT_BUG.md for the full
    # RCA.
    _ = portal_cta_url  # kwarg retained for callsite compatibility
    from services.pay_link_builder import build_pay_now_url
    pay_link = build_pay_now_url(
        inv["id"], inv.get("tenant_id") or "", src="email",
    )
    link_html = f'<p><a href="{pay_link}" style="background:#0891b2;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">Pay Now</a></p>' if pay_link else ""
    # Phase B1 · Feb 2026 — F2b attachment-count copy.
    n = max(0, int(attachment_count or 0))
    attach_html = ""
    if n > 0:
        noun = "attachment" if n == 1 else "attachments"
        attach_html = (
            f'<p style="font-size:13px;color:#475569;margin:8px 0 0;">'
            f'{n} {noun} included</p>'
        )
    # Feb-2026 · P0 template bug fix — substitute the invoice's
    # customer-facing number instead of the (legacy) title field,
    # which stored the doc_type label ("Estimate") on some prod
    # rows and produced "invoice Estimate has an outstanding
    # balance…". Full RCA in DIAG_ESTIMATE_INVOICE_REMINDER_BUG.md.
    doc_number = _invoice_display_number(inv)
    return (
        f'<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        f"<h2>Payment reminder</h2><p>Hi {name},</p>"
        f"<p>This is a friendly reminder that invoice <b>{doc_number}</b> has an outstanding balance of "
        f"<b>${balance:,.2f}</b> (was due {due}).</p>{attach_html}{link_html}"
        f"<p>Thank you,<br/>Pool &amp; Landscaping of Vistancia</p></div>"
    )


def _estimate_reminder_html(inv: dict, name: str, tenant: dict,
                                review_url: str,
                                attachment_count: int = 0) -> str:
    """Feb-2026 · P0 fix — Estimate/Quote reminder template.

    Fundamentally different from the invoice reminder:
      * no "outstanding balance" / "was due" / "Pay Now" copy — an
        estimate awaits a **decision**, not a payment.
      * CTA points to the customer-facing magic-link viewer
        (``/e/estimate?token=…``) which lets the customer approve,
        request changes, or decline.
      * The doc-type label ("estimate" vs "quote") is derived from
        ``inv.doc_type`` so the sender-shipped copy matches the
        header the customer sees on the portal page.
    """
    doc_type_label = "quote" if inv.get("doc_type") == "quote" else "estimate"
    doc_number = _invoice_display_number(inv)
    company = (tenant or {}).get("company_name") or "your service provider"
    n = max(0, int(attachment_count or 0))
    attach_html = ""
    if n > 0:
        noun = "attachment" if n == 1 else "attachments"
        attach_html = (
            f'<p style="font-size:13px;color:#475569;margin:8px 0 0;">'
            f'{n} {noun} included</p>'
        )
    cta = ""
    if review_url:
        cta = (
            f'<p><a href="{review_url}" '
            f'style="background:#0891b2;color:#fff;padding:12px 20px;'
            f'border-radius:8px;text-decoration:none;display:inline-block">'
            f'Review {doc_type_label.title()}</a></p>'
        )
    # Feb-2026 · Task 6 — Terms & Conditions block on estimate/quote
    # reminders only (invoices excluded per lock). Rendered as a
    # subdued, collapsible-looking panel so the CTA remains primary.
    terms_html = ""
    _terms_body = (inv.get("terms") or "").strip()
    if _terms_body:
        _safe_terms = (
            _terms_body
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        terms_html = (
            '<div style="margin-top:24px;padding:14px 16px;background:#F9FAFB;'
            'border:1px solid #E5E7EB;border-radius:10px;font-size:12px;'
            'line-height:1.6;color:#475569;">'
            '<div style="font-weight:700;color:#0F172A;margin-bottom:6px;">'
            'Terms &amp; Conditions</div>'
            f'<div>{_safe_terms}</div></div>'
        )
    return (
        f'<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        f"<h2>Reminder: your {doc_type_label}</h2>"
        f"<p>Hi {name},</p>"
        f"<p>This is a friendly reminder that {doc_type_label} "
        f"<b>{doc_number}</b> from {company} is awaiting your review. "
        f"Please take a moment to approve, request changes, or decline.</p>"
        f"{attach_html}{cta}{terms_html}"
        f"<p>Thank you,<br/>{company}</p></div>"
    )


async def send_invoice_reminder_email(inv: dict) -> bool:
    """Email the customer a payment reminder for an outstanding invoice.

    Feb-2026 · P0 refusal — this fn now REFUSES to fire for any doc
    whose ``doc_type`` is not ``invoice``. The old shape would happily
    email "invoice Estimate has an outstanding balance…" to customers
    on a quote/estimate detail page. The refusal returns ``False`` and
    logs a warning so callers can migrate to
    :func:`send_estimate_reminder_email`.
    """
    # Feb-2026 · P0 template-guard — invoice-only path.
    doc_type = str(inv.get("doc_type") or "invoice").lower()
    if doc_type != "invoice":
        logger.warning(
            "[emailer] refusing invoice-reminder shape for doc_type=%s id=%s "
            "— callers must switch to send_estimate_reminder_email()",
            doc_type, inv.get("id"),
        )
        return False
    if not RESEND_API_KEY:
        logger.info("Resend not configured — skipping invoice reminder email.")
        return False
    cid = inv.get("customer_id")
    if not cid:
        return False
    cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
    to_email = cust.get("email")
    if not to_email:
        user = await db.users.find_one({"customer_id": cid, "role": "customer"}, {"_id": 0})
        to_email = user.get("email") if user else None
    if not to_email:
        logger.info("No customer email — skipping reminder email.")
        return False
    # Phase 34 · Task L · Feb-2026 — outbound safety guard.
    from services.comms_env_guard import guard_outbound
    verdict = guard_outbound(kind="email", to=to_email)
    if verdict.blocked:
        logger.info(
            "[DRY-RUN] emailer.send_invoice_reminder_email SKIPPED to=%s inv=%s",
            to_email, inv.get("id"),
        )
        return False
    # Phase B1 · F2b polish — count F0 attachments linked to this
    # invoice (purpose=invoice_attachment, linked_entity_id=inv.id) so
    # the email copy can surface "N attachments included" above the
    # CTA. Query is best-effort; on failure we send without the line.
    try:
        attachment_count = await db.files.count_documents({
            "purpose": "invoice_attachment",
            "linked_entity_id": inv.get("id"),
            "deleted_at": None,
        })
    except Exception:                                                # noqa: BLE001
        attachment_count = 0
    # Feb-2026 · P0 Pay-link routing fix — do NOT mint the portal
    # auto-login URL for the Pay Now CTA any more. The public
    # pay-sheet URL from ``build_pay_now_url`` is now the sole
    # target so an expired token can never route the customer
    # through ``/portal/login?reason=link_expired``. The template
    # itself calls ``build_pay_now_url`` internally so we pass an
    # empty string here and keep the kwarg for API compatibility.
    portal_cta_url = ""
    try:
        resend.api_key = RESEND_API_KEY
        # Feb-2026 · P0 subject fix — no more "Payment reminder —
        # Estimate" chimera. Use the invoice's display number.
        subject_num = _invoice_display_number(inv)
        # Feb-2026 · Email Base Template Theming — wrap the caller's
        # HTML in the branded shell. Branding is resolved ONCE per
        # send (this function is single-recipient; multi-contact
        # fan-out resolves branding once in its outer loop and
        # threads the dict — this call is a single email so the
        # in-line resolve is safe).
        try:
            branding = await get_effective_business_settings(
                db, inv.get("tenant_id") or "", absolutize=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"branding resolve failed, using defaults: {e}")
            branding = {}
        themed_html = wrap_html_in_shell(
            _reminder_html(inv, cust.get("name", "there"),
                             attachment_count=attachment_count,
                             portal_cta_url=portal_cta_url),
            branding,
        )
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": to_email,
            "subject": f"Payment reminder — invoice {subject_num}",
            "html": themed_html,
        })
        return True
    except Exception as e:
        logger.warning(f"Reminder email failed: {e}")
        return False


async def send_estimate_reminder_email(inv: dict, tenant: dict,
                                          review_url: str,
                                          *, override_to: Optional[str] = None) -> bool:
    """Feb-2026 · P0 — Email the customer a review reminder for a
    pending estimate/quote. Distinct from ``send_invoice_reminder_email``
    in template, subject, and CTA URL. Never mentions "balance",
    "amount due", or "Pay Now".

    Feb-2026 · UX Polish Batch B — accepts an optional ``override_to``
    kwarg used by the composed ``send-to-customer`` endpoint when an
    admin explicitly targets a non-primary email (e.g. spouse /
    property manager). Falls through to the customer lookup below
    when ``override_to`` is missing/blank."""
    doc_type = str(inv.get("doc_type") or "estimate").lower()
    if doc_type not in ("estimate", "quote"):
        logger.warning(
            "[emailer] refusing estimate-reminder for doc_type=%s id=%s",
            doc_type, inv.get("id"),
        )
        return False
    if not RESEND_API_KEY:
        logger.info(
            "Resend not configured — skipping estimate reminder email.",
        )
        return False
    cid = inv.get("customer_id")
    if not cid:
        return False
    cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
    # Admin-supplied override wins over the customer's primary email.
    to_email = (override_to or "").strip() or cust.get("email")
    if not to_email:
        user = await db.users.find_one(
            {"customer_id": cid, "role": "customer"}, {"_id": 0},
        )
        to_email = user.get("email") if user else None
    if not to_email:
        logger.info("No customer email — skipping estimate reminder email.")
        return False
    from services.comms_env_guard import guard_outbound
    verdict = guard_outbound(kind="email", to=to_email)
    if verdict.blocked:
        logger.info(
            "[DRY-RUN] emailer.send_estimate_reminder_email SKIPPED "
            "to=%s doc_id=%s",
            to_email, inv.get("id"),
        )
        return False
    try:
        attachment_count = await db.files.count_documents({
            "purpose": "invoice_attachment",  # legacy label — same collection
            "linked_entity_id": inv.get("id"),
            "deleted_at": None,
        })
    except Exception:  # noqa: BLE001
        attachment_count = 0
    doc_type_label = "quote" if doc_type == "quote" else "estimate"
    company = (tenant or {}).get("company_name") or "your service provider"
    try:
        resend.api_key = RESEND_API_KEY
        # Feb-2026 · Email Base Template Theming — wrap in shared shell.
        try:
            branding = await get_effective_business_settings(
                db, (tenant or {}).get("id") or inv.get("tenant_id") or "",
                absolutize=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"branding resolve failed, using defaults: {e}")
            branding = {}
        themed_html = wrap_html_in_shell(
            _estimate_reminder_html(
                inv, cust.get("name", "there"),
                tenant or {}, review_url,
                attachment_count=attachment_count,
            ),
            branding,
        )
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": to_email,
            "subject": f"Reminder: your {doc_type_label} from {company}",
            "html": themed_html,
        })
        return True
    except Exception as e:
        logger.warning(f"Estimate reminder email failed: {e}")
        return False
