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
