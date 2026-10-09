// Phase 7C · Feb-2026 — Form Template style helper (pure).
//
// Single-source-of-truth mapping from the Phase 7A stored
// ``style`` payload to a CSS object a React element can spread.
// Every surface that applies a template style — the Phase 7B
// editor preview, the real form renderers in Phase 7C+, and the
// Phase 7D mobile mirror — MUST route through this helper so the
// bg_alpha composition / grid span / padding scaling behaves
// identically everywhere.
//
// Pure function.  No React, no DOM, no imports — safe to call from
// SSR, from tests, from tooling.


const _DEFAULTS = {
  bg_color:     "#FFFFFF",
  bg_alpha:     1.0,
  text_color:   "#111827",
  border_color: "#E5E7EB",
  width_cols:   12,
  padding_y:    2,
};


// Padding multiplier — matches the Phase 7B preview visual range.
// ``padding_y: 2`` (default seed) → 8px top + bottom, ``padding_y: 8``
// (max) → 32px top + bottom.  Tuned to the Phase 7B column-span
// strip's visual rhythm.
export const PADDING_Y_MULTIPLIER_PX = 4;


function _hexToRgb(hex) {
  if (typeof hex !== "string") return null;
  const m = hex.trim().match(/^#?([0-9A-Fa-f]{6})$/);
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff };
}


function _clampAlpha(a) {
  if (typeof a !== "number" || Number.isNaN(a)) return 1;
  if (a < 0) return 0;
  if (a > 1) return 1;
  return a;
}


function _clampCols(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return _DEFAULTS.width_cols;
  if (v < 1)  return 1;
  if (v > 12) return 12;
  return Math.round(v);
}


function _clampPad(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return _DEFAULTS.padding_y;
  if (v < 1) return 1;
  if (v > 8) return 8;
  return Math.round(v);
}


/**
 * ``styleToCss({ bg_color, bg_alpha, text_color, border_color,
 *                 width_cols, padding_y }) → CSS object``
 *
 * Returns a plain object suitable for React's ``style={}`` prop.
 * Missing / invalid fields fall back to the Phase 7A seed defaults.
 */
export function styleToCss(fieldStyle) {
  const s = fieldStyle || {};
  const rgb = _hexToRgb(s.bg_color) || _hexToRgb(_DEFAULTS.bg_color);
  const alpha = _clampAlpha(
    typeof s.bg_alpha === "number" ? s.bg_alpha : _DEFAULTS.bg_alpha,
  );
  const widthCols = _clampCols(s.width_cols ?? _DEFAULTS.width_cols);
  const paddingY  = _clampPad(s.padding_y   ?? _DEFAULTS.padding_y);
  const padPx     = paddingY * PADDING_Y_MULTIPLIER_PX;
  const textCol   = /^#[0-9A-Fa-f]{6}$/.test(s.text_color || "")
    ? s.text_color : _DEFAULTS.text_color;
  const borderCol = /^#[0-9A-Fa-f]{6}$/.test(s.border_color || "")
    ? s.border_color : _DEFAULTS.border_color;
  return {
    backgroundColor: `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`,
    color:           textCol,
    borderColor:     borderCol,
    gridColumn:      `span ${widthCols} / span ${widthCols}`,
    paddingTop:      `${padPx}px`,
    paddingBottom:   `${padPx}px`,
  };
}


export default styleToCss;
