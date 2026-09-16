/**
 * Phase D2 · Feb 2026 — deriveIndustryForJob covers all 23 slugs.
 *
 * Mirror of the backend suite `test_derive_industry_all_23.py`.
 * Keeping the case list byte-identical means client + server drift
 * surfaces as a test failure on the deviated side.
 */
import { describe, it, expect } from "vitest";
import {
  deriveIndustryForJob, CANONICAL_INDUSTRIES,
} from "../lib/deriveIndustry";


// Byte-identical to backend `test_derive_industry_all_23.CASES`.
const CASES = {
  pool:              "Weekly pool service",
  landscaping:       "Landscape maintenance",
  hvac:              "HVAC Tune-Up",
  pest_control:      "Pest control quarterly",
  cleaning:          "Deep house cleaning",
  solar:             "Solar Panel Cleaning",
  handyman:          "Handyman fence board fix",
  plumbing:          "Emergency Plumbing Repair",
  electrical:        "Electrical panel upgrade",
  roofing:           "Roof leak inspection",
  painting:          "Interior painting job",
  garage_door:       "Garage door spring replacement",
  appliance_repair:  "Appliance repair — washer",
  locksmith:         "Locksmith rekey house",
  chimney_sweep:     "Chimney sweep annual",
  gutter:            "Gutter clean-out",
  window_cleaning:   "Window Cleaning residential",
  carpet_cleaning:   "Carpet Steam Cleaning",
  pressure_washing:  "Pressure Washing driveway",
  tree_service:      "Tree trimming service",
  snow_removal:      "Snow removal contract",
  fencing:           "Wood fence install",
  irrigation:        "Sprinkler zone repair",
};


describe("Phase D2 · deriveIndustryForJob covers every canonical slug", () => {
  for (const [expected, service_type] of Object.entries(CASES)) {
    it(`"${service_type}" → ${expected}`, () => {
      expect(deriveIndustryForJob({ service_type })).toBe(expected);
    });
  }

  it("CASES covers every entry in CANONICAL_INDUSTRIES", () => {
    // Future addition to CANONICAL_INDUSTRIES without a matching
    // positive case would silently ship an unproven industry.
    const covered = new Set(Object.keys(CASES));
    const missing = CANONICAL_INDUSTRIES.filter((s) => !covered.has(s));
    expect(missing).toEqual([]);
    const extras = [...covered].filter(
      (s) => !CANONICAL_INDUSTRIES.includes(s),
    );
    expect(extras).toEqual([]);
  });

  it("CANONICAL_INDUSTRIES is frozen", () => {
    expect(Object.isFrozen(CANONICAL_INDUSTRIES)).toBe(true);
  });

  it("CANONICAL_INDUSTRIES has exactly 23 entries", () => {
    expect(CANONICAL_INDUSTRIES.length).toBe(23);
  });

  it("explicit job.industry override still wins", () => {
    expect(deriveIndustryForJob({
      industry: "roofing", service_type: "Window Cleaning",
    })).toBe("roofing");
  });

  it("legacy job.checklist_industry override still wins", () => {
    expect(deriveIndustryForJob({
      checklist_industry: "plumbing", service_type: "Solar Panel Cleaning",
    })).toBe("plumbing");
  });

  it("tenant primary industry backfill covers Phase D1 slugs", () => {
    expect(deriveIndustryForJob({}, { industries: ["locksmith"] })).toBe("locksmith");
    expect(deriveIndustryForJob({}, { industry: "irrigation" })).toBe("irrigation");
    // Legacy "pools" plural alias still normalises.
    expect(deriveIndustryForJob({}, { industry: "pools" })).toBe("pool");
  });

  it("empty job + no tenant → pool fallback (byte-identical to MI1)", () => {
    expect(deriveIndustryForJob({}, null)).toBe("pool");
    expect(deriveIndustryForJob(null, null)).toBe("pool");
  });
});
