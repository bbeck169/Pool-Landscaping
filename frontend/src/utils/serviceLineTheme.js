/**
 * Feb 2026 · Service-line theme resolver.
 *
 * Central mapper from a customer's / job's ``service_line``
 * (``"pool"`` | ``"landscape"`` | ``"both"``) to a small shape any
 * UI component can consume. Reaching for ``colors.pool[500]``
 * directly still works, but going through this helper means we
 * can retune the palette in one place later without hunting
 * across the codebase.
 *
 * Also exposes:
 *   * ``KPI_TONE_ROTATION`` — the ordered accent-tone rotation the
 *     Dashboard KpiCard uses when the caller doesn't specify a
 *     semantic tone.
 *   * ``getReadableTextColor(bg)`` — WCAG-safe text-on-color
 *     selector using the standard sRGB luminance formula.
 *   * ``getContrastRatio(a, b)`` — for tests + spot-checks.
 */
import { colors } from "@/theme";


// ─────────────────────────────────────────────────────────────────
// Service-line resolver
// ─────────────────────────────────────────────────────────────────
export function getServiceLineTheme(line) {
  const key = String(line || "").trim().toLowerCase();
  if (key === "pool") {
    return {
      key: "pool",
      primary: colors.pool[500],
      soft: colors.pool[100],
      strong: colors.pool[700],
      onPrimary: "#FFFFFF",
      label: "Pool",
    };
  }
  if (key === "landscape" || key === "landscaping") {
    return {
      key: "landscape",
      primary: colors.landscape[500],
      soft: colors.landscape[100],
      strong: colors.landscape[700],
      onPrimary: "#FFFFFF",
      label: "Landscape",
    };
  }
  // Fallback (``both`` / unknown / empty) → existing brand family
  // so nothing looks orphaned in mixed contexts.
  return {
    key: "both",
    primary: colors.brand,
    soft: colors.brandTertiary,
    strong: colors.onBrandTertiary,
    onPrimary: colors.onBrandPrimary,
    label: "Pool + Landscape",
  };
}


// ─────────────────────────────────────────────────────────────────
// KPI accent rotation — used by the Dashboard KpiCard when the
// caller doesn't pass an explicit ``tone`` prop.
//
// Ordering is chosen so consecutive tiles land on visibly distinct
// hues (violet → amber → sky → emerald → rose) rather than
// two adjacent-on-the-wheel neighbours.
// ─────────────────────────────────────────────────────────────────
export const KPI_TONE_ROTATION = [
  "violet",
  "amber",
  "sky",
  "emerald",
  "rose",
];


export function getAccentTone(name) {
  const t = colors.accent[String(name || "").toLowerCase()];
  return t || colors.accent.sky;
}


// ─────────────────────────────────────────────────────────────────
// Contrast helpers — used by tests + the ``getReadableTextColor``
// picker below.
// ─────────────────────────────────────────────────────────────────
function _hexToRgb(hex) {
  const h = String(hex || "").replace("#", "").trim();
  if (h.length !== 6) return { r: 0, g: 0, b: 0 };
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}

function _relLuminance(hex) {
  const { r, g, b } = _hexToRgb(hex);
  const chan = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b);
}


export function getContrastRatio(a, b) {
  const la = _relLuminance(a);
  const lb = _relLuminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}


/**
 * Given a background hex, return either ``"#FFFFFF"`` or the
 * theme's dark ``onSurface`` — whichever passes WCAG AA (≥ 4.5)
 * against that background. Falls back to white if both fail,
 * which is the more conservative side for CTA buttons.
 */
export function getReadableTextColor(bgHex) {
  const white = "#FFFFFF";
  const dark = colors.onSurface;   // "#09090B"
  const cWhite = getContrastRatio(bgHex, white);
  const cDark = getContrastRatio(bgHex, dark);
  if (cWhite >= 4.5 && cWhite >= cDark) return white;
  if (cDark >= 4.5) return dark;
  return cWhite > cDark ? white : dark;
}
