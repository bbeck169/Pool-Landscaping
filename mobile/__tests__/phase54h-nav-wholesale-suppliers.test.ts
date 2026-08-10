/**
 * Phase 54h-nav · Aug-2026 — Mobile drawer entry for the Wholesale
 * Suppliers credentials page.
 *
 * Companion to the web-side ``phase54h-nav-wholesale-suppliers.test.jsx``.
 * Locks:
 *   • Entry exists in the Operations group of ``ADMIN_NAV_MOBILE``
 *     with the expected label + route + tier + testID.
 *   • Native mobile screen exists at ``mobile/app/settings/suppliers.tsx``
 *     so this is a ``t1`` entry (direct native navigation, no
 *     ComingSoon stub).
 *   • Visible to super_admin / admin / manager; hidden from
 *     technician / customer via ``canSeeEntry``.
 */
import { ADMIN_NAV, canSeeEntry } from "../src/nav/adminNav";

function findEntry(route) {
  for (const g of ADMIN_NAV) {
    const hit = g.entries.find((e) => e.route === route);
    if (hit) return { group: g, entry: hit };
  }
  return null;
}

describe("Phase 54h-nav · Wholesale Suppliers mobile drawer entry", () => {
  it("is present in ADMIN_NAV_MOBILE with the expected label + route", () => {
    const found = findEntry("/settings/suppliers");
    expect(found).not.toBeNull();
    expect(found.entry.label).toBe("Wholesale Suppliers");
    expect(found.entry.tier).toBe("t1");
    expect(found.entry.testID).toBe("drawer-nav-wholesale-suppliers");
  });

  it("is grouped alongside the mobile Supplier Syncs entry", () => {
    const wholesale = findEntry("/settings/suppliers");
    const syncs = findEntry("/reports/supplier-syncs");
    expect(wholesale.group.key).toBe(syncs.group.key);
  });

  it("is visible to super_admin / admin / manager; hidden from technician + customer", () => {
    const { entry } = findEntry("/settings/suppliers");
    for (const role of ["super_admin", "admin", "manager"]) {
      expect(canSeeEntry(role, entry)).toBe(true);
    }
    for (const role of ["technician", "customer", undefined]) {
      expect(canSeeEntry(role, entry)).toBe(false);
    }
  });
});
