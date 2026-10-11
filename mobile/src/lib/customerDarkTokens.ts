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

// Phase 40 · web Phase 38 (4a675b669) visual grouping — tile-level palette
// (contrast is text-on-tile, so it holds on the Phase 32 white page).
export const CD_FINANCIAL_NEUTRAL_BG = "#115E59";    // teal-800 — KPI neutral tile bg
export const CD_FINANCIAL_NEUTRAL_LABEL = "#CBD5E1"; // slate-300 — KPI label on teal
export const CD_ACTION_BTN_BG = "#334155";           // slate-700 steel — Edit / View-as
export const CD_ACTION_BTN_BORDER = "#64748B";       // slate-500
export const CD_CALL_BTN_BG = "#059669";             // emerald-600 — web ClickToCallButton
export const CD_NAV_TILE_BG = "#0F172A";             // slate-900 — Quick Action tile bg
export const CD_NAV_TILE_ACTIVE_BG = "#0a0940";      // web active QA tile bg
export const CD_ICON_ACCENT_TEAL = "#2DD4BF";        // i % 3 === 0
export const CD_ICON_ACCENT_INDIGO = "#818CF8";      // i % 3 === 1
export const CD_ICON_ACCENT_SLATE = "#94A3B8";       // i % 3 === 2
export const CD_ICON_ACCENTS = [CD_ICON_ACCENT_TEAL, CD_ICON_ACCENT_INDIGO, CD_ICON_ACCENT_SLATE] as const;
export const CD_ACTIVE_TILE_BORDER = "#4F46E5";      // indigo-600 — web Phase 27 active QA lock
