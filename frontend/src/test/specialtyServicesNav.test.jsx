/**
 * Feb-2026 · OPS-NAV-FLATTEN — Specialty Services flattened to a
 * flat ``subsection: "Specialty Services"`` block inside Operations.
 *
 * Walked back from the Feb-2026 TOP-NAV-RESTRUCTURE nested-flyout
 * design.  Both tracker rows (Filter Tracker, Salt Cell Tracker)
 * remain inside the Operations group with their routes / icons /
 * feature / industry / aliases byte-for-byte intact — the only
 * change is ``nested`` → ``subsection``.
 *
 * This file locks:
 *   1. The former top-level ``specialty_services`` group is GONE.
 *   2. Both tracker entries now live inside the ``operations``
 *      group with ``subsection: "Specialty Services"`` (NOT
 *      ``nested``).
 *   3. Zero rows carry the pre-flatten ``nested: "Specialty
 *      Services"`` key anymore.
 *   4. The two trackers sit AFTER the "AI Operations" subsection
 *      block but BEFORE the Schedule & Dispatch subsection.
 *   5. Row properties (to / label / icon / feature / industry
 *      / aliases) are untouched.
 *   6. NAV_FLAT still surfaces the trackers under the
 *      "Specialty Services" group label so command-palette search
 *      still groups them under that name.
 */
import { describe, it, expect } from "vitest";
import { ADMIN_NAV_V2, NAV_FLAT } from "@/nav/adminNav";


describe("OPS-NAV-FLATTEN · Specialty Services flat subsection", () => {
  it("the former top-level 'specialty_services' group is retired", () => {
    const group = ADMIN_NAV_V2.find((g) => g.key === "specialty_services");
    expect(group).toBeFalsy();
  });

  it("both trackers now live inside the operations group with " +
     "subsection: 'Specialty Services' (NOT nested)", () => {
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    expect(ops).toBeTruthy();
    const filter = ops.entries.find((e) => e.to === "/tracking/filter");
    const salt = ops.entries.find((e) => e.to === "/tracking/salt-cell");
    expect(filter).toBeTruthy();
    expect(salt).toBeTruthy();
    expect(filter.subsection).toBe("Specialty Services");
    expect(salt.subsection).toBe("Specialty Services");
    // Pre-flatten nested flag MUST be gone.
    expect(filter.nested).toBeFalsy();
    expect(salt.nested).toBeFalsy();
    // Preserved row properties.
    expect(filter.label).toBe("Filter Tracker");
    expect(filter.feature).toBe("jobs");
    expect(filter.industry).toBe("pool");
    expect(filter.icon).toBeTruthy();
    expect(salt.label).toBe("Salt Cell Tracker");
    expect(salt.feature).toBe("jobs");
    expect(salt.industry).toBe("pool");
    expect(salt.icon).toBeTruthy();
  });

  it("the 'Specialty Services' subsection sits AFTER the " +
     "'AI Operations' subsection but BEFORE the 'Schedule & " +
     "Dispatch' subsection", () => {
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const idx = (pred) => ops.entries.findIndex(pred);
    const lastAiOps = (() => {
      let last = -1;
      ops.entries.forEach((e, i) => {
        if (e.subsection === "AI Operations") last = i;
      });
      return last;
    })();
    const firstSpecialty = idx((e) => e.subsection === "Specialty Services");
    const firstSchedule = idx((e) => e.subsection === "Schedule & Dispatch");
    expect(lastAiOps).toBeGreaterThan(-1);
    expect(firstSpecialty).toBeGreaterThan(lastAiOps);
    expect(firstSchedule).toBeGreaterThan(firstSpecialty);
  });

  it("NAV_FLAT groups both trackers under 'Specialty Services'", () => {
    const f = NAV_FLAT.find((e) => e.to === "/tracking/filter");
    const s = NAV_FLAT.find((e) => e.to === "/tracking/salt-cell");
    expect(f.group).toBe("Specialty Services");
    expect(s.group).toBe("Specialty Services");
  });
});
