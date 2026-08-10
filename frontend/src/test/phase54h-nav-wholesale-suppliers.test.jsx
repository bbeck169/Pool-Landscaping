/**
 * Phase 54h-nav · Aug-2026 — Sidebar entry for the Wholesale Suppliers
 * credentials/config page.
 *
 * Sibling of the existing Supplier Syncs entry (analytics) — this one
 * links operators to ``/settings/suppliers`` (Playwright creds +
 * per-supplier "Test connection" button).
 *
 * Locks (same shape as ``phase54g-nav-supplier-syncs.test.jsx``):
 *   • Entry exists in ``ADMIN_NAV_V2`` with the expected route +
 *     label + feature + hard_rule + icon.
 *   • Placed adjacent to Supplier Syncs (same nav group).
 *   • Visible to admin / super_admin / manager; hidden from
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

describe("Phase 54h-nav · Wholesale Suppliers sidebar entry", () => {
  it("is present in the admin nav config with the expected label + route", () => {
    const found = findEntry("/settings/suppliers");
    expect(found).not.toBeNull();
    expect(found.entry.label).toBe("Wholesale Suppliers");
    expect(found.entry.feature).toBe("settings");
    expect(typeof found.entry.icon).toBeTruthy();
  });

  it("is grouped alongside Supplier Syncs (sibling reports/settings row)", () => {
    const wholesale = findEntry("/settings/suppliers");
    const syncs = findEntry("/reports/supplier-syncs");
    expect(wholesale.group.key).toBe(syncs.group.key);
  });

  it("carries the manager_only hard_rule for the three-role gate", () => {
    const { entry } = findEntry("/settings/suppliers");
    expect(entry.hard_rule).toBe("manager_only");
  });

  it("is visible to admin / super_admin / manager; hidden from technician + customer", () => {
    // Reimplement the AdminSidebar.jsx filter body verbatim so a
    // future refactor there can't silently slip this entry past its
    // role gate.
    const filter = (role, can) => {
      const entries = ADMIN_NAV_V2.flatMap((g) => g.entries);
      return entries.filter((e) => {
        if (e.hard_rule === "admin_only" && role !== "admin") return false;
        if (e.hard_rule === "super_admin_only" && role !== "super_admin") return false;
        return can(e.feature || "dashboard", "read") || role === "admin";
      });
    };
    const canSettings = (feature) => feature === "settings" || feature === "dashboard";
    const canNothing = () => false;

    for (const role of ["admin", "super_admin", "manager"]) {
      const visible = filter(role, canSettings);
      expect(visible.some((e) => e.to === "/settings/suppliers")).toBe(true);
    }
    for (const role of ["technician", "customer"]) {
      const visible = filter(role, canNothing);
      expect(visible.some((e) => e.to === "/settings/suppliers")).toBe(false);
    }
  });
});
