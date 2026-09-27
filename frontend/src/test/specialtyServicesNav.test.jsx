/**
 * Feb-2026 · Pool Service PS-C — Specialty Services nav group.
 *
 * Pins the new top-level "Specialty Services" group + two entries
 * (Filter Tracker, Salt Cell Tracker) added to ADMIN_NAV_V2.  Also
 * regressions the surrounding groups (Operations before, Customers
 * after) so a future refactor that shuffles group order fails
 * loudly here.
 */
import { describe, it, expect } from "vitest";
import { ADMIN_NAV_V2, NAV_FLAT } from "@/nav/adminNav";


describe("PS-C · Specialty Services nav group", () => {
  const group = ADMIN_NAV_V2.find(
    (g) => g.key === "specialty_services",
  );

  it("is present in ADMIN_NAV_V2 with the expected label", () => {
    expect(group).toBeTruthy();
    expect(group.label).toBe("Specialty Services");
    // Group must carry an icon (lucide component ref).
    expect(group.icon).toBeTruthy();
  });

  it("carries exactly Filter + Salt Cell tracker entries", () => {
    const paths = group.entries.map((e) => e.to);
    expect(paths).toContain("/tracking/filter");
    expect(paths).toContain("/tracking/salt-cell");
    expect(group.entries.length).toBe(2);
  });

  it("filter tracker entry has label + icon + jobs feature", () => {
    const e = group.entries.find(
      (x) => x.to === "/tracking/filter",
    );
    expect(e.label).toBe("Filter Tracker");
    expect(e.feature).toBe("jobs");
    expect(e.icon).toBeTruthy();
  });

  it("salt cell tracker entry has label + icon + jobs feature", () => {
    const e = group.entries.find(
      (x) => x.to === "/tracking/salt-cell",
    );
    expect(e.label).toBe("Salt Cell Tracker");
    expect(e.feature).toBe("jobs");
    expect(e.icon).toBeTruthy();
  });

  it("is placed immediately after Operations and before Customers", () => {
    const keys = ADMIN_NAV_V2.map((g) => g.key);
    const opsIdx  = keys.indexOf("operations");
    const custIdx = keys.indexOf("customers");
    const ssIdx   = keys.indexOf("specialty_services");
    expect(opsIdx).toBeGreaterThan(-1);
    expect(custIdx).toBeGreaterThan(-1);
    expect(ssIdx).toBe(opsIdx + 1);
    expect(ssIdx).toBe(custIdx - 1);
  });

  it("NAV_FLAT includes the two tracker entries with group='Specialty Services'", () => {
    const filterFlat = NAV_FLAT.find(
      (e) => e.to === "/tracking/filter",
    );
    const saltFlat = NAV_FLAT.find(
      (e) => e.to === "/tracking/salt-cell",
    );
    expect(filterFlat.group).toBe("Specialty Services");
    expect(saltFlat.group).toBe("Specialty Services");
  });

  it("does not disturb pre-existing groups (Finance, AI Employees, Marketing, Operations, Customers, Reports)", () => {
    const requiredKeys = [
      "finance", "ai_employees", "marketing",
      "operations", "customers", "reports",
    ];
    for (const k of requiredKeys) {
      expect(ADMIN_NAV_V2.find((g) => g.key === k)).toBeTruthy();
    }
  });
});
