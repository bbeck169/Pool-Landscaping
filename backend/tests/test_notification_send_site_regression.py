"""Phase D5 · Feb-2026 — wired send-site regression.

Confirms the ONE fully-wired send site (``completion_sms_template.
build_completion_sms_body``) produces the expected locale-specific
body when the customer / tenant carry a locale field. Fallback path
(missing loader → inline English) is also covered so a template-tree
bug can't blank an outbound SMS.

The visit_summary email subject wiring is covered by the auto-visit-
email regression tests already in the pytest suite — that path
resolves through ``services.i18n_notifications`` and reuses the same
loader.
"""
from __future__ import annotations

from services.completion_sms_template import build_completion_sms_body


def test_completion_sms_english_default_is_byte_identical_to_pre_d5():
    body = build_completion_sms_body(
        tenant={"name": "Acme Pools"},
        job={"title": "Weekly pool cleaning"},
        customer={"first_name": "Diego"},
        portal_link="https://p.example/z",
    )
    # Pre-D5 wording — byte identical.
    assert body == (
        "Hi Diego, your Weekly pool cleaning with Acme Pools is complete! "
        "View your full report and photos here: https://p.example/z"
    )


def test_completion_sms_spanish_customer_locale_wins():
    body = build_completion_sms_body(
        tenant={"name": "Acme Pools", "default_locale": "en"},
        job={"title": "Servicio de piscina"},
        customer={"first_name": "Ana", "locale": "es"},
        portal_link="https://p.example/z",
    )
    assert body.startswith("Hola Ana,")
    assert "Servicio de piscina" in body
    assert "Acme Pools" in body
    assert "https://p.example/z" in body


def test_completion_sms_french_tenant_default_when_no_customer_locale():
    body = build_completion_sms_body(
        tenant={"name": "Acme Pools", "default_locale": "fr"},
        job={"title": "Nettoyage"},
        customer={"first_name": "Pierre"},
        portal_link="https://p.example/z",
    )
    assert body.startswith("Bonjour Pierre,")
    assert "Nettoyage" in body


def test_completion_sms_admin_always_english_in_scope():
    # The completion SMS is a customer-facing template — the resolver
    # for this template always uses ``audience="customer"``. If a
    # tenant.default_locale is set to fr, it should apply. Admin
    # audience routing isn't the completion SMS's concern; this test
    # documents the wired contract.
    body = build_completion_sms_body(
        tenant={"name": "Acme"},
        job={"title": "Service"},
        customer={"first_name": "X"},
        portal_link="https://p.example/z",
    )
    assert body.startswith("Hi X,")


def test_completion_sms_fallback_to_inline_english_on_loader_crash(
    monkeypatch,
):
    """If the i18n loader can't be imported or crashes, the send site
    must fall back to the pre-D5 inline English composition — never
    blank the SMS."""
    from services import i18n_notifications as _mod

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated template tree corruption")

    monkeypatch.setattr(_mod, "resolve_notification_body", _boom)
    body = build_completion_sms_body(
        tenant={"name": "Acme"},
        job={"title": "Pool service"},
        customer={"first_name": "Y", "locale": "es"},
        portal_link="https://p.example/z",
    )
    # Falls back to inline English wording even though customer.locale=es.
    assert body.startswith("Hi Y,")
    assert "Pool service" in body


def test_completion_sms_length_within_two_segments_all_locales():
    """A realistic long-name / long-title tenant + customer should
    still fit within 2 SMS segments across every locale — otherwise
    tighten the copy."""
    from services.i18n_notifications import sms_segment_count

    for loc in ("en", "es", "fr"):
        body = build_completion_sms_body(
            tenant={"name": "Pool & Landscaping of Vistancia",
                     "default_locale": loc},
            job={"title": "Weekly pool cleaning"},
            customer={"first_name": "Alexander"},
            portal_link="https://app.plofv.com/portal/j/abcd1234",
        )
        segs = sms_segment_count(body)
        assert segs <= 2, (
            f"completion_sms in {loc} → {len(body)} chars / {segs} "
            "segments (over the 2-segment budget)"
        )
