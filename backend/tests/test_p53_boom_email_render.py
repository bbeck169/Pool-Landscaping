"""Phase P53 · Feb-2026 — BOOM referral-reward email render lockdown.

Locks the visual + merge-variable + CSS invariants of the new
BOOM celebration body. This is a pure-render test (no DB, no
network, no live server) so it runs in <1s and gives instant
feedback on any regression to the template constant.
"""
from __future__ import annotations

import re

import pytest

from services.marketing.merge_tags import render_template
from services.referral_watcher import (
    _REFERRAL_EMAIL_BODY,
    _REFERRAL_EMAIL_BODY_LEGACY_P10,
    _REFERRAL_EMAIL_BODY_VERSION,
    _REFERRAL_EMAIL_SUBJECT,
    _absolute_portal_referrals_url,
)


# ═════════════════════════════════════════════════════════════════════
# Fixtures — canonical + alternate stub contexts
# ═════════════════════════════════════════════════════════════════════
def _ctx(*, credit: str = "$55.00", company: str = "BOOM Test Co",
          first: str = "Alex", friend: str = "Prasad Mikkilineni",
          balance: str = "$110.00") -> dict:
    return {
        "CUSTOMER_FIRST_NAME": first,
        "REFERRAL_FRIEND_NAME": friend,
        "REFERRAL_CREDIT_AMOUNT": credit,
        "CUSTOMER_CREDIT_BALANCE": balance,
        "COMPANY_NAME": company,
        "PORTAL_REFERRALS_URL": _absolute_portal_referrals_url(),
    }


def _render(ctx: dict) -> str:
    body, _ = render_template(_REFERRAL_EMAIL_BODY, ctx)
    return body


# ═════════════════════════════════════════════════════════════════════
# Section 1 — Design markers (raw template contains them)
# ═════════════════════════════════════════════════════════════════════
def test_hero_gradient_exact_stops():
    """Locks the 135deg #1B1F5C → #16A34A hero gradient exactly."""
    assert "linear-gradient(135deg,#1B1F5C 0%,#16A34A 100%)" \
        in _REFERRAL_EMAIL_BODY


def test_reward_badge_uses_emerald_bg():
    """Locks the pill badge emerald bg color (#10B981)."""
    assert "#10B981" in _REFERRAL_EMAIL_BODY


def test_pill_border_radius_is_full_round():
    """Pill shape — ``border-radius:999px`` (rendered twice —
    once on the badge, once on the CTA button)."""
    assert _REFERRAL_EMAIL_BODY.count("border-radius:999px") >= 2


def test_boom_headline_text_and_emoji_present():
    """The literal 'BOOM! 🚀 You just earned ' string must appear so
    subject lines and preview panes render the tagline."""
    assert "BOOM! 🚀 You just earned " in _REFERRAL_EMAIL_BODY


def test_cta_label_present():
    """CTA button text — 'Refer another friend'."""
    assert "Refer another friend" in _REFERRAL_EMAIL_BODY


def test_signoff_present():
    """Sign-off literal — the '{{COMPANY_NAME}} Team' variant so it
    stays tenant-agnostic (no hardcoded Vistancia)."""
    assert "Keep sharing the love! — {{COMPANY_NAME}} Team" \
        in _REFERRAL_EMAIL_BODY


def test_amount_font_size_is_large_display():
    """Reward badge amount font-size ≥ 48px per the P53 spec."""
    assert "font-size:48px" in _REFERRAL_EMAIL_BODY


def test_soft_drop_shadow_on_badge():
    """Emerald soft drop shadow — helps modern clients that support
    ``box-shadow``. Outlook degrades gracefully; that is expected."""
    assert "box-shadow:0 4px 16px rgba(16,185,129,0.35)" \
        in _REFERRAL_EMAIL_BODY


# ═════════════════════════════════════════════════════════════════════
# Section 2 — Merge variables substitute correctly + no leaks
# ═════════════════════════════════════════════════════════════════════
def test_all_five_placeholders_substituted():
    """After render, every original ``{{TOKEN}}`` must be gone."""
    ctx = _ctx()
    out = _render(ctx)
    for token in ("{{CUSTOMER_FIRST_NAME}}", "{{REFERRAL_FRIEND_NAME}}",
                  "{{REFERRAL_CREDIT_AMOUNT}}", "{{CUSTOMER_CREDIT_BALANCE}}",
                  "{{COMPANY_NAME}}", "{{PORTAL_REFERRALS_URL}}"):
        assert token not in out, (
            f"unrendered placeholder {token!r} leaked into output"
        )


def test_all_substituted_values_land_in_output():
    ctx = _ctx()
    out = _render(ctx)
    assert ctx["CUSTOMER_FIRST_NAME"] in out
    assert ctx["REFERRAL_FRIEND_NAME"] in out
    assert ctx["REFERRAL_CREDIT_AMOUNT"] in out
    assert ctx["CUSTOMER_CREDIT_BALANCE"] in out
    assert ctx["COMPANY_NAME"] in out


def test_amount_25_renders_without_leak():
    """Prove the amount is NOT hardcoded to $55 — legacy $25 tenants
    must render just as cleanly."""
    ctx = _ctx(credit="$25.00")
    out = _render(ctx)
    assert "$25.00" in out
    assert "$55" not in out


def test_amount_55_renders_without_leak():
    ctx = _ctx(credit="$55.00")
    out = _render(ctx)
    assert "$55.00" in out


def test_company_name_variable_not_vistancia_hardcode():
    """Prove no 'Vistancia' hardcode — a different tenant must render
    with their own company name."""
    ctx = _ctx(company="AquaTerra Pools")
    out = _render(ctx)
    assert "AquaTerra Pools Team" in out
    assert "Vistancia" not in out


# ═════════════════════════════════════════════════════════════════════
# Section 3 — Zero external CSS / <style> block
# ═════════════════════════════════════════════════════════════════════
def test_no_external_stylesheet_link():
    """Email-client compatibility — no ``<link rel="stylesheet">``."""
    assert not re.search(
        r"<link[^>]*rel=[\"']stylesheet[\"']", _REFERRAL_EMAIL_BODY,
        flags=re.IGNORECASE,
    )


def test_no_style_block():
    """All CSS must be inline — no ``<style>`` block anywhere."""
    assert "<style" not in _REFERRAL_EMAIL_BODY.lower()


# ═════════════════════════════════════════════════════════════════════
# Section 4 — CTA href shape
# ═════════════════════════════════════════════════════════════════════
def test_cta_href_points_to_portal_referrals(monkeypatch):
    """CTA link resolves to ``/portal/referrals`` (with or without a
    ``PUBLIC_APP_URL`` prefix)."""
    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
    ctx = _ctx()
    ctx["PORTAL_REFERRALS_URL"] = _absolute_portal_referrals_url()
    out = _render(ctx)
    assert 'href="/portal/referrals"' in out


def test_cta_href_absolute_when_public_app_url_set(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.example.com")
    ctx = _ctx()
    ctx["PORTAL_REFERRALS_URL"] = _absolute_portal_referrals_url()
    out = _render(ctx)
    assert 'href="https://app.example.com/portal/referrals"' in out


# ═════════════════════════════════════════════════════════════════════
# Section 5 — Version marker + subject line
# ═════════════════════════════════════════════════════════════════════
def test_body_version_marker_is_p53_v1():
    """The version constant is the single source of truth for the
    upsert to detect 'already-current' rows."""
    assert _REFERRAL_EMAIL_BODY_VERSION == "p53_v1"


def test_subject_uses_boom_and_amount_var():
    """Subject line must include the amount variable, not a hardcoded
    dollar figure."""
    assert "BOOM!" in _REFERRAL_EMAIL_SUBJECT
    assert "{{REFERRAL_CREDIT_AMOUNT}}" in _REFERRAL_EMAIL_SUBJECT
    # No accidental hardcode.
    assert "$25" not in _REFERRAL_EMAIL_SUBJECT
    assert "$55" not in _REFERRAL_EMAIL_SUBJECT


def test_legacy_p10_body_preserved_as_constant():
    """The Phase-10 canonical body is preserved as
    ``_REFERRAL_EMAIL_BODY_LEGACY_P10`` — the upsert uses it to
    detect 'system row not tenant-customized'. If someone deletes
    it, we'd silently stop upgrading existing rows."""
    assert _REFERRAL_EMAIL_BODY_LEGACY_P10, (
        "legacy Phase-10 body constant must be preserved for the "
        "P53 upsert customization detector to function"
    )
    assert "Great news — your referral of" in _REFERRAL_EMAIL_BODY_LEGACY_P10
