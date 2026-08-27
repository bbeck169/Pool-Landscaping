/**
 * Feb 2026 · Color pass — token existence + shape.
 *
 * Locks the additive contract: the new ``pool`` / ``landscape``
 * / ``accent`` / ``status`` families exist and preserve the
 * expected shape, AND the legacy ``brand*`` keys are still
 * present (backwards-compat).
 */
import { describe, it, expect } from "vitest";
import { colors } from "@/theme";


const HEX_RE = /^#[0-9A-Fa-f]{6}$/;


describe("theme.colors · Feb-2026 additive color tokens", () => {
  it("preserves the legacy brand + status keys (no rename regression)", () => {
    expect(colors.brand).toBe("#0284C7");
    expect(colors.brandPrimary).toBe("#0284C7");
    expect(colors.brandSecondary).toBe("#16A34A");
    expect(colors.brandTertiary).toBe("#E0F2FE");
    expect(colors.error).toBe("#DC2626");
    expect(colors.surface).toBe("#FFFFFF");
  });

  it("exposes the pool[] family with 6 canonical shades", () => {
    expect(colors.pool).toBeDefined();
    for (const s of [50, 100, 300, 500, 600, 700]) {
      expect(HEX_RE.test(colors.pool[s])).toBe(true);
    }
    // Product-spec anchors.
    expect(colors.pool[500]).toBe("#06B6D4");
    expect(colors.pool[700]).toBe("#0E7490");
  });

  it("exposes the landscape[] family with 6 canonical shades", () => {
    expect(colors.landscape).toBeDefined();
    for (const s of [50, 100, 300, 500, 600, 700]) {
      expect(HEX_RE.test(colors.landscape[s])).toBe(true);
    }
    expect(colors.landscape[500]).toBe("#22C55E");
    expect(colors.landscape[700]).toBe("#15803D");
  });

  it("exposes the accent.{violet,amber,rose,emerald,sky} families", () => {
    expect(colors.accent).toBeDefined();
    for (const family of ["violet", "amber", "rose", "emerald", "sky"]) {
      expect(colors.accent[family]).toBeDefined();
      for (const s of [50, 100, 500, 600, 700]) {
        expect(HEX_RE.test(colors.accent[family][s])).toBe(true);
      }
    }
    // Product-spec anchors.
    expect(colors.accent.violet[500]).toBe("#8B5CF6");
    expect(colors.accent.amber[500]).toBe("#F59E0B");
    expect(colors.accent.rose[500]).toBe("#F43F5E");
    expect(colors.accent.emerald[500]).toBe("#10B981");
    expect(colors.accent.sky[500]).toBe("#0EA5E9");
  });

  it("exposes semantic status tokens keyed to the correct hues", () => {
    expect(colors.status).toBeDefined();
    // ``scheduled`` == pool.500 primary.
    expect(colors.status.scheduled.primary).toBe(colors.pool[500]);
    // ``completed`` == landscape.500 primary.
    expect(colors.status.completed.primary).toBe(colors.landscape[500]);
    // ``inProgress`` == amber.500.
    expect(colors.status.inProgress.primary).toBe(colors.accent.amber[500]);
    // ``overdue`` == rose.500.
    expect(colors.status.overdue.primary).toBe(colors.accent.rose[500]);
    // ``paid`` == emerald.500.
    expect(colors.status.paid.primary).toBe(colors.accent.emerald[500]);
  });
});
