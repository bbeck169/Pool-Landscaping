/**
 * Phase M1 — TeardropPin parity tests.
 *
 * Locks the canonical fallback palette v1 (/app/memory/tech_color_palette.md)
 * so a hash-regression or palette-drift fails loud.
 *
 * Test vectors computed from the web reference implementation
 * (Java-style String.hashCode, 12-entry palette, raw input).
 */
import { colorFromId, deriveDarker } from "../src/components/maps/TeardropPin";

/* ── colorFromId parity vectors ────────────────────────────────────── */

describe("colorFromId — canonical palette v1 parity", () => {
  // Empty / null / undefined → palette[0] = #EF4444
  it('returns #EF4444 for empty string', () => {
    expect(colorFromId("")).toBe("#EF4444");
  });

  it('returns #EF4444 for null', () => {
    expect(colorFromId(null)).toBe("#EF4444");
  });

  it('returns #EF4444 for undefined', () => {
    expect(colorFromId(undefined)).toBe("#EF4444");
  });

  // Parity vectors — generated from web reference impl, not fabricated.
  it('returns #3B82F6 (blue-500) for "tech-jenny"', () => {
    expect(colorFromId("tech-jenny")).toBe("#3B82F6");
  });

  it('returns #0EA5E9 (sky-500) for "tech-1"', () => {
    expect(colorFromId("tech-1")).toBe("#0EA5E9");
  });

  it('returns #EF4444 (red-500) for "u-alice"', () => {
    expect(colorFromId("u-alice")).toBe("#EF4444");
  });

  it('returns #8B5CF6 (violet-500) for "tech_alice"', () => {
    expect(colorFromId("tech_alice")).toBe("#8B5CF6");
  });

  // Determinism — same input always same output
  it("is deterministic across repeated calls", () => {
    const a = colorFromId("stable-id-123");
    const b = colorFromId("stable-id-123");
    expect(a).toBe(b);
  });

  // Every return value is in the palette
  it("always returns a value from the 12-entry palette", () => {
    const PALETTE = [
      "#EF4444", "#F97316", "#EAB308", "#22C55E",
      "#10B981", "#06B6D4", "#0EA5E9", "#3B82F6",
      "#6366F1", "#8B5CF6", "#EC4899", "#14B8A6",
    ];
    const ids = ["a", "bb", "ccc", "test-xyz", "663e…fake-mongo-id", "🚀"];
    for (const id of ids) {
      expect(PALETTE).toContain(colorFromId(id));
    }
  });
});

/* ── deriveDarker ──────────────────────────────────────────────────── */

describe("deriveDarker", () => {
  it("darkens #FFFFFF by 25% to #bfbfbf", () => {
    expect(deriveDarker("#FFFFFF", 0.25)).toBe("#bfbfbf");
  });

  it("darkens #000000 to #000000 (floor is 0)", () => {
    expect(deriveDarker("#000000", 0.5)).toBe("#000000");
  });

  it("uses 0.25 as default pct", () => {
    // #FF0000 → r=191, g=0, b=0 → #bf0000
    expect(deriveDarker("#FF0000")).toBe("#bf0000");
  });
});
