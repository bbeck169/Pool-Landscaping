/**
 * Feb-2026 · Live-Tech-Map · Phase 1 — 12-color palette (WEB mirror).
 *
 * MUST stay in lockstep with the backend source of truth at
 * ``/app/backend/constants/tech_colors.py``. When editing this
 * palette, edit that file in the same PR.
 *
 * Palette: Tailwind 500-tier, user-approved Feb-2026 (Q2 of the
 * Live-Tech-Map audit). Order matters — deterministic hash
 * assignment reads ``palette[hash % 12]``, so re-ordering would
 * re-key every existing tech that was auto-filled by the null-fill
 * migration.
 */

export const TECH_COLOR_PALETTE = [
  { name: "blue",    hex: "#3B82F6" },
  { name: "red",     hex: "#EF4444" },
  { name: "emerald", hex: "#10B981" },
  { name: "amber",   hex: "#F59E0B" },
  { name: "violet",  hex: "#8B5CF6" },
  { name: "pink",    hex: "#EC4899" },
  { name: "teal",    hex: "#14B8A6" },
  { name: "orange",  hex: "#F97316" },
  { name: "indigo",  hex: "#6366F1" },
  { name: "lime",    hex: "#84CC16" },
  { name: "cyan",    hex: "#06B6D4" },
  { name: "fuchsia", hex: "#D946EF" },
];

export const PALETTE_HEXES = TECH_COLOR_PALETTE.map((p) => p.hex);

const _PALETTE_HEX_SET = new Set(PALETTE_HEXES.map((h) => h.toUpperCase()));

/**
 * Return true when ``hex`` is one of the 12 approved palette colors.
 * Case-insensitive on the hex digits.
 */
export function isPaletteColor(hex) {
  if (!hex || typeof hex !== "string") return false;
  return _PALETTE_HEX_SET.has(hex.toUpperCase());
}
