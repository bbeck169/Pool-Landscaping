"""Phase 21 · Feb-2026 — Portal invite URL-encoded merge-tag repair.

Locks the contract for the ``%7B%7BTOKEN%7D%7D`` repair added to the
``services.marketing.merge_tags`` module and wired into the two
send paths that render tenant-editable bodies:

  * ``routers.portal_admin._try_send_reset_email``
    (both ``/customers/{cid}/portal-invite`` single + the
    ``/admin/customers/portal-invite/bulk`` loop share this helper)
  * ``routers.admin_users._send_password_reset_email``

Root cause (per Phase 21 brief): some tenants have the body
stored with URL-encoded brace sequences — stems from a rich-text
editor's clipboard-paste path, a legacy querystring migration,
or an operator pasting a URL-encoded sample as the default. The
``render_template`` regex matches literal ``{{…}}`` only, so the
encoded tokens slipped through to the recipient unchanged.

Fix: a pre-render ``normalize_url_encoded_merge_tags`` pass that
rewrites ``%7B%7BTOKEN%7D%7D`` → ``{{TOKEN}}`` (and the single-
brace catalog ``%7BTOKEN%7D`` → ``{TOKEN}``) only when the braces
bracket a token-shaped identifier. Non-brace URL encodings in
the body (``%2F``, ``%3A`` in tracked click URLs, etc.) are
untouched.

Strictly manual pytest — no testing agent per the brief.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types

import pytest


from services.marketing.merge_tags import (
    normalize_url_encoded_merge_tags,
    rebrace_single_brace_catalog_tokens,
    render_template,
)


# ─── normaliser · double-brace URL-encoded → canonical ────────────

def test_normalise_double_brace_name_token():
    out = normalize_url_encoded_merge_tags("Hi %7B%7BNAME%7D%7D,")
    assert out == "Hi {{NAME}},"


def test_normalise_double_brace_all_four_portal_invite_tokens():
    body = (
        "Hi %7B%7BNAME%7D%7D,\n"
        "Email: %7B%7BTO%7D%7D\n"
        "Password: %7B%7BTEMP_PASSWORD%7D%7D\n"
        "Sign in: %7B%7BLOGIN_URL%7D%7D"
    )
    out = normalize_url_encoded_merge_tags(body)
    assert out == (
        "Hi {{NAME}},\n"
        "Email: {{TO}}\n"
        "Password: {{TEMP_PASSWORD}}\n"
        "Sign in: {{LOGIN_URL}}"
    )


def test_normalise_double_brace_is_case_insensitive_on_hex():
    """``%7b%7b…%7d%7d`` and the uppercase variant both normalise."""
    out = normalize_url_encoded_merge_tags(
        "Hi %7b%7bNAME%7d%7d, %7B%7BTO%7D%7D"
    )
    assert out == "Hi {{NAME}}, {{TO}}"


def test_normalise_double_brace_tolerates_internal_whitespace():
    out = normalize_url_encoded_merge_tags("%7B%7B NAME %7D%7D")
    assert out == "{{NAME}}"


def test_normalise_single_brace_catalog_token_upgrades_to_single_brace():
    # Single-brace catalog token — the follow-up
    # ``rebrace_single_brace_catalog_tokens`` promotes it to the
    # double-brace form on the next pass.  This test confirms the
    # normalise step UN-encodes the braces to the canonical
    # single-brace shape so the catalog upgrade can see them.
    out = normalize_url_encoded_merge_tags("Hi %7BCOMPANY_NAME%7D")
    assert out == "Hi {COMPANY_NAME}"


def test_normalise_single_brace_non_catalog_identifier_left_verbatim():
    # Unknown identifier — not in the catalog, so the single-brace
    # UNENCODE must NOT fire (prevents collateral damage on genuine
    # URL-encoded braces in prose or JSON snippets).
    out = normalize_url_encoded_merge_tags("Code: %7Bfoo_unknown%7D")
    assert out == "Code: %7Bfoo_unknown%7D"


# ─── normaliser · negative paths (non-brace URL encodings) ────────

def test_normalise_leaves_non_brace_url_encodings_alone():
    body = "https://example.com/path%2Fto%3Alogin?x=%26y=%3F"
    assert normalize_url_encoded_merge_tags(body) == body


def test_normalise_leaves_literal_percent_hex_prose_alone():
    body = "Price up 7% to $100%7E, no decoding here."
    assert normalize_url_encoded_merge_tags(body) == body


def test_normalise_leaves_already_canonical_double_brace_tokens_alone():
    body = "Hi {{NAME}}, visit {{LOGIN_URL}}"
    assert normalize_url_encoded_merge_tags(body) == body


def test_normalise_is_idempotent():
    body = "Hi %7B%7BNAME%7D%7D, Email: %7B%7BTO%7D%7D"
    once = normalize_url_encoded_merge_tags(body)
    twice = normalize_url_encoded_merge_tags(once)
    assert once == twice == "Hi {{NAME}}, Email: {{TO}}"


def test_normalise_mixed_canonical_and_url_encoded_tokens():
    body = "Hi {{NAME}}, Email: %7B%7BTO%7D%7D"
    assert normalize_url_encoded_merge_tags(body) == (
        "Hi {{NAME}}, Email: {{TO}}"
    )


# ─── normaliser · guards against malformed input ───────────────────

def test_normalise_handles_empty_and_none():
    assert normalize_url_encoded_merge_tags("") == ""
    assert normalize_url_encoded_merge_tags(None) == ""


def test_normalise_handles_non_string_input():
    # Defensive — a caller mistakenly passing a dict / list / int
    # should get an empty string, never raise.
    assert normalize_url_encoded_merge_tags(123) == ""
    assert normalize_url_encoded_merge_tags(["body"]) == ""


# ─── end-to-end · normaliser + rebrace + render chain ──────────────

def test_end_to_end_url_encoded_portal_invite_body_renders_correctly():
    """The exact failure shape from the Phase 21 brief: the four
    portal-invite tokens arrive URL-encoded and the recipient
    receives ``%7B%7BLOGIN_URL%7D%7D`` instead of their login
    link. This test runs the full pre-render pipeline from
    ``_try_send_reset_email`` (normalise → rebrace → render) and
    asserts every token resolves to its ``ctx`` value."""
    body = (
        "<p>Hi %7B%7BNAME%7D%7D,</p>"
        "<p>Your portal login is ready.</p>"
        "<p><strong>Email:</strong> %7B%7BTO%7D%7D<br>"
        "<strong>Temporary password:</strong> "
        "<code>%7B%7BTEMP_PASSWORD%7D%7D</code></p>"
        "<p><a href='%7B%7BLOGIN_URL%7D%7D'>Sign in here</a>.</p>"
    )
    ctx = {
        "name": "Jane Smith",
        "to": "jane@example.com",
        "temp_password": "TempPass123",
        "login_url": "https://app.plofv.com/portal/login",
        "tenant": {"id": "aquaterra"},
    }
    body = normalize_url_encoded_merge_tags(body)
    body = rebrace_single_brace_catalog_tokens(body)
    rendered, unresolved = render_template(body, ctx, missing="empty")

    # Regression lock — raw brace / URL-encoded brace patterns MUST
    # NOT survive to the recipient.
    assert "%7B%7B" not in rendered
    assert "{{" not in rendered

    # Each token resolves to its ctx value.
    assert "Jane Smith" in rendered
    assert "jane@example.com" in rendered
    assert "TempPass123" in rendered
    assert "https://app.plofv.com/portal/login" in rendered
    assert unresolved == []


def test_end_to_end_mixed_canonical_and_url_encoded_tokens_render():
    """Mixed input — some tokens are already canonical ``{{NAME}}``,
    others are URL-encoded. Pipeline resolves BOTH."""
    body = (
        "Hi {{NAME}}, we received your request to "
        "<a href='%7B%7BLOGIN_URL%7D%7D'>reset your password</a>."
    )
    ctx = {
        "name": "Jane",
        "login_url": "https://app.plofv.com/reset?t=xyz",
    }
    body = normalize_url_encoded_merge_tags(body)
    body = rebrace_single_brace_catalog_tokens(body)
    rendered, _ = render_template(body, ctx, missing="empty")
    assert "Hi Jane," in rendered
    assert "https://app.plofv.com/reset?t=xyz" in rendered
    assert "%7B" not in rendered
    assert "{{" not in rendered


def test_end_to_end_special_characters_in_name_substituted_safely():
    """Edge case from the brief — NAME with apostrophe + accented
    chars + HTML-dangerous ``<script>``. Substitution must deliver
    the exact raw ``ctx`` string; ANY escape-step for the HTML
    surface is the caller's responsibility (the hardcoded body
    treats the recipient name as text content, not an attribute).
    """
    body = "Hi %7B%7BNAME%7D%7D,"
    ctx = {"name": "José O'Connor <script>"}
    body = normalize_url_encoded_merge_tags(body)
    rendered, _ = render_template(body, ctx, missing="empty")
    assert rendered == "Hi José O'Connor <script>,"


def test_end_to_end_plus_symbol_in_recipient_email_substituted():
    """Edge case from the brief — recipient email with ``+``
    (RFC-5321 subaddressing). Must substitute verbatim WITHOUT
    URL-encoding the ``+`` to ``%2B``."""
    body = "Email: %7B%7BTO%7D%7D"
    ctx = {"to": "jane+billing@example.com"}
    body = normalize_url_encoded_merge_tags(body)
    rendered, _ = render_template(body, ctx, missing="empty")
    assert rendered == "Email: jane+billing@example.com"


# ─── Resend-capture · single + bulk invite paths both repaired ─────

def test_single_invite_send_captures_substituted_body_with_url_encoded_template():
    """End-to-end repro of the Phase 21 bug — a tenant whose
    ``portal_invite_email`` DB row carries URL-encoded brace
    tokens. Patches Resend to capture the sent payload and
    verifies the HTML + text bodies ship substituted values.

    Also serves as the shared regression coverage for the BULK
    path: the bulk endpoint (``/admin/customers/portal-invite/bulk``)
    processes per-recipient via ``_do_portal_provision`` →
    ``_try_send_reset_email``, so single + bulk share this helper
    and this test covers both.
    """
    async def _run():
        # Capture Resend payload instead of actually sending.
        import resend
        captured: dict = {}

        class _FakeEmails:
            @staticmethod
            def send(payload):
                captured.update(payload)
                return {"id": "test-resend-id"}

        original_emails = getattr(resend, "Emails", None)
        resend.Emails = _FakeEmails

        import config as cfg
        cfg.RESEND_API_KEY = "fake-key-for-test"
        cfg.EMAIL_FROM = "test@example.com"

        # Patch the DB template lookup to return a URL-encoded body —
        # repro the exact failure shape from the brief.
        url_encoded_body = (
            "<p>Hi %7B%7BNAME%7D%7D,</p>"
            "<p>Your portal login is ready.</p>"
            "<p><strong>Email:</strong> %7B%7BTO%7D%7D<br>"
            "<strong>Temporary password:</strong> "
            "<code>%7B%7BTEMP_PASSWORD%7D%7D</code></p>"
            "<p><a href='%7B%7BLOGIN_URL%7D%7D'>Sign in here</a>.</p>"
        )

        import services.marketing_template_lookup as _lookup_mod
        original_lookup = _lookup_mod.get_template_by_code

        async def _fake_lookup(code, tenant_id):
            return {
                "code": code,
                "subject": "Your customer portal login",
                "body": url_encoded_body,
            }

        _lookup_mod.get_template_by_code = _fake_lookup

        # Also stub the tenant fetch so the branding safety rail
        # doesn't abort the send.
        import routers.portal_admin as _pa_mod
        original_db = _pa_mod.db

        class _FakeDB:
            class tenants:
                @staticmethod
                async def find_one(*args, **kwargs):
                    return {
                        "id": "test-tenant",
                        "name": "AquaTerra Pools",
                        "settings": {
                            "business_card": {
                                "company_name": "AquaTerra Pools",
                                "phone": "+1-555-0100",
                            },
                        },
                    }

        _pa_mod.db = _FakeDB

        try:
            from routers.portal_admin import _try_send_reset_email
            result = await _try_send_reset_email(
                "jane+billing@example.com",
                "Jane Smith",
                "TempPass123",
                "https://app.plofv.com/login",
                tenant_id="test-tenant",
            )
        finally:
            _lookup_mod.get_template_by_code = original_lookup
            _pa_mod.db = original_db
            if original_emails is not None:
                resend.Emails = original_emails

        return result, captured

    result, captured = asyncio.run(_run())

    assert result == "test-resend-id"
    assert captured["subject"] == "Your customer portal login"

    # Regression lock — raw brace / URL-encoded brace patterns MUST
    # NOT appear in either the HTML or the plain-text body.
    html = captured["html"]
    text = captured["text"]
    for probe in ("%7B%7B", "%7D%7D", "{{NAME}}", "{{TO}}",
                  "{{TEMP_PASSWORD}}", "{{LOGIN_URL}}"):
        assert probe not in html, f"HTML still contains {probe!r}"
        assert probe not in text, f"TEXT still contains {probe!r}"

    # Each enumerated token resolved to its ``ctx`` value.
    assert "Jane Smith" in html
    assert "jane+billing@example.com" in html
    assert "TempPass123" in html
    assert "https://app.plofv.com/login" in html
    assert "Jane Smith" in text
    assert "jane+billing@example.com" in text
    assert "TempPass123" in text
    assert "https://app.plofv.com/login" in text
