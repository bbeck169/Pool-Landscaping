"""Feb-2026 · Responsive Quote / Estimate — email logo aspect
ratio + centering contract.

Locks in the ``wrap_html_in_shell(...)`` change that:
  * Sets ``height:auto`` + ``max-width:200px`` + ``width:auto``
    on the header ``<img>`` so the logo scales down (or stays
    natural) without vertical distortion. The prior
    ``max-height:56px`` cap is retired — tall logos no longer
    squish.
  * Centres the logo inside the dark brand header band via
    ``<td align="center">`` + inline ``text-align:center`` +
    ``margin:0 auto;display:block`` on the ``<img>``.
  * Retains the ``width="200"`` HTML attribute for MSO / Outlook
    (Windows) which honours the attribute over CSS.

This shell is the single wrap point for every themed email
(quote sent, invoice, receipt, send-to-customer, estimate,
portal invite, password reset, …), so a single test covers
the fix for every downstream email.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.email.theming import wrap_html_in_shell


_FULL_BRANDING = {
    "brand_primary_hex":    "#1F5A6F",
    "company_display_name": "AquaTerra Pools & Landscape",
    "logo_url":             "https://cdn.example/api/objects/logo.png",
}


def _extract_img_tag(html: str) -> str:
    match = re.search(r"<img\s[^>]*/>", html)
    assert match, "Header <img> tag not present in themed shell"
    return match.group(0)


def test_logo_img_uses_aspect_ratio_preserving_styles():
    """Logo <img> keeps aspect ratio + no vertical squish."""
    html = wrap_html_in_shell("<p>hi</p>", _FULL_BRANDING)
    img = _extract_img_tag(html)
    # ``height:auto`` is required in every major email client to
    # preserve aspect ratio when ``width`` is fixed.
    assert "height:auto" in img
    # ``max-width:200px`` caps the display width across viewports
    # while still allowing the natural intrinsic size.
    assert "max-width:200px" in img
    # ``width:auto`` (in CSS) lets modern clients scale naturally
    # when the HTML ``width`` attr is present as an MSO fallback.
    assert "width:auto" in img
    # ``display:block`` + ``margin:0 auto`` is the aspect-safe
    # centering pair inside the ``<td align="center">``.
    assert "display:block" in img
    assert "margin:0 auto" in img
    # The prior ``max-height:56px`` cap is retired — vertical
    # squish for tall logos is fixed only when this rule is gone.
    assert "max-height:" not in img


def test_logo_img_html_width_attribute_pins_at_200_for_mso():
    """Outlook / MSO honours the ``width=`` HTML attribute over CSS.
    Keep it aligned with the CSS ``max-width:200px``.
    """
    html = wrap_html_in_shell("<p>hi</p>", _FULL_BRANDING)
    img = _extract_img_tag(html)
    assert re.search(r'\bwidth="200"', img), (
        "Expected width=\"200\" MSO fallback on the logo img tag"
    )


def test_header_td_is_centered_so_logo_sits_in_the_middle():
    """The dark brand header ``<td>`` MUST be ``align="center"`` + inline
    ``text-align:center`` so the logo is horizontally centered in the
    band (was ``align="left"``, causing the logo to hug the left edge).
    """
    html = wrap_html_in_shell("<p>hi</p>", _FULL_BRANDING)
    # Find the header <td> (identified by the brand background).
    header_td = re.search(
        r'<td\s+align="([^"]+)"\s+style="([^"]*background:#1F5A6F[^"]*)"',
        html,
    )
    assert header_td, "Themed header <td> not found (background hex)"
    assert header_td.group(1) == "center", (
        f"Expected header <td align=\"center\">, got \"{header_td.group(1)}\""
    )
    assert "text-align:center" in header_td.group(2), (
        f"Expected inline text-align:center on header <td>, got style=\"{header_td.group(2)}\""
    )


def test_header_bar_brand_color_and_footer_still_intact():
    """Regression guard — the aspect-ratio fix must NOT flip the
    header/footer brand background or drop the MSO VML fallback.
    """
    html = wrap_html_in_shell("<p>hi</p>", _FULL_BRANDING)
    assert 'bgcolor="#1F5A6F"' in html
    assert "background:#1F5A6F" in html
    # MSO VML header fallback is still emitted — Outlook 2007-2019.
    assert "<!--[if mso]>" in html
    assert 'fill="true"' in html


def test_text_header_fallback_unchanged_when_logo_url_missing():
    """When ``logo_url`` is ``None`` the text header path stays intact
    — no <img>, company display name centered by the same ``<td>``.
    """
    b = dict(_FULL_BRANDING)
    b["logo_url"] = None
    html = wrap_html_in_shell("<p>hi</p>", b)
    assert "<img" not in html
    assert "AquaTerra Pools &amp; Landscape" in html
    header_td = re.search(
        r'<td\s+align="([^"]+)"\s+style="[^"]*background:#1F5A6F',
        html,
    )
    assert header_td and header_td.group(1) == "center"
