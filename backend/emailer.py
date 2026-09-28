from typing import Optional

from config import db, logger, RESEND_API_KEY, APP_PUBLIC_URL
# SAFE-SEND-C · Feb-2026 — migrated from direct ``resend.Emails.send``
# to the SAFE-SEND-gated adapter.  All three send fns now pass
# ``context=CommsContext.SYSTEM`` (production transactional).  The
# adapter runs suppression, is_comm_allowed, K72 kill-switch,
# ``guard_outbound``, BYO probe, testmode, and the retry loop
# internally; we consume its envelope + return the legacy ``bool``
# contract to callers.
from services.comms_env_guard import CommsContext
from services.email.resend_adapter import send as _resend_send
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


def _completion_html(job: dict, customer_name: str,
                       *, locale: str = "en") -> str:
    """Feb-2026 · Phase D6 — subject + body copy resolved via
    :func:`services.email_body_i18n.t_email_body`.

    The HTML skeleton (branded shell, table cells, CTA button
    styling) stays hardcoded — only the customer-facing sentences
    are catalogued. Callers pass an already-resolved locale (via
    :func:`services.i18n.email_locale.resolve_email_locale`).
    """
    from services.email_body_i18n import t_email_body
    report_url = f"{APP_PUBLIC_URL}/job/{job['id']}"
    service = job.get("service_type", "service")
    when = (job.get("scheduled_date") or "")[:10]
    heading = t_email_body(locale, "email.job_completed.heading")
    if when:
        body_line = t_email_body(
            locale, "email.job_completed.body_with_date",
            customer_name=customer_name, service_type=service, when=when,
        )
    else:
        body_line = t_email_body(
            locale, "email.job_completed.body_no_date",
            customer_name=customer_name, service_type=service,
        )
    cta_label = t_email_body(
        locale, "email.job_completed.cta_view_report",
    )
    support_line = t_email_body(
        locale, "email.job_completed.support_line",
    )
    # Photos block heading is threaded into ``_thumbs_html`` via a
    # locale-aware pre-render so the caption localises alongside the
    # rest of the body.
    photos_heading = t_email_body(
        locale, "email.job_completed.photos_heading",
    )
    thumbs = _thumbs_html_with_heading(job, photos_heading)
    return f"""
    <div style="max-width:560px;margin:0 auto;font-family:Arial,sans-serif;color:#1A2B3C;">
      <div style="background:#003C5F;padding:24px;border-radius:12px 12px 0 0;">
        <h1 style="color:#fff;margin:0;font-size:20px;">Pool &amp; Landscaping of Vistancia</h1>
      </div>
      <div style="border:1px solid #E2E8F0;border-top:none;border-radius:0 0 12px 12px;padding:24px;">
        <h2 style="font-size:18px;margin:0 0 8px;">{heading} ✅</h2>
        <p style="font-size:14px;color:#334155;line-height:20px;margin:0 0 4px;">
          {body_line}
        </p>
        {thumbs}
        <div style="text-align:center;margin:28px 0 8px;">
          <a href="{report_url}"
             style="background:#0EA5B7;color:#fff;text-decoration:none;font-size:15px;font-weight:bold;
                    padding:14px 28px;border-radius:10px;display:inline-block;">
            {cta_label}
          </a>
        </div>
        <p style="font-size:12px;color:#94A3B8;text-align:center;margin:12px 0 0;">
          {support_line}
        </p>
      </div>
    </div>
    """


def _thumbs_html_with_heading(job: dict, heading: str) -> str:
    """Same as :func:`_thumbs_html` but with a locale-injected
    heading. Kept as a separate function so
    :func:`send_completion_email`'s locale plumbing doesn't force
    every other caller of ``_thumbs_html`` (none today, but
    future-proofing) to thread a locale kwarg they don't need."""
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
        f"{heading}</p>"
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0"><tr>'
        f"{cells}</tr></table>"
    )


async def send_completion_email(job: dict) -> bool:
    """Email the customer that their job is complete, with photo thumbnails + a report link.

    Feb-2026 · Phase D6 — subject + body copy resolved through the
    D6 i18n catalog. Locale is derived from the customer doc, then
    tenant default, then falls back to ``en``.
    """
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
    # Phase D6 · Feb-2026 — resolve recipient locale for subject +
    # body i18n. Tenant default is optional (best-effort lookup).
    try:
        _tenant = await db.tenants.find_one(
            {"id": job.get("tenant_id")},
            {"_id": 0, "default_locale": 1},
        ) if job.get("tenant_id") else None
    except Exception:  # noqa: BLE001
        _tenant = None
    from services.i18n.email_locale import resolve_email_locale
    from services.email_body_i18n import t_email_body
    _locale = resolve_email_locale(recipient=cust, tenant=_tenant)
    try:
        res = await _resend_send(
            to=to_email,
            subject=t_email_body(
                _locale, "email.job_completed.subject",
                service_type=job.get("service_type", "service"),
            ),
            html=_completion_html(
                job, cust.get("name", "there"), locale=_locale,
            ),
            category="transactional",
            tenant_id=job.get("tenant_id"),
            audience="customer",
            context=CommsContext.SYSTEM,
        )
        return res.get("provider_status") in (
            "sent", "queued", "mocked", "dry_run",
        )
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
                     portal_cta_url: str = "",
                     locale: str = "en") -> str:
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
    # backwards-compat callers but is now IGNORED for the CTA
    # button.  See DIAG_PAY_LINK_LOGIN_REDIRECT_BUG.md for the full
    # RCA.
    _ = portal_cta_url  # kwarg retained for callsite compatibility
    from services.pay_link_builder import build_pay_now_url
    from services.email_cta_i18n import t_email_cta
    pay_link = build_pay_now_url(
        inv["id"], inv.get("tenant_id") or "", src="email",
    )
    # Feb 2026 · Invoice Email CTA Label — CTA text renames from
    # "Pay Now" to the localised "View Invoice" so all invoice-
    # adjacent emails point the customer at the viewer (Pay Now
    # lives on the viewer page itself, restyled full-width red).
    cta_label = t_email_cta(locale, "view_invoice")
    link_html = (
        f'<p><a href="{pay_link}" '
        f'style="background:#DC2626;color:#fff;padding:12px 20px;'
        f'border-radius:8px;text-decoration:none;display:inline-block;'
        f'font-size:22px;font-weight:700;">'
        f'{cta_label}</a></p>'
    ) if pay_link else ""
    # Phase B1 · Feb 2026 — F2b attachment-count copy.
    # Phase D6 · Feb 2026 — pluralised via the i18n catalog so the
    # ``1 attachment / N attachments`` singular/plural split is
    # translator-controlled per locale.
    n = max(0, int(attachment_count or 0))
    attach_html = ""
    if n > 0:
        from services.email_body_i18n import t_email_body as _t
        line_key = (
            "email.invoice_reminder.attachments_one" if n == 1
            else "email.invoice_reminder.attachments_many"
        )
        attach_line = _t(locale, line_key, count=n)
        attach_html = (
            f'<p style="font-size:13px;color:#475569;margin:8px 0 0;">'
            f'{attach_line}</p>'
        )
    # Feb-2026 · P0 template bug fix — substitute the invoice's
    # customer-facing number instead of the (legacy) title field,
    # which stored the doc_type label ("Estimate") on some prod
    # rows and produced "invoice Estimate has an outstanding
    # balance…". Full RCA in DIAG_ESTIMATE_INVOICE_REMINDER_BUG.md.
    doc_number = _invoice_display_number(inv)
    # Phase D6 · Feb 2026 — the customer-facing sentences (heading,
    # greeting, body, thanks) are catalogued via ``t_email_body``.
    # Only the HTML skeleton stays hardcoded.
    from services.email_body_i18n import t_email_body
    heading = t_email_body(locale, "email.invoice_reminder.heading")
    greeting = t_email_body(
        locale, "email.invoice_reminder.greeting",
        customer_name=name,
    )
    body_line = t_email_body(
        locale, "email.invoice_reminder.body",
        invoice_number=doc_number,
        balance=f"{balance:,.2f}",
        due_date=due,
    )
    thanks = t_email_body(
        locale, "email.invoice_reminder.thanks",
        company="Pool &amp; Landscaping of Vistancia",
    )
    return (
        f'<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        f"<h2>{heading}</h2><p>{greeting}</p>"
        f"<p>{body_line}</p>{attach_html}{link_html}"
        f"<p>{thanks}</p></div>"
    )


def _human_size(nbytes: int) -> str:
    """Compact 'x B / x KB / x MB' formatter shared by the reminder
    email attachment link list. Never returns negative numbers.
    """
    n = max(0, int(nbytes or 0))
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _estimate_reminder_html(inv: dict, name: str, tenant: dict,
                                review_url: str,
                                attachment_count: int = 0,
                                attachments: Optional[list] = None,
                                magic_token: str = "",
                                *, locale: str = "en",
                                ) -> str:
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

    Phase D6 · Feb-2026 — subject + body copy resolved via
    :func:`services.email_body_i18n.t_email_body`. The doc-type
    label is also catalogued so ``estimate`` → ``presupuesto`` /
    ``devis`` (etc.) renders correctly on the ``<h2>`` and the CTA
    button.
    """
    from services.email_body_i18n import t_email_body
    is_quote = inv.get("doc_type") == "quote"
    doc_type_key = ("email.estimate_reminder.doc_type.quote"
                     if is_quote
                     else "email.estimate_reminder.doc_type.estimate")
    doc_type_label = t_email_body(locale, doc_type_key)
    doc_number = _invoice_display_number(inv)
    company = (tenant or {}).get("company_name") or "your service provider"
    # Feb-2026 · Public Quote Attachments — prefer a clickable list
    # over the legacy count-only copy when the caller passed a
    # per-attachment list AND the reminder's ``magic_token``. Each
    # link resolves against the SAME public token-scoped file route
    # the customer viewer already uses, so there's zero extra auth
    # to hand-roll. Falls back to the count copy when the list is
    # empty or the token is missing (legacy callers).
    _attach_list = list(attachments or [])
    n = max(0, int(attachment_count if attachment_count else len(_attach_list)))
    attach_html = ""
    if _attach_list and magic_token:
        _base = (APP_PUBLIC_URL or "").rstrip("/")
        _rows_html = ""
        for att in _attach_list:
            _fid = att.get("id")
            if not _fid:
                continue
            _fname = (att.get("filename") or _fid)
            _size_str = _human_size(att.get("size"))
            _rel = (
                f"/api/portal/quotes/via-token/files/{_fid}"
                f"?token={magic_token}"
            )
            _href = f"{_base}{_rel}" if _base else _rel
            _rows_html += (
                f'<li style="margin:6px 0;">'
                f'<a href="{_href}" '
                f'style="color:#0891b2;text-decoration:none;font-weight:600;">'
                f'{_fname}</a>'
                f' <span style="color:#64748b;font-size:12px;">'
                f'({_size_str})</span></li>'
            )
        if _rows_html:
            _attach_heading = t_email_body(
                locale, "email.estimate_reminder.attachments_heading",
            )
            attach_html = (
                '<div style="margin-top:14px;padding:12px 16px;'
                'background:#F8FAFC;border:1px solid #E2E8F0;'
                'border-radius:10px;">'
                '<div style="font-weight:700;color:#0F172A;'
                f'font-size:13px;margin-bottom:4px;">{_attach_heading}</div>'
                f'<ul style="margin:0;padding-left:18px;">{_rows_html}</ul>'
                '</div>'
            )
    elif n > 0:
        _line_key = ("email.estimate_reminder.attachments_one" if n == 1
                     else "email.estimate_reminder.attachments_many")
        _attach_line = t_email_body(locale, _line_key, count=n)
        attach_html = (
            f'<p style="font-size:13px;color:#475569;margin:8px 0 0;">'
            f'{_attach_line}</p>'
        )
    cta = ""
    if review_url:
        cta_label = t_email_body(
            locale, "email.estimate_reminder.cta_review",
            doc_type_label_titled=doc_type_label.title(),
        )
        cta = (
            f'<p><a href="{review_url}" '
            f'style="background:#0891b2;color:#fff;padding:12px 20px;'
            f'border-radius:8px;text-decoration:none;display:inline-block">'
            f'{cta_label}</a></p>'
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
        _terms_heading = t_email_body(
            locale, "email.estimate_reminder.terms_heading",
        )
        terms_html = (
            '<div style="margin-top:24px;padding:14px 16px;background:#F9FAFB;'
            'border:1px solid #E5E7EB;border-radius:10px;font-size:12px;'
            'line-height:1.6;color:#475569;">'
            '<div style="font-weight:700;color:#0F172A;margin-bottom:6px;">'
            f'{_terms_heading}</div>'
            f'<div>{_safe_terms}</div></div>'
        )
    heading = t_email_body(
        locale, "email.estimate_reminder.heading",
        doc_type_label=doc_type_label,
    )
    greeting = t_email_body(
        locale, "email.estimate_reminder.greeting", customer_name=name,
    )
    body_line = t_email_body(
        locale, "email.estimate_reminder.body",
        doc_type_label=doc_type_label,
        doc_number=doc_number, company=company,
    )
    thanks = t_email_body(
        locale, "email.estimate_reminder.thanks", company=company,
    )
    return (
        f'<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        f"<h2>{heading}</h2>"
        f"<p>{greeting}</p>"
        f"<p>{body_line}</p>"
        f"{attach_html}{cta}{terms_html}"
        f"<p>{thanks}</p></div>"
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
    # Feb 2026 · Invoice Email CTA Label — resolve the recipient
    # locale so the "View Invoice" CTA renders in the customer's
    # language (customer.locale → tenant.default_locale → "en").
    # Phase D6 · Feb-2026 — route through the D6 shared resolver so
    # the subject line + body sentences use the same locale as the
    # CTA button.
    try:
        _tenant = await db.tenants.find_one(
            {"id": inv.get("tenant_id")}, {"_id": 0, "default_locale": 1},
        ) if inv.get("tenant_id") else None
    except Exception:                                                # noqa: BLE001
        _tenant = None
    from services.i18n.email_locale import resolve_email_locale
    from services.email_body_i18n import t_email_body
    _locale = resolve_email_locale(recipient=cust, tenant=_tenant)
    # Feb-2026 · P0 Pay-link routing fix — do NOT mint the portal
    # auto-login URL for the Pay Now CTA any more. The public
    # pay-sheet URL from ``build_pay_now_url`` is now the sole
    # target so an expired token can never route the customer
    # through ``/portal/login?reason=link_expired``. The template
    # itself calls ``build_pay_now_url`` internally so we pass an
    # empty string here and keep the kwarg for API compatibility.
    portal_cta_url = ""
    try:
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
                             portal_cta_url=portal_cta_url,
                             locale=_locale),
            branding,
        )
        res = await _resend_send(
            to=to_email,
            subject=t_email_body(
                _locale, "email.invoice_reminder.subject",
                invoice_number=subject_num,
            ),
            html=themed_html,
            category="transactional",
            tenant_id=inv.get("tenant_id"),
            audience="customer",
            context=CommsContext.SYSTEM,
        )
        return res.get("provider_status") in (
            "sent", "queued", "mocked", "dry_run",
        )
    except Exception as e:
        logger.warning(f"Reminder email failed: {e}")
        return False


async def send_estimate_reminder_email(inv: dict, tenant: dict,
                                          review_url: str,
                                          *,
                                          override_to: Optional[str] = None,
                                          magic_token: str = "",
                                          ) -> bool:
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
        # Feb-2026 · Public Quote Attachments — pull the per-file
        # rows (id + filename + size) so the template can render a
        # click-through list. Falls back to the count-only copy
        # inside ``_estimate_reminder_html`` when either the list is
        # empty OR the caller didn't pass a ``magic_token`` (legacy
        # callsites). ``is_deleted != True`` matches the files.py
        # convention (missing OR false).
        _files = await db.files.find(
            {
                "tenant_id": inv.get("tenant_id"),
                "purpose": "invoice_attachment",
                "linked_entity_type": "invoice",
                "linked_entity_id": inv.get("id"),
                "is_deleted": {"$ne": True},
            },
            {
                "_id": 0, "id": 1, "original_filename": 1,
                "content_type": 1, "size": 1, "created_at": 1,
            },
        ).sort("created_at", -1).to_list(500)
        _attachments = [
            {
                "id": r.get("id"),
                "filename": r.get("original_filename") or r.get("id"),
                "content_type": (
                    r.get("content_type") or "application/octet-stream"
                ),
                "size": int(r.get("size") or 0),
            }
            for r in _files if r.get("id")
        ]
        attachment_count = len(_attachments)
    except Exception:  # noqa: BLE001
        _attachments = []
        attachment_count = 0
    doc_type_label = "quote" if doc_type == "quote" else "estimate"
    company = (tenant or {}).get("company_name") or "your service provider"
    # Phase D6 · Feb-2026 — resolve locale for subject + body i18n.
    from services.i18n.email_locale import resolve_email_locale
    from services.email_body_i18n import t_email_body
    _locale = resolve_email_locale(recipient=cust, tenant=tenant)
    _localized_dt_label = t_email_body(
        _locale,
        ("email.estimate_reminder.doc_type.quote" if doc_type == "quote"
         else "email.estimate_reminder.doc_type.estimate"),
    )
    try:
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
                attachments=_attachments,
                magic_token=magic_token,
                locale=_locale,
            ),
            branding,
        )
        res = await _resend_send(
            to=to_email,
            subject=t_email_body(
                _locale, "email.estimate_reminder.subject",
                doc_type_label=_localized_dt_label, company=company,
            ),
            html=themed_html,
            category="transactional",
            tenant_id=(tenant or {}).get("id") or inv.get("tenant_id"),
            audience="customer",
            context=CommsContext.SYSTEM,
        )
        return res.get("provider_status") in (
            "sent", "queued", "mocked", "dry_run",
        )
    except Exception as e:
        logger.warning(f"Estimate reminder email failed: {e}")
        return False
