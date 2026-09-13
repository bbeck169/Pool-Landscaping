"""Feb-2026 · Email Base Template Theming — tests.

Locks the contract on
``services.email.theming.wrap_html_in_shell(inner_html, branding)``
and the 5-template smoke matrix that consumes it.

Case list
---------

1.  Full branding (``brand_primary_hex="#1F5A6F"`` + ``logo_url``):
    header band renders the hex AND an ``<img>`` tag pointing at the
    absolutized logo URL.
2.  ``brand_primary_hex`` set, ``logo_url=None``: header band renders
    the hex AND the ``company_display_name`` text (NO ``<img>`` tag).
3.  All branding fields ``None``: shell falls back to defaults, does
    NOT crash, and does NOT emit the literal string ``"None"``
    anywhere in the rendered HTML.
4.  Rendered HTML uses ONLY inline styles — zero ``<style>`` blocks
    outside of MSO conditional comments.
5.  ``tax_id`` set on the branding dict → NEVER surfaces in the
    rendered HTML (customer-facing footers must not leak it).
6.  Five-template smoke matrix — each of the customer-facing
    templates renders through the shared shell with a full-branding
    dict and produces valid HTML containing both the header band
    color and the footer note.
7.  Absolutization: when the caller passes an already-absolutized
    ``logo_url = "https://…/api/objects/xyz"``, that exact URL
    appears in the rendered HTML (the shell does NO absolutization
    itself — the pure-function contract is preserved).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.email.theming import wrap_html_in_shell


_FULL_BRANDING = {
    "brand_primary_hex":    "#1F5A6F",
    "company_display_name": "Vistancia Pools & Landscape",
    "logo_url":             "https://cdn.example/api/objects/logo.png",
    "footer_note":          "We're proud of every service call.",
    "mailing_address":      "123 Main St, Peoria, AZ 85383",
    "phone":                "(602) 555-0100",
    "email":                "hello@vistancia.example",
    "website":              "https://vistancia.example",
}


# ═════════════════════════════════════════════════════════════════════
# Case 1 — Full branding: header band + <img> tag.
# ═════════════════════════════════════════════════════════════════════

def test_case1_full_branding_renders_header_band_and_logo_img():
    html = wrap_html_in_shell("<p>hi</p>", _FULL_BRANDING)
    # Header band uses the tenant primary hex on the ``bgcolor`` +
    # inline ``background:`` declarations.
    assert 'bgcolor="#1F5A6F"' in html
    assert "background:#1F5A6F" in html
    # Logo <img> renders and points at the absolutized URL.
    assert 'src="https://cdn.example/api/objects/logo.png"' in html
    assert re.search(
        r'<img\s[^>]*src="https://cdn\.example/api/objects/logo\.png"',
        html,
    )


# ═════════════════════════════════════════════════════════════════════
# Case 2 — brand_primary_hex set, logo_url=None → text header.
# ═════════════════════════════════════════════════════════════════════

def test_case2_text_header_when_logo_url_missing():
    b = dict(_FULL_BRANDING)
    b["logo_url"] = None
    html = wrap_html_in_shell("<p>hi</p>", b)
    assert 'bgcolor="#1F5A6F"' in html
    # No <img> tag at all when there's no logo.
    assert "<img" not in html
    # Company text is rendered inside the header band.
    assert "Vistancia Pools &amp; Landscape" in html


# ═════════════════════════════════════════════════════════════════════
# Case 3 — All branding None → defaults kick in, no literal "None".
# ═════════════════════════════════════════════════════════════════════

def test_case3_all_none_falls_back_to_defaults_no_literal_None():
    html = wrap_html_in_shell("<p>body only</p>", None)
    # Default primary hex — matches ``colors.brand`` and
    # ``DEFAULT_PRIMARY_HEX`` in business_settings.
    assert 'bgcolor="#0B4A6F"' in html
    # Default footer note.
    assert "Thank you for your business!" in html
    # No literal ``None`` anywhere in the rendered HTML — the biggest
    # regression risk from ``str(None)`` slipping into an f-string.
    assert "None" not in html


def test_case3b_all_empty_dict_falls_back_same_way():
    html = wrap_html_in_shell("<p>body</p>", {})
    assert 'bgcolor="#0B4A6F"' in html
    assert "Thank you for your business!" in html
    assert "None" not in html


# ═════════════════════════════════════════════════════════════════════
# Case 4 — Inline styles only, no <style> blocks outside MSO.
# ═════════════════════════════════════════════════════════════════════

def test_case4_no_style_blocks_outside_mso_conditionals():
    html = wrap_html_in_shell("<p>hi</p>", _FULL_BRANDING)
    # Strip MSO conditional comment content — anything between
    # ``<!--[if mso]>`` and ``<![endif]-->``. The shell is allowed
    # to embed VML fallbacks inside there.
    stripped = re.sub(r"<!--\[if[^>]*\]>.*?<!\[endif\]-->", "",
                        html, flags=re.DOTALL)
    # After stripping, there must be zero <style> tags and zero
    # <link rel="stylesheet"> tags. Both are unreliable in email.
    assert "<style" not in stripped.lower()
    assert '<link ' not in stripped.lower()


# ═════════════════════════════════════════════════════════════════════
# Case 5 — tax_id never rendered in the shell.
# ═════════════════════════════════════════════════════════════════════

def test_case5_tax_id_never_rendered_in_footer():
    b = dict(_FULL_BRANDING)
    b["tax_id"] = "EIN 12-3456789 — SENSITIVE"
    html = wrap_html_in_shell("<p>hi</p>", b)
    # Neither the label nor the value can appear.
    assert "tax_id" not in html
    assert "EIN 12-3456789" not in html
    assert "SENSITIVE" not in html


# ═════════════════════════════════════════════════════════════════════
# Case 6 — 5-template smoke matrix.
# ═════════════════════════════════════════════════════════════════════

def _mini_quote_html():
    """Approximation of ``_estimate_reminder_html`` output — just
    enough for the shell to wrap around. The actual builder is
    exercised by the emailer end-to-end path, but this test
    guarantees the shell doesn't clobber typical body markup."""
    return (
        '<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        '<h2>Reminder: your quote</h2>'
        '<p>Hi Alex,</p>'
        '<p>Your quote is awaiting review.</p>'
        '</div>'
    )


def _mini_invoice_html():
    return (
        '<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        '<h2>Payment reminder</h2>'
        '<p>Hi Alex, your invoice <b>#A-102</b> has an outstanding '
        'balance of <b>$450.00</b>.</p>'
        '</div>'
    )


def _mini_payment_reminder_html():
    # Same shape as invoice-sent — the emailer helper is shared. We
    # still exercise it separately because subject-line + call site
    # differ upstream and the shell wrap contract must hold in both.
    return _mini_invoice_html()


def _mini_password_reset_html():
    return (
        '<div style="max-width:520px;margin:0 auto;">'
        '<h1 style="margin:0 0 12px 0;font-size:20px">Reset your password</h1>'
        '<p>Click the button below to set a new password.</p>'
        '</div>'
    )


def _mini_portal_invite_html():
    return (
        '<div style="max-width:520px;margin:0 auto;">'
        '<h1 style="margin:0 0 12px 0;font-size:20px">Password reset by admin</h1>'
        '<p>Sign in with the temporary password below.</p>'
        '</div>'
    )


@pytest.mark.parametrize("label,inner_fn", [
    ("quote_sent",       _mini_quote_html),
    ("invoice_sent",     _mini_invoice_html),
    ("payment_reminder", _mini_payment_reminder_html),
    ("password_reset",   _mini_password_reset_html),
    ("portal_invite",    _mini_portal_invite_html),
])
def test_case6_five_template_smoke_matrix(label, inner_fn):
    html = wrap_html_in_shell(inner_fn(), _FULL_BRANDING)
    # Header band + footer band both present.
    assert 'bgcolor="#1F5A6F"' in html, f"{label}: header band missing"
    assert "background:#1F5A6F" in html
    # Footer note surfaces.
    assert "We&#x27;re proud of every service call." in html \
        or "We're proud of every service call." in html, \
        f"{label}: footer_note missing"
    # Caller's headline made it through unchanged (an anchor that
    # helps confirm the shell wraps rather than replaces).
    assert (
        "Reminder: your quote" in html
        or "Payment reminder" in html
        or "Reset your password" in html
        or "Password reset by admin" in html
    ), f"{label}: caller body clobbered"
    # doctype + <html> tags present.
    assert html.lower().startswith("<!doctype html>")
    assert "<html" in html
    assert "</html>" in html


# ═════════════════════════════════════════════════════════════════════
# Case 8 · Feb-2026 · Housekeeping Batch A — the collapsed
# ``_password_reset_html`` builder in ``routers/admin_users.py`` used
# to return a full ``<!doctype html><html>...`` document that was
# then wrapped again by the shell, producing a double-``<html>``
# structural defect. Assert exactly one ``<html`` occurrence in the
# rendered output — a ``>=1`` assertion would silently pass future
# double-wrap regressions. Also assert the same invariant for the
# portal-invite/password-reset caller-fragment shape end-to-end.
# ═════════════════════════════════════════════════════════════════════

_HTML_TAG_RE = re.compile(r"<html\b", re.IGNORECASE)


def test_password_reset_shell_yields_single_html_tag():
    """The admin-driven password-reset email must render exactly one
    ``<html>`` document after passing through :func:`wrap_html_in_shell`.

    Uses the real production builder from ``routers/admin_users`` so
    a regression that reintroduces the ``<!doctype html><html>``
    prefix trips the assertion immediately.
    """
    from routers.admin_users import _password_reset_html

    inner = _password_reset_html(
        target_name="Jamie",
        actor_name="Alex the admin",
        company_name="AquaTerra",
        temp_password="TempPass!23",
        login_url="https://app.example.com/login",
    )
    # Sanity — builder is now a fragment; must NOT self-wrap.
    assert not _HTML_TAG_RE.search(inner), (
        "regression: _password_reset_html re-introduced its own <html> wrapper"
    )
    html = wrap_html_in_shell(inner, _FULL_BRANDING)
    matches = _HTML_TAG_RE.findall(html)
    assert len(matches) == 1, (
        f"expected exactly one <html> tag, found {len(matches)}: "
        f"double-wrap regression?"
    )
    # Fragment content must survive verbatim.
    assert "Password reset by admin" in html
    assert "TempPass!23" in html


def test_portal_invite_shell_yields_single_html_tag():
    """Portal-invite / password-reset-portal templates share the same
    single-``<html>`` invariant. Exercises the mini-template used in
    the case-6 smoke matrix so we lock the shape on every caller
    shape the theming pipeline supports.
    """
    inner = _mini_portal_invite_html()
    assert not _HTML_TAG_RE.search(inner), (
        "test fixture regressed — mini portal-invite fragment must not "
        "carry its own <html>"
    )
    html = wrap_html_in_shell(inner, _FULL_BRANDING)
    matches = _HTML_TAG_RE.findall(html)
    assert len(matches) == 1, (
        f"expected exactly one <html> tag, found {len(matches)}: "
        f"double-wrap regression?"
    )


def test_self_serve_password_reset_shell_yields_single_html_tag():
    """Mirror the admin-driven builder invariant for the self-serve
    ``forgot-password`` flow. The self-serve builder in
    ``routers.auth._password_reset_email_html`` currently returns a
    body fragment (a styled ``<div>``) — this test locks that shape
    so a future refactor that re-introduces a ``<!doctype html>``
    /``<html>`` prefix trips exactly the same
    ``count == 1`` regex assertion as the admin builder.
    """
    from routers.auth import _password_reset_email_html

    inner = _password_reset_email_html(
        first_name="Jamie",
        reset_link="https://app.example.com/reset?token=abc",
        expiry_minutes=15,
    )
    # Reject inner self-wrap — mirrors the admin-builder guard.
    assert not _HTML_TAG_RE.search(inner), (
        "regression: _password_reset_email_html re-introduced its own "
        "<html> wrapper"
    )
    html = wrap_html_in_shell(inner, _FULL_BRANDING)
    matches = _HTML_TAG_RE.findall(html)
    assert len(matches) == 1, (
        f"expected exactly one <html> tag, found {len(matches)}: "
        f"double-wrap regression?"
    )
    # Fragment content survives verbatim through the shell.
    assert "Reset your password" in html
    assert "Jamie" in html


# ═════════════════════════════════════════════════════════════════════
# Case 7 — Absolutized logo URL survives verbatim.
# ═════════════════════════════════════════════════════════════════════

def test_case7_absolutized_logo_url_survives_verbatim():
    b = dict(_FULL_BRANDING)
    # ``get_effective_business_settings(..., absolutize=True)`` maps
    # relative /api/objects/... URLs to full https URLs. The shell
    # is a pure function — it should render whatever the caller
    # passed, no further transformation.
    b["logo_url"] = "https://poolscape-audit.preview.emergentagent.com/api/objects/xyz"
    html = wrap_html_in_shell("<p>hi</p>", b)
    assert (
        'src="https://poolscape-audit.preview.emergentagent.com/api/objects/xyz"'
        in html
    )
    # No relative path leak — the raw ``/api/objects/xyz`` alone
    # (without the origin) must NOT appear as an ``src`` value.
    assert not re.search(r'src="/api/objects/xyz"', html)


# ═════════════════════════════════════════════════════════════════════
# Item 2 · P3 flip — Admin notification wrapping.
# ═════════════════════════════════════════════════════════════════════
#
# ``services/quote_notifications.render_email`` emits the admin-facing
# body for the "customer accepted / declined your quote" flow. The
# retrofit in ``notify_quote_decision`` wraps its output through the
# shared shell — the two smokes below assert that ``wrap_html_in_shell``
# handles the exact body shape ``render_email`` returns, both for the
# ``quote_accepted`` and ``quote_declined`` events, without clobbering
# the caller's headline copy.

def _admin_render(event: str):
    """Local helper — invoke ``quote_notifications.render_email`` on
    a synthetic doc so we get the real body verbatim.
    """
    from services.quote_notifications import render_email
    doc = {
        "id": "q-admin-probe-1234abcd",
        "customer_name": "Alex Sample",
        "total": 1250.75,
        "decline_reason": ("Timing doesn't work for us right now."
                            if event == "quote_declined" else None),
    }
    subject, html, _text = render_email(
        event=event, doc_type="quote", doc=doc,
        frontend_origin="https://admin.example.com",
    )
    return subject, html


def test_admin_notification_accepted_wraps_through_shell():
    _subject, admin_html = _admin_render("quote_accepted")
    themed = wrap_html_in_shell(admin_html, _FULL_BRANDING)
    # Header band renders the brand primary hex.
    assert 'bgcolor="#1F5A6F"' in themed
    # Caller's headline copy survives verbatim (the exact string
    # ``quote_notifications.render_email`` emits — locked so a
    # subject/copy refactor in that module trips a loud failure
    # here rather than silently changing admin-facing wording).
    assert "Alex Sample accepted quote" in themed
    assert "Total:" in themed
    # Footer note from the branding dict makes it through.
    assert "We're proud of every service call." in themed \
        or "We&#x27;re proud of every service call." in themed
    # ``tax_id`` MUST NOT leak — same guarantee as customer footers.
    b = dict(_FULL_BRANDING); b["tax_id"] = "EIN 99-9999999 admin only"
    themed_with_taxid = wrap_html_in_shell(admin_html, b)
    assert "EIN 99-9999999" not in themed_with_taxid
    assert "admin only" not in themed_with_taxid


def test_admin_notification_declined_wraps_through_shell():
    _subject, admin_html = _admin_render("quote_declined")
    themed = wrap_html_in_shell(admin_html, _FULL_BRANDING)
    assert 'bgcolor="#1F5A6F"' in themed
    # Declined-branch headline + reason preserved.
    assert "Alex Sample declined quote" in themed
    assert "Timing doesn&#x27;t work for us right now." in themed \
        or "Timing doesn't work for us right now." in themed
    # ``notify_quote_decision`` wraps ONCE per notification and reuses
    # the wrapped html across recipients — sanity check that calling
    # the pure ``wrap_html_in_shell`` twice with the same inputs
    # yields the same output (fan-out safety).
    themed2 = wrap_html_in_shell(admin_html, _FULL_BRANDING)
    assert themed == themed2
