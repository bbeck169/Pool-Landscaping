/**
 * TD-64 Phase 2b · shouldShowTimeClock helper + web drift guard.
 */
import { LANDSCAPE_DEPTS, shouldShowTimeClock, isPoolTechWithoutTimeClock } from "@/src/lib/timeClockVisibility";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const web = require("../../frontend/src/lib/timeClockVisibility.js");

describe("shouldShowTimeClock", () => {
  it.each<[string, any, boolean]>([
    ["null", null, false],
    ["undefined", undefined, false],
    ["pool", { department: "pool" }, false],
    ["pool_tech", { department: "pool_tech" }, false],
    ["landscaping", { department: "landscaping" }, true],
    ["effective_department landscape_tech", { effective_department: "landscape_tech" }, true],
    ["effective_department wins over department", { effective_department: "pool_tech", department: "landscaping" }, false],
    ["BE boolean true wins (department pool)", { show_time_clock: true, department: "pool" }, true],
    ["BE boolean false wins (department landscaping)", { show_time_clock: false, department: "landscaping" }, false],
    ["case + whitespace ' LANDSCAPER '", { department: " LANDSCAPER " }, true],
    ["both", { department: "both" }, true],
    ["non-boolean show_time_clock ignored", { show_time_clock: "true", department: "pool" }, false],
    ["no designation", { department: null }, false],
  ])("%s → %s", (_n, user, expected) => {
    expect(shouldShowTimeClock(user)).toBe(expected);
  });

  it("route-guard predicate: only technicians without the designation are bounced", () => {
    expect(isPoolTechWithoutTimeClock({ role: "technician", show_time_clock: false })).toBe(true);
    expect(isPoolTechWithoutTimeClock({ role: "technician", department: "pool_tech" })).toBe(true);
    expect(isPoolTechWithoutTimeClock({ role: "technician", show_time_clock: true })).toBe(false);
    expect(isPoolTechWithoutTimeClock({ role: "admin", show_time_clock: false })).toBe(false);
    expect(isPoolTechWithoutTimeClock({ role: "super_admin" })).toBe(false);
    expect(isPoolTechWithoutTimeClock({ role: "manager", show_time_clock: false })).toBe(false);
  });
});

describe("drift guard — mobile ↔ frontend/src/lib/timeClockVisibility.js", () => {
  it("LANDSCAPE_DEPTS sets are identical", () => {
    expect([...LANDSCAPE_DEPTS].sort()).toEqual([...web.LANDSCAPE_DEPTS].sort());
  });

  it("helpers agree on a persona matrix", () => {
    const personas = [
      null, {}, { department: "pool" }, { department: "landscaping" }, { department: " Both " },
      { effective_department: "landscape_tech" }, { effective_department: null, department: "landscaper" },
      { show_time_clock: true }, { show_time_clock: false, department: "landscaping" },
      { role: "admin" }, { role: "technician", department: "north" },
    ];
    for (const p of personas) expect(shouldShowTimeClock(p as any)).toBe(web.shouldShowTimeClock(p));
  });
});
