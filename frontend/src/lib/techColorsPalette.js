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
  // ─── Feb-2026 · Palette expansion (Ticket B) ──────────────────
  // 12 professional/desaturated colors appended AFTER the original
  // 12 so existing tenants' deterministic ``palette[hash % 12]``
  // assignments stay byte-identical. Order + case MUST match the
  // backend mirror at ``backend/constants/tech_colors.py``.
  { name: "slate_amber",   hex: "#B45309" },
  { name: "deep_teal",     hex: "#0F766E" },
  { name: "royal_magenta", hex: "#A21CAF" },
  { name: "olive",         hex: "#3F6212" },
  { name: "indigo_violet", hex: "#6D28D9" },
  { name: "brick_red",     hex: "#B91C1C" },
  { name: "ocean_blue",    hex: "#0369A1" },
  { name: "forest_green",  hex: "#4D7C0F" },
  { name: "ruby_rose",     hex: "#9F1239" },
  { name: "midnight_blue", hex: "#1E3A8A" },
  { name: "chestnut",      hex: "#78350F" },
  { name: "moss",          hex: "#365314" },
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
