/**
 * Phase F8 · Feb-2026 — Frontend service-type classifier tests.
 *
 * Unit tests on ``@/lib/serviceTypeGroups::classifyServiceType`` to
 * lock the widened vocab in place. Pure function → no DOM, no api mocks.
 */
import { describe, it, expect } from "vitest";
import {
  classifyServiceType,
  POOL_KEYWORDS,
  LANDSCAPE_KEYWORDS,
} from "../lib/serviceTypeGroups";

describe("F8 · classifyServiceType widened vocab", () => {
  // Pool group — includes the newly-added tokens.
  it.each([
    "Pool Cleaning",
    "Weekly Pool",
    "Chemical Balance",   // NEW
    "Filter Clean",       // NEW
    "Shock Treatment",    // NEW
    "Backwash",           // NEW
    "Algae Bloom Service",// NEW
  ])('classifies "%s" as pool', (svc) => {
    expect(classifyServiceType(svc)).toBe("pool");
  });

  // Landscape group — includes the newly-added tokens.
  it.each([
    "Landscaping",
    "Landscape Design",
    "Lawn Mow",          // NEW
    "Yard Cleanup",      // NEW
    "Tree Removal",      // NEW
    "Hedge Trimming",    // NEW
    "Irrigation Repair", // NEW
  ])('classifies "%s" as landscape', (svc) => {
    expect(classifyServiceType(svc)).toBe("landscape");
  });

  // Neither group — must fall through to "other" so the pill hides.
  it.each(["Inspection", "Repair", "Installation", "", null, undefined, "   "])(
    'classifies "%s" as other',
    (svc) => {
      expect(classifyServiceType(svc)).toBe("other");
    },
  );

  it("landscape wins when both groups would match (determinism)", () => {
    // "Yard Cleanup" — "yard" (landscape) + "clean" (pool). Real-
    // world semantic anchor: this is a landscape job. Landscape
    // checked first.
    expect(classifyServiceType("Yard Cleanup")).toBe("landscape");
    // "Landscape Cleanup" — landscap + clean → landscape.
    expect(classifyServiceType("Landscape Cleanup")).toBe("landscape");
    // Contrived — "Clean the yard pool" hits landscape first.
    expect(classifyServiceType("Clean the yard pool")).toBe("landscape");
  });

  it("exports the documented vocab lists", () => {
    // Guardrail — if these change, mirror the backend
    // customers.py::_POOL_KEYWORDS / _LANDSCAPE_KEYWORDS in lockstep.
    expect(new Set(POOL_KEYWORDS)).toEqual(new Set([
      "pool", "chemical", "filter", "clean", "shock", "backwash", "algae",
    ]));
    expect(new Set(LANDSCAPE_KEYWORDS)).toEqual(new Set([
      "landscap", "lawn", "yard", "tree", "trim", "mow", "hedge",
      "irrigation",
    ]));
  });
});
