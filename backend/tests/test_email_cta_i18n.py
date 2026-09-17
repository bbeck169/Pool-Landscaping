"""Feb 2026 · Invoice Email CTA Label ticket — regression tests.

Scope
-----
1. Pure helper contract: ``t_email_cta(locale, key)`` returns the
   correct label for en/es/fr, coerces unsupported locales to en,
   and raises on unknown keys.
2. All 5 invoice-URL CTA emails render the new "View Invoice" label
   (or its localised variant) instead of the legacy Pay Now / Pay
   online / Pay invoice copy:
     a. ``emailer._reminder_html`` (Payment Reminder — screenshot)
     b. ``comms_seed.system_data._invoice_created_blocks``
     c. ``comms_seed.system_data._invoice_overdue_blocks``
     d. ``seed_system_templates._build_templates`` (Invoice past due 7d)
     e. ``routers.email_preview._stub_invoice_reminder``
3. Dunning plaintext bodies rename "Pay online:" to "View invoice:"
   in all 6 ``DEFAULT_STAGES``.

Truthful assertions — no mocks for the pure helpers; the reminder
HTML shim uses a synthetic invoice dict + ``patch`` for
``build_pay_now_url`` to avoid Motor / env dependencies.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════
# 1 · Pure helper contract
# ═══════════════════════════════════════════════════════════════════

def test_t_email_cta_returns_english_label_for_en():
    from services.email_cta_i18n import t_email_cta
    assert t_email_cta("en", "view_invoice") == "View Invoice"


def test_t_email_cta_returns_spanish_label_for_es():
    from services.email_cta_i18n import t_email_cta
    assert t_email_cta("es", "view_invoice") == "Ver factura"


def test_t_email_cta_returns_french_label_for_fr():
    from services.email_cta_i18n import t_email_cta
    assert t_email_cta("fr", "view_invoice") == "Voir la facture"


def test_t_email_cta_trims_bcp47_region_suffix():
    """``es-MX`` should collapse to ``es`` — matches
    :func:`services.i18n_notifications._normalise_locale`."""
    from services.email_cta_i18n import t_email_cta
    assert t_email_cta("es-MX", "view_invoice") == "Ver factura"
    assert t_email_cta("fr_CA", "view_invoice") == "Voir la facture"


def test_t_email_cta_unsupported_locale_falls_back_to_english():
    from services.email_cta_i18n import t_email_cta
    for bogus in ("de", "ja", "", None, "not-a-locale"):
        assert t_email_cta(bogus, "view_invoice") == "View Invoice"


def test_t_email_cta_unknown_key_raises_keyerror():
    from services.email_cta_i18n import t_email_cta
    with pytest.raises(KeyError):
        t_email_cta("en", "nonexistent_key")


def test_t_email_cta_empty_key_raises_keyerror():
    from services.email_cta_i18n import t_email_cta
    with pytest.raises(KeyError):
        t_email_cta("en", "")


# ═══════════════════════════════════════════════════════════════════
# 2a · emailer._reminder_html (Payment Reminder email — screenshot)
# ═══════════════════════════════════════════════════════════════════

def _stub_inv():
    """Minimal invoice dict for ``_reminder_html``."""
    return {
        "id": "inv-abc123",
        "tenant_id": "t-1",
        "total": 250.00,
        "amount_paid": 0,
        "due_date": "2026-02-15",
        "invoice_number": "INV-42",
    }


def test_payment_reminder_html_default_locale_uses_english_label(monkeypatch):
    """Default locale (en) → "View Invoice", NOT the legacy "Pay Now"."""
    from services import pay_link_builder
    monkeypatch.setattr(
        pay_link_builder, "build_pay_now_url",
        lambda _iid, _tid, src="email": "https://ex.test/pay/inv-abc123",
    )
    from emailer import _reminder_html
    html = _reminder_html(_stub_inv(), "Sample Customer", locale="en")
    assert "View Invoice" in html
    assert "Pay Now" not in html
    assert "https://ex.test/pay/inv-abc123" in html


def test_payment_reminder_html_spanish_uses_spanish_label(monkeypatch):
    from services import pay_link_builder
    monkeypatch.setattr(
        pay_link_builder, "build_pay_now_url",
        lambda _iid, _tid, src="email": "https://ex.test/pay/inv-abc123",
    )
    from emailer import _reminder_html
    html = _reminder_html(_stub_inv(), "Sample Customer", locale="es")
    assert "Ver factura" in html
    assert "Pay Now" not in html


def test_payment_reminder_html_french_uses_french_label(monkeypatch):
    from services import pay_link_builder
    monkeypatch.setattr(
        pay_link_builder, "build_pay_now_url",
        lambda _iid, _tid, src="email": "https://ex.test/pay/inv-abc123",
    )
    from emailer import _reminder_html
    html = _reminder_html(_stub_inv(), "Sample Customer", locale="fr")
    assert "Voir la facture" in html
    assert "Pay Now" not in html


# ═══════════════════════════════════════════════════════════════════
# 2b/2c · comms_seed system templates use "View Invoice" label
# ═══════════════════════════════════════════════════════════════════

def _find_button_label(blocks):
    for b in blocks:
        if b.get("type") == "button":
            return b.get("props", {}).get("label")
    return None


def test_invoice_created_blocks_renames_cta_to_view_invoice():
    """system.invoice_created template — the initial invoice email —
    now uses "View Invoice" instead of the legacy "Pay online" label."""
    from comms_seed.system_data import _invoice_created_blocks
    label = _find_button_label(_invoice_created_blocks())
    assert label == "View Invoice"
    assert label != "Pay online"


def test_invoice_overdue_blocks_renames_cta_to_view_invoice():
    """system.invoice_overdue template — the "polite nudge" past-due
    reminder — now uses "View Invoice" instead of the legacy "Pay now"."""
    from comms_seed.system_data import _invoice_overdue_blocks
    label = _find_button_label(_invoice_overdue_blocks())
    assert label == "View Invoice"
    assert label != "Pay now"


# ═══════════════════════════════════════════════════════════════════
# 2b/2c (follow-up) · Locale threading for the two comms_seed blocks
# ═══════════════════════════════════════════════════════════════════
# Tester follow-up B2 gap: ``_invoice_created_blocks`` and
# ``_invoice_overdue_blocks`` hardcoded ``t_email_cta("en", ...)`` in
# the initial ship, so non-English tenants received an English CTA.
# The blocks now accept a ``locale`` kwarg; ``build_system_email_templates``
# threads the tenant/recipient locale through both.

def test_invoice_created_blocks_spanish_uses_ver_factura():
    from comms_seed.system_data import _invoice_created_blocks
    label = _find_button_label(_invoice_created_blocks(locale="es"))
    assert label == "Ver factura"


def test_invoice_created_blocks_french_uses_voir_la_facture():
    from comms_seed.system_data import _invoice_created_blocks
    label = _find_button_label(_invoice_created_blocks(locale="fr"))
    assert label == "Voir la facture"


def test_invoice_overdue_blocks_spanish_uses_ver_factura():
    from comms_seed.system_data import _invoice_overdue_blocks
    label = _find_button_label(_invoice_overdue_blocks(locale="es"))
    assert label == "Ver factura"


def test_invoice_overdue_blocks_french_uses_voir_la_facture():
    from comms_seed.system_data import _invoice_overdue_blocks
    label = _find_button_label(_invoice_overdue_blocks(locale="fr"))
    assert label == "Voir la facture"


def test_invoice_blocks_unsupported_locale_falls_back_to_english():
    """Bogus tenant.default_locale must render a valid CTA — English
    is the fallback per ``t_email_cta`` contract."""
    from comms_seed.system_data import (
        _invoice_created_blocks, _invoice_overdue_blocks,
    )
    for bogus in ("de", "ja", "not-a-locale"):
        assert _find_button_label(
            _invoice_created_blocks(locale=bogus)) == "View Invoice"
        assert _find_button_label(
            _invoice_overdue_blocks(locale=bogus)) == "View Invoice"


def test_build_system_email_templates_threads_locale_into_invoice_blocks():
    """``build_system_email_templates(locale=…)`` returns the same
    template list with the two invoice-CTA blocks rebuilt for the
    requested locale. Locale-invariant templates (welcome, appointment
    reminder, visit summary, etc.) pass through unchanged."""
    from comms_seed.system_data import build_system_email_templates

    tpls_es = build_system_email_templates("es")
    created = next(t for t in tpls_es
                    if t["code"] == "system.invoice_created")
    overdue = next(t for t in tpls_es
                    if t["code"] == "system.invoice_overdue")
    assert _find_button_label(created["blocks_json"]) == "Ver factura"
    assert _find_button_label(overdue["blocks_json"]) == "Ver factura"

    tpls_fr = build_system_email_templates("fr")
    created_fr = next(t for t in tpls_fr
                       if t["code"] == "system.invoice_created")
    overdue_fr = next(t for t in tpls_fr
                       if t["code"] == "system.invoice_overdue")
    assert _find_button_label(created_fr["blocks_json"]) == "Voir la facture"
    assert _find_button_label(overdue_fr["blocks_json"]) == "Voir la facture"


def test_module_level_system_email_templates_stays_english_for_backcompat():
    """``SYSTEM_EMAIL_TEMPLATES`` remains the ``locale="en"`` variant
    at module import time so ``seed_comms`` (system-wide
    ``tenant_id=None`` seed) + every legacy caller keeps behaving
    byte-identically to pre-refactor."""
    from comms_seed.system_data import SYSTEM_EMAIL_TEMPLATES
    created = next(t for t in SYSTEM_EMAIL_TEMPLATES
                    if t["code"] == "system.invoice_created")
    overdue = next(t for t in SYSTEM_EMAIL_TEMPLATES
                    if t["code"] == "system.invoice_overdue")
    assert _find_button_label(created["blocks_json"]) == "View Invoice"
    assert _find_button_label(overdue["blocks_json"]) == "View Invoice"


# ═══════════════════════════════════════════════════════════════════
# 2d · seed_system_templates.py — locale-aware CTA
# ═══════════════════════════════════════════════════════════════════

def test_seed_system_templates_english_uses_view_invoice_label():
    """Per-tenant seed for an English tenant should embed the new
    "View Invoice" label + not the legacy "Pay invoice" copy."""
    from services.migrations.seed_system_templates import _build_templates
    tpls = _build_templates("en")
    past_due = next(t for t in tpls
                    if t["system_template_id"] == "invoice_past_due_7d")
    body = past_due["email_template"]["body"]
    assert "View Invoice" in body
    assert "Pay invoice</a>" not in body  # legacy CTA gone


def test_seed_system_templates_spanish_uses_ver_factura_label():
    from services.migrations.seed_system_templates import _build_templates
    tpls = _build_templates("es")
    past_due = next(t for t in tpls
                    if t["system_template_id"] == "invoice_past_due_7d")
    body = past_due["email_template"]["body"]
    assert "Ver factura" in body
    assert "View Invoice" not in body


def test_seed_system_templates_french_uses_voir_la_facture_label():
    from services.migrations.seed_system_templates import _build_templates
    tpls = _build_templates("fr")
    past_due = next(t for t in tpls
                    if t["system_template_id"] == "invoice_past_due_7d")
    body = past_due["email_template"]["body"]
    assert "Voir la facture" in body
    assert "View Invoice" not in body


def test_seed_system_templates_unsupported_locale_falls_back_to_english():
    """Guarantees a bogus tenant.default_locale never renders an empty
    label. English is the fallback per the helper contract."""
    from services.migrations.seed_system_templates import _build_templates
    tpls = _build_templates("de")
    past_due = next(t for t in tpls
                    if t["system_template_id"] == "invoice_past_due_7d")
    body = past_due["email_template"]["body"]
    assert "View Invoice" in body


# ═══════════════════════════════════════════════════════════════════
# 2e · email_preview.py stub — locale-aware
# ═══════════════════════════════════════════════════════════════════

def test_email_preview_invoice_reminder_stub_en_uses_view_invoice():
    from routers.email_preview import _stub_invoice_reminder
    html = _stub_invoice_reminder("en")
    assert "View Invoice" in html
    assert "Pay now" not in html


def test_email_preview_invoice_reminder_stub_es_uses_ver_factura():
    from routers.email_preview import _stub_invoice_reminder
    html = _stub_invoice_reminder("es")
    assert "Ver factura" in html


def test_email_preview_invoice_reminder_stub_fr_uses_voir_la_facture():
    from routers.email_preview import _stub_invoice_reminder
    html = _stub_invoice_reminder("fr")
    assert "Voir la facture" in html


def test_email_preview_invoice_reminder_stub_default_arg_is_english():
    """Legacy no-arg callers still get the English label."""
    from routers.email_preview import _stub_invoice_reminder
    html = _stub_invoice_reminder()
    assert "View Invoice" in html


# ═══════════════════════════════════════════════════════════════════
# 3 · Dunning plaintext bodies use "View invoice:" not "Pay online:"
# ═══════════════════════════════════════════════════════════════════

def test_dunning_default_stages_use_view_invoice_label_in_all_bodies():
    """All 6 canonical dunning stages ship the new "View invoice:"
    plaintext label in the email body_template. The legacy "Pay
    online:" copy must be fully gone (SMS templates keep "Pay:" —
    out of scope for this ticket)."""
    from routers.dunning import DEFAULT_STAGES
    assert len(DEFAULT_STAGES) == 6, "unexpected default-stage count"
    for stage in DEFAULT_STAGES:
        body = stage["body_template"]
        assert "View invoice:" in body, (
            f"stage {stage['id']} missing 'View invoice:' — body:\n{body}")
        assert "Pay online:" not in body, (
            f"stage {stage['id']} still uses legacy 'Pay online:' copy")


def test_dunning_manual_synthesized_stage_uses_view_invoice_label():
    """The manual-send fallback in ``manual_send`` synthesizes a
    minimal stage when the caller doesn't pass a stage_id. Its body
    template also renames to "View invoice:"."""
    from routers import dunning as _d
    # We can't easily reach the inline synthesised stage without
    # rebuilding the manual_send call graph — instead assert the
    # legacy 'Pay online:' string is fully absent from the source
    # of the module (belt-and-braces).
    import inspect
    src = inspect.getsource(_d)
    assert "Pay online:" not in src, (
        "dunning module still contains legacy 'Pay online:' plaintext "
        "label — check both DEFAULT_STAGES and the manual_send "
        "synthesised stage."
    )
