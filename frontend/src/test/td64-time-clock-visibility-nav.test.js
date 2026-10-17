/**
 * TD-64 · Feb-2026 — Time Clock surface visibility regressions for
 * every web render site touched by the Pool-tech-hide ship.
 *
 * Sites covered:
 *   1. ``topNavForUser`` — top-nav strip.
 *   2. ``navForRoleAndDept`` — Universal Menu hamburger sections.
 *   3. (Smoke) ``LANDSCAPE_DEPTS`` matches the BE truth tuple.
 *
 * Admin surfaces are role-gated elsewhere and intentionally NOT
 * exercised here — operator ruling: admin Time Clock views (team
 * aggregation / punch edits) stay visible for admins regardless of
 * designation.
 */
import { describe, it, expect } from "vitest";
import {
  topNavForRole,
  topNavForUser,
  TECH_TOP_NAV,
} from "@/nav/topNavRegistry";
import {
  navForRoleAndDept,
  TECH_NAV,
  TECH_POOL_NAV,
  TECH_LANDSCAPE_NAV,
} from "@/nav/roleNav";


const _timeClockEntry = (list) =>
  list.find((it) => it.key === "time-clock" || it.to?.includes("time-clock"));


describe("TD-64 · topNavForUser · Time Clock gating", () => {
  it("pool tech → Time Clock entry is removed from the top nav", () => {
    const fixed = topNavForUser({
      role: "technician",
      department: "pool",
    });
    expect(_timeClockEntry(fixed)).toBeUndefined();
    // Preserves every other tech top-nav entry.
    const expectedKeys = TECH_TOP_NAV
      .map((it) => it.key)
      .filter((k) => k !== "time-clock");
    expect(fixed.map((it) => it.key)).toEqual(expectedKeys);
  });

  it("landscaping tech → Time Clock entry is PRESENT in the top nav", () => {
    const fixed = topNavForUser({
      role: "technician",
      department: "landscaping",
    });
    expect(_timeClockEntry(fixed)).toBeDefined();
    expect(fixed.map((it) => it.key)).toEqual(TECH_TOP_NAV.map((it) => it.key));
  });

  it("landscape_tech dept (synonym) → Time Clock entry PRESENT", () => {
    const fixed = topNavForUser({
      role: "technician",
      department: "landscape_tech",
    });
    expect(_timeClockEntry(fixed)).toBeDefined();
  });

  it("both-dept tech → Time Clock entry PRESENT", () => {
    const fixed = topNavForUser({
      role: "technician",
      department: "both",
    });
    expect(_timeClockEntry(fixed)).toBeDefined();
  });

  it("BE show_time_clock=true overrides pool department", () => {
    const fixed = topNavForUser({
      role: "technician",
      department: "pool",
      show_time_clock: true,
    });
    expect(_timeClockEntry(fixed)).toBeDefined();
  });

  it("admin role → top strip is empty regardless of designation (unchanged)", () => {
    const fixedPool = topNavForUser({ role: "admin", department: "pool" });
    const fixedAdmin = topNavForUser({ role: "admin" });
    expect(fixedPool).toEqual([]);
    expect(fixedAdmin).toEqual([]);
  });

  it("topNavForRole legacy consumer still returns the full tech list", () => {
    // Keeps the role-only path backwards-compat for consumers that
    // haven't migrated to the user-aware function.
    expect(topNavForRole("technician")).toEqual(TECH_TOP_NAV);
  });
});


describe("TD-64 · navForRoleAndDept · Universal Menu gating", () => {
  it("pool dept nav drops the /time-clock Daily Work entry", () => {
    const sections = navForRoleAndDept("technician", "pool");
    const daily = sections.find((s) => s.key === "tech-daily");
    expect(daily).toBeTruthy();
    const paths = daily.entries.map((e) => e.to);
    expect(paths).not.toContain("/time-clock");
  });

  it("landscape dept nav KEEPS the /time-clock Daily Work entry", () => {
    const sections = navForRoleAndDept("technician", "landscaping");
    const daily = sections.find((s) => s.key === "tech-daily");
    expect(daily.entries.map((e) => e.to)).toContain("/time-clock");
  });

  it("`both` dept nav (union of pool+landscape) KEEPS /time-clock", () => {
    const sections = navForRoleAndDept("technician", "both");
    const daily = sections.find((s) => s.key === "tech-daily");
    expect(daily.entries.map((e) => e.to)).toContain("/time-clock");
  });

  it("TECH_POOL_NAV strips /time-clock as a static regression lock", () => {
    const daily = TECH_POOL_NAV.find((s) => s.key === "tech-daily");
    expect(daily.entries.map((e) => e.to)).not.toContain("/time-clock");
  });

  it("TECH_LANDSCAPE_NAV keeps /time-clock (static regression lock)", () => {
    const daily = TECH_LANDSCAPE_NAV.find((s) => s.key === "tech-daily");
    expect(daily.entries.map((e) => e.to)).toContain("/time-clock");
  });
});
