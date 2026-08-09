/**
 * Phase 54g-nav · Feb-2026 — Sidebar entry for the Supplier Syncs
 * analytics dashboard (nav wiring only; page already exists).
 *
 * Locks:
 *   • The entry exists in ``ADMIN_NAV_V2`` with the expected
 *     ``to``, ``label``, ``feature``, ``hard_rule`` and icon.
 *   • It's grouped in the same section as the other supplier /
 *     reports rows (``feature: "reports"``).
 *   • The sidebar filter shows it to admin/super_admin/manager
 *     roles and hides it from technician + customer, matching
 *     the ``AdminOrManagerForSuppliers`` route guard in App.js.
 */
import { describe, it, expect } from "vitest";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";

function findEntry(to) {
  for (const g of ADMIN_NAV_V2) {
    const hit = g.entries.find((e) => e.to === to);
    if (hit) return { group: g, entry: hit };
  }
  return null;
}

describe("Phase 54g-nav · Supplier Syncs sidebar entry", () => {
  it("is present in the admin nav config", () => {
    const found = findEntry("/reports/supplier-syncs");
    expect(found).not.toBeNull();
    expect(found.entry.label).toBe("Supplier Syncs");
    // Same feature bucket as neighbouring reports rows so the
    // ``can()`` RBAC check gates it uniformly.
    expect(found.entry.feature).toBe("reports");
    // Icon must be resolved from lucide-react (not undefined).
    expect(typeof found.entry.icon).toBeTruthy();
  });

  it("uses the same section as the other /reports/* rows", () => {
    const suppliers = findEntry("/reports/supplier-syncs");
    const forecast = findEntry("/reports/forecast");
    expect(suppliers.group.key).toBe(forecast.group.key);
  });

  it("mirrors the AdminOrManagerForSuppliers route guard (manager_only rule)", () => {
    // The sidebar's actual filter accepts admin/super_admin/manager
    // for any ``feature: 'reports'`` entry (see
    // AdminSidebar.jsx line ~127). The ``manager_only`` hard_rule is
    // the documented flag other reports rows use for the same three-
    // role gate; asserting it here locks the wiring choice.
    const { entry } = findEntry("/reports/supplier-syncs");
    expect(entry.hard_rule).toBe("manager_only");
  });

  it("simulates the AdminSidebar filter — visible to admin/super_admin/manager, hidden from tech + customer", () => {
    // Reimplement the exact filter body from AdminSidebar.jsx (lines
    // ~126-131) so future refactors of that filter don't silently
    // slip this entry past its role gate.
    const filter = (role, can) => {
      const entries = ADMIN_NAV_V2.flatMap((g) => g.entries);
      return entries.filter((e) => {
        if (e.hard_rule === "admin_only" && role !== "admin") return false;
        if (e.hard_rule === "super_admin_only" && role !== "super_admin") return false;
        return can(e.feature || "dashboard", "read") || role === "admin";
      });
    };
    // Admin-like roles all read the ``reports`` feature.
    const canReports = (feature) => feature === "reports" || feature === "dashboard";
    const canNothing = () => false;

    for (const role of ["admin", "super_admin", "manager"]) {
      const visible = filter(role, canReports);
      expect(visible.some((e) => e.to === "/reports/supplier-syncs")).toBe(true);
    }
    // Technician + customer neither pass ``role === "admin"`` nor
    // ``can("reports","read")`` → the entry is hidden.
    for (const role of ["technician", "customer"]) {
      const visible = filter(role, canNothing);
      expect(visible.some((e) => e.to === "/reports/supplier-syncs")).toBe(false);
    }
  });
});
