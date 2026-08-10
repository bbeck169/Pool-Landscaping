/**
 * Phase 56-a.5 nav · Aug-2026 — Sidebar entry for the Pricebook
 * Suppliers admin page.
 *
 * Sibling of the existing Wholesale Suppliers row, but tighter gate
 * (admin_only per preflight §3). Locks (same shape as
 * ``phase54h-nav-wholesale-suppliers.test.jsx``):
 *   • Entry exists in ``ADMIN_NAV_V2`` with the expected route +
 *     label + feature + hard_rule + icon.
 *   • Placed adjacent to Wholesale Suppliers (same nav group).
 *   • Visible to admin / super_admin; hidden from manager /
 *     technician / customer.
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

describe("Phase 56-a.5-nav · Pricebook Suppliers sidebar entry", () => {
  it("is present in the admin nav config with the expected label + route", () => {
    const found = findEntry("/settings/pricebook-suppliers");
    expect(found).not.toBeNull();
    expect(found.entry.label).toBe("Pricebook Suppliers");
    expect(found.entry.feature).toBe("settings");
    expect(found.entry.icon).toBeTruthy();
  });

  it("carries the admin_only hard_rule (tighter than Wholesale Suppliers)", () => {
    const { entry } = findEntry("/settings/pricebook-suppliers");
    expect(entry.hard_rule).toBe("admin_only");
  });

  it("is grouped alongside Wholesale Suppliers as a sibling row", () => {
    const pricebook = findEntry("/settings/pricebook-suppliers");
    const wholesale = findEntry("/settings/suppliers");
    expect(pricebook.group.key).toBe(wholesale.group.key);
  });

  it("is visible to admin / super_admin; hidden from manager / technician / customer", () => {
    // Reimplement the AdminSidebar.jsx filter body verbatim (same
    // pattern as phase54h-nav test).
    const filter = (role, can) => {
      const entries = ADMIN_NAV_V2.flatMap((g) => g.entries);
      return entries.filter((e) => {
        if (e.hard_rule === "admin_only" && role !== "admin" && role !== "super_admin") return false;
        if (e.hard_rule === "super_admin_only" && role !== "super_admin") return false;
        return can(e.feature || "dashboard", "read") || role === "admin";
      });
    };
    const canSettings = (feature) => feature === "settings" || feature === "dashboard";

    for (const role of ["admin", "super_admin"]) {
      const visible = filter(role, canSettings);
      expect(visible.some((e) => e.to === "/settings/pricebook-suppliers")).toBe(true);
    }
    for (const role of ["manager", "technician", "customer"]) {
      const visible = filter(role, canSettings);
      expect(visible.some((e) => e.to === "/settings/pricebook-suppliers")).toBe(false);
    }
  });
});
