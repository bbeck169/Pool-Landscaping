/**
 * Phase 56-a.5-nav · Aug-2026 — Mobile drawer stub for the Pricebook
 * Suppliers admin page.
 *
 * Companion to the web-side ``pricebook-suppliers-nav.test.jsx``.
 * Native mobile screen is a TODO — this ships as a t2 ComingSoon
 * stub per preflight §3.
 *
 * Locks:
 *   • Entry exists in the Operations group of ``ADMIN_NAV`` with
 *     the expected label + route + tier + testID.
 *   • Tier is ``t2`` (ComingSoon) — native screen deferred to
 *     Phase 56-mobile-B.
 *   • Grouped alongside the existing Wholesale Suppliers row.
 *   • Visible to super_admin / admin ONLY; hidden from manager /
 *     technician / customer (tighter gate than the sibling row).
 */
import { ADMIN_NAV, canSeeEntry } from "../src/nav/adminNav";

function findEntry(route) {
  for (const g of ADMIN_NAV) {
    const hit = g.entries.find((e) => e.route === route);
    if (hit) return { group: g, entry: hit };
  }
  return null;
}

describe("Phase 56-a.5-nav · Pricebook Suppliers mobile drawer stub", () => {
  it("is present in ADMIN_NAV with the expected label + route + tier", () => {
    const found = findEntry("/settings/pricebook-suppliers");
    expect(found).not.toBeNull();
    expect(found.entry.label).toBe("Pricebook Suppliers");
    expect(found.entry.tier).toBe("t2");
    expect(found.entry.testID).toBe("drawer-nav-pricebook-suppliers");
  });

  it("is grouped alongside the mobile Wholesale Suppliers entry", () => {
    const pricebook = findEntry("/settings/pricebook-suppliers");
    const wholesale = findEntry("/settings/suppliers");
    expect(pricebook.group.key).toBe(wholesale.group.key);
  });

  it("is visible to super_admin / admin ONLY; hidden from manager / technician / customer", () => {
    const { entry } = findEntry("/settings/pricebook-suppliers");
    for (const role of ["super_admin", "admin"]) {
      expect(canSeeEntry(role, entry)).toBe(true);
    }
    for (const role of ["manager", "technician", "customer", undefined]) {
      expect(canSeeEntry(role, entry)).toBe(false);
    }
  });
});
