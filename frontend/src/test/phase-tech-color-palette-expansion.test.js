/**
 * Feb-2026 · Ticket B · Palette expansion regression pin.
 */
import { describe, it, expect } from "vitest";

import {
  TECH_COLOR_PALETTE,
  PALETTE_HEXES,
  isPaletteColor,
} from "../lib/techColorsPalette";


// Pre-expansion 12 colors, pinned as an inline literal. Any drift
// in ordering trips this test instead of silently re-keying every
// tenant's deterministic tech color assignment.
const _ORIGINAL_TWELVE = [
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

const _APPENDED_TWELVE = [
  "#B45309", "#0F766E", "#A21CAF", "#3F6212",
  "#6D28D9", "#B91C1C", "#0369A1", "#4D7C0F",
  "#9F1239", "#1E3A8A", "#78350F", "#365314",
];


describe("techColorsPalette · Ticket B expansion", () => {
  it("has at least 24 entries", () => {
    expect(TECH_COLOR_PALETTE.length).toBeGreaterThanOrEqual(24);
    expect(PALETTE_HEXES.length).toBe(TECH_COLOR_PALETTE.length);
  });

  it("preserves first-12 order + names + hexes (no re-keying)", () => {
    _ORIGINAL_TWELVE.forEach((expected, idx) => {
      expect(TECH_COLOR_PALETTE[idx]).toEqual(expected);
    });
  });

  it("appended 12 land in the correct index range", () => {
    _APPENDED_TWELVE.forEach((hex, idx) => {
      const entry = TECH_COLOR_PALETTE[12 + idx];
      expect(entry.hex).toBe(hex);
    });
  });

  it("every appended hex validates as a palette color", () => {
    _APPENDED_TWELVE.forEach((hex) => {
      expect(isPaletteColor(hex)).toBe(true);
      // Case-insensitive match.
      expect(isPaletteColor(hex.toLowerCase())).toBe(true);
    });
  });

  it("has no duplicate hex codes across the full palette", () => {
    const upper = PALETTE_HEXES.map((h) => h.toUpperCase());
    expect(new Set(upper).size).toBe(upper.length);
  });
});
