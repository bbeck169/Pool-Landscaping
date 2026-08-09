/**
 * Phase 54g-nav · Feb-2026 — Mobile drawer entry for Supplier Syncs.
 *
 * Nav-wiring test only. The mobile page mirrors the web dashboard
 * lands in Phase 54g-B; for now the drawer entry deep-links to the
 * existing ``/settings/suppliers`` scaffold (health + last-sync
 * status live there).
 *
 * Locks:
 *   • Entry exists in the Reports section of ``ADMIN_NAV``.
 *   • ``testID`` matches the drawer's expected pattern.
 *   • Admin-like roles (super_admin/admin/manager) can see it;
 *     technician + customer cannot.
 */
import {
  ADMIN_NAV,
  canSeeEntry,
} from "@/src/nav/adminNav";

function findEntry(route: string) {
  for (const g of ADMIN_NAV) {
    const hit = g.entries.find((e) => e.route === route);
    if (hit) return { group: g, entry: hit };
  }
  return null;
}

describe("Phase 54g-nav · mobile drawer Supplier Syncs entry", () => {
  it("is grouped under the Reports section", () => {
    // Route currently deep-links to /settings/suppliers per the TODO
    // in adminNav.ts.  If Phase 54g-B ships a dedicated mobile
    // dashboard, both this route and the assertion below flip.
    const found = findEntry("/settings/suppliers");
    expect(found).not.toBeNull();
    expect(found?.group.key).toBe("reports");
    const supplierEntry = found?.group.entries.find(
      (e) => e.label === "Supplier Syncs",
    );
    expect(supplierEntry).toBeDefined();
    expect(supplierEntry?.testID).toBe("drawer-nav-supplier-syncs");
    expect(supplierEntry?.icon).toBe("refresh-circle-outline");
  });

  it("is visible to admin-like roles + hidden from tech/customer", () => {
    const found = findEntry("/settings/suppliers");
    const supplierEntry = found?.group.entries.find(
      (e) => e.label === "Supplier Syncs",
    );
    expect(supplierEntry).toBeDefined();
    // The mobile canSeeEntry helper accepts admin/super_admin/manager
    // when ``roles`` is omitted.
    for (const role of ["admin", "super_admin", "manager"]) {
      expect(canSeeEntry(role, supplierEntry!)).toBe(true);
    }
    for (const role of ["technician", "customer", undefined]) {
      expect(canSeeEntry(role as any, supplierEntry!)).toBe(false);
    }
  });
});
