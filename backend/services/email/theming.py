"""Feb-2026 · Email Base Template Theming — shared HTML shell.

Public API
----------

``wrap_html_in_shell(inner_html, branding) -> str``

    Pure function. Wraps a caller-supplied HTML fragment in a
    branded shell (header band + body slot + footer band) using
    email-safe inline styles + ``<table>`` layout. ``branding`` is
    the dict returned by
    :func:`services.tenants.business_settings.get_effective_business_settings`
    with ``absolutize=True``.

    Callers are responsible for resolving ``branding`` in their
    surrounding (already-async) context and reusing the dict across
    a fan-out loop — this helper does NO database work.

Design rules
------------

* Inline styles only — no ``<style>`` blocks, no ``<link>`` tags,
  no CSS classes. Gmail / Outlook / Apple Mail all render inline
  reliably; class-based CSS is inconsistent.
* Layout: HTML ``<table role="presentation">`` — flexbox / grid are
  unreliable across email clients.
* Max-width 640 px container, centered with ``margin: 0 auto`` and
  a Word/MSO width fallback via conditional comments.
* System font stack via inline ``font-family`` — no web fonts, no
  ``@import``.
* Header background uses an MSO ``<v:rect>`` VML fallback so
  Outlook 2007 – 2019 (Windows) renders the brand-colored band.
* No reference to ``tax_id`` anywhere in the shell — admin-only
  field per the Business Settings contract.

Fallback resolution
-------------------

When any of the branding fields are missing, defaults kick in:

===============  ===============================================
Field            Default when missing
===============  ===============================================
``primary_hex``  ``#0B4A6F``  (matches ``colors.brand`` in the
                 frontend theme and the ReportLab
                 ``pdf_theme.py``)
``logo_url``     Fall back to ``company_display_name`` text
                 header (white, bold, 24 px)
``company``      ``"Our team"``
``footer_note``  ``"Thank you for your business!"``
===============  ===============================================

Missing ``mailing_address`` / ``phone`` / ``email`` / ``website``
are simply omitted from the footer small-print line. The shell
never renders the literal string ``"None"``.

See ``/app/memory/FEATURE_EMAIL_THEMING.md`` for the full
coverage matrix and before/after HTML samples.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


# ─── Fallback constants ─────────────────────────────────────────────

_DEFAULT_PRIMARY_HEX = "#0B4A6F"   # colors.brand — matches web + PDF
_DEFAULT_FOOTER_NOTE = "Thank you for your business!"
_DEFAULT_COMPANY = "Our team"
# TD-email-template-header-bg-white · Feb-2026 — email-shell header
# band + no-logo fallback-text defaults. Kept at module level so
# the pytest regression suite can import + assert on the exact
# values the shell will render under default branding.
_DEFAULT_EMAIL_HEADER_BG = "#FFFFFF"
_DEFAULT_EMAIL_HEADER_TEXT = "#111827"
# TD-email-template-header-bg-white · Feb-2026 — unconditional
# header-to-body separator. Lives at module level so the pytest
# suite's regression lock imports the exact literal instead of
# duplicating the hex string.
_HEADER_BORDER_BOTTOM = "border-bottom:1px solid #E5E7EB;"
_DEFAULT_FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, "
    "Arial, sans-serif"
)


# ─── HTML escape (kept local — no stdlib html import churn) ─────────

def _esc(value: Any) -> str:
    """Minimal HTML escape suitable for text nodes and attribute
    values. We deliberately do NOT call the stdlib ``html.escape``
    to keep this helper dependency-free and easy to reason about.
    """
    if value is None:
        return ""
    s = str(value)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _first_non_empty(*candidates: Any) -> Optional[str]:
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return None


def _valid_hex(candidate: Any) -> Optional[str]:
    """Return the candidate hex string if it looks like a well-formed
    ``#RRGGBB``; otherwise ``None``. Prevents rogue values (empty
    string, ``None``, ``"transparent"``) from being interpolated
    into a ``background:`` declaration.
    """
    if not candidate:
        return None
    s = str(candidate).strip()
    if not s.startswith("#") or len(s) != 7:
        return None
    try:
        int(s[1:], 16)
    except ValueError:
        return None
    return s


def _resolve_branding(branding: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Normalise the effective-branding dict into the exact keys the
    shell renders against, with defaults applied.
    """
    b: Mapping[str, Any] = branding or {}
    primary = (
        _valid_hex(b.get("brand_primary_hex"))
        or _valid_hex(b.get("primary_hex"))
        or _DEFAULT_PRIMARY_HEX
    )
    # TD-email-template-header-bg-white · Feb-2026 — the email shell
    # header band now renders on a per-tenant color (white default)
    # instead of the tenant brand color. The companion
    # ``email_header_text`` drives the no-logo company-name text
    # fallback inside the header cell. Both default to a safe
    # white-bg + dark-text combo for every tenant on first email
    # render post-deploy; operator opts into a dark header by
    # setting ``email_header_bg`` on the Business Settings page.
    # Footer stays on ``primary`` — scope was header-only.
    email_header_bg = (
        _valid_hex(b.get("email_header_bg"))
        or _DEFAULT_EMAIL_HEADER_BG
    )
    email_header_text = (
        _valid_hex(b.get("email_header_text"))
        or _DEFAULT_EMAIL_HEADER_TEXT
    )
    company = _first_non_empty(
        b.get("company_display_name"),
        b.get("company_name"),
    ) or _DEFAULT_COMPANY
    logo_url = _first_non_empty(
        b.get("logo_url"),
        b.get("logo_absolute_url"),
    )
    footer_note = _first_non_empty(b.get("footer_note")) or _DEFAULT_FOOTER_NOTE
    mailing_address = _first_non_empty(
        b.get("mailing_address"),
        b.get("business_address"),
    )
    phone = _first_non_empty(b.get("phone"), b.get("business_phone"))
    email = _first_non_empty(b.get("email"), b.get("business_email"))
    website = _first_non_empty(b.get("website"), b.get("business_website"))
    # Feb-2026 · tax_id is deliberately NOT copied — it must never
    # appear in a customer-facing email footer.
    return {
        "primary_hex": primary,
        "email_header_bg": email_header_bg,
        "email_header_text": email_header_text,
        "company_display_name": company,
        "logo_url": logo_url,
        "footer_note": footer_note,
        "mailing_address": mailing_address,
        "phone": phone,
        "email": email,
        "website": website,
    }


def _footer_small_print(resolved: Dict[str, Any]) -> str:
    """Compose the footer small-print line: company · address · phone
    · email · website. Every ``None`` field is dropped so the line
    doesn't render as ``"Foo · None · 555-1212"``.
    """
    parts = [
        resolved["company_display_name"],
        resolved["mailing_address"],
        resolved["phone"],
        resolved["email"],
        resolved["website"],
    ]
    return " &middot; ".join(_esc(p) for p in parts if p)


# ─── Public API ─────────────────────────────────────────────────────

def wrap_html_in_shell(
    inner_html: str,
    branding: Optional[Mapping[str, Any]] = None,
) -> str:
    """Wrap ``inner_html`` in the shared brand shell.

    ``inner_html`` should be a body fragment — do NOT pass a full
    ``<html>...</html>`` document. Existing full-doc builders should
    hand only the body content (typically the styled ``<div>`` card).
    The shell provides its own ``<!doctype html>``, ``<html>``,
    ``<head>``, ``<body>``, header band, body container, and footer
    band. Anything the caller passes lives inside the body slot.

    ``branding`` is the dict returned by
    :func:`services.tenants.business_settings.get_effective_business_settings`.
    Passing ``None`` renders the shell with default branding — used
    by callers that either lack tenant context (rare) or that hit
    a resolver error (fail-open).
    """
    r = _resolve_branding(branding)
    primary = r["primary_hex"]
    header_bg = r["email_header_bg"]
    header_text = r["email_header_text"]
    company_txt = _esc(r["company_display_name"])
    footer_note_txt = _esc(r["footer_note"])
    inner = inner_html or ""

    if r["logo_url"]:
        # Feb-2026 · Responsive quote/estimate ship — logo aspect
        # ratio fix. The prior style pinned ``max-height:56px`` which
        # squished tall logos at ``width=180``. Now: HTML width attr
        # relaxed to 200, ``max-width:200px`` + ``height:auto`` +
        # ``width:auto`` preserves the natural aspect ratio in every
        # major email client, and ``margin:0 auto;display:block``
        # combined with the surrounding ``<td align="center">`` (see
        # below) centers the logo inside the brand header bar.
        header_cell = (
            f'<img src="{_esc(r["logo_url"])}" '
            f'alt="{company_txt}" '
            f'width="200" '
            f'style="max-width:200px;width:auto;height:auto;display:block;'
            f'margin:0 auto;border:0;outline:none;text-decoration:none;'
            f'line-height:100%;-ms-interpolation-mode:bicubic;" />'
        )
    else:
        # TD-email-template-header-bg-white · Feb-2026 — fallback
        # company-name text uses the per-tenant ``email_header_text``
        # (dark default) instead of the hardcoded ``#FFFFFF`` so the
        # no-logo text stays legible on a white header. Operator
        # pairs this with ``email_header_bg`` for a dark-header
        # tenant (text goes back to ``#FFFFFF``).
        header_cell = (
            f'<span style="color:{header_text};font-weight:700;'
            f'font-size:24px;line-height:32px;">{company_txt}</span>'
        )

    small_print = _footer_small_print(r)
    small_print_row = (
        f'<tr><td align="center" '
        f'style="padding:6px 24px 22px 24px;color:#FFFFFF;opacity:0.85;'
        f'font-family:{_DEFAULT_FONT};font-size:11px;line-height:16px;">'
        f'{small_print}</td></tr>'
    ) if small_print else ""

    # TD-email-template-header-bg-white · Feb-2026 — the MSO/Outlook
    # VML fallback inherits the per-tenant ``email_header_bg`` so
    # Outlook 2007-2019 (Windows) renders the same white header the
    # modern CSS path uses. Prior code tiled ``primary`` (dark
    # brand), which would have left Outlook with a dark header
    # even after this ticket flipped every other client to white.
    mso_header = (
        f'<!--[if mso]>'
        f'<v:rect xmlns:v="urn:schemas-microsoft-com:vml" '
        f'fill="true" stroke="false" style="width:640px;height:88px;">'
        f'<v:fill type="tile" color="{header_bg}" />'
        f'<v:textbox inset="0,0,0,0">'
        f'<![endif]-->'
    )
    mso_header_close = "<!--[if mso]></v:textbox></v:rect><![endif]-->"
    mso_footer = (
        f'<!--[if mso]>'
        f'<v:rect xmlns:v="urn:schemas-microsoft-com:vml" '
        f'fill="true" stroke="false" style="width:640px;">'
        f'<v:fill type="tile" color="{primary}" />'
        f'<v:textbox inset="0,0,0,0">'
        f'<![endif]-->'
    )
    mso_footer_close = "<!--[if mso]></v:textbox></v:rect><![endif]-->"

    return (
        f'<!doctype html>'
        f'<html lang="en" '
        f'xmlns:v="urn:schemas-microsoft-com:vml" '
        f'xmlns:o="urn:schemas-microsoft-com:office:office">'
        f'<head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="X-UA-Compatible" content="IE=edge">'
        f'<title>{company_txt}</title>'
        f'</head>'
        f'<body style="margin:0;padding:0;background:#F3F4F6;'
        f'font-family:{_DEFAULT_FONT};color:#111827;">'
        # Outer wrapper — full width, muted page background.
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" '
        f'style="background:#F3F4F6;padding:24px 0;">'
        f'<tr><td align="center">'
        # 640-px container.
        f'<table role="presentation" width="640" cellpadding="0" '
        f'cellspacing="0" border="0" '
        f'style="width:640px;max-width:100%;background:#FFFFFF;'
        f'border-collapse:collapse;">'
        # Header band.
        # TD-email-template-header-bg-white · Feb-2026 — background
        # drives off the per-tenant ``email_header_bg`` (white
        # default). ``_HEADER_BORDER_BOTTOM`` is UNCONDITIONAL (every
        # tenant gets the thin gray-200 divider) — operator Decision 2
        # locked the border independently of the bg flip so a
        # dark-header tenant still gets visual separation from the
        # body cell below.
        f'<tr>'
        f'<td align="center" '
        f'style="background:{header_bg};padding:22px 28px;'
        f'text-align:center;{_HEADER_BORDER_BOTTOM}" '
        f'bgcolor="{header_bg}">'
        f'{mso_header}'
        f'{header_cell}'
        f'{mso_header_close}'
        f'</td>'
        f'</tr>'
        # Body slot — caller's HTML rendered here verbatim.
        f'<tr>'
        f'<td '
        f'style="padding:24px 28px;background:#FFFFFF;'
        f'font-family:{_DEFAULT_FONT};font-size:14px;line-height:22px;'
        f'color:#111827;">'
        f'{inner}'
        f'</td>'
        f'</tr>'
        # Footer band.
        f'<tr>'
        f'<td align="center" '
        f'style="background:{primary};padding:22px 24px 6px 24px;" '
        f'bgcolor="{primary}">'
        f'{mso_footer}'
        f'<div style="color:#FFFFFF;font-family:{_DEFAULT_FONT};'
        f'font-size:14px;line-height:20px;font-weight:600;">'
        f'{footer_note_txt}</div>'
        f'{mso_footer_close}'
        f'</td>'
        f'</tr>'
        f'{small_print_row}'
        # Close inner container + outer wrapper.
        f'</table>'
        f'</td></tr>'
        f'</table>'
        f'</body>'
        f'</html>'
    )


__all__ = ["wrap_html_in_shell"]
