"""Phase P50 · Feb-2026 — Backend notification template locale fallback.

Locks the two locale-fallback contracts that already ship in the
backend i18n stack (P50 audit-only for the backend surface — the
ES/FR variants were already fully populated at import time):

  1. ``services.email_body_i18n.t_email_body`` — the LABELS dict
     catalogues 131 keys × 3 locales (en/es/fr).  The resolver
     falls back:
       * unsupported locale       → English variant.
       * key missing under locale → English variant.
       * key missing under EN too → ``KeyError`` (bug).
     P50 test locks all three branches + the "empty ES/FR bundles
     is a wire failure not a runtime crash" invariant (parity check).

  2. ``services.i18n_notifications.resolve_notification_body`` —
     disk-backed templates at
     ``services/notification_templates/{en,es,fr}/`` mirror the same
     fallback contract but hit the filesystem instead of a dict.
     P50 test locks the ``requested → en → TemplateNotFoundError``
     chain, plus parity (every EN template file has ES + FR
     siblings).

Both surfaces are net-shipped in earlier phases (D5 / D6).  P50
adds the regression lockdown so a future migration doesn't
silently drop a template.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.email_body_i18n import (
    FALLBACK_LOCALE,
    LABELS,
    SUPPORTED_LOCALES,
    t_email_body,
)


TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "services" / "notification_templates"
)


# ═════════════════════════════════════════════════════════════════════
# Section 1 — services.email_body_i18n.t_email_body
# ═════════════════════════════════════════════════════════════════════
def test_email_body_labels_parity_across_locales():
    """Every EN key MUST have an ES + FR mirror.  A missing key
    would silently fall back to EN at runtime — the test catches the
    drift at CI time instead."""
    en_keys = set(LABELS["en"].keys())
    for loc in SUPPORTED_LOCALES:
        assert loc in LABELS, f"missing bundle for locale={loc!r}"
        loc_keys = set(LABELS[loc].keys())
        missing = en_keys - loc_keys
        assert not missing, (
            f"locale={loc!r} missing {len(missing)} keys "
            f"(sample: {sorted(missing)[:5]!r})"
        )
        orphan = loc_keys - en_keys
        assert not orphan, (
            f"locale={loc!r} carries {len(orphan)} orphan keys not "
            f"in EN (sample: {sorted(orphan)[:5]!r})"
        )


def test_email_body_supported_locales_are_en_es_fr():
    """The P50 spec locks the supported locale set at three: EN, ES,
    FR.  Additions require a separate phase (D7+) with translator
    review."""
    assert set(SUPPORTED_LOCALES) == {"en", "es", "fr"}
    assert FALLBACK_LOCALE == "en"


def test_email_body_resolves_each_locale():
    """Spot-check that a shipped key resolves distinctly per locale
    (i.e., ES / FR aren't accidentally aliased to EN)."""
    key = "email.invoice_reminder.subject"
    en = t_email_body("en", key, invoice_number="INV-1")
    es = t_email_body("es", key, invoice_number="INV-1")
    fr = t_email_body("fr", key, invoice_number="INV-1")
    assert en, "EN must resolve"
    assert es, "ES must resolve"
    assert fr, "FR must resolve"
    # All three must be distinct — a runtime alias would defeat the
    # whole point of i18n.
    assert en != es, (en, es)
    assert en != fr, (en, fr)


def test_email_body_unsupported_locale_falls_back_to_en():
    """Requested locale not in SUPPORTED_LOCALES → EN variant is
    returned.  This is the wire-level defence against a stale
    ``user.locale`` value in Mongo."""
    en = t_email_body("en", "email.invoice_reminder.heading")
    weird = t_email_body("de-invalid", "email.invoice_reminder.heading")
    assert weird == en


def test_email_body_missing_key_under_es_falls_back_to_en():
    """Inject a temporary EN-only key so we can prove the fallback
    without depending on organic drift in the LABELS dict."""
    key = "email.__p50_test_only.en_only"
    LABELS["en"][key] = "EN-only test value"
    try:
        assert "es" in LABELS and key not in LABELS["es"], (
            "test invariant broken — ES bundle should NOT carry "
            "this synthetic key")
        assert t_email_body("es", key) == "EN-only test value"
        assert t_email_body("fr", key) == "EN-only test value"
    finally:
        LABELS["en"].pop(key, None)


def test_email_body_missing_key_under_en_raises_keyerror():
    """If a key is missing under EN too, the resolver raises
    KeyError — signalling a code bug (call site referenced a key
    that was never catalogued)."""
    with pytest.raises(KeyError):
        t_email_body("en", "email.__p50_test.definitely_not_catalogued")


# ═════════════════════════════════════════════════════════════════════
# Section 2 — services/notification_templates/{en,es,fr}/
# ═════════════════════════════════════════════════════════════════════
def test_notification_template_files_parity():
    """Every EN template file (email .html/.txt/.subject.txt + SMS
    .sms.txt) MUST have an ES + FR sibling at the exact same
    filename.  A drift would silently short-circuit through the
    resolver's ``requested → en`` fallback at runtime; this test
    catches the drift at CI time."""
    en_dir = TEMPLATE_ROOT / "en"
    es_dir = TEMPLATE_ROOT / "es"
    fr_dir = TEMPLATE_ROOT / "fr"
    assert en_dir.is_dir(), f"missing EN template root: {en_dir}"

    en_files = {p.name for p in en_dir.iterdir() if p.is_file()}
    es_files = {p.name for p in es_dir.iterdir() if p.is_file()}
    fr_files = {p.name for p in fr_dir.iterdir() if p.is_file()}

    assert en_files, "EN template dir must not be empty"

    es_missing = en_files - es_files
    fr_missing = en_files - fr_files
    assert not es_missing, (
        f"ES template dir missing {len(es_missing)} sibling(s): "
        f"{sorted(es_missing)!r}"
    )
    assert not fr_missing, (
        f"FR template dir missing {len(fr_missing)} sibling(s): "
        f"{sorted(fr_missing)!r}"
    )

    # Orphan check — ES / FR carry files that don't exist in EN
    # would signal a rogue add that got merged without an EN
    # canonical source.
    es_orphan = es_files - en_files
    fr_orphan = fr_files - en_files
    assert not es_orphan, (
        f"ES template dir carries {len(es_orphan)} orphan file(s) "
        f"(no EN sibling): {sorted(es_orphan)!r}"
    )
    assert not fr_orphan, (
        f"FR template dir carries {len(fr_orphan)} orphan file(s) "
        f"(no EN sibling): {sorted(fr_orphan)!r}"
    )


def test_notification_template_resolver_falls_back_to_en_on_unsupported_locale():
    """``resolve_notification_body`` requested → en → TemplateNotFound
    contract.  An unsupported locale returns the EN variant."""
    from services.i18n_notifications import resolve_notification_body

    # Pick a template we KNOW exists — ``visit_summary_email`` ships
    # in all three locales.  Supply every placeholder the EN + ES +
    # FR variants reference (grep-derived so the test stays stable
    # when translators add merge vars).
    ctx = {
        "business_name": "AquaTerra",
        "customer_first_name": "Ada",
        "portal_link": "https://example.com/portal",
        "visit_date": "2026-02-01",
    }

    en_result = resolve_notification_body(
        "visit_summary_email", locale="en", context=ctx,
    )
    weird_result = resolve_notification_body(
        "visit_summary_email", locale="zz-nonsense", context=ctx,
    )
    # The resolver normalises unsupported → EN, so both results
    # must be identical.
    assert weird_result == en_result
    # Sanity check on shape — visit_summary_email is an email
    # template so we expect subject + body_html + body_text keys.
    assert set(en_result.keys()) >= {"subject", "body_html", "body_text"}


def test_notification_template_resolver_unknown_template_raises():
    """Nonexistent template → the resolver raises rather than
    silently returning None."""
    from services.i18n_notifications import (
        resolve_notification_body, TemplateNotFoundError,
    )
    with pytest.raises(TemplateNotFoundError):
        resolve_notification_body(
            "__p50_definitely_not_a_real_template", locale="en",
            context={"any": "thing"},
        )
