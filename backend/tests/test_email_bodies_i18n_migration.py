"""Phase D6 · Feb-2026 — dynamic email body i18n regression tests.

Covers the D6 acceptance criteria:

1. ``resolve_email_locale`` priority order — ``override`` >
   ``recipient.locale`` > ``tenant.default_locale`` > ``en``.
2. ``resolve_email_locale`` fallback returns ``en`` when every
   argument is ``None``.
3. Each migrated template renders in ``en`` — full body + subject
   contain the expected English phrases.
4. Each migrated template renders in ``es`` — full body + subject
   contain the expected Spanish phrases.
5. Each migrated template renders in ``fr`` — full body + subject
   contain the expected French phrases.
6. Interpolation variables (customer name, invoice #, amount)
   land in the right place in every locale.
7. No hardcoded English body sentence survives in the composer
   functions (grep-based assertion against the migrated files).
8. ``t_email_body`` catalog parity — every key present under ``en``
   is present under ``es`` and ``fr``.
9. Missing merge var raises :class:`KeyError` naming the offending
   token (never let a literal ``{placeholder}`` reach an inbox).

All tests are pure — no Motor / Resend / storage clients are
instantiated. Rendering paths are exercised directly.
"""
from __future__ import annotations

import inspect
import re

import pytest


# ═════════════════════════════════════════════════════════════════════
# 1 · resolve_email_locale priority order
# ═════════════════════════════════════════════════════════════════════
def test_resolve_email_locale_override_wins_over_everything():
    from services.i18n.email_locale import resolve_email_locale
    assert resolve_email_locale(
        recipient={"locale": "fr"},
        tenant={"default_locale": "es"},
        override="es",
    ) == "es"


def test_resolve_email_locale_recipient_wins_over_tenant():
    from services.i18n.email_locale import resolve_email_locale
    assert resolve_email_locale(
        recipient={"locale": "fr"},
        tenant={"default_locale": "es"},
    ) == "fr"


def test_resolve_email_locale_tenant_used_when_no_recipient_locale():
    from services.i18n.email_locale import resolve_email_locale
    assert resolve_email_locale(
        recipient={"locale": None},
        tenant={"default_locale": "es"},
    ) == "es"


def test_resolve_email_locale_falls_back_to_en_when_all_none():
    from services.i18n.email_locale import resolve_email_locale
    assert resolve_email_locale() == "en"
    assert resolve_email_locale(recipient=None, tenant=None, override=None) == "en"


def test_resolve_email_locale_normalises_bcp47_suffix():
    from services.i18n.email_locale import resolve_email_locale
    assert resolve_email_locale(override="es-MX") == "es"
    assert resolve_email_locale(recipient={"locale": "fr_CA"}) == "fr"


def test_resolve_email_locale_unknown_locale_becomes_en():
    from services.i18n.email_locale import resolve_email_locale
    for bogus in ("de", "ja", "xx"):
        assert resolve_email_locale(override=bogus) == "en"


# ═════════════════════════════════════════════════════════════════════
# 2 · Catalog parity — every en key present under es + fr
# ═════════════════════════════════════════════════════════════════════
def test_email_body_catalog_parity_across_locales():
    from services.email_body_i18n import LABELS, SUPPORTED_LOCALES
    en_keys = set(LABELS["en"].keys())
    assert en_keys, "English catalog is empty — nothing to test"
    for loc in SUPPORTED_LOCALES:
        loc_keys = set(LABELS[loc].keys())
        missing = en_keys - loc_keys
        assert not missing, (
            f"Locale {loc!r} is missing keys present under 'en': "
            f"{sorted(missing)}"
        )


def test_email_body_catalog_placeholder_parity():
    """Every locale variant of a key must reference the same
    ``{placeholder}`` set. A translator that renames
    ``{customer_name}`` to ``{nombre}`` should fail this test in CI.
    """
    from services.email_body_i18n import LABELS
    tag_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    for key, en_tmpl in LABELS["en"].items():
        en_placeholders = set(tag_re.findall(en_tmpl))
        for loc in ("es", "fr"):
            loc_tmpl = LABELS[loc].get(key)
            assert loc_tmpl is not None, (
                f"catalog gap: {key!r} missing under {loc!r}"
            )
            loc_placeholders = set(tag_re.findall(loc_tmpl))
            assert loc_placeholders == en_placeholders, (
                f"placeholder drift on {key!r} in {loc!r}: "
                f"en={en_placeholders}, {loc}={loc_placeholders}"
            )


# ═════════════════════════════════════════════════════════════════════
# 3 · t_email_body basics
# ═════════════════════════════════════════════════════════════════════
def test_t_email_body_interpolates_named_variables():
    from services.email_body_i18n import t_email_body
    s = t_email_body(
        "en", "email.invoice_reminder.subject", invoice_number="INV-42",
    )
    assert s == "Payment reminder — invoice INV-42"


def test_t_email_body_missing_variable_raises_keyerror():
    from services.email_body_i18n import t_email_body
    with pytest.raises(KeyError) as excinfo:
        t_email_body("en", "email.invoice_reminder.subject")
    # KeyError message must name the offending placeholder token.
    assert "invoice_number" in str(excinfo.value)


def test_t_email_body_unknown_key_raises_keyerror():
    from services.email_body_i18n import t_email_body
    with pytest.raises(KeyError):
        t_email_body("en", "email.does_not_exist")


def test_t_email_body_unknown_locale_falls_back_to_english():
    from services.email_body_i18n import t_email_body
    s = t_email_body(
        "xx", "email.invoice_reminder.heading",
    )
    assert s == "Payment reminder"


# ═════════════════════════════════════════════════════════════════════
# 4 · Invoice-reminder HTML renders correctly in all 3 locales
# ═════════════════════════════════════════════════════════════════════
def _stub_invoice():
    return {
        "id": "inv-abc123",
        "tenant_id": "t-1",
        "total": 250.00,
        "amount_paid": 0,
        "due_date": "2026-02-15",
        "invoice_number": "INV-42",
    }


def test_invoice_reminder_html_renders_english_body(monkeypatch):
    from services import pay_link_builder
    monkeypatch.setattr(
        pay_link_builder, "build_pay_now_url",
        lambda _iid, _tid, src="email": "https://ex.test/pay/inv-abc123",
    )
    from emailer import _reminder_html
    html = _reminder_html(
        _stub_invoice(), "Sample Customer", locale="en",
    )
    assert "Payment reminder" in html
    assert "Hi Sample Customer," in html
    assert "outstanding balance of" in html
    assert "INV-42" in html
    assert "$250.00" in html
    assert "Thank you," in html


def test_invoice_reminder_html_renders_spanish_body(monkeypatch):
    from services import pay_link_builder
    monkeypatch.setattr(
        pay_link_builder, "build_pay_now_url",
        lambda _iid, _tid, src="email": "https://ex.test/pay/inv-abc123",
    )
    from emailer import _reminder_html
    html = _reminder_html(
        _stub_invoice(), "María López", locale="es",
    )
    assert "Recordatorio de pago" in html
    assert "Hola María López:" in html
    assert "saldo pendiente" in html
    assert "INV-42" in html
    assert "$250.00" in html
    assert "Gracias," in html
    # English body sentences must not survive in the Spanish render.
    assert "Payment reminder" not in html
    assert "outstanding balance" not in html


def test_invoice_reminder_html_renders_french_body(monkeypatch):
    from services import pay_link_builder
    monkeypatch.setattr(
        pay_link_builder, "build_pay_now_url",
        lambda _iid, _tid, src="email": "https://ex.test/pay/inv-abc123",
    )
    from emailer import _reminder_html
    html = _reminder_html(
        _stub_invoice(), "Jean Dupont", locale="fr",
    )
    assert "Rappel de paiement" in html
    assert "Bonjour Jean Dupont," in html
    assert "solde impayé" in html
    assert "INV-42" in html
    assert "$250.00" in html
    assert "Merci," in html
    assert "Payment reminder" not in html


def test_invoice_reminder_attachment_copy_localises(monkeypatch):
    from services import pay_link_builder
    monkeypatch.setattr(
        pay_link_builder, "build_pay_now_url",
        lambda _iid, _tid, src="email": "https://ex.test/pay/inv-abc123",
    )
    from emailer import _reminder_html
    html_en = _reminder_html(
        _stub_invoice(), "N", attachment_count=3, locale="en",
    )
    assert "3 attachments included" in html_en
    html_es = _reminder_html(
        _stub_invoice(), "N", attachment_count=3, locale="es",
    )
    assert "3 archivos adjuntos incluidos" in html_es
    html_fr = _reminder_html(
        _stub_invoice(), "N", attachment_count=1, locale="fr",
    )
    assert "1 pièce jointe incluse" in html_fr


# ═════════════════════════════════════════════════════════════════════
# 5 · Estimate/quote reminder HTML — 3 locales
# ═════════════════════════════════════════════════════════════════════
def _stub_estimate(doc_type: str = "estimate"):
    return {
        "id": "est-xyz789",
        "tenant_id": "t-1",
        "doc_type": doc_type,
        "invoice_number": "EST-77",
    }


def test_estimate_reminder_html_renders_english_body():
    from emailer import _estimate_reminder_html
    html = _estimate_reminder_html(
        _stub_estimate(), "Sample Customer",
        {"company_name": "AquaTerra"},
        review_url="https://ex.test/review/est-xyz789",
        locale="en",
    )
    assert "Reminder: your estimate" in html
    assert "Hi Sample Customer," in html
    assert "awaiting your review" in html
    assert "EST-77" in html
    assert "AquaTerra" in html
    assert "Review Estimate" in html


def test_estimate_reminder_html_renders_spanish_body():
    from emailer import _estimate_reminder_html
    html = _estimate_reminder_html(
        _stub_estimate(), "Cliente", {"company_name": "AquaTerra"},
        review_url="https://ex.test/review/est-xyz789", locale="es",
    )
    assert "Recordatorio: su presupuesto" in html
    assert "Hola Cliente:" in html
    assert "pendiente de revisión" in html
    assert "AquaTerra" in html
    assert "Revisar Presupuesto" in html
    assert "Reminder: your estimate" not in html


def test_estimate_reminder_html_renders_french_body():
    from emailer import _estimate_reminder_html
    html = _estimate_reminder_html(
        _stub_estimate(), "Client", {"company_name": "AquaTerra"},
        review_url="https://ex.test/review/est-xyz789", locale="fr",
    )
    assert "Rappel : votre devis" in html
    assert "Bonjour Client," in html
    assert "en attente de votre examen" in html
    assert "Examiner le Devis" in html
    assert "Reminder: your estimate" not in html


def test_estimate_reminder_quote_variant_swaps_doc_type_label():
    from emailer import _estimate_reminder_html
    html_en = _estimate_reminder_html(
        _stub_estimate("quote"), "N", {"company_name": "AT"},
        review_url="https://ex.test/r", locale="en",
    )
    assert "Reminder: your quote" in html_en
    assert "Review Quote" in html_en
    html_es = _estimate_reminder_html(
        _stub_estimate("quote"), "N", {"company_name": "AT"},
        review_url="https://ex.test/r", locale="es",
    )
    assert "Recordatorio: su cotización" in html_es


# ═════════════════════════════════════════════════════════════════════
# 6 · Job-completion HTML — 3 locales
# ═════════════════════════════════════════════════════════════════════
def _stub_job():
    return {
        "id": "job-abc",
        "customer_id": "c-1",
        "tenant_id": "t-1",
        "service_type": "chemical cleaning",
        "scheduled_date": "2026-02-14T10:00:00Z",
        "photos": [],
    }


def test_completion_html_renders_english_body():
    from emailer import _completion_html
    html = _completion_html(_stub_job(), "Sample Customer", locale="en")
    assert "Your service is complete" in html
    assert "Hi Sample Customer," in html
    assert "chemical cleaning" in html
    assert "on 2026-02-14" in html
    assert "View Your Service Report" in html


def test_completion_html_renders_spanish_body():
    from emailer import _completion_html
    html = _completion_html(_stub_job(), "María", locale="es")
    assert "Su servicio se ha completado" in html
    assert "Hola María," in html
    assert "chemical cleaning" in html
    assert "el 2026-02-14" in html
    assert "Ver su informe de servicio" in html
    assert "View Your Service Report" not in html


def test_completion_html_renders_french_body():
    from emailer import _completion_html
    html = _completion_html(_stub_job(), "Jean", locale="fr")
    assert "Votre service est terminé" in html
    assert "Bonjour Jean," in html
    assert "chemical cleaning" in html
    assert "le 2026-02-14" in html
    assert "Voir votre rapport de service" in html


def test_completion_html_no_date_variant_still_renders():
    """``scheduled_date`` empty → the "body_no_date" variant."""
    from emailer import _completion_html
    job = dict(_stub_job()); job["scheduled_date"] = ""
    html = _completion_html(job, "N", locale="en")
    # No "on <date>" phrase but the rest is intact.
    assert "we've finished your" in html
    assert " on " not in html.replace("padding:24px", "")
    # ES / FR variants same.
    html_es = _completion_html(job, "N", locale="es")
    assert "hemos terminado su" in html_es


# ═════════════════════════════════════════════════════════════════════
# 7 · Dunning stage copy — 3 locales
# ═════════════════════════════════════════════════════════════════════
def _stage_ctx():
    return {
        "customer_name": "Alice",
        "invoice_number": "INV-9",
        "invoice_total": "125.00",
        "due_date": "2026-02-20",
        "days_past_due": 7,
        "payment_link": "https://ex.test/pay/inv-9",
        "tenant_name": "AquaTerra",
        "tenant_phone": "555-0100",
        "customer_email": "alice@example.com",
        "customer_phone": "555-0101",
    }


@pytest.mark.parametrize("stage_id", [
    "pre_due_3d", "on_due_day", "past_due_7d",
    "past_due_14d", "past_due_30d", "past_due_60d",
])
def test_dunning_stock_stage_localises_subject_body_sms_en(stage_id):
    from routers.dunning import _localised_stage_copy
    copy = _localised_stage_copy(
        {"id": stage_id}, _stage_ctx(), "en",
    )
    assert copy["subject"], f"{stage_id}/en subject empty"
    assert copy["body"], f"{stage_id}/en body empty"
    assert copy["sms"], f"{stage_id}/en sms empty"
    # Placeholders must be substituted.
    assert "{" not in copy["subject"] or "{{" in copy["subject"]
    assert "AquaTerra" in copy["body"] or "AquaTerra" in copy["sms"]
    assert "INV-9" in copy["body"]


@pytest.mark.parametrize("stage_id", [
    "pre_due_3d", "on_due_day", "past_due_7d",
    "past_due_14d", "past_due_30d", "past_due_60d",
])
def test_dunning_stock_stage_localises_es(stage_id):
    from routers.dunning import _localised_stage_copy
    copy = _localised_stage_copy(
        {"id": stage_id}, _stage_ctx(), "es",
    )
    # Spanish-only phrase in every stage subject or body.
    combined = copy["subject"] + " " + copy["body"] + " " + copy["sms"]
    assert (
        "factura" in combined.lower()
        or "aviso" in combined.lower()
        or "cobranza" in combined.lower()
    ), f"{stage_id}/es did not localise: {combined!r}"
    assert "Reminder:" not in combined  # no English leakage


@pytest.mark.parametrize("stage_id", [
    "pre_due_3d", "on_due_day", "past_due_7d",
    "past_due_14d", "past_due_30d", "past_due_60d",
])
def test_dunning_stock_stage_localises_fr(stage_id):
    from routers.dunning import _localised_stage_copy
    copy = _localised_stage_copy(
        {"id": stage_id}, _stage_ctx(), "fr",
    )
    combined = copy["subject"] + " " + copy["body"] + " " + copy["sms"]
    assert (
        "facture" in combined.lower()
        or "avis" in combined.lower()
        or "recouvrement" in combined.lower()
    ), f"{stage_id}/fr did not localise: {combined!r}"
    assert "Reminder:" not in combined


def test_dunning_custom_stage_falls_through_to_legacy_render():
    """A tenant-customised stage id keeps rendering from its own
    ``*_template`` fields — the D6 wrapper must NOT force such
    stages into a missing i18n key."""
    from routers.dunning import _localised_stage_copy
    custom_stage = {
        "id": "custom_stage_abc",
        "subject_template": "Custom subject for {invoice_number}",
        "body_template": "Custom body for {customer_name}",
        "sms_template": "Custom SMS for {tenant_name}",
    }
    copy = _localised_stage_copy(custom_stage, _stage_ctx(), "es")
    # Locale is irrelevant for custom stages — they render as
    # authored. Substitution still happens through the merge-tag
    # engine.
    assert "INV-9" in copy["subject"]
    assert "Alice" in copy["body"]
    assert "AquaTerra" in copy["sms"]


# ═════════════════════════════════════════════════════════════════════
# 8 · Grep-based assertion — hardcoded English sentences GONE
# ═════════════════════════════════════════════════════════════════════
def test_no_hardcoded_english_body_in_emailer_py():
    """Composer functions must not embed the customer-facing
    sentences as Python literals any more — those live in the
    i18n catalog."""
    src = inspect.getsource(__import__("emailer"))
    # Sentences that used to be hardcoded pre-D6:
    forbidden = [
        "This is a friendly reminder that invoice",
        "This is a friendly reminder that estimate",
        "This is a friendly reminder that quote",
        "has an outstanding balance of",
        "is awaiting your review",
        "Thank you,<br/>Pool",
        "Your service is complete ✅",
        "View Your Service Report",
        "Questions? Just reply in the app",
        "Payment reminder — invoice",
    ]
    hits = [phrase for phrase in forbidden if phrase in src]
    assert not hits, (
        "emailer.py still ships hardcoded English body copy that "
        f"should have moved into the i18n catalog: {hits}"
    )


def test_no_hardcoded_english_dunning_body_in_send_reminder():
    """The `_send_reminder` code path must go through
    ``_localised_stage_copy`` for stock stages — the legacy
    ``_render(stage.get('subject_template') or '', ...)`` line in
    the body of ``_send_reminder`` should be gone."""
    from routers import dunning as _mod
    src = inspect.getsource(_mod._send_reminder)
    assert "_localised_stage_copy" in src, (
        "_send_reminder no longer references the D6 locale render helper"
    )
    # The pre-D6 body-only line used ``_render(custom_message or "…")``
    # — accept the migrated one (custom-message override goes
    # through _render, stock stages go through _localised_stage_copy).
    assert (
        "stage.get(\"subject_template\")" not in src
        and "stage.get('subject_template')" not in src
    ), "legacy stage.subject_template pull is still present in _send_reminder"


# ═════════════════════════════════════════════════════════════════════
# 9 · Subject-line i18n via t_email_body (not concatenation)
# ═════════════════════════════════════════════════════════════════════
def test_invoice_subject_line_localises_via_t_email_body():
    from services.email_body_i18n import t_email_body
    en = t_email_body("en", "email.invoice_reminder.subject",
                       invoice_number="INV-999")
    es = t_email_body("es", "email.invoice_reminder.subject",
                       invoice_number="INV-999")
    fr = t_email_body("fr", "email.invoice_reminder.subject",
                       invoice_number="INV-999")
    assert en == "Payment reminder — invoice INV-999"
    assert es == "Recordatorio de pago — factura INV-999"
    assert fr == "Rappel de paiement — facture INV-999"


def test_estimate_subject_line_localises_via_t_email_body():
    from services.email_body_i18n import t_email_body
    en = t_email_body("en", "email.estimate_reminder.subject",
                       doc_type_label="estimate", company="AquaTerra")
    es = t_email_body("es", "email.estimate_reminder.subject",
                       doc_type_label="presupuesto", company="AquaTerra")
    fr = t_email_body("fr", "email.estimate_reminder.subject",
                       doc_type_label="devis", company="AquaTerra")
    assert en == "Reminder: your estimate from AquaTerra"
    assert es == "Recordatorio: su presupuesto de AquaTerra"
    assert fr == "Rappel : votre devis de AquaTerra"


def test_completion_subject_line_localises_via_t_email_body():
    from services.email_body_i18n import t_email_body
    en = t_email_body("en", "email.job_completed.subject",
                       service_type="chemical cleaning")
    es = t_email_body("es", "email.job_completed.subject",
                       service_type="chemical cleaning")
    fr = t_email_body("fr", "email.job_completed.subject",
                       service_type="chemical cleaning")
    assert en == "Your chemical cleaning is complete"
    assert es == "Su chemical cleaning se ha completado"
    assert fr == "Votre chemical cleaning est terminé"
