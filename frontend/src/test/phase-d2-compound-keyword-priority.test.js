/**
 * Phase D2 · Feb 2026 — compound-keyword priority regression pins.
 *
 * The derivation keyword scan MUST match compound multi-word
 * keywords before their component words. A future refactor that
 * accidentally sorts the KEYWORD_MAP alphabetically (or drops the
 * "narrowest first" ordering rule) would misroute inbound-industry
 * lookups en masse — these tests catch that drift.
 */
import { describe, it, expect } from "vitest";
import { deriveIndustryForJob } from "../lib/deriveIndustry";


const COMPOUND_CASES = [
  // Compound-cleaning must beat generic ``cleaning``.
  ["Window Cleaning",              "window_cleaning"],
  ["Carpet Steam Cleaning",        "carpet_cleaning"],
  ["Pressure Washing driveway",    "pressure_washing"],
  // Existing MI1 guarantees preserved.
  ["Solar Panel Cleaning",         "solar"],
  ["Pool Chemical Balance",        "pool"],
  // Phase D1 compound-first slugs.
  ["Garage Door Spring Replacement", "garage_door"],
  ["Snow Removal Route",            "snow_removal"],
  ["Tree Trimming",                 "tree_service"],
  ["Chimney Sweep annual",          "chimney_sweep"],
];


describe("Phase D2 · compound keywords win over component keywords", () => {
  for (const [service_type, expected] of COMPOUND_CASES) {
    it(`"${service_type}" → ${expected}`, () => {
      expect(deriveIndustryForJob({ service_type })).toBe(expected);
    });
  }

  it("Power wash aliases the pressure-washing compound", () => {
    expect(deriveIndustryForJob({ service_type: "Power wash siding" }))
      .toBe("pressure_washing");
  });

  it("Rekey aliases locksmith", () => {
    expect(deriveIndustryForJob({ service_type: "Emergency rekey visit" }))
      .toBe("locksmith");
  });

  it("Sprinkler aliases irrigation", () => {
    expect(deriveIndustryForJob({ service_type: "Sprinkler head repair" }))
      .toBe("irrigation");
  });

  it("Cleaning-only string still resolves to cleaning", () => {
    // Regression: making compound keywords narrow must NOT starve
    // the plain ``clean`` slug of matches.
    expect(deriveIndustryForJob({ service_type: "Deep house cleaning" }))
      .toBe("cleaning");
  });
});
