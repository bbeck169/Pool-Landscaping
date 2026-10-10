/**
 * Phase 32 · Customer profile two-tone — light-side tokens.
 *
 * White page + light card wrappers under the dark navy tiles (KPI grid,
 * Quick Actions, action row, nav bar keep customerDarkTokens). Every
 * value aliases an existing theme token — no new raw hex.
 *
 * Kept in a sibling file (not customerDarkTokens.ts) because
 * customerDarkTokens is imported by the shared Header (widgets.tsx) and
 * must stay free of a theme import for tests that partially mock it.
 */
import { colors } from "@/src/theme";
import { DARK_TILE_RADIUS } from "@/src/lib/customerDarkTokens";

export const LIGHT_PAGE_BG = colors.surface;          // #FFFFFF
export const LIGHT_CARD_BG = colors.surface;          // #FFFFFF
export const LIGHT_CARD_BORDER = colors.border;       // #E4E4E7
export const LIGHT_TEXT = colors.onSurface;           // #09090B
export const LIGHT_TEXT_MUTED = colors.onSurfaceSecondary; // #52525B
export const LIGHT_CARD_RADIUS = DARK_TILE_RADIUS;    // 12
