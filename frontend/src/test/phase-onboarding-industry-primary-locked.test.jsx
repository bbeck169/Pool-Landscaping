/**
 * SP3 · Feb-2026 — Onboarding step 4 · primary industry lock.
 *
 * Regression guard: verifies the D1 canonical set is 23 industries
 * and that ``"pool"`` (singular) is canonical while ``"pools"``
 * (legacy plural) is NOT in the canonical set — so a naive
 * uniqueness check on the frontend won't reintroduce the drift.
 */
import { describe, it, expect } from "vitest";
import { CANONICAL_INDUSTRIES } from "../lib/deriveIndustry";

describe("SP3 · industry canonical set (pool singular, 23 slugs)", () => {
  it("CANONICAL_INDUSTRIES has exactly 23 entries", () => {
    expect(CANONICAL_INDUSTRIES).toHaveLength(23);
  });

  it("uses canonical singular 'pool' not plural 'pools'", () => {
    expect(CANONICAL_INDUSTRIES).toContain("pool");
    expect(CANONICAL_INDUSTRIES).not.toContain("pools");
  });

  it("frozen (Object.freeze prevents accidental mutation)", () => {
    expect(Object.isFrozen(CANONICAL_INDUSTRIES)).toBe(true);
  });

  it("contains the D1 additions absent from the drifted SP1 set", () => {
    // Slugs the drifted SP1 signup.py set was MISSING vs D1 canonical.
    for (const s of ["garage_door", "tree_service", "snow_removal",
                        "fencing", "irrigation"]) {
      expect(CANONICAL_INDUSTRIES, `missing ${s}`).toContain(s);
    }
  });

  it("does NOT contain the drifted non-canonical slugs the SP1 set added", () => {
    // Slugs the SP1 signup.py set added that are NOT D1 canonical.
    for (const s of ["carpentry", "flooring", "gutter_cleaning",
                        "moving", "junk_removal", "general_services"]) {
      expect(CANONICAL_INDUSTRIES, `unexpected ${s}`).not.toContain(s);
    }
  });
});
