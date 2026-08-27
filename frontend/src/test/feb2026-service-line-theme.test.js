/**
 * Feb 2026 · Color pass — service-line resolver + KPI tone
 * rotation + WCAG-safe text picker.
 */
import { describe, it, expect } from "vitest";
import { colors } from "@/theme";
import {
  getServiceLineTheme,
  getAccentTone,
  getReadableTextColor,
  getContrastRatio,
  KPI_TONE_ROTATION,
} from "@/utils/serviceLineTheme";


describe("getServiceLineTheme", () => {
  it("pool → cyan family with primary + soft + strong shades", () => {
    const t = getServiceLineTheme("pool");
    expect(t.key).toBe("pool");
    expect(t.primary).toBe(colors.pool[500]);
    expect(t.soft).toBe(colors.pool[100]);
    expect(t.strong).toBe(colors.pool[700]);
    expect(t.label).toBe("Pool");
    // ``strong`` is the shade we ship on CTAs / labels — it must
    // pass AA against white text. ``primary`` (500) is a lighter
    // accent used for icons + borders and doesn't need the
    // 4.5:1 CTA-body threshold on its own.
    expect(getContrastRatio(t.strong, "#FFFFFF"))
      .toBeGreaterThanOrEqual(4.5);
  });

  it("landscape → green family with primary + soft + strong shades", () => {
    const t = getServiceLineTheme("landscape");
    expect(t.key).toBe("landscape");
    expect(t.primary).toBe(colors.landscape[500]);
    expect(t.soft).toBe(colors.landscape[100]);
    expect(t.strong).toBe(colors.landscape[700]);
    expect(t.label).toBe("Landscape");
  });

  it("landscaping (alias) → landscape family", () => {
    // Tolerate the plural spelling common in raw customer-facing
    // labels — resolver should still land on the green palette.
    expect(getServiceLineTheme("Landscaping").key).toBe("landscape");
    expect(getServiceLineTheme("LANDSCAPING").primary)
      .toBe(colors.landscape[500]);
  });

  it("both → fallback to brand palette", () => {
    const t = getServiceLineTheme("both");
    expect(t.key).toBe("both");
    expect(t.primary).toBe(colors.brand);
    expect(t.soft).toBe(colors.brandTertiary);
    expect(t.label).toBe("Pool + Landscape");
  });

  it("unknown / null / empty → falls back to brand palette", () => {
    for (const bad of [null, undefined, "", "  ", "bogus"]) {
      expect(getServiceLineTheme(bad).primary).toBe(colors.brand);
    }
  });
});


describe("KPI_TONE_ROTATION", () => {
  it("contains exactly the five accent tones the KPI grid rotates", () => {
    expect(KPI_TONE_ROTATION).toEqual([
      "violet", "amber", "sky", "emerald", "rose",
    ]);
    // Every tone in the rotation must resolve to a real accent
    // family — protects against typos in the rotation array.
    for (const t of KPI_TONE_ROTATION) {
      expect(getAccentTone(t)).toBe(colors.accent[t]);
    }
  });

  it("getAccentTone falls back to sky on unknown input", () => {
    expect(getAccentTone("nope")).toBe(colors.accent.sky);
    expect(getAccentTone(null)).toBe(colors.accent.sky);
  });
});


describe("getReadableTextColor + getContrastRatio (WCAG AA)", () => {
  it("picker returns white for shades that pass ≥4.5:1 against white", () => {
    // ONLY the 700-tier + darker/deeper 600s pass the strict
    // WCAG AA 4.5:1 body-text threshold with white. Medium 600
    // shades (pool.600, landscape.600, sky.600) fall in the
    // 3.3-4.1 range — they still pass AA LARGE-text (3:1) which
    // is why the Button component ships them as CTA fills, but
    // the ``getReadableTextColor`` picker uses strict 4.5:1 so
    // it correctly returns DARK on those (see the next test).
    for (const bg of [
      colors.pool[700],
      colors.landscape[700],
      colors.accent.violet[600], colors.accent.violet[700],
      colors.accent.amber[700],
      colors.accent.rose[600], colors.accent.rose[700],
      colors.accent.emerald[700],
      colors.accent.sky[700],
    ]) {
      expect(getReadableTextColor(bg)).toBe("#FFFFFF");
      expect(getContrastRatio(bg, "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("picker returns dark on medium 600 shades (below strict-4.5:1 vs white)", () => {
    // These SHIP as CTA fills with white text (button text
    // counts as 18pt+ / large-text AA at 3:1) but the picker
    // in strict body-text mode correctly flags them.
    for (const bg of [
      colors.pool[600], colors.landscape[600], colors.accent.sky[600],
    ]) {
      expect(getReadableTextColor(bg)).toBe(colors.onSurface);
      // Still passes AA large text (3:1) with white — that's
      // why our CTA buttons legitimately use white on these.
      expect(getContrastRatio(bg, "#FFFFFF")).toBeGreaterThanOrEqual(3);
    }
  });

  it("returns dark onSurface for light 50/100 shades", () => {
    for (const bg of [
      colors.pool[50], colors.pool[100],
      colors.landscape[50], colors.landscape[100],
      colors.accent.violet[50], colors.accent.amber[50],
      colors.accent.rose[100], colors.accent.emerald[50],
    ]) {
      expect(getReadableTextColor(bg)).toBe(colors.onSurface);
      expect(getContrastRatio(bg, colors.onSurface))
        .toBeGreaterThanOrEqual(4.5);
    }
  });

  it("known-good spot-checks match published WCAG contrast ratios", () => {
    // Anchors — these are canonical values that changed hues will
    // trip on. Values verified against WebAIM's contrast checker.
    expect(getContrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 0);
    expect(getContrastRatio("#0284C7", "#FFFFFF")).toBeGreaterThan(4);
    expect(getContrastRatio("#F59E0B", "#000000")).toBeGreaterThan(4);
  });
});
