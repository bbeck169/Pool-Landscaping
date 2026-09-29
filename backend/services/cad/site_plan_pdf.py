"""Phase CAD-3 · Feb-2026 — Site Plan PDF renderer.

Server-side, ReportLab-driven, two-page PDF export for a
``designs`` document. Reproducible from a design ID alone so the
render is DB-driven, not FE-snapshot-driven.

Public surface:
  * ``build_render_context(*, design, customer, tenant, map_meta,
                           map_bytes, generated_by)`` — pure. Returns
    the dict the tests + endpoint hand to ``render_pdf``.
  * ``render_pdf(ctx)`` — returns ``bytes`` of a 2-page US-Letter PDF.

All geometry math flows through ``services.geometry`` — the shoelace
+ polyline helpers are the single source of truth (CAD-2 extracted
them out of ``routers.ai_measure``).
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rl_canvas

from services.geometry import (
    polygon_area_normalized_to_sqft,
    polyline_length_normalized_to_ft,
)

logger = logging.getLogger("pool_crm")


PAGE_W, PAGE_H = letter  # 8.5in × 11in in points
MARGIN = 0.5 * inch
BAND_HEIGHT = 0.5 * inch
_PLACEHOLDER = "—"


# ── Element-type styling (kept in sync with FE ShapeNode). ─────────
_TYPE_FILLS = {
    "pool":     "#0284C7",
    "spa":      "#7C3AED",
    "paver":    "#D97706",
    "wall":     "#0F172A",
    "firepit":  "#DC2626",
    "rect":     "#0284C7",
    "circle":   "#0F172A",
    "text":     "#0F172A",
    "icon":     "#059669",
    "boundary": "#7C3AED",
    "dimension": "#DC2626",
    "line":     "#0F172A",
    "curve":    "#0F172A",
    "tree":     "#059669",
    "cactus":   "#059669",
}


# Phase CAD-3.5b · Feb-2026 — Paver material palette.
#   Kept in sync with the FE catalog in ``pages/cad/Editor.jsx``.
#   ReportLab lacks first-class pattern fills for arbitrary
#   polygons, so the PDF path uses per-material representative
#   colors + surfaces the material name in the element-inventory
#   legend row (``paver_materials`` breakdown). ``label`` mirrors
#   the FE dropdown text so operators recognise the row.
PAVER_MATERIAL_PALETTE: Dict[str, Dict[str, str]] = {
    "travertine":         {"color": "#D9C7A9",
                            "label": "Travertine"},
    "flagstone":          {"color": "#7C7A75",
                            "label": "Flagstone"},
    "brick_running_bond": {"color": "#8B4A3B",
                            "label": "Brick (running bond)"},
    "slate":              {"color": "#3F434B",
                            "label": "Slate"},
}
_DEFAULT_PAVER_MATERIAL_ID = "travertine"


def _paver_material(el: Dict[str, Any]) -> Dict[str, str]:
    mid = ((el.get("props") or {}).get("material_id")
           or _DEFAULT_PAVER_MATERIAL_ID)
    return PAVER_MATERIAL_PALETTE.get(mid,
                                       PAVER_MATERIAL_PALETTE[
                                           _DEFAULT_PAVER_MATERIAL_ID
                                       ])


def _fmt_or_placeholder(v, fmt: Optional[str] = None) -> str:
    if v is None or v == "":
        return _PLACEHOLDER
    if fmt:
        try:
            return fmt.format(v)
        except Exception:
            return str(v)
    return str(v)


def _summarise_elements(
    elements: List[Dict[str, Any]], *,
    canvas_w_ft: float, canvas_h_ft: float,
) -> List[Dict[str, Any]]:
    """Aggregate element inventory rows for the Page-1 table.

    One row per unique ``type``. Each row carries:
      * ``count`` — total occurrences
      * ``total_sqft`` — Σ shoelace-area (pool + spa + paver only)
      * ``total_linear_ft`` — Σ polyline length (wall + dimension)
      * ``icon_subtypes`` — Counter for ``type=="icon"`` rows
    """
    by_type: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "count": 0, "total_sqft": 0.0, "total_linear_ft": 0.0,
        "icon_subtypes": Counter(),
        # Phase CAD-3.5b — paver-by-material breakdown surfaces
        # the material catalog choice in the summary table so the
        # PDF legend can render "Pavers · Travertine · 3" style
        # rows without a second aggregation pass.
        "paver_materials": Counter(),
    })
    for el in elements or []:
        t = el.get("type") or "unknown"
        by_type[t]["count"] += 1
        coords = el.get("coords") or []
        if t in ("pool", "spa", "paver") and len(coords) >= 3:
            computed = (el.get("computed") or {}).get("area_sqft")
            sqft = (float(computed) if computed
                    else polygon_area_normalized_to_sqft(
                        coords,
                        canvas_w_ft=canvas_w_ft,
                        canvas_h_ft=canvas_h_ft,
                    ))
            by_type[t]["total_sqft"] += sqft
            if t == "paver":
                # Bucket paver rows by material_id so the summary
                # table can render one line per material.
                mid = ((el.get("props") or {}).get("material_id")
                       or _DEFAULT_PAVER_MATERIAL_ID)
                by_type[t]["paver_materials"][mid] += 1
        # Phase CAD-3.5b — line + curve carry linear-foot totals
        # so the legend can surface running-total lengths just
        # like walls / dimensions.
        elif t in ("wall", "dimension", "line", "curve") and len(coords) >= 2:
            computed = (el.get("computed") or {}).get("linear_ft")
            lft = (float(computed) if computed
                   else polyline_length_normalized_to_ft(
                       coords,
                       canvas_w_ft=canvas_w_ft,
                       canvas_h_ft=canvas_h_ft,
                   ))
            by_type[t]["total_linear_ft"] += lft
        elif t == "icon":
            icon = (el.get("props") or {}).get("icon") or "unknown"
            by_type[t]["icon_subtypes"][icon] += 1
    # Alphabetical for deterministic rendering / test-friendliness.
    rows = []
    for t in sorted(by_type.keys()):
        d = by_type[t]
        rows.append({
            "type": t,
            "count": d["count"],
            "total_sqft": round(d["total_sqft"], 1),
            "total_linear_ft": round(d["total_linear_ft"], 1),
            "icon_subtypes": dict(d["icon_subtypes"]),
            "paver_materials": dict(d["paver_materials"]),
        })
    return rows


def build_render_context(
    *,
    design: Dict[str, Any],
    customer: Optional[Dict[str, Any]],
    tenant: Dict[str, Any],
    map_bytes: Optional[bytes] = None,
    generated_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure — no I/O. Assembles every field the PDF needs.

    ``customer`` may be ``None`` (design has no customer_id or the
    referenced customer was deleted) OR may have empty ``address``.
    Both degrade gracefully — the render context reflects the
    degradation with placeholder ``"—"`` values on Page 1 fields.
    """
    canvas_w_ft = float(design.get("canvas_w_ft") or 60.0)
    canvas_h_ft = float(design.get("canvas_h_ft") or 40.0)
    fpp = design.get("feet_per_pixel")

    company = {
        "name": (tenant or {}).get("name") or "Pool & Landscaping",
        "logo_url": (tenant or {}).get("logo_url") or None,
    }

    cust = customer or {}
    customer_block = {
        "name":    _fmt_or_placeholder(cust.get("name")),
        "address": _fmt_or_placeholder(cust.get("address")),
        "phone":   _fmt_or_placeholder(cust.get("phone")),
        "email":   _fmt_or_placeholder(cust.get("email")),
    }

    job_block = {
        "design_name": design.get("name") or "Untitled design",
        "canvas_dims": f"{canvas_w_ft:g} ft × {canvas_h_ft:g} ft",
        "feet_per_pixel": (
            _PLACEHOLDER if not fpp else f"{float(fpp):.4f}"
        ),
        "map_center_lat": (
            _PLACEHOLDER if design.get("map_center_lat") is None
            else f"{float(design['map_center_lat']):.6f}"
        ),
        "map_center_lng": (
            _PLACEHOLDER if design.get("map_center_lng") is None
            else f"{float(design['map_center_lng']):.6f}"
        ),
        "map_zoom": (
            _PLACEHOLDER if design.get("map_zoom") is None
            else str(int(design["map_zoom"]))
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    elements = list(design.get("elements") or [])
    inventory = _summarise_elements(
        elements,
        canvas_w_ft=canvas_w_ft, canvas_h_ft=canvas_h_ft,
    )

    map_state = "available" if map_bytes else "unavailable"
    map_caption = (
        None if map_bytes
        else "No satellite backdrop available"
    )

    return {
        "company":  company,
        "customer": customer_block,
        "job":      job_block,
        "canvas_w_ft": canvas_w_ft,
        "canvas_h_ft": canvas_h_ft,
        "feet_per_pixel": fpp,
        # CAD-2.5 · Feb-2026 — persist the map-tile dims into the
        # render context so the scale bar can derive its length from
        # real-world (feet_per_pixel × map_size_px.w) rather than
        # the design's declared canvas_w_ft, which the user may have
        # overridden after calibrating the map.
        "map_size_px": design.get("map_size_px") or None,
        "boundary": list(design.get("boundary") or []),
        "elements": elements,
        "inventory": inventory,
        "map_bytes": map_bytes,
        "map_state": map_state,
        "map_caption": map_caption,
        "generated_by": generated_by,
        "page_count": 2,
    }


# ═══════════════════════════════════════════════════════════════════
# Page renderers
# ═══════════════════════════════════════════════════════════════════
def _draw_footer(c: rl_canvas.Canvas, *, page_no: int, total: int,
                 brand_hex: str) -> None:
    c.setFillColor(HexColor(brand_hex))
    c.rect(0, 0, PAGE_W, BAND_HEIGHT, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica", 9)
    c.drawCentredString(
        PAGE_W / 2.0, BAND_HEIGHT / 2.0 - 3,
        f"{page_no} / {total}",
    )


def _draw_header(c: rl_canvas.Canvas, *, title: str,
                 brand_hex: str, company_name: str) -> None:
    c.setFillColor(HexColor(brand_hex))
    c.rect(0, PAGE_H - BAND_HEIGHT * 2, PAGE_W, BAND_HEIGHT * 2,
           stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(MARGIN, PAGE_H - BAND_HEIGHT - 4, company_name)
    c.setFont("Helvetica", 10)
    c.drawString(MARGIN, PAGE_H - BAND_HEIGHT * 2 + 8, title)


def _draw_kv_block(c: rl_canvas.Canvas, *, x: float, y: float,
                   heading: str, pairs: List[tuple],
                   line_h: float = 14.0) -> float:
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, heading)
    y -= line_h
    c.setFont("Helvetica", 10)
    for k, v in pairs:
        c.drawString(x, y, f"{k}:")
        c.drawString(x + 1.3 * inch, y, str(v))
        y -= line_h
    return y


def _draw_inventory_table(c: rl_canvas.Canvas, *,
                          x: float, y: float, rows: List[dict],
                          brand_hex: str) -> float:
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Element inventory")
    y -= 16
    if not rows:
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(x, y, "(no elements)")
        return y - 14
    # Header row.
    c.setFillColor(HexColor(brand_hex))
    c.rect(x, y - 4, PAGE_W - 2 * MARGIN, 14, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 4, y, "TYPE")
    c.drawString(x + 1.5 * inch, y, "COUNT")
    c.drawString(x + 2.5 * inch, y, "TOTAL SQ FT")
    c.drawString(x + 4.0 * inch, y, "TOTAL LIN FT")
    c.drawString(x + 5.5 * inch, y, "NOTES")
    y -= 16
    c.setFillColor(black)
    c.setFont("Helvetica", 9)
    for row in rows:
        notes = ""
        if row.get("icon_subtypes"):
            parts = [f"{k}: {v}" for k, v in
                     sorted(row["icon_subtypes"].items())]
            notes = ", ".join(parts)[:60]
        c.drawString(x + 4, y, row["type"])
        c.drawRightString(x + 2.3 * inch, y, str(row["count"]))
        c.drawRightString(x + 3.7 * inch, y,
                          f"{row['total_sqft']:.1f}"
                          if row["total_sqft"] else "—")
        c.drawRightString(x + 5.2 * inch, y,
                          f"{row['total_linear_ft']:.1f}"
                          if row["total_linear_ft"] else "—")
        c.drawString(x + 5.5 * inch, y, notes or "—")
        y -= 13
    return y


def _draw_page1(c: rl_canvas.Canvas, ctx: dict,
                brand_hex: str) -> None:
    _draw_header(c, title="Site Plan · Property Overview",
                 brand_hex=brand_hex,
                 company_name=ctx["company"]["name"])
    y = PAGE_H - BAND_HEIGHT * 2 - 24
    # Property block.
    y = _draw_kv_block(
        c, x=MARGIN, y=y, heading="Property",
        pairs=[
            ("Customer", ctx["customer"]["name"]),
            ("Service address", ctx["customer"]["address"]),
            ("Phone", ctx["customer"]["phone"]),
            ("Email", ctx["customer"]["email"]),
        ],
    )
    y -= 6
    # Job block.
    y = _draw_kv_block(
        c, x=MARGIN, y=y, heading="Design",
        pairs=[
            ("Name", ctx["job"]["design_name"]),
            ("Canvas", ctx["job"]["canvas_dims"]),
            ("Feet/pixel", ctx["job"]["feet_per_pixel"]),
            ("Map center lat", ctx["job"]["map_center_lat"]),
            ("Map center lng", ctx["job"]["map_center_lng"]),
            ("Map zoom", ctx["job"]["map_zoom"]),
            ("Generated at", ctx["job"]["generated_at"]),
        ],
    )
    y -= 10
    _draw_inventory_table(
        c, x=MARGIN, y=y, rows=ctx["inventory"],
        brand_hex=brand_hex,
    )
    _draw_footer(c, page_no=1, total=ctx["page_count"],
                 brand_hex=brand_hex)


def _draw_element(c: rl_canvas.Canvas, el: dict, *,
                  ox: float, oy: float, sw: float, sh: float) -> None:
    """Draw a single element on the Page-2 canvas. ``(ox, oy)`` is
    the top-left corner of the drawing region in PDF points;
    ``(sw, sh)`` is the region size. Coordinates in ``el`` are
    normalized 0..1 relative to the design canvas."""
    t = el.get("type")
    fill_hex = _TYPE_FILLS.get(t, "#334155")
    stroke = HexColor("#0F172A")
    fill = HexColor(fill_hex)
    coords = el.get("coords") or []

    def _pt(p):
        return (ox + p["x"] * sw, oy + (1.0 - p["y"]) * sh)

    if t in ("rect", "pool", "spa", "firepit", "text", "circle") \
            and el.get("x") is not None:
        # Legacy x/y/w/h element.
        px = ox + el["x"] * sw
        py = oy + (1.0 - (el["y"] + (el.get("h") or 0.06))) * sh
        pw = (el.get("w") or 0.1) * sw
        ph = (el.get("h") or 0.06) * sh
        c.setStrokeColor(stroke)
        c.setFillColor(fill)
        c.setLineWidth(0.7)
        if t == "circle":
            c.setFillColor(HexColor("#FFFFFF"))
            r = pw / 2.0
            c.circle(px + r, py + r, r, stroke=1, fill=0)
        elif t == "text":
            c.setFillColor(black)
            c.setFont("Helvetica", 9)
            c.drawString(px, py + ph - 4, el.get("label") or "Label")
        else:
            c.rect(px, py, pw, ph, stroke=1, fill=1)
        return

    if t in ("pool", "spa", "paver") and len(coords) >= 3:
        # Phase CAD-3.5b — paver uses the material-specific fill
        # color (per-material palette) instead of the flat orange.
        # Pool/spa retain the legacy fills.
        if t == "paver":
            mat = _paver_material(el)
            fill = HexColor(mat["color"])
        c.setStrokeColor(stroke)
        c.setFillColor(fill)
        c.setLineWidth(0.7)
        path = c.beginPath()
        p0 = _pt(coords[0])
        path.moveTo(*p0)
        for p in coords[1:]:
            path.lineTo(*_pt(p))
        path.close()
        c.drawPath(path, stroke=1, fill=1)
        return

    # Phase CAD-3.5b — straight line element.
    if t == "line" and len(coords) == 2:
        c.setStrokeColor(stroke)
        c.setLineWidth(1.2)
        a = _pt(coords[0]); b = _pt(coords[1])
        c.line(a[0], a[1], b[0], b[1])
        return

    # Phase CAD-3.5b — smooth-curve element. ReportLab renders a
    # sampled poly-Bezier approximation using
    # :func:`canvas.bezier` between successive vertex triplets.
    # For a 2-point curve we fall through to a straight line.
    # Higher-order paths approximate the Konva ``tension=0.5``
    # look by using Catmull–Rom → cubic-Bezier control-point
    # derivation (standard formula: control = anchor ±
    # (next – prev)/6, matching Konva's default line-tension of
    # 0.5).
    if t == "curve" and len(coords) >= 2:
        c.setStrokeColor(stroke)
        c.setLineWidth(1.2)
        pts = [_pt(p) for p in coords]
        if len(pts) == 2:
            c.line(pts[0][0], pts[0][1], pts[1][0], pts[1][1])
            return
        path = c.beginPath()
        path.moveTo(*pts[0])
        for i in range(len(pts) - 1):
            p0 = pts[i - 1] if i > 0 else pts[i]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[i + 2] if i + 2 < len(pts) else pts[i + 1]
            # Catmull-Rom → cubic Bezier (α = 1/6 keeps parity
            # with the FE ``tension = 0.5`` visual).
            c1 = (p1[0] + (p2[0] - p0[0]) / 6.0,
                  p1[1] + (p2[1] - p0[1]) / 6.0)
            c2 = (p2[0] - (p3[0] - p1[0]) / 6.0,
                  p2[1] - (p3[1] - p1[1]) / 6.0)
            path.curveTo(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
        c.drawPath(path, stroke=1, fill=0)
        return

    if t == "wall" and len(coords) >= 2:
        c.setStrokeColor(stroke)
        c.setLineWidth(1.6)
        path = c.beginPath()
        p0 = _pt(coords[0])
        path.moveTo(*p0)
        for p in coords[1:]:
            path.lineTo(*_pt(p))
        c.drawPath(path, stroke=1, fill=0)
        return

    if t == "dimension" and len(coords) >= 2:
        c.setStrokeColor(HexColor("#DC2626"))
        c.setLineWidth(1.2)
        a = _pt(coords[0]); b = _pt(coords[1])
        c.line(a[0], a[1], b[0], b[1])
        return

    if t == "boundary" and len(coords) >= 3:
        c.setStrokeColor(HexColor("#7C3AED"))
        c.setLineWidth(1.0)
        c.setDash(3, 2)
        path = c.beginPath()
        p0 = _pt(coords[0])
        path.moveTo(*p0)
        for p in coords[1:]:
            path.lineTo(*_pt(p))
        path.close()
        c.drawPath(path, stroke=1, fill=0)
        c.setDash()
        return

    if t == "icon" and coords:
        p = _pt(coords[0])
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.circle(p[0], p[1], 4, stroke=1, fill=1)
        return

    if t in ("tree", "cactus") and el.get("x") is not None:
        px = ox + el["x"] * sw
        py = oy + (1.0 - el["y"]) * sh
        c.setFillColor(HexColor("#059669"))
        c.circle(px, py, 4, stroke=0, fill=1)
        return


def _draw_north_arrow(c: rl_canvas.Canvas, *, cx: float, cy: float) -> None:
    c.setStrokeColor(black); c.setFillColor(black)
    c.setLineWidth(0.7)
    # Arrow up.
    c.line(cx, cy - 10, cx, cy + 10)
    c.line(cx - 4, cy + 4, cx, cy + 10)
    c.line(cx + 4, cy + 4, cx, cy + 10)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(cx, cy - 20, "N")


def _draw_scale_bar(c: rl_canvas.Canvas, *, cx: float, cy: float,
                    feet_label: str, bar_width_pt: float) -> None:
    c.setStrokeColor(black); c.setFillColor(black)
    c.setLineWidth(0.7)
    c.line(cx - bar_width_pt / 2.0, cy, cx + bar_width_pt / 2.0, cy)
    c.line(cx - bar_width_pt / 2.0, cy - 3,
           cx - bar_width_pt / 2.0, cy + 3)
    c.line(cx + bar_width_pt / 2.0, cy - 3,
           cx + bar_width_pt / 2.0, cy + 3)
    c.setFont("Helvetica", 8)
    c.drawCentredString(cx, cy + 6, feet_label)


def compute_scale_bar_pt(ctx: Dict[str, Any], sw: float,
                         *, feet: float = 50.0) -> float:
    """CAD-2.5 · Feb-2026 — Scale-bar length in PDF points.

    Derives the bar length for a ``feet``-foot real-world reference
    (default 50 ft) from ``feet_per_pixel`` applied to the actual
    map-tile dimensions rather than the design's declared
    ``canvas_w_ft``. This fixes the drift case where the customer
    calibrated the map or overrode ``feet_per_pixel`` at a different
    tile width than the canvas base.

    Formulation:
        map_real_ft = map_size_px.w × feet_per_pixel   (real width
                                                         of the map)
        pt_per_ft   = sw / map_real_ft                 (PDF pt per
                                                         real-world ft)
        bar_pt      = min(sw × 0.4, feet × pt_per_ft)  (cap at 40%
                                                         of drawing
                                                         region width)

    Legacy fall-throughs:
    * ``feet_per_pixel`` set but ``map_size_px`` missing (pre-CAD-1
      designs): the ``sw / canvas_w_ft`` computation preserves the
      CAD-3 behavior without crashing.
    * ``feet_per_pixel`` unset or non-positive: return a nominal
      ``sw × 0.2`` bar. The caller renders the label as
      ``"scale unknown"``.
    """
    fpp = ctx.get("feet_per_pixel")
    if not fpp or float(fpp) <= 0:
        return sw * 0.2
    map_size = ctx.get("map_size_px") or {}
    map_w = None
    if isinstance(map_size, dict):
        map_w = map_size.get("w")
    if map_w and float(map_w) > 0:
        map_real_ft = float(map_w) * float(fpp)
        pt_per_ft = sw / map_real_ft
    else:
        # Legacy pre-CAD-1 fallback — CAD-3 formula.
        pt_per_ft = sw / float(ctx.get("canvas_w_ft") or 60.0)
    return min(sw * 0.4, feet * pt_per_ft)


def _draw_legend(c: rl_canvas.Canvas, *, x: float, y: float,
                 inventory: List[dict]) -> None:
    if not inventory:
        return
    c.setFillColor(HexColor("#FFFFFF"))
    box_h = 12 * (len(inventory) + 1) + 6
    box_w = 2.0 * inch
    c.rect(x, y - box_h, box_w, box_h, stroke=1, fill=1)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 6, y - 12, "Legend")
    yy = y - 24
    c.setFont("Helvetica", 8)
    for row in inventory:
        swatch = HexColor(_TYPE_FILLS.get(row["type"], "#334155"))
        c.setFillColor(swatch)
        c.rect(x + 6, yy - 6, 10, 8, stroke=0, fill=1)
        c.setFillColor(black)
        c.drawString(x + 20, yy, f"{row['type']} · {row['count']}")
        yy -= 12


def _draw_page2(c: rl_canvas.Canvas, ctx: dict,
                brand_hex: str) -> None:
    # Title band.
    _draw_header(c, title="Site Plan · Design",
                 brand_hex=brand_hex,
                 company_name=ctx["company"]["name"])
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(
        PAGE_W / 2.0,
        PAGE_H - BAND_HEIGHT * 2 - 24,
        f"Site Plan — {ctx['job']['design_name']}",
    )
    # Border rectangle.
    inner_x = MARGIN
    inner_y = BAND_HEIGHT + MARGIN
    inner_w = PAGE_W - 2 * MARGIN
    inner_h = PAGE_H - 2 * MARGIN - 2 * BAND_HEIGHT - 40
    c.setStrokeColor(black)
    c.setLineWidth(1.0)
    c.rect(inner_x, inner_y, inner_w, inner_h, stroke=1, fill=0)
    # Drawing region — inset from the border so labels don't clip.
    pad = 12
    ox = inner_x + pad
    oy = inner_y + pad
    sw = inner_w - 2 * pad
    # Preserve the design canvas aspect ratio.
    aspect = ctx["canvas_w_ft"] / ctx["canvas_h_ft"]
    sh = sw / aspect
    if sh > inner_h - 2 * pad:
        sh = inner_h - 2 * pad
        sw = sh * aspect
    # Centre the drawing region horizontally within the border.
    ox = inner_x + (inner_w - sw) / 2.0
    oy = inner_y + (inner_h - sh) / 2.0

    # Map backdrop (or caption).
    if ctx["map_bytes"]:
        try:
            from reportlab.lib.utils import ImageReader
            img = ImageReader(BytesIO(ctx["map_bytes"]))
            c.drawImage(img, ox, oy, width=sw, height=sh,
                        preserveAspectRatio=True, mask="auto")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[cad-3] drawImage failed: {e}")
            c.setFillColor(HexColor("#F1F5F9"))
            c.rect(ox, oy, sw, sh, stroke=0, fill=1)
    else:
        c.setFillColor(HexColor("#F1F5F9"))
        c.rect(ox, oy, sw, sh, stroke=0, fill=1)
        c.setFillColor(HexColor("#64748B"))
        c.setFont("Helvetica-Oblique", 10)
        c.drawCentredString(ox + sw / 2.0, oy + sh / 2.0,
                            ctx["map_caption"] or "")

    # Design boundary + elements.
    if ctx["boundary"]:
        _draw_element(
            c, {"type": "boundary", "coords": ctx["boundary"]},
            ox=ox, oy=oy, sw=sw, sh=sh,
        )
    for el in ctx["elements"]:
        _draw_element(c, el, ox=ox, oy=oy, sw=sw, sh=sh)

    # North arrow (top-right of the drawing region).
    _draw_north_arrow(c, cx=ox + sw - 18, cy=oy + sh - 18)

    # Scale bar (bottom-center of the drawing region).
    fpp = ctx.get("feet_per_pixel")
    bar_pt = compute_scale_bar_pt(ctx, sw)
    _draw_scale_bar(
        c,
        cx=ox + sw / 2.0, cy=oy + 12,
        feet_label="50 ft" if fpp else "scale unknown",
        bar_width_pt=bar_pt,
    )

    # Legend (bottom-right, outside the drawing region if there's room).
    _draw_legend(
        c,
        x=inner_x + inner_w - 2.1 * inch,
        y=inner_y + inner_h - 4,
        inventory=ctx["inventory"],
    )
    _draw_footer(c, page_no=2, total=ctx["page_count"],
                 brand_hex=brand_hex)


def render_pdf(ctx: Dict[str, Any], *,
               brand_hex: str = "#0B4A6F") -> bytes:
    """Render the 2-page Site Plan PDF as bytes."""
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    _draw_page1(c, ctx, brand_hex=brand_hex)
    c.showPage()
    _draw_page2(c, ctx, brand_hex=brand_hex)
    c.showPage()
    c.save()
    return buf.getvalue()
