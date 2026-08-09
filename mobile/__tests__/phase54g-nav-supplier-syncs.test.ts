/**
 * Phase 54g-B · Feb-2026 — Mobile drawer entry for Supplier Syncs.
 *
 * The drawer entry now points at the dedicated mobile analytics
 * screen at ``app/reports/supplier-syncs.tsx`` (parity with the web
 * ``/reports/supplier-syncs`` dashboard). Phase 54g-nav's interim
 * deep-link to ``/settings/suppliers`` is retired.
 *
 * Locks:
 *   • Entry exists in the Reports section of ``ADMIN_NAV`` under the
 *     new mobile route.
 *   • Entry is ``tier: "t1"`` — the mobile screen exists.
 *   • ``testID`` matches the drawer's expected pattern.
 *   • Admin-like roles (super_admin/admin/manager) can see it;
 *     technician + customer cannot.
 *   • The old deep-link route is no longer wired in the drawer.
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

describe("Phase 54g-B · mobile drawer Supplier Syncs entry", () => {
  it("is grouped under Reports and points at the new mobile route", () => {
    const found = findEntry("/reports/supplier-syncs");
    expect(found).not.toBeNull();
    expect(found?.group.key).toBe("reports");
    const supplierEntry = found?.entry;
    expect(supplierEntry).toBeDefined();
    expect(supplierEntry?.label).toBe("Supplier Syncs");
    expect(supplierEntry?.testID).toBe("drawer-nav-supplier-syncs");
    expect(supplierEntry?.icon).toBe("refresh-circle-outline");
    // Now that a native screen exists, the entry is tier-1 (direct
    // navigation, not a ComingSoon deep-link).
    expect(supplierEntry?.tier).toBe("t1");
  });

  it("retires the interim /settings/suppliers deep-link entry", () => {
    // /settings/suppliers still exists as a settings surface but is
    // no longer wired as the Supplier Syncs drawer entry.
    for (const g of ADMIN_NAV) {
      for (const e of g.entries) {
        if (e.label === "Supplier Syncs") {
          expect(e.route).toBe("/reports/supplier-syncs");
          expect(e.route).not.toBe("/settings/suppliers");
        }
      }
    }
  });

  it("is visible to admin-like roles + hidden from tech/customer", () => {
    const found = findEntry("/reports/supplier-syncs");
    const supplierEntry = found?.entry;
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
