"""Phase R1.c · Feb-2026 — PDF export helpers for the Financial
Suite reports.

This module mirrors ``csv_export`` and produces branded PDFs for
scalar and grouped metrics. Uses ``reportlab.platypus`` (already
in ``requirements.txt`` — no new dependency).

Design contract
---------------

* Every PDF opens with a header row: tenant logo (left) + report
  title + period label (right).
* A second row summarizes filters applied (lens, service_type,
  tech_id) so the exported file self-documents its scope.
* Body:
  - **Scalar** — one hero KpiTable with value / prior / delta%,
    plus an optional sparkline table underneath.
  - **Grouped** — one wide table with humanised column headers.
    Wraps to further pages via ``LongTable`` so 500-row unpaid-
    invoices exports still render.
* Footer on every page: "Generated at <ISO ts> · R1 Financial
  Suite · services.reporting" plus page numbers.
* Brand colors are pulled from ``services.reporting.exports.brand``
  which mirrors the ``theme.js`` token equivalents (navy header,
  green accents).

Deliberately simple. Ships as a bytes body suitable for
``fastapi.Response(media_type='application/pdf', content=body)``.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Brand tokens — kept in this file so the CSS ``theme.js`` values
# and the PDF renderer never drift. If K64/K67 rebalance the palette
# again, update these hex values only.
BRAND_NAVY  = "#0B2A4A"
BRAND_GREEN = "#1F7A3A"
BRAND_INK   = "#111827"
BRAND_MUTED = "#6B7280"
BRAND_LINE  = "#E5E7EB"
BRAND_BG    = "#F8FAFC"

_TRUSTED_LOGO_HOSTS = (
    "app.plofv.com",
    "plofv.com",
    "cdn.plofv.com",
    "images.unsplash.com",  # sample tenant assets
)


def _is_trusted_logo(url: Optional[str]) -> bool:
    """Guard against SSRF via tenant-controlled ``logo_url``. Only
    fetch remote logos from a small allow-list; everything else
    silently falls back to a text wordmark."""
    if not url or not isinstance(url, str):
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # pragma: no cover — defensive
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in _TRUSTED_LOGO_HOSTS)


def _fetch_logo_bytes(url: str, timeout: float = 3.0) -> Optional[bytes]:
    """Best-effort HTTP GET of a tenant logo. Returns ``None`` on
    any failure — never raises. Time-boxed so a slow logo host
    can't make the whole PDF endpoint hang."""
    try:
        import requests  # local import — keeps helper lazy-safe.
        r = requests.get(url, timeout=timeout, stream=False)
        if r.status_code != 200:
            return None
        # Reject anything that's not clearly an image.
        ctype = (r.headers.get("content-type") or "").lower()
        if not ctype.startswith("image/"):
            return None
        return r.content
    except Exception as exc:  # pragma: no cover — network exceptions
        logger.warning("[reports.pdf] logo fetch failed for %s: %s", url, exc)
        return None


def _humanise(key: str) -> str:
    return key.replace("_", " ").title()


def _fmt_cell(v: Any, key: Optional[str] = None) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        # Currency-ish columns get 2dp, everything else keeps
        # the same shape but drops trailing zeros for pct-style
        # columns (revenue / amount / balance / total).
        if key and any(k in key for k in
                       ("revenue", "amount", "balance", "total",
                        "value", "invoiced", "collected", "net",
                        "outstanding", "cogs", "opex")):
            return f"{v:,.2f}"
        return f"{v:g}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _reportlab():
    """Deferred reportlab import so the module can be safely
    referenced from tests that shouldn't drag reportlab in."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
        Table, TableStyle, Image, KeepTogether, LongTable,
    )
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    return {
        "letter": letter, "getSampleStyleSheet": getSampleStyleSheet,
        "ParagraphStyle": ParagraphStyle, "colors": rl_colors,
        "inch": inch, "BaseDocTemplate": BaseDocTemplate,
        "Frame": Frame, "PageTemplate": PageTemplate,
        "Paragraph": Paragraph, "Spacer": Spacer, "Table": Table,
        "TableStyle": TableStyle, "Image": Image,
        "KeepTogether": KeepTogether, "LongTable": LongTable,
        "TA_LEFT": TA_LEFT, "TA_RIGHT": TA_RIGHT,
    }


def _styles(rl):
    """Return a small palette of Paragraph styles branded for the
    financial-suite exports."""
    base = rl["getSampleStyleSheet"]()
    ps = rl["ParagraphStyle"]
    from reportlab.lib import colors as rlc
    return {
        "title": ps("brand-title", parent=base["Title"],
                    fontName="Helvetica-Bold", fontSize=18, leading=22,
                    textColor=rlc.HexColor(BRAND_NAVY), alignment=rl["TA_LEFT"]),
        "subtitle": ps("brand-subtitle", parent=base["Normal"],
                       fontName="Helvetica", fontSize=10, leading=14,
                       textColor=rlc.HexColor(BRAND_MUTED)),
        "hero_value": ps("hero-value", parent=base["Title"],
                         fontName="Helvetica-Bold", fontSize=36, leading=40,
                         textColor=rlc.HexColor(BRAND_GREEN)),
        "chip": ps("chip", parent=base["Normal"],
                   fontName="Helvetica-Bold", fontSize=10, leading=12,
                   textColor=rlc.HexColor(BRAND_NAVY)),
        "small": ps("small", parent=base["Normal"],
                    fontName="Helvetica", fontSize=8, leading=10,
                    textColor=rlc.HexColor(BRAND_MUTED)),
        "cell": ps("cell", parent=base["Normal"],
                   fontName="Helvetica", fontSize=9, leading=11,
                   textColor=rlc.HexColor(BRAND_INK)),
        "cell_r": ps("cell-r", parent=base["Normal"],
                     fontName="Helvetica", fontSize=9, leading=11,
                     textColor=rlc.HexColor(BRAND_INK),
                     alignment=rl["TA_RIGHT"]),
    }


def _header_flowables(rl, styles, *, tenant_name: str, tenant_logo_url: Optional[str],
                       title: str, period_label: str,
                       period_start: str, period_end: str) -> list:
    """Build the top-of-page tenant-branded header row."""
    logo_flow = None
    if _is_trusted_logo(tenant_logo_url):
        b = _fetch_logo_bytes(tenant_logo_url)
        if b:
            try:
                logo_flow = rl["Image"](io.BytesIO(b), width=1.4 * rl["inch"], height=0.6 * rl["inch"])
            except Exception as exc:  # pragma: no cover — image decode
                logger.warning("[reports.pdf] logo decode failed: %s", exc)
                logo_flow = None
    if logo_flow is None:
        logo_flow = rl["Paragraph"](f"<b>{tenant_name}</b>", styles["chip"])

    right_col = [
        rl["Paragraph"](title, styles["title"]),
        rl["Paragraph"](
            f"{period_label} · {period_start} → {period_end}",
            styles["subtitle"],
        ),
    ]

    tbl = rl["Table"](
        [[logo_flow, right_col]],
        colWidths=[1.6 * rl["inch"], None],
    )
    tbl.setStyle(rl["TableStyle"]([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [tbl, rl["Spacer"](1, 6)]


def _filter_flowables(rl, styles, filters: Optional[Dict[str, Any]]) -> list:
    if not filters:
        return []
    pairs = []
    for k in sorted(filters.keys()):
        v = filters[k]
        if v in (None, "", [], {}, False, 0):
            continue
        pairs.append(f"<b>{_humanise(k)}:</b> {v}")
    if not pairs:
        return []
    return [
        rl["Paragraph"]("  ·  ".join(pairs), styles["small"]),
        rl["Spacer"](1, 6),
    ]


def _table_style(rl, header_row: bool = True):
    from reportlab.lib import colors as rlc
    style = rl["TableStyle"]([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), rlc.HexColor(BRAND_INK)),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, 0), 1, rlc.HexColor(BRAND_NAVY)),
        ("GRID", (0, 1), (-1, -1), 0.25, rlc.HexColor(BRAND_LINE)),
        ("BACKGROUND", (0, 0), (-1, 0), rlc.HexColor(BRAND_NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), rlc.HexColor("#FFFFFF")),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [rlc.HexColor("#FFFFFF"), rlc.HexColor(BRAND_BG)]),
    ])
    return style


def _build_doc(buf, rl, *, on_page):
    doc = rl["BaseDocTemplate"](
        buf,
        pagesize=rl["letter"],
        leftMargin=0.6 * rl["inch"],
        rightMargin=0.6 * rl["inch"],
        topMargin=0.5 * rl["inch"],
        bottomMargin=0.6 * rl["inch"],
        title="Aquaterra · Financial Report",
    )
    frame = rl["Frame"](
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="main",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([
        rl["PageTemplate"](id="R1cPage", frames=[frame], onPage=on_page),
    ])
    return doc


def _footer_painter(rl, *, tenant_name: str):
    """Return a reportlab ``onPage`` callback for the shared
    footer row + page numbers."""
    def _paint(canvas, doc):
        from reportlab.lib import colors as rlc
        canvas.saveState()
        canvas.setStrokeColor(rlc.HexColor(BRAND_LINE))
        canvas.setLineWidth(0.3)
        y = 0.45 * rl["inch"]
        canvas.line(doc.leftMargin, y,
                    doc.leftMargin + doc.width, y)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(rlc.HexColor(BRAND_MUTED))
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        canvas.drawString(doc.leftMargin, y - 12,
                          f"Generated at {ts} · R1 Financial Suite · {tenant_name}")
        canvas.drawRightString(doc.leftMargin + doc.width, y - 12,
                               f"Page {doc.page}")
        canvas.restoreState()
    return _paint


# ─────────────────────────────────────────────────────────────
# Public renderers — mirror the CSV surface
# ─────────────────────────────────────────────────────────────

def render_scalar_pdf(*,
                      metric_label: str,
                      period_label: str,
                      period_start: str,
                      period_end: str,
                      value: float,
                      prior_value: float,
                      delta_pct: Optional[float],
                      sparkline: Optional[List[Dict[str, Any]]] = None,
                      tenant_name: Optional[str] = None,
                      tenant_logo_url: Optional[str] = None,
                      filters_applied: Optional[Dict[str, Any]] = None,
                      format_hint: str = "currency",
                      ) -> bytes:
    """Render a scalar-metric envelope (P&L Net Income, revenue
    total, etc.) as a branded, printable PDF."""
    rl = _reportlab()
    styles = _styles(rl)
    buf = io.BytesIO()
    doc = _build_doc(
        buf, rl,
        on_page=_footer_painter(rl, tenant_name=tenant_name or "Aquaterra"),
    )
    story = _header_flowables(
        rl, styles,
        tenant_name=tenant_name or "Aquaterra",
        tenant_logo_url=tenant_logo_url,
        title=metric_label,
        period_label=period_label,
        period_start=period_start, period_end=period_end,
    )
    story += _filter_flowables(rl, styles, filters_applied)

    hero_label = "$" if format_hint == "currency" else ""
    hero_value = _fmt_cell(value, "value")
    prior_str = _fmt_cell(prior_value, "prior_value")
    delta_str = f"{delta_pct:+.1f}%" if isinstance(delta_pct, (int, float)) else "—"

    story.append(rl["Paragraph"](
        f"<font color='{BRAND_GREEN}'>{hero_label}{hero_value}</font>",
        styles["hero_value"],
    ))
    story.append(rl["Paragraph"](
        f"Prior period {hero_label}{prior_str} · Δ {delta_str}",
        styles["subtitle"],
    ))
    story.append(rl["Spacer"](1, 12))

    if sparkline:
        rows = [["Bucket", "Value"]]
        for pt in sparkline:
            rows.append([_fmt_cell(pt.get("t")), _fmt_cell(pt.get("v"), "value")])
        t = rl["Table"](rows, colWidths=[3 * rl["inch"], 2 * rl["inch"]])
        t.setStyle(_table_style(rl))
        story.append(rl["KeepTogether"]([
            rl["Paragraph"]("Sparkline points", styles["chip"]),
            rl["Spacer"](1, 4),
            t,
        ]))

    doc.build(story)
    return buf.getvalue()


def render_rows_pdf(*,
                    metric_label: str,
                    period_label: str,
                    period_start: str,
                    period_end: str,
                    columns: List[str],
                    rows: Iterable[Dict[str, Any]],
                    total: Optional[float] = None,
                    tenant_name: Optional[str] = None,
                    tenant_logo_url: Optional[str] = None,
                    filters_applied: Optional[Dict[str, Any]] = None,
                    ) -> bytes:
    """Render a grouped/line-item envelope (P&L line items, AR
    aging by customer, unpaid invoices, revenue by service type,
    cash flow by period) as a branded, printable PDF."""
    rl = _reportlab()
    styles = _styles(rl)
    buf = io.BytesIO()
    doc = _build_doc(
        buf, rl,
        on_page=_footer_painter(rl, tenant_name=tenant_name or "Aquaterra"),
    )
    story = _header_flowables(
        rl, styles,
        tenant_name=tenant_name or "Aquaterra",
        tenant_logo_url=tenant_logo_url,
        title=metric_label,
        period_label=period_label,
        period_start=period_start, period_end=period_end,
    )
    story += _filter_flowables(rl, styles, filters_applied)

    if total is not None:
        story.append(rl["Paragraph"](
            f"<b>Total:</b> ${_fmt_cell(total, 'total')}",
            styles["chip"],
        ))
        story.append(rl["Spacer"](1, 6))

    header_row = [_humanise(k) for k in columns]
    body: List[List[str]] = [header_row]
    n = 0
    for row in rows:
        body.append([_fmt_cell(row.get(k), k) for k in columns])
        n += 1
    if n == 0:
        body.append(["(no rows for this period)"] + [""] * (len(columns) - 1))

    # LongTable so unpaid-invoices exports paginate across pages
    # instead of overflowing a single frame.
    tbl = rl["LongTable"](body, repeatRows=1)
    tbl.setStyle(_table_style(rl))
    story.append(tbl)

    doc.build(story)
    return buf.getvalue()
