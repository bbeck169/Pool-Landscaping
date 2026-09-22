/**
 * K60 · Feb-2026 — Chemistry-label expander assertions (mobile).
 *
 * Guards ``mobile/src/lib/expandChemistryLabel.ts::expandChemistryLabel``
 * against regressions.  Covers the current user-adjudicated mapping
 * (post Phase P17.2 · Feb-2026 · display-label unification):
 *
 *   FC   → Chlorine        (P17.2 — was ``Free Chlorine`` under P17)
 *   TC   → Total Chlorine  (restored from CHEM1 removal so legacy
 *                            templates that still ship ``TC`` expand)
 *   pH   → pH   (identity; no expansion required)
 *   TA   → Alkalinity      (P17.2 — was ``Total Alkalinity`` under P17)
 *   CYA  → Cyanuric Acid
 *   CH   → Calcium Hardness
 *   Salt → Salt (identity)
 *   TDS  → Total Dissolved Solids
 *   PO4  → Phosphates
 *
 * ``CC`` (combined_chlorine short-form) stays REMOVED from the map —
 * Phase CHEM1 retired the reading and product spec drops it from
 * the customer view.
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
  // Phase P17.2 · Feb-2026 — unified display labels.
  const cases: Array<[string, string]> = [
    ["FC", "Chlorine"],
    ["TC", "Total Chlorine"],
    ["pH", "pH"],
    ["TA", "Alkalinity"],
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
    // Phase CHEM1 · Feb-2026 — combined_chlorine dropped from the
    // map; ``CC`` short-form is no longer expanded and passes
    // through verbatim so a tenant literally sending "CC" still
    // renders as "CC" (not the retired "Combined Chlorine").
    expect(expandChemistryLabel("CC")).toBe("CC");
  });

  it("passes through the already-expanded name unchanged (idempotent)", () => {
    // Phase P17.2 · Feb-2026 — unified customer-facing labels
    // stay idempotent under a second pass through the expander.
    expect(expandChemistryLabel("Chlorine")).toBe("Chlorine");
    expect(expandChemistryLabel("Alkalinity")).toBe("Alkalinity");
    // Legacy P17-era long forms are no longer emitted by the map,
    // but a stored template still carrying them passes through
    // verbatim (they're not map KEYS, they're passthrough strings).
    expect(expandChemistryLabel("Free Chlorine")).toBe("Free Chlorine");
    expect(expandChemistryLabel("Total Alkalinity")).toBe("Total Alkalinity");
  });
});

describe("K60 · expandChemistryLabel — whitespace + edge inputs", () => {
  it("trims leading/trailing whitespace before lookup", () => {
    // Phase P17.2 · Feb-2026 — unified customer-facing labels.
    expect(expandChemistryLabel(" FC ")).toBe("Chlorine");
    expect(expandChemistryLabel("\tTA\n")).toBe("Alkalinity");
  });

  it("returns empty string for null / undefined / empty", () => {
    expect(expandChemistryLabel(null)).toBe("");
    expect(expandChemistryLabel(undefined)).toBe("");
    expect(expandChemistryLabel("")).toBe("");
    expect(expandChemistryLabel("   ")).toBe("");
  });
});
