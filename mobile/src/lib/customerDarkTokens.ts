/**
 * Phase 25b · Shared dark-navy chassis tokens (web Phase 23 / 27 hexes,
 * verbatim). Values + KPI_GLOW are byte-identical to the Phase 25
 * constants in ``app/portal/home.tsx`` (left in place there — Phase 25
 * portal home is a PRESERVE surface).
 */
export const DARK_BG = "#03002e";
export const DARK_BORDER = "#1E293B";
export const DARK_TILE_RADIUS = 12;
export const DARK_TEXT = "#FFFFFF";
export const DARK_TEXT_MUTED = "rgba(255,255,255,0.7)";
export const DANGER_BG = "#7F1D1D";
export const SUCCESS_BG = "#064E3B";

// Phase 24 glow → static soft white halo on every KPI tile.
export const KPI_GLOW = {
  shadowColor: "#FFFFFF", shadowOpacity: 0.6, shadowRadius: 20,
  shadowOffset: { width: 0, height: 0 }, elevation: 8,
} as const;
