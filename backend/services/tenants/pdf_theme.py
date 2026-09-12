"""Feb-2026 · Theme Refresh — ReportLab canvas hooks for branded
header + footer bands on customer-facing quote / estimate / invoice
PDFs.

Attaches to ``SimpleDocTemplate.build(onFirstPage=…, onLaterPages=…)``.

Contract:
  * ``brand_hex`` — validated ``#RRGGBB`` string (defaults handled
    by ``business_settings.build_business_settings_view``).
  * ``footer_note`` — optional short string (max 300 chars). When
    blank the footer falls back to "Thank you for your business!".
  * ``title`` — uppercase document type (``"INVOICE"`` / ``"ESTIMATE"``)
    rendered inside the header band.
  * ``company_display_name`` — small line under the title when no
    logo is embedded.
  * ``logo_absolute_url`` — absolute URL only. Passing a relative
    path will fail silently (ReportLab tries to HTTP-fetch and
    aborts). Use ``business_settings.resolve_absolute_url`` at the
    call site.

Header band:
  * Page 1 only (via ``onFirstPage``).
  * Fills a 1.2-inch tall rectangle at the top of the page with
    ``brand_hex``. White uppercase title top-left; white company
    contact block top-right when supplied.

Footer band:
  * Every page (via ``onLaterPages`` — installed as both first and
    later hook by the caller).
  * Fills a 0.5-inch tall rectangle at the bottom of the page.
    Centered white footer text.

See /app/memory/FEATURE_THEME_REFRESH_ESTIMATES_INVOICES.md.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

logger = logging.getLogger("pool_crm")


HEADER_BAND_HEIGHT = 1.2 * inch
FOOTER_BAND_HEIGHT = 0.5 * inch
DEFAULT_PRIMARY_HEX = "#0B4A6F"
DEFAULT_FOOTER_NOTE = "Thank you for your business!"


def _safe_color(hex_str: Optional[str]):
    """Return a ReportLab ``Color`` from ``#RRGGBB``. Falls back to
    the default primary token when the input is empty / invalid.
    """
    try:
        if hex_str and len(hex_str) == 7 and hex_str.startswith("#"):
            return HexColor(hex_str)
    except Exception:  # pragma: no cover - defensive
        pass
    return HexColor(DEFAULT_PRIMARY_HEX)


def build_header_footer_hooks(
    *,
    brand_hex: Optional[str] = None,
    title: str = "",
    company_display_name: Optional[str] = None,
    company_lines: Optional[list] = None,
    logo_absolute_url: Optional[str] = None,
    footer_note: Optional[str] = None,
    page_size=letter,
) -> tuple[Callable, Callable]:
    """Return ``(on_first_page, on_later_pages)`` callbacks that
    paint the branded header (page 1 only) and footer band (every
    page). Wired at the ``SimpleDocTemplate.build`` boundary.

    See module docstring for the contract on each parameter.
    """
    color = _safe_color(brand_hex)
    _, page_h = page_size

    def _draw_footer(canvas, doc):
        try:
            canvas.saveState()
            canvas.setFillColor(color)
            canvas.rect(0, 0, doc.pagesize[0], FOOTER_BAND_HEIGHT,
                          stroke=0, fill=1)
            canvas.setFillColor(white)
            canvas.setFont("Helvetica-Bold", 10)
            msg = (footer_note or "").strip() or DEFAULT_FOOTER_NOTE
            canvas.drawCentredString(
                doc.pagesize[0] / 2.0, FOOTER_BAND_HEIGHT / 2.0 - 4, msg,
            )
            canvas.restoreState()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("pdf_theme_footer_failed: %s", exc)

    def _draw_header(canvas, doc):
        try:
            canvas.saveState()
            page_w = doc.pagesize[0]
            page_top = doc.pagesize[1]
            # Header rectangle (top of page 1).
            canvas.setFillColor(color)
            canvas.rect(0, page_top - HEADER_BAND_HEIGHT,
                          page_w, HEADER_BAND_HEIGHT, stroke=0, fill=1)
            # Title, uppercase, left-anchored.
            canvas.setFillColor(white)
            canvas.setFont("Helvetica-Bold", 26)
            canvas.drawString(
                0.6 * inch, page_top - 0.8 * inch,
                (title or "").upper(),
            )
            if company_display_name and not logo_absolute_url:
                canvas.setFont("Helvetica", 10)
                canvas.drawString(
                    0.6 * inch, page_top - 1.02 * inch,
                    company_display_name,
                )
            # Right-side company contact lines (small white).
            if company_lines:
                canvas.setFont("Helvetica", 9)
                y = page_top - 0.5 * inch
                for line in company_lines[:5]:
                    if not line:
                        continue
                    canvas.drawRightString(
                        page_w - 0.6 * inch, y, str(line)[:80],
                    )
                    y -= 12
            # Logo: ReportLab can render remote images via URL, but
            # the fetch is synchronous and blocks; we only try when
            # an ABSOLUTE URL was supplied. Failure is silent — the
            # header remains readable without the logo.
            if logo_absolute_url:
                try:
                    from reportlab.lib.utils import ImageReader
                    img = ImageReader(logo_absolute_url)
                    canvas.drawImage(
                        img, 0.4 * inch, page_top - 1.05 * inch,
                        width=1.6 * inch, height=0.9 * inch,
                        preserveAspectRatio=True, mask="auto",
                    )
                except Exception as exc:  # pragma: no cover
                    logger.warning("pdf_theme_logo_failed: %s", exc)
            canvas.restoreState()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("pdf_theme_header_failed: %s", exc)
        # Footer follows on the same first page.
        _draw_footer(canvas, doc)

    def _later(canvas, doc):
        # No header rectangle on later pages, per the design brief.
        _draw_footer(canvas, doc)

    return _draw_header, _later


__all__ = [
    "HEADER_BAND_HEIGHT",
    "FOOTER_BAND_HEIGHT",
    "DEFAULT_PRIMARY_HEX",
    "DEFAULT_FOOTER_NOTE",
    "build_header_footer_hooks",
]
