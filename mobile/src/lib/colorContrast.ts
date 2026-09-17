/**
 * Feb-2026 · Client-side contrast helper.
 *
 * Mirrors `frontend/src/lib/colorContrast.js`. The mobile app runs
 * the contrast check LOCALLY for instant feedback (disable the
 * Apply button + inline warning) — the server still runs its own
 * check so a hand-crafted API call can't bypass the gate.
 *
 * Threshold: WCAG 2.1 ratio vs pure white strictly BELOW 3.0 is
 * rejected. The "3:1 large UI graphics" bar.
 */

export const MIN_CONTRAST_VS_WHITE = 3.0;

const HEX_RE = /^#?([0-9a-fA-F]{6})$/;

function _parseHex(hex: string): [number, number, number] | null {
  if (typeof hex !== "string") return null;
  const m = HEX_RE.exec(hex.trim());
  if (!m) return null;
  const raw = m[1];
  return [
    parseInt(raw.slice(0, 2), 16),
    parseInt(raw.slice(2, 4), 16),
    parseInt(raw.slice(4, 6), 16),
  ];
}

function _linearize(v255: number): number {
  const c = v255 / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(hex: string): number {
  const rgb = _parseHex(hex);
  if (!rgb) return NaN;
  const [r, g, b] = rgb;
  return 0.2126 * _linearize(r)
       + 0.7152 * _linearize(g)
       + 0.0722 * _linearize(b);
}

export function contrastRatioVsWhite(hex: string): number {
  const l = relativeLuminance(hex);
  if (Number.isNaN(l)) return NaN;
  // White luminance = 1.0; formula: (L1 + 0.05) / (L2 + 0.05)
  return 1.05 / (l + 0.05);
}

export type ValidationResult =
  | { ok: true; canonical: string; ratio: number }
  | { ok: false; reason: "invalid" | "contrast"; ratio?: number };

/**
 * Return `{ ok: true, canonical }` on success, else
 * `{ ok: false, reason: "invalid" | "contrast", ratio? }`.
 */
export function validateColorHexForPin(hex: string): ValidationResult {
  const rgb = _parseHex(hex);
  if (!rgb) return { ok: false, reason: "invalid" };
  const [r, g, b] = rgb;
  const ratio = contrastRatioVsWhite(hex);
  if (ratio < MIN_CONTRAST_VS_WHITE) {
    return { ok: false, reason: "contrast", ratio };
  }
  const hx = (v: number) => v.toString(16).padStart(2, "0").toUpperCase();
  return { ok: true, canonical: `#${hx(r)}${hx(g)}${hx(b)}`, ratio };
}
