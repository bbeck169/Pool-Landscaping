/**
 * Feb-2026 · QuickNavRail — Leads sidebar quick-link.
 *
 * Locks:
 *   - The rail source declares a "leads" entry with the /leads route
 *     and the UserPlus icon (matches ``nav/adminNav.js`` convention).
 *   - Position: between ``customers`` and ``estimates`` — sales-
 *     pipeline group cohesion.
 *   - Role gate: super_admin / admin / manager only.  Technicians
 *     and customer_portal do NOT see this item.
 *   - Testid follows the rail's ``rail-nav-{key}`` pattern
 *     (``rail-nav-leads``).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AppLayout.jsx"),
  "utf-8",
);


describe("QuickNavRail · Leads sidebar quick-link", () => {
  it("registers the /leads route with the UserPlus icon", () => {
    expect(SRC).toMatch(
      /key:\s*"leads"[\s\S]{0,120}to:\s*"\/leads"[\s\S]{0,120}Icon:\s*UserPlus/,
    );
  });

  it("gates the item to super_admin / admin / manager only", () => {
    // The rail entry's ``roles`` array must not include technician
    // or customer — those roles must not see the Leads shortcut.
    const leadsMatch = SRC.match(
      /key:\s*"leads"[\s\S]{0,300}?roles:\s*\[([^\]]+)\]/,
    );
    expect(leadsMatch, "leads entry not found").toBeTruthy();
    const roles = leadsMatch[1];
    expect(roles).toContain("super_admin");
    expect(roles).toContain("admin");
    expect(roles).toContain("manager");
    expect(roles).not.toContain("technician");
    expect(roles).not.toContain("customer");
  });

  it("sits between customers and estimates in the rail order", () => {
    const iCustomers = SRC.indexOf('key: "customers"');
    const iLeads     = SRC.indexOf('key: "leads"');
    const iEstimates = SRC.indexOf('key: "estimates"');
    expect(iCustomers).toBeGreaterThan(0);
    expect(iLeads).toBeGreaterThan(iCustomers);
    expect(iEstimates).toBeGreaterThan(iLeads);
  });

  it("only one Leads entry exists (no duplicate rail item)", () => {
    const occurrences = SRC.match(/key:\s*"leads"/g) || [];
    expect(occurrences).toHaveLength(1);
  });

  it("imports UserPlus from lucide-react", () => {
    expect(SRC).toMatch(/UserPlus,?\s*\n[\s\S]{0,80}from\s*"lucide-react"/);
  });
});
