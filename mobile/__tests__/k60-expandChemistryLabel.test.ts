/**
 * K60 · Feb-2026 — Chemistry-label expander assertions (mobile).
 *
 * Guards ``mobile/src/lib/expandChemistryLabel.ts::expandChemistryLabel``
 * against regressions.  Covers the full user-adjudicated mapping:
 *
 *   FC   → Free Chlorine
 *   TC   → Total Chlorine
 *   pH   → pH   (identity; no expansion required)
 *   TA   → Total Alkalinity
 *   CYA  → Cyanuric Acid
 *   CH   → Calcium Hardness
 *   Salt → Salt (identity)
 *   TDS  → Total Dissolved Solids
 *   PO4  → Phosphates
 *
 * Also asserts:
 *   - Tenant-customised labels pass through UNCHANGED.
 *   - Input is case-insensitive + whitespace-trimmed.
 *   - null / undefined / empty inputs return the empty string.
 *
 * See /app/memory/PHASE_K60_CHEMISTRY_LABELS.md.
 */
import { expandChemistryLabel } from "@/src/lib/expandChemistryLabel";

describe("K60 · expandChemistryLabel — full mapping (case-insensitive)", () => {
  const cases: Array<[string, string]> = [
    ["FC", "Free Chlorine"],
    ["TC", "Total Chlorine"],
    ["pH", "pH"],
    ["TA", "Total Alkalinity"],
    ["CYA", "Cyanuric Acid"],
    ["CH", "Calcium Hardness"],
    ["Salt", "Salt"],
    ["TDS", "Total Dissolved Solids"],
    ["PO4", "Phosphates"],
  ];
  for (const [input, expected] of cases) {
    it(`${input} → ${expected}`, () => {
      expect(expandChemistryLabel(input)).toBe(expected);
    });
    it(`${input.toLowerCase()} → ${expected} (case-insensitive)`, () => {
      expect(expandChemistryLabel(input.toLowerCase())).toBe(expected);
    });
    it(`${input.toUpperCase()} → ${expected} (uppercase)`, () => {
      expect(expandChemistryLabel(input.toUpperCase())).toBe(expected);
    });
  }
});

describe("K60 · expandChemistryLabel — tenant customisations", () => {
  it("passes through a fully custom label unchanged", () => {
    expect(expandChemistryLabel("Free Cl (deep end)")).toBe("Free Cl (deep end)");
  });

  it("passes through an unknown short-form unchanged", () => {
    expect(expandChemistryLabel("ORP")).toBe("ORP");
    expect(expandChemistryLabel("Copper")).toBe("Copper");
  });

  it("passes through the already-expanded name unchanged (idempotent)", () => {
    expect(expandChemistryLabel("Free Chlorine")).toBe("Free Chlorine");
    expect(expandChemistryLabel("Total Alkalinity")).toBe("Total Alkalinity");
  });
});

describe("K60 · expandChemistryLabel — whitespace + edge inputs", () => {
  it("trims leading/trailing whitespace before lookup", () => {
    expect(expandChemistryLabel(" FC ")).toBe("Free Chlorine");
    expect(expandChemistryLabel("\tTA\n")).toBe("Total Alkalinity");
  });

  it("returns empty string for null / undefined / empty", () => {
    expect(expandChemistryLabel(null)).toBe("");
    expect(expandChemistryLabel(undefined)).toBe("");
    expect(expandChemistryLabel("")).toBe("");
    expect(expandChemistryLabel("   ")).toBe("");
  });
});
