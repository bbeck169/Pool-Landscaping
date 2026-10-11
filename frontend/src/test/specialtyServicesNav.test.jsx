/**
 * Feb-2026 · TOP-NAV-RESTRUCTURE — Specialty Services nested nav.
 *
 * Walked back from the Feb-2026 Pool Service PS-C "top-level
 * Specialty Services group" to its new home as a NESTED submenu
 * inside Operations (second nested row, directly below
 * "AI Operations").  Both tracker rows (Filter Tracker, Salt
 * Cell Tracker) are preserved byte-for-byte with
 * ``nested: "Specialty Services"`` added.
 *
 * This file locks:
 *   1. The former top-level ``specialty_services`` group is GONE.
 *   2. Both tracker entries now live inside the ``operations``
 *      group with ``nested: "Specialty Services"``.
 *   3. The two trackers sit AFTER the "AI Operations" nested
 *      block but BEFORE the Schedule & Dispatch subsection.
 *   4. Row properties (to / label / icon / feature / industry
 *      / aliases) are untouched.
 *   5. NAV_FLAT still surfaces the trackers under the
 *      "Specialty Services" group label (so command-palette
 *      search still groups them under that name even though
 *      they're nested inside Operations now).
 */
import { describe, it, expect } from "vitest";
import { ADMIN_NAV_V2, NAV_FLAT } from "@/nav/adminNav";


describe("TOP-NAV-RESTRUCTURE · Specialty Services nested nav", () => {
  it("the former top-level 'specialty_services' group is retired", () => {
    const group = ADMIN_NAV_V2.find((g) => g.key === "specialty_services");
    expect(group).toBeFalsy();
  });

  it("both trackers now live inside the operations group with " +
     "nested: 'Specialty Services'", () => {
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    expect(ops).toBeTruthy();
    const filter = ops.entries.find((e) => e.to === "/tracking/filter");
    const salt = ops.entries.find((e) => e.to === "/tracking/salt-cell");
    expect(filter).toBeTruthy();
    expect(salt).toBeTruthy();
    expect(filter.nested).toBe("Specialty Services");
    expect(salt.nested).toBe("Specialty Services");
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

  it("the nested 'Specialty Services' block sits AFTER the " +
     "nested 'AI Operations' block but BEFORE the Schedule & " +
     "Dispatch subsection", () => {
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const idx = (pred) => ops.entries.findIndex(pred);
    const lastAiOps = (() => {
      let last = -1;
      ops.entries.forEach((e, i) => {
        if (e.nested === "AI Operations") last = i;
      });
      return last;
    })();
    const firstSpecialty = idx((e) => e.nested === "Specialty Services");
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
