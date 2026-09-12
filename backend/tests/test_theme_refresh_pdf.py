"""Feb-2026 · Theme Refresh — PDF band + absolutization contract.

Locks the branded header/footer bands + logo absolutization shipped
by the Theme Refresh dispatch. Uses in-process helpers (no HTTP)
so the tests never depend on the running server, matching the
``test_reports_*`` unit-test pattern.
"""
from __future__ import annotations

import asyncio
import io
import re


def _extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def _extract_pdf_content_stream(data: bytes) -> bytes:
    """Return the decompressed concatenation of every page's content
    stream. Colour ops (``rg``, ``RG``) live here.
    """
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    out = b""
    for page in reader.pages:
        try:
            contents = page.get_contents()
            if contents is None:
                continue
            raw = contents.get_data()
            out += raw
        except Exception:
            continue
    return out


# ═════════════════════════════════════════════════════════════════════
# 1. PDF header band uses the tenant's brand primary hex
# ═════════════════════════════════════════════════════════════════════

def test_pdf_header_band_uses_brand_hex():
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    from services.tenants.pdf_theme import (
        build_header_footer_hooks, HEADER_BAND_HEIGHT,
    )
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    doc.topMargin = HEADER_BAND_HEIGHT + 12
    first, later = build_header_footer_hooks(
        brand_hex="#1F5A6F",
        title="ESTIMATE",
        company_display_name="Acme Pools",
        company_lines=["Acme Pools", "555-0100"],
        footer_note="Licensed & Insured",
    )
    doc.build([Paragraph("body", getSampleStyleSheet()["Normal"])],
              onFirstPage=first, onLaterPages=later)
    data = buf.getvalue()
    assert data[:4] == b"%PDF"
    stream = _extract_pdf_content_stream(data)
    # #1F5A6F → rgb(31, 90, 111) → .121 .352 .435 rg. ReportLab
    # drops the leading zero and uses variable precision — match a
    # tolerant regex on the first few decimal digits.
    assert re.search(rb"\.12\d+ \.35\d+ \.43\d+ rg", stream), (
        f"expected fill colour bytes in the decoded stream, "
        f"got: {stream[:400]!r}"
    )
    # Title renders (extracted via pypdf).
    text = _extract_pdf_text(data)
    assert "ESTIMATE" in text
    assert "Licensed & Insured" in text


# ═════════════════════════════════════════════════════════════════════
# 2. Null brand hex → default primary fallback (no crash)
# ═════════════════════════════════════════════════════════════════════

def test_pdf_header_band_fallback_when_hex_missing():
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    from services.tenants.pdf_theme import build_header_footer_hooks
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    first, later = build_header_footer_hooks(
        brand_hex=None,           # → default primary
        title="QUOTE",
        footer_note=None,         # → "Thank you for your business!"
    )
    doc.build([Paragraph("body", getSampleStyleSheet()["Normal"])],
              onFirstPage=first, onLaterPages=later)
    data = buf.getvalue()
    assert data[:4] == b"%PDF"
    stream = _extract_pdf_content_stream(data)
    # Default #0B4A6F → rgb(11, 74, 111) → .043 .290 .435.
    assert re.search(rb"\.04\d+ \.29\d+ \.43\d+ rg", stream), (
        f"expected default fill bytes, got: {stream[:400]!r}"
    )
    # Fallback footer text renders.
    text = _extract_pdf_text(data)
    assert "Thank you for your business" in text


# ═════════════════════════════════════════════════════════════════════
# 3. Multi-page PDF — footer band on every page, header only on 1
# ═════════════════════════════════════════════════════════════════════

def test_pdf_footer_repeats_header_does_not():
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from services.tenants.pdf_theme import build_header_footer_hooks
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    first, later = build_header_footer_hooks(
        brand_hex="#0B4A6F", title="INVOICE",
        company_display_name="Acme",
        footer_note="Ops footer note",
    )
    story = []
    for i in range(3):
        story.append(Paragraph(f"page {i}", styles["Normal"]))
        if i < 2:
            story.append(PageBreak())
    doc.build(story, onFirstPage=first, onLaterPages=later)
    data = buf.getvalue()
    # Assert per-page content via pypdf.
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 3
    pages_text = [p.extract_text() or "" for p in reader.pages]
    # Footer note on every page.
    for i, t in enumerate(pages_text):
        assert "Ops footer" in t, f"footer missing on page {i}: {t!r}"
    # Title INVOICE on page 1 only.
    assert "INVOICE" in pages_text[0]
    for i in range(1, len(pages_text)):
        assert "INVOICE" not in pages_text[i], (
            f"header title leaked to page {i}: {pages_text[i]!r}"
        )


# ═════════════════════════════════════════════════════════════════════
# 4. resolve_absolute_url promotes a same-origin path
# ═════════════════════════════════════════════════════════════════════

def test_resolve_absolute_url_promotes_relative_path(monkeypatch):
    from services.tenants.business_settings import resolve_absolute_url
    monkeypatch.setenv("APP_BASE_URL", "https://example.plofv.com")
    monkeypatch.delenv("PUBLIC_APP_BASE_URL", raising=False)
    monkeypatch.delenv("FRONTEND_BASE_URL", raising=False)
    got = resolve_absolute_url("/api/objects/tenant/logo.png")
    assert got == "https://example.plofv.com/api/objects/tenant/logo.png"


# ═════════════════════════════════════════════════════════════════════
# 5. Absolute URLs pass through unchanged
# ═════════════════════════════════════════════════════════════════════

def test_resolve_absolute_url_passes_through_absolute():
    from services.tenants.business_settings import resolve_absolute_url
    got = resolve_absolute_url("https://cdn.example.com/logo.png")
    assert got == "https://cdn.example.com/logo.png"
    assert resolve_absolute_url("data:image/png;base64,xxx") \
        == "data:image/png;base64,xxx"
    assert resolve_absolute_url("") is None
    assert resolve_absolute_url(None) is None


# ═════════════════════════════════════════════════════════════════════
# 6. get_effective_business_settings absolutize=True round-trip
# ═════════════════════════════════════════════════════════════════════

def test_effective_settings_absolutize_promotes_logo(monkeypatch):
    from services.tenants.business_settings import (
        get_effective_business_settings,
    )
    monkeypatch.setenv("APP_BASE_URL", "https://theme.plofv.com")
    monkeypatch.delenv("PUBLIC_APP_BASE_URL", raising=False)
    monkeypatch.delenv("FRONTEND_BASE_URL", raising=False)

    class _FakeDB:
        class tenants:
            @staticmethod
            async def find_one(q, proj):  # noqa
                return {
                    "id": "t-1", "company_name": "Legacy Co",
                    "logo_url": "/api/objects/x/logo.png",
                    "brand_primary_hex": "#0B4A6F",
                }
    eff = asyncio.run(
        get_effective_business_settings(_FakeDB(), "t-1", absolutize=True),
    )
    assert eff["logo_url"] == "https://theme.plofv.com/api/objects/x/logo.png"
    eff2 = asyncio.run(
        get_effective_business_settings(_FakeDB(), "t-1", absolutize=False),
    )
    assert eff2["logo_url"] == "/api/objects/x/logo.png"
