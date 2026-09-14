/**
 * Phase Feb-2026 · Multi-industry Phase C — hasIndustry gating.
 *
 * Verifies:
 *   1. filterNavByIndustries hides ``industry``-tagged entries
 *      unless the slug is in the industries array.
 *   2. Untagged entries always render (nav gating is a light touch).
 *   3. Empty industries array → fail-open (nothing hides).
 *   4. Pool-only tenant → sees pool tab, hides landscape items.
 *   5. Multi-industry tenant → sees the UNION of tagged items.
 */
import { describe, it, expect } from "vitest";
import { filterNavByIndustries } from "@/nav/adminNav";

const SAMPLE = [
  { to: "/dashboard",     label: "Dashboard" },
  { to: "/pool-service",  label: "Pool Service",  industry: "pools" },
  { to: "/landscape",     label: "Landscape AI",  industry: "landscaping" },
  { to: "/reports",       label: "Reports" },
];

describe("Phase C · filterNavByIndustries", () => {
  it("untagged entries always render", () => {
    const out = filterNavByIndustries(SAMPLE, ["pools"]);
    expect(out.map((e) => e.to)).toContain("/dashboard");
    expect(out.map((e) => e.to)).toContain("/reports");
  });

  it("hides pool-tagged entry when tenant lacks pools", () => {
    const out = filterNavByIndustries(SAMPLE, ["landscaping"]);
    expect(out.map((e) => e.to)).not.toContain("/pool-service");
    expect(out.map((e) => e.to)).toContain("/landscape");
  });

  it("hides landscape-tagged entry when tenant lacks landscaping", () => {
    const out = filterNavByIndustries(SAMPLE, ["pools"]);
    expect(out.map((e) => e.to)).toContain("/pool-service");
    expect(out.map((e) => e.to)).not.toContain("/landscape");
  });

  it("multi-industry tenant sees the union of tagged entries", () => {
    const out = filterNavByIndustries(SAMPLE, ["pools", "landscaping"]);
    expect(out.map((e) => e.to)).toEqual([
      "/dashboard", "/pool-service", "/landscape", "/reports",
    ]);
  });

  it("empty industries array is fail-open (nothing hides)", () => {
    // Migration might not have landed yet, or an admin cleared the
    // array. Preserve the pre-Phase-A behaviour where every nav
    // entry renders.
    const out = filterNavByIndustries(SAMPLE, []);
    expect(out.map((e) => e.to)).toEqual([
      "/dashboard", "/pool-service", "/landscape", "/reports",
    ]);
  });

  it("non-array industries treated as fail-open", () => {
    const out = filterNavByIndustries(SAMPLE, undefined);
    expect(out.map((e) => e.to)).toEqual([
      "/dashboard", "/pool-service", "/landscape", "/reports",
    ]);
  });
});
