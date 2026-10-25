"""TD-email-template-header-bg-white · Feb-2026
==============================================

Regression lock for the Ticket O refactor.  Covers:

  §1 — ``_resolve_branding`` applies white/dark defaults when the
       tenant has NOT set ``email_header_bg`` / ``email_header_text``.
  §2 — Tenant-set overrides are honored + hex-normalised (lowercased
       via the validator contract).
  §3 — ``wrap_html_in_shell`` renders the header ``<td>`` with the
       per-tenant background, the no-logo fallback-text span with
       the per-tenant text color, and the MSO VML fill mirroring the
       background.
  §4 — Border-bottom on the header ``<td>`` is UNCONDITIONAL
       regardless of branding (Decision 2 regression lock).
  §5 — Footer band is UNCHANGED by the ticket (still tenant primary).
  §6 — Logo centering CSS (``margin:0 auto;display:block``) still
       present when the branding carries a logo URL.
  §7 — ``build_business_settings_view`` surfaces both new keys in
       stored + effective, with defaults applied in effective.
  §8 — ``BusinessSettingsPatch`` accepts both new fields;
       hex-validator rejects non-``#RRGGBB`` and lowercases on
       accept.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════
# §1-§6 · theming.wrap_html_in_shell + _resolve_branding
# ═══════════════════════════════════════════════════════════════════
def test_resolve_branding_applies_white_dark_defaults_when_unset():
    from services.email.theming import (
        _resolve_branding,
        _DEFAULT_EMAIL_HEADER_BG,
        _DEFAULT_EMAIL_HEADER_TEXT,
    )
    out = _resolve_branding({})
    assert out["email_header_bg"] == _DEFAULT_EMAIL_HEADER_BG == "#FFFFFF"
    assert out["email_header_text"] == _DEFAULT_EMAIL_HEADER_TEXT == "#111827"


def test_resolve_branding_honors_tenant_overrides():
    from services.email.theming import _resolve_branding
    out = _resolve_branding({
        "email_header_bg": "#0b4a6f",
        "email_header_text": "#ffffff",
    })
    assert out["email_header_bg"] == "#0b4a6f"
    assert out["email_header_text"] == "#ffffff"


def test_resolve_branding_rejects_bogus_hex_and_falls_to_default():
    """``_valid_hex`` returns None on malformed input; the resolver
    then falls to the default. Prevents a bad branding doc from
    rendering a broken ``background:`` declaration in the inlined
    style string."""
    from services.email.theming import _resolve_branding
    out = _resolve_branding({
        "email_header_bg": "transparent",   # bogus
        "email_header_text": "red",         # bogus
    })
    assert out["email_header_bg"] == "#FFFFFF"
    assert out["email_header_text"] == "#111827"


def test_shell_header_td_bg_defaults_to_white():
    from services.email.theming import wrap_html_in_shell
    html = wrap_html_in_shell("<p>Hi</p>", {})
    # Header <td> is the FIRST <td> inside the 640-px container
    # that carries a ``background:`` property.
    import re
    tds = re.findall(r'<td[^>]*background:[^"]*"[^>]*>', html)
    assert len(tds) >= 2
    assert "background:#FFFFFF" in tds[0]
    assert 'bgcolor="#FFFFFF"' in tds[0]


def test_shell_header_td_bg_honors_tenant_override():
    from services.email.theming import wrap_html_in_shell
    html = wrap_html_in_shell("<p>Hi</p>", {
        "email_header_bg": "#0B4A6F",
        "email_header_text": "#FFFFFF",
    })
    import re
    tds = re.findall(r'<td[^>]*background:[^"]*"[^>]*>', html)
    # ``_valid_hex`` preserves input case — the resolver stores
    # whatever hex the branding doc carries. Only the PATCH-side
    # validator lowercases on write. Accept either case in the
    # rendered output.
    hdr = tds[0]
    assert "background:#0B4A6F" in hdr or "background:#0b4a6f" in hdr
    assert ('bgcolor="#0B4A6F"' in hdr
             or 'bgcolor="#0b4a6f"' in hdr)


def test_shell_fallback_text_color_defaults_to_dark():
    from services.email.theming import wrap_html_in_shell
    # No logo URL → shell renders the ``<span>`` fallback instead
    # of the ``<img>``.  Default text color is ``#111827``.
    html = wrap_html_in_shell("<p>Hi</p>", {})
    assert 'color:#111827' in html
    # And NOT the pre-fix invisible-on-white white text.
    assert 'color:#FFFFFF;font-weight:700;font-size:24px' not in html


def test_shell_fallback_text_color_honors_tenant_override():
    from services.email.theming import wrap_html_in_shell
    html = wrap_html_in_shell("<p>Hi</p>", {
        "email_header_bg": "#0B4A6F",
        "email_header_text": "#FFFFFF",
    })
    # Dark-header tenant: fallback text goes back to white.
    assert '<span style="color:#FFFFFF;font-weight:700;font-size:24px' in html


def test_shell_header_td_always_carries_border_bottom():
    """Decision 2 regression lock — the gray-200 separator is
    UNCONDITIONAL, independent of branding."""
    from services.email.theming import wrap_html_in_shell
    # Default branding.
    html1 = wrap_html_in_shell("<p>Hi</p>", {})
    assert "border-bottom:1px solid #E5E7EB" in html1
    # Dark-header override.
    html2 = wrap_html_in_shell("<p>Hi</p>", {
        "email_header_bg": "#0B4A6F",
    })
    assert "border-bottom:1px solid #E5E7EB" in html2


def test_shell_footer_bg_still_uses_tenant_primary_hex():
    """Operator scope was header-only; footer MUST keep rendering on
    tenant primary color. Guards against an accidental over-flip."""
    from services.email.theming import wrap_html_in_shell
    html = wrap_html_in_shell("<p>Hi</p>", {
        "brand_primary_hex": "#0B4A6F",
        # email_header_bg deliberately unset — footer should still
        # pick up primary even when the header is white.
    })
    import re
    tds = re.findall(r'<td[^>]*background:[^"]*"[^>]*>', html)
    # tds[0] is header, tds[1] is body (white bg), tds[2] is footer.
    # Case-insensitive match on the footer primary (``_resolve_branding``
    # preserves the input hex case).
    footer_tds = [t for t in tds[1:]
                   if "background:#0B4A6F" in t
                   or "background:#0b4a6f" in t]
    assert footer_tds, (
        f"footer <td> missing tenant primary color. "
        f"background-carrying tds: {tds}"
    )


def test_shell_mso_vml_header_fill_mirrors_header_bg():
    """Outlook 2007-2019 VML fallback must match the modern CSS
    header, not the old primary-colored brand band."""
    from services.email.theming import wrap_html_in_shell
    # Default — white.
    html = wrap_html_in_shell("<p>Hi</p>", {})
    assert '<v:fill type="tile" color="#FFFFFF" />' in html
    # Dark override — case-preserving per the ``_resolve_branding``
    # contract. Accept either case.
    html2 = wrap_html_in_shell("<p>Hi</p>", {
        "email_header_bg": "#0B4A6F",
    })
    assert (
        '<v:fill type="tile" color="#0B4A6F" />' in html2
        or '<v:fill type="tile" color="#0b4a6f" />' in html2
    )


def test_shell_logo_centering_css_still_present_when_logo_url_set():
    """Decision 1 pre-check — flipping the bg must NOT shift the
    logo's center. Lock the centering CSS literals. Note the actual
    style order emitted by the shell is ``display:block;margin:0 auto``
    (not the reverse) — assert both tokens individually so the test
    is order-independent."""
    from services.email.theming import wrap_html_in_shell
    html = wrap_html_in_shell("<p>Hi</p>", {
        "logo_url": "https://cdn.example/logo.png",
        "email_header_bg": "#FFFFFF",
    })
    assert "<img" in html
    assert 'src="https://cdn.example/logo.png"' in html
    assert "display:block" in html
    assert "margin:0 auto" in html


# ═══════════════════════════════════════════════════════════════════
# §7 · business_settings view — stored + effective
# ═══════════════════════════════════════════════════════════════════
def test_business_settings_view_surfaces_new_keys_in_stored_and_effective():
    from services.tenants.business_settings import (
        build_business_settings_view,
        DEFAULT_EMAIL_HEADER_BG,
        DEFAULT_EMAIL_HEADER_TEXT,
    )
    # Unset case — stored carries None, effective carries defaults.
    view = build_business_settings_view({})
    assert "email_header_bg" in view["stored"]
    assert view["stored"]["email_header_bg"] is None
    assert view["effective"]["email_header_bg"] == DEFAULT_EMAIL_HEADER_BG
    assert view["effective"]["email_header_text"] == DEFAULT_EMAIL_HEADER_TEXT
    # Set case — effective carries the stored values.
    view2 = build_business_settings_view({
        "email_header_bg": "#0b4a6f",
        "email_header_text": "#ffffff",
    })
    assert view2["effective"]["email_header_bg"] == "#0b4a6f"
    assert view2["effective"]["email_header_text"] == "#ffffff"


# ═══════════════════════════════════════════════════════════════════
# §8 · PATCH model — hex-validator contract
# ═══════════════════════════════════════════════════════════════════
def test_business_settings_patch_accepts_new_fields_and_lowercases():
    from routers.business_settings import BusinessSettingsPatch
    p = BusinessSettingsPatch(
        email_header_bg="#0B4A6F",
        email_header_text="#FFFFFF",
    )
    # Validator lowercases on accept (mirrors the brand_primary_hex
    # contract — operator can type uppercase, backend stores lower).
    assert p.email_header_bg == "#0b4a6f"
    assert p.email_header_text == "#ffffff"


def test_business_settings_patch_rejects_non_hex():
    from routers.business_settings import BusinessSettingsPatch
    with pytest.raises(Exception):
        BusinessSettingsPatch(email_header_bg="red")
    with pytest.raises(Exception):
        BusinessSettingsPatch(email_header_text="#ZZZZZZ")


def test_business_settings_patch_accepts_null_for_clearout():
    """A ``null`` PATCH restores the default on next render.
    Mirrors the ``brand_primary_hex`` contract."""
    from routers.business_settings import BusinessSettingsPatch
    p = BusinessSettingsPatch(email_header_bg=None, email_header_text=None)
    assert p.email_header_bg is None
    assert p.email_header_text is None
