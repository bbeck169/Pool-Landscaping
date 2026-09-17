/**
 * colorContrast.ts — unit tests.
 *
 * 5 cases: pure white, near-white, mid-gray boundary, primary blue, pure black.
 */
import {
  MIN_CONTRAST_VS_WHITE,
  relativeLuminance,
  contrastRatioVsWhite,
  validateColorHexForPin,
} from "@/src/lib/colorContrast";

describe("colorContrast", () => {
  it("MIN_CONTRAST_VS_WHITE equals 3.0 (matches server)", () => {
    expect(MIN_CONTRAST_VS_WHITE).toBe(3.0);
  });

  it("pure white (#FFFFFF) has ratio ~1.0 — below threshold", () => {
    const ratio = contrastRatioVsWhite("#FFFFFF");
    expect(ratio).toBeCloseTo(1.0, 1);
    const v = validateColorHexForPin("#FFFFFF");
    expect(v.ok).toBe(false);
    expect(v.reason).toBe("contrast");
  });

  it("near-white (#F5F5F5) is below threshold", () => {
    const ratio = contrastRatioVsWhite("#F5F5F5");
    expect(ratio).toBeLessThan(3.0);
    const v = validateColorHexForPin("#F5F5F5");
    expect(v.ok).toBe(false);
    expect(v.reason).toBe("contrast");
  });

  it("primary blue (#3B82F6) passes threshold", () => {
    const ratio = contrastRatioVsWhite("#3B82F6");
    expect(ratio).toBeGreaterThanOrEqual(3.0);
    const v = validateColorHexForPin("#3B82F6");
    expect(v.ok).toBe(true);
    if (v.ok) {
      expect(v.canonical).toBe("#3B82F6");
      expect(v.ratio).toBeGreaterThanOrEqual(3.0);
    }
  });

  it("pure black (#000000) has very high ratio (~21:1)", () => {
    const ratio = contrastRatioVsWhite("#000000");
    expect(ratio).toBeGreaterThan(20);
    const v = validateColorHexForPin("#000000");
    expect(v.ok).toBe(true);
    if (v.ok) expect(v.canonical).toBe("#000000");
  });

  it("rejects malformed hex strings", () => {
    expect(validateColorHexForPin("xyz").ok).toBe(false);
    expect(validateColorHexForPin("").ok).toBe(false);
    expect(validateColorHexForPin("#GG0000").ok).toBe(false);
  });

  it("canonicalises lowercase to uppercase with # prefix", () => {
    const v = validateColorHexForPin("3b82f6");
    expect(v.ok).toBe(true);
    if (v.ok) expect(v.canonical).toBe("#3B82F6");
  });

  it("relativeLuminance returns NaN for bad input", () => {
    expect(Number.isNaN(relativeLuminance("notahex"))).toBe(true);
  });
});
