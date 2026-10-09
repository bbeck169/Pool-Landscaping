/**
 * Phase 7D · Form Template Runtime (mobile) — pure style mapper.
 * Port of web `frontend/src/lib/formStyle.js` (77a0c83de). Zero React dep.
 *
 * Divergence from web: CSS-grid `gridColumn: span N` has no RN analogue.
 * `width_cols` (1–12) becomes a percentage — `width` for vertical stacks
 * (default) or `flexBasis` + `maxWidth` inside wrapping flex rows. We never
 * emit `flexBasis` for column stacks (it would size HEIGHT there).
 */

export type FieldStyle = {
  bg_color?: string;
  bg_alpha?: number;
  text_color?: string;
  border_color?: string;
  width_cols?: number;
  padding_y?: number;
};

export type RNFieldStyle = {
  backgroundColor: string;
  color: string;
  borderColor: string;
  paddingVertical: number;
  width?: `${number}%`;
  flexBasis?: `${number}%`;
  maxWidth?: `${number}%`;
};

export const FIELD_STYLE_DEFAULTS = Object.freeze({
  bg_color: "#FFFFFF",
  bg_alpha: 1.0,
  text_color: "#111827",
  border_color: "#E5E7EB",
  width_cols: 12,
  padding_y: 2,
});

/** Same multiplier as web (`padding_y * 4` px). */
export const PADDING_Y_MULTIPLIER_PX = 4;

const HEX6 = /^#[0-9A-Fa-f]{6}$/;

function hexToRgb(hex: unknown): { r: number; g: number; b: number } | null {
  if (typeof hex !== "string") return null;
  const m = hex.trim().match(/^#?([0-9A-Fa-f]{6})$/);
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff };
}

function clampAlpha(a: unknown): number {
  if (typeof a !== "number" || Number.isNaN(a)) return 1;
  return Math.min(1, Math.max(0, a));
}

function clampInt(n: unknown, lo: number, hi: number, dflt: number): number {
  const v = Number(n);
  if (!Number.isFinite(v)) return dflt;
  return Math.min(hi, Math.max(lo, Math.round(v)));
}

/** 1–12 grid span → percent (2 dp), e.g. 6 → 50, 4 → 33.33. */
export function widthColsToPercent(cols: unknown): number {
  const c = clampInt(cols ?? FIELD_STYLE_DEFAULTS.width_cols, 1, 12, FIELD_STYLE_DEFAULTS.width_cols);
  return Math.round((c / 12) * 10000) / 100;
}

export function styleToRNStyle(
  fieldStyle?: FieldStyle | null,
  opts: { layout?: "column" | "row" } = {},
): RNFieldStyle {
  const s = fieldStyle || {};
  const rgb = hexToRgb(s.bg_color) || hexToRgb(FIELD_STYLE_DEFAULTS.bg_color)!;
  const alpha = clampAlpha(typeof s.bg_alpha === "number" ? s.bg_alpha : FIELD_STYLE_DEFAULTS.bg_alpha);
  const pad = clampInt(s.padding_y ?? FIELD_STYLE_DEFAULTS.padding_y, 1, 8, FIELD_STYLE_DEFAULTS.padding_y);
  const pct = `${widthColsToPercent(s.width_cols)}%` as `${number}%`;
  const out: RNFieldStyle = {
    backgroundColor: `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`,
    color: HEX6.test(s.text_color || "") ? (s.text_color as string) : FIELD_STYLE_DEFAULTS.text_color,
    borderColor: HEX6.test(s.border_color || "") ? (s.border_color as string) : FIELD_STYLE_DEFAULTS.border_color,
    paddingVertical: pad * PADDING_Y_MULTIPLIER_PX,
  };
  if (opts.layout === "row") {
    out.flexBasis = pct;
    out.maxWidth = pct;
  } else {
    out.width = pct;
  }
  return out;
}

export default styleToRNStyle;
