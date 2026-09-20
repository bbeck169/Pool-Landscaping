"""Phase D6 · Feb-2026 — dynamic email body copy translation catalog.

Follows the exact pattern established by :mod:`services.email_cta_i18n`
(the "Pay Now" → "View Invoice" CTA translation catalog) so callers
that already thread a locale through ``t_email_cta`` can adopt this
helper without a new mental model.

Contract
--------
* ``LABELS[locale][key]`` is a Python ``str.format``-compatible
  template with named ``{placeholder}`` tokens. ``t_email_body``
  substitutes them; missing tokens raise :class:`KeyError` so a
  literal ``{customer_name}`` never lands in a real inbox.
* Unknown locale → English fallback (identical semantics to
  ``email_cta_i18n``).
* Unknown key → :class:`KeyError` (a programming error, not a
  translation gap).
* Missing key under the requested locale but present under
  English → renders the English variant (translation gap, not a
  code bug).

Supported locales mirror the D5 SMS + email pipeline: ``en``,
``es``, ``fr``. No new locales are added in this phase per the D6
scope lock.

Key namespace convention
------------------------
``email.<template>.<field>`` — e.g.::

    email.invoice_reminder.subject
    email.invoice_reminder.heading
    email.invoice_reminder.body
    email.invoice_reminder.thanks

Full sentences are catalogued as ONE key each — never concatenate
fragments across translations. Adding a new key is a symmetric
three-locale edit (miss one and the drift-guard pytest fires).
"""
from __future__ import annotations

import string
from typing import Any, Dict

__all__ = [
    "FALLBACK_LOCALE",
    "SUPPORTED_LOCALES",
    "t_email_body",
    "LABELS",
]

SUPPORTED_LOCALES = ("en", "es", "fr")
FALLBACK_LOCALE = "en"


# Namespace: nested dict keyed by locale → key → template string.
LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        # ── Invoice reminder ─────────────────────────────────────
        "email.invoice_reminder.subject":
            "Payment reminder — invoice {invoice_number}",
        "email.invoice_reminder.heading": "Payment reminder",
        "email.invoice_reminder.greeting": "Hi {customer_name},",
        "email.invoice_reminder.body":
            "This is a friendly reminder that invoice "
            "<b>{invoice_number}</b> has an outstanding balance of "
            "<b>${balance}</b> (was due {due_date}).",
        "email.invoice_reminder.attachments_one":
            "{count} attachment included",
        "email.invoice_reminder.attachments_many":
            "{count} attachments included",
        "email.invoice_reminder.thanks":
            "Thank you,<br/>{company}",

        # ── Estimate / quote reminder ────────────────────────────
        "email.estimate_reminder.subject":
            "Reminder: your {doc_type_label} from {company}",
        "email.estimate_reminder.heading":
            "Reminder: your {doc_type_label}",
        "email.estimate_reminder.greeting": "Hi {customer_name},",
        "email.estimate_reminder.body":
            "This is a friendly reminder that {doc_type_label} "
            "<b>{doc_number}</b> from {company} is awaiting your "
            "review. Please take a moment to approve, request "
            "changes, or decline.",
        "email.estimate_reminder.cta_review":
            "Review {doc_type_label_titled}",
        "email.estimate_reminder.terms_heading":
            "Terms &amp; Conditions",
        "email.estimate_reminder.thanks":
            "Thank you,<br/>{company}",
        "email.estimate_reminder.doc_type.estimate": "estimate",
        "email.estimate_reminder.doc_type.quote": "quote",
        "email.estimate_reminder.attachments_heading": "Attachments",
        "email.estimate_reminder.attachments_one":
            "{count} attachment included",
        "email.estimate_reminder.attachments_many":
            "{count} attachments included",

        # ── Job completion ───────────────────────────────────────
        "email.job_completed.subject":
            "Your {service_type} is complete",
        "email.job_completed.heading":
            "Your service is complete",
        "email.job_completed.body_with_date":
            "Hi {customer_name}, we've finished your "
            "<strong>{service_type}</strong> on {when}. "
            "Your full service report — checklist, water readings "
            "and chemicals added — is ready to view.",
        "email.job_completed.body_no_date":
            "Hi {customer_name}, we've finished your "
            "<strong>{service_type}</strong>. "
            "Your full service report — checklist, water readings "
            "and chemicals added — is ready to view.",
        "email.job_completed.cta_view_report":
            "View Your Service Report",
        "email.job_completed.photos_heading":
            "Photos from your visit:",
        "email.job_completed.support_line":
            "Questions? Just reply in the app and our team "
            "(and Marina, our assistant) will help.",

        # ── Dunning stages (used by routers/dunning.py) ──────────
        # Namespace is ``dunning.<stage_id>.<field>``.
        "dunning.pre_due_3d.subject":
            "Reminder: invoice {invoice_number} due in 3 days",
        "dunning.pre_due_3d.body":
            "Hi {customer_name},\n\n"
            "Just a friendly reminder that invoice "
            "{invoice_number} for ${invoice_total} is due on "
            "{due_date}.\n\n"
            "View invoice: {payment_link}\n\n"
            "Thanks,\n{tenant_name}",
        "dunning.pre_due_3d.sms":
            "{tenant_name}: invoice {invoice_number} "
            "(${invoice_total}) due {due_date}. Pay: {payment_link}",

        "dunning.on_due_day.subject":
            "Invoice {invoice_number} is due today",
        "dunning.on_due_day.body":
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} for ${invoice_total} is due "
            "today. View invoice: {payment_link}\n\n"
            "Thanks,\n{tenant_name}",
        "dunning.on_due_day.sms":
            "{tenant_name}: invoice {invoice_number} "
            "(${invoice_total}) is due today. Pay: {payment_link}",

        "dunning.past_due_7d.subject":
            "Past due: invoice {invoice_number} ({days_past_due}d)",
        "dunning.past_due_7d.body":
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} for ${invoice_total} is now "
            "{days_past_due} days past due. Please settle at your "
            "earliest convenience.\n\n"
            "View invoice: {payment_link}\n\n"
            "Questions? Call {tenant_phone}.\n\n{tenant_name}",
        "dunning.past_due_7d.sms":
            "{tenant_name}: invoice {invoice_number} is "
            "{days_past_due}d past due (${invoice_total}). "
            "Pay: {payment_link}",

        "dunning.past_due_14d.subject":
            "Second notice: invoice {invoice_number}",
        "dunning.past_due_14d.body":
            "Hi {customer_name},\n\n"
            "This is a second reminder that invoice "
            "{invoice_number} for ${invoice_total} is "
            "{days_past_due} days past due. Please pay to avoid "
            "further follow-up.\n\n"
            "View invoice: {payment_link}\n\n"
            "{tenant_name} · {tenant_phone}",
        "dunning.past_due_14d.sms":
            "{tenant_name}: SECOND NOTICE — invoice "
            "{invoice_number} is {days_past_due}d past due. "
            "Pay: {payment_link}",

        "dunning.past_due_30d.subject":
            "Final notice: invoice {invoice_number}",
        "dunning.past_due_30d.body":
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} is now 30+ days past due. "
            "This is our final courtesy reminder before your "
            "account is flagged at risk. Please pay "
            "${invoice_total} today.\n\n"
            "View invoice: {payment_link}\n\n"
            "{tenant_name} · {tenant_phone}",
        "dunning.past_due_30d.sms":
            "{tenant_name}: FINAL NOTICE — invoice "
            "{invoice_number} is 30d+ past due "
            "(${invoice_total}). Pay: {payment_link}",

        "dunning.past_due_60d.subject":
            "Collections notice: invoice {invoice_number}",
        "dunning.past_due_60d.body":
            "Hi {customer_name},\n\n"
            "Invoice {invoice_number} (${invoice_total}) is now "
            "60+ days past due. Your account has been flagged for "
            "collections. Please contact us immediately at "
            "{tenant_phone}.\n\n"
            "View invoice: {payment_link}\n\n{tenant_name}",
        "dunning.past_due_60d.sms":
            "{tenant_name}: your account is flagged for "
            "collections. Invoice {invoice_number} 60d+ past due. "
            "Call {tenant_phone}.",

        # ── D6.2 · Password reset (routers/admin_users.py) ───────
        "email.password_reset.subject":
            "Your {company_name} password was reset",
        "email.password_reset.heading": "Password reset by admin",
        "email.password_reset.body_intro":
            "Hi {target_name}, {actor_name} reset your "
            "{company_name} password. Sign in with the temporary "
            "password below — you'll be asked to choose a new "
            "password immediately on first login.",
        "email.password_reset.temp_password_label":
            "Temporary password",
        "email.password_reset.cta_sign_in": "Sign in",
        "email.password_reset.footer_security":
            "If this wasn't you, contact your administrator "
            "immediately.",

        # ── D6.2 · Trial-billing fallback strings (services/tenant_billing_reminders.py) ──
        # These get substituted into the D5-localised
        # ``trial_ending_reminder`` template when the Stripe lookup
        # or admin doc doesn't provide a value. Localising them
        # keeps the surrounding sentence coherent per-locale.
        "email.trial_reminder.fallback.plan_amount": "your plan pricing",
        "email.trial_reminder.fallback.admin_name": "there",
        "email.trial_reminder.fallback.business_name": "your business",

        # ── D6.2 · Lead alert (services/lead_notifications.py) ───
        "email.lead_alert.subject.with_phone":
            "New lead — {name} ({phone})",
        "email.lead_alert.subject.no_phone":
            "New lead — {name}",
        "email.lead_alert.heading":
            "New lead — {name}",
        "email.lead_alert.field.name":             "Name",
        "email.lead_alert.field.phone":            "Phone",
        "email.lead_alert.field.email":            "Email",
        "email.lead_alert.field.address":          "Address",
        "email.lead_alert.field.service_address":  "Service address",
        "email.lead_alert.field.service_interest": "Service interest",
        "email.lead_alert.cta_view": "View lead in admin",
        "email.lead_alert.website_visitor": "Website Visitor",
        "sms.lead_alert.header": "New lead — {name}",
        "sms.lead_alert.view_link": "View: {url}",

        # ── D6.2 · Monthly pricing digest (services/monthly_pricing_digest.py) ──
        "email.monthly_pricing_digest.subject":
            "{tenant_name} · Monthly Pricing Insights · {month}",
        "email.monthly_pricing_digest.title":
            "{tenant_name} · Monthly Pricing Insights",
        "email.monthly_pricing_digest.subtitle":
            "{month} · least-profitable service types + "
            "AI-drafted price increases",
        "email.monthly_pricing_digest.col.service":   "Service",
        "email.monthly_pricing_digest.col.pricing":   "Pricing",
        "email.monthly_pricing_digest.col.rationale":
            "Rationale · Talking Points",
        "email.monthly_pricing_digest.jobs_and_margin":
            "{count} jobs · margin {margin_pct}%",
        "email.monthly_pricing_digest.current_avg": "Current avg:",
        "email.monthly_pricing_digest.recommend":   "Recommend:",
        "email.monthly_pricing_digest.margin_lift":
            "+{pct}% margin lift",
        "email.monthly_pricing_digest.empty_state":
            "No completed jobs with cost data in this month.",
        "email.monthly_pricing_digest.cta_open_app":
            "Open in the app →",

        # ── D6.2 · Weekly digest (services/weekly_digest.py) ─────
        "email.weekly_digest.subject":
            "[{tenant_name}] Weekly Digest · Week of {week_of}",
        "email.weekly_digest.subtitle":
            "Weekly Digest · Week of {week_of}",
        "email.weekly_digest.section.revenue":   "Revenue &amp; Billing",
        "email.weekly_digest.section.operations": "Field Operations",
        "email.weekly_digest.section.customers": "Customer Activity",
        "email.weekly_digest.section.team":      "Team",
        "email.weekly_digest.section.training":  "Training",
        "email.weekly_digest.section.templates": "Templates Library",
        "email.weekly_digest.section.cfo":       "AI CFO Highlights",
        "email.weekly_digest.section.growth":    "Growth Playbook",
        "email.weekly_digest.revenue.new_invoices":
            "New invoices: <b>{value}</b>",
        "email.weekly_digest.revenue.invoiced_total":
            "Invoiced total: <b>${value}</b>",
        "email.weekly_digest.revenue.payments_received":
            "Payments received: <b>${value}</b>",
        "email.weekly_digest.revenue.overdue":
            "Overdue: <b>{value}</b>",
        "email.weekly_digest.operations.jobs_completed":
            "Jobs completed: <b>{value}</b>",
        "email.weekly_digest.operations.jobs_pending":
            "Jobs pending: <b>{value}</b>",
        "email.weekly_digest.operations.new_requests":
            "New job requests: <b>{value}</b>",
        "email.weekly_digest.customers.new":
            "New customers: <b>{value}</b>",
        "email.weekly_digest.customers.portal_downloads":
            "Portal document downloads/uploads: <b>{value}</b>",
        "email.weekly_digest.team.new_employees":
            "New employees onboarded: <b>{value}</b>",
        "email.weekly_digest.team.top_techs_label":
            "Top techs by completed jobs:",
        "email.weekly_digest.team.no_completions":
            "No completions this week",
        "email.weekly_digest.team.techrow_unassigned":
            "Unassigned",
        "email.weekly_digest.onboarding.heading":
            "Onboarding attention:",
        "email.weekly_digest.onboarding.body":
            "{count} tech(s) below 50% after 14 days: {names}",
        "email.weekly_digest.training.modules_completed":
            "Modules completed: <b>{value}</b>",
        "email.weekly_digest.templates.empty":
            "No finalizations this week",
        "email.weekly_digest.cfo.empty":
            "No highlights this week",
        "email.weekly_digest.growth.empty":
            "No growth playbook snapshot this week.",
        "email.weekly_digest.cta_dashboard":
            "View Full Dashboard",
        "email.weekly_digest.footer_note":
            "Sent automatically each Monday morning.",

        # ── D6.2 · AEO digest email (services/aeo_digest.py) ─────
        # NOTE: The PDF body itself stays English — ReportLab's
        # default Helvetica font can't render every UTF-8 character
        # our es/fr copy needs, and swapping fonts is out of D6
        # scope. The email that carries the PDF still localises.
        "email.aeo_digest.subject":
            "Weekly AEO Digest · {tenant_name} · "
            "Week of {period_start}",
        "email.aeo_digest.heading":
            "Weekly AEO Digest · {tenant_name}",
        "email.aeo_digest.aeo_score_line":
            "AEO score: {score} / 100",
        "email.aeo_digest.visibility_line":
            "AI visibility avg: {avg} · mention rate: {rate}%",
        "email.aeo_digest.new_mentions_line":
            "New mentions: {count}",
        "email.aeo_digest.action_items_line":
            "Pending fixes: {fixes} · drafts: {drafts}",
        "email.aeo_digest.pdf_attached": "PDF attached.",

        # ── Phase A4 · Feb-2026 — Renewal proposal (manual-renew
        # contracts) & renewal receipt (auto-renew contracts). Each
        # composer is FIVE full-sentence keys: subject, body_intro,
        # body_price, body_cta, body_footer — matching the exact
        # slot layout of ``services.intelligence.renewal_scan``.
        "email.renewal_proposal.subject":
            "Your {plan_name} renews in {days_left} days",
        "email.renewal_proposal.body_intro":
            "Hi {customer_first_name}, your <b>{plan_name}</b> "
            "service agreement expires on {expires_at_short}. "
            "Renew today to keep your service uninterrupted.",
        "email.renewal_proposal.body_price":
            "Renewal price: {monthly_amount}/month ({currency}).",
        "email.renewal_proposal.body_cta": "Renew now",
        "email.renewal_proposal.body_footer":
            "Questions? Reply to this email or contact your "
            "service team — we're happy to help.",

        "email.renewal_receipt.subject":
            "Your {plan_name} auto-renews in {days_left} days",
        "email.renewal_receipt.body_intro":
            "Hi {customer_first_name}, your <b>{plan_name}</b> "
            "service agreement will automatically renew on "
            "{expires_at_short}. No action needed on your part.",
        "email.renewal_receipt.body_price":
            "You'll be billed {monthly_amount}/month ({currency}) "
            "at renewal.",
        "email.renewal_receipt.body_cta":
            "View or manage renewal",
        "email.renewal_receipt.body_footer":
            "If anything looks off — reply to this email or "
            "contact your service team and we'll sort it out.",
    },
    "es": {
        # ── Invoice reminder ─────────────────────────────────────
        "email.invoice_reminder.subject":
            "Recordatorio de pago — factura {invoice_number}",
        "email.invoice_reminder.heading": "Recordatorio de pago",
        "email.invoice_reminder.greeting": "Hola {customer_name}:",
        "email.invoice_reminder.body":
            "Este es un recordatorio amistoso de que la factura "
            "<b>{invoice_number}</b> tiene un saldo pendiente de "
            "<b>${balance}</b> (vencía el {due_date}).",
        "email.invoice_reminder.attachments_one":
            "{count} archivo adjunto incluido",
        "email.invoice_reminder.attachments_many":
            "{count} archivos adjuntos incluidos",
        "email.invoice_reminder.thanks":
            "Gracias,<br/>{company}",

        # ── Estimate / quote reminder ────────────────────────────
        "email.estimate_reminder.subject":
            "Recordatorio: su {doc_type_label} de {company}",
        "email.estimate_reminder.heading":
            "Recordatorio: su {doc_type_label}",
        "email.estimate_reminder.greeting": "Hola {customer_name}:",
        "email.estimate_reminder.body":
            "Este es un recordatorio amistoso de que su "
            "{doc_type_label} <b>{doc_number}</b> de {company} "
            "está pendiente de revisión. Por favor, tómese un "
            "momento para aprobarlo, solicitar cambios o "
            "rechazarlo.",
        "email.estimate_reminder.cta_review":
            "Revisar {doc_type_label_titled}",
        "email.estimate_reminder.terms_heading":
            "Términos y condiciones",
        "email.estimate_reminder.thanks":
            "Gracias,<br/>{company}",
        "email.estimate_reminder.doc_type.estimate": "presupuesto",
        "email.estimate_reminder.doc_type.quote": "cotización",
        "email.estimate_reminder.attachments_heading":
            "Archivos adjuntos",
        "email.estimate_reminder.attachments_one":
            "{count} archivo adjunto incluido",
        "email.estimate_reminder.attachments_many":
            "{count} archivos adjuntos incluidos",

        # ── Job completion ───────────────────────────────────────
        "email.job_completed.subject":
            "Su {service_type} se ha completado",
        "email.job_completed.heading":
            "Su servicio se ha completado",
        "email.job_completed.body_with_date":
            "Hola {customer_name}, hemos terminado su "
            "<strong>{service_type}</strong> el {when}. "
            "Su informe de servicio completo — lista de "
            "verificación, mediciones del agua y químicos "
            "agregados — está listo para consultar.",
        "email.job_completed.body_no_date":
            "Hola {customer_name}, hemos terminado su "
            "<strong>{service_type}</strong>. "
            "Su informe de servicio completo — lista de "
            "verificación, mediciones del agua y químicos "
            "agregados — está listo para consultar.",
        "email.job_completed.cta_view_report":
            "Ver su informe de servicio",
        "email.job_completed.photos_heading":
            "Fotos de su visita:",
        "email.job_completed.support_line":
            "¿Preguntas? Responda desde la aplicación y nuestro "
            "equipo (y Marina, nuestra asistente) le ayudará.",

        # ── Dunning stages ───────────────────────────────────────
        "dunning.pre_due_3d.subject":
            "Recordatorio: factura {invoice_number} vence en 3 días",
        "dunning.pre_due_3d.body":
            "Hola {customer_name}:\n\n"
            "Solo un recordatorio amistoso de que la factura "
            "{invoice_number} por ${invoice_total} vence el "
            "{due_date}.\n\n"
            "Ver factura: {payment_link}\n\n"
            "Gracias,\n{tenant_name}",
        "dunning.pre_due_3d.sms":
            "{tenant_name}: factura {invoice_number} "
            "(${invoice_total}) vence el {due_date}. "
            "Pagar: {payment_link}",

        "dunning.on_due_day.subject":
            "La factura {invoice_number} vence hoy",
        "dunning.on_due_day.body":
            "Hola {customer_name}:\n\n"
            "La factura {invoice_number} por ${invoice_total} "
            "vence hoy. Ver factura: {payment_link}\n\n"
            "Gracias,\n{tenant_name}",
        "dunning.on_due_day.sms":
            "{tenant_name}: factura {invoice_number} "
            "(${invoice_total}) vence hoy. Pagar: {payment_link}",

        "dunning.past_due_7d.subject":
            "Vencida: factura {invoice_number} ({days_past_due}d)",
        "dunning.past_due_7d.body":
            "Hola {customer_name}:\n\n"
            "La factura {invoice_number} por ${invoice_total} "
            "está vencida hace {days_past_due} días. Por favor, "
            "liquídela a la brevedad posible.\n\n"
            "Ver factura: {payment_link}\n\n"
            "¿Preguntas? Llame al {tenant_phone}.\n\n{tenant_name}",
        "dunning.past_due_7d.sms":
            "{tenant_name}: factura {invoice_number} lleva "
            "{days_past_due}d vencida (${invoice_total}). "
            "Pagar: {payment_link}",

        "dunning.past_due_14d.subject":
            "Segundo aviso: factura {invoice_number}",
        "dunning.past_due_14d.body":
            "Hola {customer_name}:\n\n"
            "Este es un segundo recordatorio de que la factura "
            "{invoice_number} por ${invoice_total} lleva "
            "{days_past_due} días vencida. Por favor pague para "
            "evitar más seguimiento.\n\n"
            "Ver factura: {payment_link}\n\n"
            "{tenant_name} · {tenant_phone}",
        "dunning.past_due_14d.sms":
            "{tenant_name}: SEGUNDO AVISO — factura "
            "{invoice_number} lleva {days_past_due}d vencida. "
            "Pagar: {payment_link}",

        "dunning.past_due_30d.subject":
            "Aviso final: factura {invoice_number}",
        "dunning.past_due_30d.body":
            "Hola {customer_name}:\n\n"
            "La factura {invoice_number} lleva más de 30 días "
            "vencida. Este es nuestro último recordatorio de "
            "cortesía antes de marcar su cuenta como en riesgo. "
            "Por favor pague ${invoice_total} hoy.\n\n"
            "Ver factura: {payment_link}\n\n"
            "{tenant_name} · {tenant_phone}",
        "dunning.past_due_30d.sms":
            "{tenant_name}: AVISO FINAL — factura "
            "{invoice_number} lleva más de 30d vencida "
            "(${invoice_total}). Pagar: {payment_link}",

        "dunning.past_due_60d.subject":
            "Aviso de cobranza: factura {invoice_number}",
        "dunning.past_due_60d.body":
            "Hola {customer_name}:\n\n"
            "La factura {invoice_number} (${invoice_total}) lleva "
            "más de 60 días vencida. Su cuenta se ha marcado para "
            "cobranza. Por favor comuníquese con nosotros de "
            "inmediato al {tenant_phone}.\n\n"
            "Ver factura: {payment_link}\n\n{tenant_name}",
        "dunning.past_due_60d.sms":
            "{tenant_name}: su cuenta se ha marcado para "
            "cobranza. Factura {invoice_number} lleva más de 60d "
            "vencida. Llame al {tenant_phone}.",

        # ── D6.2 · Password reset ────────────────────────────────
        "email.password_reset.subject":
            "Se restableció su contraseña de {company_name}",
        "email.password_reset.heading":
            "Restablecimiento de contraseña por el administrador",
        "email.password_reset.body_intro":
            "Hola {target_name}, {actor_name} restableció su "
            "contraseña de {company_name}. Inicie sesión con la "
            "contraseña temporal a continuación — se le pedirá que "
            "elija una nueva contraseña inmediatamente al iniciar "
            "sesión.",
        "email.password_reset.temp_password_label":
            "Contraseña temporal",
        "email.password_reset.cta_sign_in": "Iniciar sesión",
        "email.password_reset.footer_security":
            "Si no fue usted, comuníquese con su administrador "
            "de inmediato.",

        # ── D6.2 · Trial-billing fallback strings ────────────────
        "email.trial_reminder.fallback.plan_amount":
            "el precio de su plan",
        "email.trial_reminder.fallback.admin_name": "hola",
        "email.trial_reminder.fallback.business_name":
            "su negocio",

        # ── D6.2 · Lead alert ────────────────────────────────────
        "email.lead_alert.subject.with_phone":
            "Nuevo cliente potencial — {name} ({phone})",
        "email.lead_alert.subject.no_phone":
            "Nuevo cliente potencial — {name}",
        "email.lead_alert.heading":
            "Nuevo cliente potencial — {name}",
        "email.lead_alert.field.name":             "Nombre",
        "email.lead_alert.field.phone":            "Teléfono",
        "email.lead_alert.field.email":            "Correo electrónico",
        "email.lead_alert.field.address":          "Dirección",
        "email.lead_alert.field.service_address":  "Dirección de servicio",
        "email.lead_alert.field.service_interest": "Servicio de interés",
        "email.lead_alert.cta_view":
            "Ver cliente potencial en admin",
        "email.lead_alert.website_visitor":
            "Visitante del sitio web",
        "sms.lead_alert.header":
            "Nuevo cliente potencial — {name}",
        "sms.lead_alert.view_link": "Ver: {url}",

        # ── D6.2 · Monthly pricing digest ────────────────────────
        "email.monthly_pricing_digest.subject":
            "{tenant_name} · Informe mensual de precios · {month}",
        "email.monthly_pricing_digest.title":
            "{tenant_name} · Informe mensual de precios",
        "email.monthly_pricing_digest.subtitle":
            "{month} · tipos de servicio menos rentables + "
            "aumentos de precio propuestos por la IA",
        "email.monthly_pricing_digest.col.service":   "Servicio",
        "email.monthly_pricing_digest.col.pricing":   "Precios",
        "email.monthly_pricing_digest.col.rationale":
            "Justificación · Puntos de conversación",
        "email.monthly_pricing_digest.jobs_and_margin":
            "{count} trabajos · margen {margin_pct}%",
        "email.monthly_pricing_digest.current_avg":
            "Promedio actual:",
        "email.monthly_pricing_digest.recommend":
            "Recomendado:",
        "email.monthly_pricing_digest.margin_lift":
            "+{pct}% de aumento de margen",
        "email.monthly_pricing_digest.empty_state":
            "No hay trabajos completados con datos de costos este mes.",
        "email.monthly_pricing_digest.cta_open_app":
            "Abrir en la aplicación →",

        # ── D6.2 · Weekly digest ─────────────────────────────────
        "email.weekly_digest.subject":
            "[{tenant_name}] Resumen semanal · Semana del {week_of}",
        "email.weekly_digest.subtitle":
            "Resumen semanal · Semana del {week_of}",
        "email.weekly_digest.section.revenue":
            "Ingresos y facturación",
        "email.weekly_digest.section.operations":
            "Operaciones de campo",
        "email.weekly_digest.section.customers":
            "Actividad del cliente",
        "email.weekly_digest.section.team":      "Equipo",
        "email.weekly_digest.section.training":  "Capacitación",
        "email.weekly_digest.section.templates": "Biblioteca de plantillas",
        "email.weekly_digest.section.cfo":
            "Puntos destacados del CFO IA",
        "email.weekly_digest.section.growth":
            "Manual de crecimiento",
        "email.weekly_digest.revenue.new_invoices":
            "Nuevas facturas: <b>{value}</b>",
        "email.weekly_digest.revenue.invoiced_total":
            "Total facturado: <b>${value}</b>",
        "email.weekly_digest.revenue.payments_received":
            "Pagos recibidos: <b>${value}</b>",
        "email.weekly_digest.revenue.overdue":
            "Vencidas: <b>{value}</b>",
        "email.weekly_digest.operations.jobs_completed":
            "Trabajos completados: <b>{value}</b>",
        "email.weekly_digest.operations.jobs_pending":
            "Trabajos pendientes: <b>{value}</b>",
        "email.weekly_digest.operations.new_requests":
            "Nuevas solicitudes de trabajo: <b>{value}</b>",
        "email.weekly_digest.customers.new":
            "Nuevos clientes: <b>{value}</b>",
        "email.weekly_digest.customers.portal_downloads":
            "Descargas/subidas de documentos del portal: <b>{value}</b>",
        "email.weekly_digest.team.new_employees":
            "Nuevos empleados incorporados: <b>{value}</b>",
        "email.weekly_digest.team.top_techs_label":
            "Mejores técnicos por trabajos completados:",
        "email.weekly_digest.team.no_completions":
            "Sin trabajos completados esta semana",
        "email.weekly_digest.team.techrow_unassigned":
            "Sin asignar",
        "email.weekly_digest.onboarding.heading":
            "Atención al onboarding:",
        "email.weekly_digest.onboarding.body":
            "{count} técnico(s) por debajo del 50% después de "
            "14 días: {names}",
        "email.weekly_digest.training.modules_completed":
            "Módulos completados: <b>{value}</b>",
        "email.weekly_digest.templates.empty":
            "Sin plantillas finalizadas esta semana",
        "email.weekly_digest.cfo.empty":
            "Sin puntos destacados esta semana",
        "email.weekly_digest.growth.empty":
            "Sin instantánea del manual de crecimiento esta semana.",
        "email.weekly_digest.cta_dashboard":
            "Ver panel completo",
        "email.weekly_digest.footer_note":
            "Enviado automáticamente cada lunes por la mañana.",

        # ── D6.2 · AEO digest email ──────────────────────────────
        "email.aeo_digest.subject":
            "Resumen semanal de AEO · {tenant_name} · "
            "Semana del {period_start}",
        "email.aeo_digest.heading":
            "Resumen semanal de AEO · {tenant_name}",
        "email.aeo_digest.aeo_score_line":
            "Puntaje de AEO: {score} / 100",
        "email.aeo_digest.visibility_line":
            "Promedio de visibilidad de IA: {avg} · "
            "tasa de mención: {rate}%",
        "email.aeo_digest.new_mentions_line":
            "Nuevas menciones: {count}",
        "email.aeo_digest.action_items_line":
            "Correcciones pendientes: {fixes} · borradores: {drafts}",
        "email.aeo_digest.pdf_attached": "PDF adjunto.",

        # ── Phase A4 · Feb-2026 — Renewal proposal / receipt (es) ──
        "email.renewal_proposal.subject":
            "Su {plan_name} se renueva en {days_left} días",
        "email.renewal_proposal.body_intro":
            "Hola {customer_first_name}, su acuerdo de servicio "
            "<b>{plan_name}</b> vence el {expires_at_short}. "
            "Renueve hoy para mantener su servicio sin "
            "interrupciones.",
        "email.renewal_proposal.body_price":
            "Precio de renovación: {monthly_amount}/mes ({currency}).",
        "email.renewal_proposal.body_cta": "Renovar ahora",
        "email.renewal_proposal.body_footer":
            "¿Preguntas? Responda a este correo o contacte con su "
            "equipo de servicio — estaremos encantados de ayudar.",

        "email.renewal_receipt.subject":
            "Su {plan_name} se renueva automáticamente en {days_left} días",
        "email.renewal_receipt.body_intro":
            "Hola {customer_first_name}, su acuerdo de servicio "
            "<b>{plan_name}</b> se renovará automáticamente el "
            "{expires_at_short}. No es necesario que haga nada.",
        "email.renewal_receipt.body_price":
            "Se le facturará {monthly_amount}/mes ({currency}) "
            "en la renovación.",
        "email.renewal_receipt.body_cta":
            "Ver o gestionar la renovación",
        "email.renewal_receipt.body_footer":
            "Si algo no parece correcto, responda a este correo o "
            "contacte con su equipo de servicio — lo resolveremos.",
    },
    "fr": {
        # ── Invoice reminder ─────────────────────────────────────
        "email.invoice_reminder.subject":
            "Rappel de paiement — facture {invoice_number}",
        "email.invoice_reminder.heading": "Rappel de paiement",
        "email.invoice_reminder.greeting": "Bonjour {customer_name},",
        "email.invoice_reminder.body":
            "Ceci est un rappel amical que la facture "
            "<b>{invoice_number}</b> présente un solde impayé de "
            "<b>${balance}</b> (échéance le {due_date}).",
        "email.invoice_reminder.attachments_one":
            "{count} pièce jointe incluse",
        "email.invoice_reminder.attachments_many":
            "{count} pièces jointes incluses",
        "email.invoice_reminder.thanks":
            "Merci,<br/>{company}",

        # ── Estimate / quote reminder ────────────────────────────
        "email.estimate_reminder.subject":
            "Rappel : votre {doc_type_label} de {company}",
        "email.estimate_reminder.heading":
            "Rappel : votre {doc_type_label}",
        "email.estimate_reminder.greeting": "Bonjour {customer_name},",
        "email.estimate_reminder.body":
            "Ceci est un rappel amical que votre "
            "{doc_type_label} <b>{doc_number}</b> de {company} "
            "est en attente de votre examen. Veuillez prendre un "
            "moment pour l'approuver, demander des modifications "
            "ou le refuser.",
        "email.estimate_reminder.cta_review":
            "Examiner le {doc_type_label_titled}",
        "email.estimate_reminder.terms_heading":
            "Conditions générales",
        "email.estimate_reminder.thanks":
            "Merci,<br/>{company}",
        "email.estimate_reminder.doc_type.estimate": "devis",
        "email.estimate_reminder.doc_type.quote": "devis",
        "email.estimate_reminder.attachments_heading":
            "Pièces jointes",
        "email.estimate_reminder.attachments_one":
            "{count} pièce jointe incluse",
        "email.estimate_reminder.attachments_many":
            "{count} pièces jointes incluses",

        # ── Job completion ───────────────────────────────────────
        "email.job_completed.subject":
            "Votre {service_type} est terminé",
        "email.job_completed.heading":
            "Votre service est terminé",
        "email.job_completed.body_with_date":
            "Bonjour {customer_name}, nous avons terminé votre "
            "<strong>{service_type}</strong> le {when}. "
            "Votre rapport de service complet — liste de "
            "contrôle, mesures d'eau et produits chimiques "
            "ajoutés — est prêt à consulter.",
        "email.job_completed.body_no_date":
            "Bonjour {customer_name}, nous avons terminé votre "
            "<strong>{service_type}</strong>. "
            "Votre rapport de service complet — liste de "
            "contrôle, mesures d'eau et produits chimiques "
            "ajoutés — est prêt à consulter.",
        "email.job_completed.cta_view_report":
            "Voir votre rapport de service",
        "email.job_completed.photos_heading":
            "Photos de votre visite :",
        "email.job_completed.support_line":
            "Des questions ? Répondez simplement dans "
            "l'application et notre équipe (ainsi que Marina, "
            "notre assistante) vous aidera.",

        # ── Dunning stages ───────────────────────────────────────
        "dunning.pre_due_3d.subject":
            "Rappel : facture {invoice_number} arrive à échéance "
            "dans 3 jours",
        "dunning.pre_due_3d.body":
            "Bonjour {customer_name},\n\n"
            "Un simple rappel amical que la facture "
            "{invoice_number} de ${invoice_total} arrive à "
            "échéance le {due_date}.\n\n"
            "Voir la facture : {payment_link}\n\n"
            "Merci,\n{tenant_name}",
        "dunning.pre_due_3d.sms":
            "{tenant_name} : facture {invoice_number} "
            "(${invoice_total}) échéance {due_date}. "
            "Payer : {payment_link}",

        "dunning.on_due_day.subject":
            "La facture {invoice_number} arrive à échéance "
            "aujourd'hui",
        "dunning.on_due_day.body":
            "Bonjour {customer_name},\n\n"
            "La facture {invoice_number} de ${invoice_total} "
            "arrive à échéance aujourd'hui. "
            "Voir la facture : {payment_link}\n\n"
            "Merci,\n{tenant_name}",
        "dunning.on_due_day.sms":
            "{tenant_name} : facture {invoice_number} "
            "(${invoice_total}) échéance aujourd'hui. "
            "Payer : {payment_link}",

        "dunning.past_due_7d.subject":
            "En retard : facture {invoice_number} "
            "({days_past_due}j)",
        "dunning.past_due_7d.body":
            "Bonjour {customer_name},\n\n"
            "La facture {invoice_number} de ${invoice_total} est "
            "maintenant en retard de {days_past_due} jours. "
            "Veuillez régler dans les meilleurs délais.\n\n"
            "Voir la facture : {payment_link}\n\n"
            "Des questions ? Appelez le {tenant_phone}.\n\n"
            "{tenant_name}",
        "dunning.past_due_7d.sms":
            "{tenant_name} : facture {invoice_number} en retard "
            "de {days_past_due}j (${invoice_total}). "
            "Payer : {payment_link}",

        "dunning.past_due_14d.subject":
            "Deuxième avis : facture {invoice_number}",
        "dunning.past_due_14d.body":
            "Bonjour {customer_name},\n\n"
            "Ceci est un deuxième rappel que la facture "
            "{invoice_number} de ${invoice_total} est en retard "
            "de {days_past_due} jours. Veuillez régler pour "
            "éviter d'autres relances.\n\n"
            "Voir la facture : {payment_link}\n\n"
            "{tenant_name} · {tenant_phone}",
        "dunning.past_due_14d.sms":
            "{tenant_name} : DEUXIÈME AVIS — facture "
            "{invoice_number} en retard de {days_past_due}j. "
            "Payer : {payment_link}",

        "dunning.past_due_30d.subject":
            "Avis final : facture {invoice_number}",
        "dunning.past_due_30d.body":
            "Bonjour {customer_name},\n\n"
            "La facture {invoice_number} est maintenant en "
            "retard de plus de 30 jours. Ceci est notre dernier "
            "rappel de courtoisie avant que votre compte ne soit "
            "signalé comme à risque. Veuillez payer "
            "${invoice_total} aujourd'hui.\n\n"
            "Voir la facture : {payment_link}\n\n"
            "{tenant_name} · {tenant_phone}",
        "dunning.past_due_30d.sms":
            "{tenant_name} : AVIS FINAL — facture "
            "{invoice_number} en retard de plus de 30j "
            "(${invoice_total}). Payer : {payment_link}",

        "dunning.past_due_60d.subject":
            "Avis de recouvrement : facture {invoice_number}",
        "dunning.past_due_60d.body":
            "Bonjour {customer_name},\n\n"
            "La facture {invoice_number} (${invoice_total}) est "
            "maintenant en retard de plus de 60 jours. Votre "
            "compte a été signalé pour recouvrement. Veuillez "
            "nous contacter immédiatement au {tenant_phone}.\n\n"
            "Voir la facture : {payment_link}\n\n{tenant_name}",
        "dunning.past_due_60d.sms":
            "{tenant_name} : votre compte est signalé pour "
            "recouvrement. Facture {invoice_number} en retard "
            "de plus de 60j. Appelez le {tenant_phone}.",

        # ── D6.2 · Password reset ────────────────────────────────
        "email.password_reset.subject":
            "Votre mot de passe {company_name} a été réinitialisé",
        "email.password_reset.heading":
            "Mot de passe réinitialisé par un administrateur",
        "email.password_reset.body_intro":
            "Bonjour {target_name}, {actor_name} a réinitialisé "
            "votre mot de passe {company_name}. Connectez-vous "
            "avec le mot de passe temporaire ci-dessous — vous "
            "devrez choisir un nouveau mot de passe immédiatement "
            "lors de votre première connexion.",
        "email.password_reset.temp_password_label":
            "Mot de passe temporaire",
        "email.password_reset.cta_sign_in": "Se connecter",
        "email.password_reset.footer_security":
            "Si ce n'était pas vous, contactez immédiatement votre "
            "administrateur.",

        # ── D6.2 · Trial-billing fallback strings ────────────────
        "email.trial_reminder.fallback.plan_amount":
            "le tarif de votre forfait",
        "email.trial_reminder.fallback.admin_name": "bonjour",
        "email.trial_reminder.fallback.business_name":
            "votre entreprise",

        # ── D6.2 · Lead alert ────────────────────────────────────
        "email.lead_alert.subject.with_phone":
            "Nouveau prospect — {name} ({phone})",
        "email.lead_alert.subject.no_phone":
            "Nouveau prospect — {name}",
        "email.lead_alert.heading":
            "Nouveau prospect — {name}",
        "email.lead_alert.field.name":             "Nom",
        "email.lead_alert.field.phone":            "Téléphone",
        "email.lead_alert.field.email":            "Courriel",
        "email.lead_alert.field.address":          "Adresse",
        "email.lead_alert.field.service_address":  "Adresse du service",
        "email.lead_alert.field.service_interest":
            "Service demandé",
        "email.lead_alert.cta_view":
            "Voir le prospect dans l'admin",
        "email.lead_alert.website_visitor":
            "Visiteur du site web",
        "sms.lead_alert.header":
            "Nouveau prospect — {name}",
        "sms.lead_alert.view_link": "Voir : {url}",

        # ── D6.2 · Monthly pricing digest ────────────────────────
        "email.monthly_pricing_digest.subject":
            "{tenant_name} · Analyse mensuelle des prix · {month}",
        "email.monthly_pricing_digest.title":
            "{tenant_name} · Analyse mensuelle des prix",
        "email.monthly_pricing_digest.subtitle":
            "{month} · types de services les moins rentables + "
            "augmentations de prix suggérées par l'IA",
        "email.monthly_pricing_digest.col.service":   "Service",
        "email.monthly_pricing_digest.col.pricing":   "Tarification",
        "email.monthly_pricing_digest.col.rationale":
            "Justification · Points de discussion",
        "email.monthly_pricing_digest.jobs_and_margin":
            "{count} interventions · marge {margin_pct}%",
        "email.monthly_pricing_digest.current_avg":
            "Moyenne actuelle :",
        "email.monthly_pricing_digest.recommend":
            "Recommandé :",
        "email.monthly_pricing_digest.margin_lift":
            "+{pct}% d'augmentation de marge",
        "email.monthly_pricing_digest.empty_state":
            "Aucune intervention terminée avec des données de "
            "coût ce mois-ci.",
        "email.monthly_pricing_digest.cta_open_app":
            "Ouvrir dans l'application →",

        # ── D6.2 · Weekly digest ─────────────────────────────────
        "email.weekly_digest.subject":
            "[{tenant_name}] Résumé hebdomadaire · Semaine du {week_of}",
        "email.weekly_digest.subtitle":
            "Résumé hebdomadaire · Semaine du {week_of}",
        "email.weekly_digest.section.revenue":
            "Revenus et facturation",
        "email.weekly_digest.section.operations":
            "Opérations sur le terrain",
        "email.weekly_digest.section.customers":
            "Activité des clients",
        "email.weekly_digest.section.team":      "Équipe",
        "email.weekly_digest.section.training":  "Formation",
        "email.weekly_digest.section.templates":
            "Bibliothèque de modèles",
        "email.weekly_digest.section.cfo":
            "Faits saillants du CFO IA",
        "email.weekly_digest.section.growth":
            "Plan de croissance",
        "email.weekly_digest.revenue.new_invoices":
            "Nouvelles factures : <b>{value}</b>",
        "email.weekly_digest.revenue.invoiced_total":
            "Total facturé : <b>${value}</b>",
        "email.weekly_digest.revenue.payments_received":
            "Paiements reçus : <b>${value}</b>",
        "email.weekly_digest.revenue.overdue":
            "En retard : <b>{value}</b>",
        "email.weekly_digest.operations.jobs_completed":
            "Interventions terminées : <b>{value}</b>",
        "email.weekly_digest.operations.jobs_pending":
            "Interventions en attente : <b>{value}</b>",
        "email.weekly_digest.operations.new_requests":
            "Nouvelles demandes d'intervention : <b>{value}</b>",
        "email.weekly_digest.customers.new":
            "Nouveaux clients : <b>{value}</b>",
        "email.weekly_digest.customers.portal_downloads":
            "Téléchargements/envois de documents du portail : "
            "<b>{value}</b>",
        "email.weekly_digest.team.new_employees":
            "Nouveaux employés intégrés : <b>{value}</b>",
        "email.weekly_digest.team.top_techs_label":
            "Meilleurs techniciens par interventions terminées :",
        "email.weekly_digest.team.no_completions":
            "Aucune intervention terminée cette semaine",
        "email.weekly_digest.team.techrow_unassigned":
            "Non attribué",
        "email.weekly_digest.onboarding.heading":
            "Attention à l'onboarding :",
        "email.weekly_digest.onboarding.body":
            "{count} technicien(s) en dessous de 50% après "
            "14 jours : {names}",
        "email.weekly_digest.training.modules_completed":
            "Modules terminés : <b>{value}</b>",
        "email.weekly_digest.templates.empty":
            "Aucune finalisation de modèle cette semaine",
        "email.weekly_digest.cfo.empty":
            "Aucun fait saillant cette semaine",
        "email.weekly_digest.growth.empty":
            "Aucun instantané du plan de croissance cette semaine.",
        "email.weekly_digest.cta_dashboard":
            "Voir le tableau de bord complet",
        "email.weekly_digest.footer_note":
            "Envoyé automatiquement chaque lundi matin.",

        # ── D6.2 · AEO digest email ──────────────────────────────
        "email.aeo_digest.subject":
            "Résumé AEO hebdomadaire · {tenant_name} · "
            "Semaine du {period_start}",
        "email.aeo_digest.heading":
            "Résumé AEO hebdomadaire · {tenant_name}",
        "email.aeo_digest.aeo_score_line":
            "Score AEO : {score} / 100",
        "email.aeo_digest.visibility_line":
            "Moyenne de visibilité IA : {avg} · "
            "taux de mention : {rate}%",
        "email.aeo_digest.new_mentions_line":
            "Nouvelles mentions : {count}",
        "email.aeo_digest.action_items_line":
            "Corrections en attente : {fixes} · brouillons : {drafts}",
        "email.aeo_digest.pdf_attached": "PDF joint.",

        # ── Phase A4 · Feb-2026 — Renewal proposal / receipt (fr) ──
        "email.renewal_proposal.subject":
            "Votre {plan_name} se renouvelle dans {days_left} jours",
        "email.renewal_proposal.body_intro":
            "Bonjour {customer_first_name}, votre contrat de "
            "service <b>{plan_name}</b> expire le "
            "{expires_at_short}. Renouvelez dès aujourd'hui pour "
            "conserver un service ininterrompu.",
        "email.renewal_proposal.body_price":
            "Prix de renouvellement : {monthly_amount}/mois "
            "({currency}).",
        "email.renewal_proposal.body_cta": "Renouveler maintenant",
        "email.renewal_proposal.body_footer":
            "Des questions ? Répondez à cet e-mail ou contactez "
            "votre équipe de service — nous sommes là pour vous "
            "aider.",

        "email.renewal_receipt.subject":
            "Votre {plan_name} se renouvelle automatiquement "
            "dans {days_left} jours",
        "email.renewal_receipt.body_intro":
            "Bonjour {customer_first_name}, votre contrat de "
            "service <b>{plan_name}</b> sera automatiquement "
            "renouvelé le {expires_at_short}. Aucune action "
            "requise de votre part.",
        "email.renewal_receipt.body_price":
            "Vous serez facturé {monthly_amount}/mois "
            "({currency}) au renouvellement.",
        "email.renewal_receipt.body_cta":
            "Voir ou gérer le renouvellement",
        "email.renewal_receipt.body_footer":
            "Si quelque chose semble incorrect, répondez à cet "
            "e-mail ou contactez votre équipe de service — nous "
            "règlerons cela.",
    },
}


def _normalise_locale(raw: object) -> str:
    """Coerce any input to a supported locale. Mirrors
    :func:`services.email_cta_i18n._normalise_locale`."""
    if not raw:
        return FALLBACK_LOCALE
    s = str(raw).strip().lower()
    if "-" in s:
        s = s.split("-", 1)[0]
    if "_" in s:
        s = s.split("_", 1)[0]
    return s if s in SUPPORTED_LOCALES else FALLBACK_LOCALE


_FORMATTER = string.Formatter()


def t_email_body(locale: object, key: str, **variables: Any) -> str:
    """Return the localised email-body string for ``key`` in ``locale``
    with any ``{placeholder}`` tokens substituted from ``variables``.

    Fallback chain:
      * unsupported locale → English variant.
      * key missing under requested locale → English variant.
      * key missing under English too → :class:`KeyError` (bug).

    A referenced ``{placeholder}`` missing from ``variables`` raises
    :class:`KeyError` naming the offending token — literal markers
    must never reach a recipient.
    """
    if not key:
        raise KeyError("email_body key is required")
    loc = _normalise_locale(locale)
    labels_for_loc = LABELS.get(loc) or {}
    tmpl = labels_for_loc.get(key)
    if tmpl is None:
        tmpl = LABELS[FALLBACK_LOCALE].get(key)
    if tmpl is None:
        raise KeyError(f"unknown email_body key: {key!r}")
    try:
        return _FORMATTER.vformat(tmpl, (), dict(variables))
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "?"
        raise KeyError(
            f"email_body key={key!r} missing merge var "
            f"{missing!r} in variables"
        ) from exc
