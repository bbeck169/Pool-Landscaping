/**
 * Feb-2026 · QuickPinsRail — Leads sidebar quick-link.
 *
 * Phase K75 · Step B · Feb-2026 — the pre-K75 hard-coded rail
 * array moved from ``AppLayout.jsx`` → ``nav/defaultQuickPins.js``
 * where the shared seed lives. Per-role gating is now enforced by
 * ``defaultQuickPinsForRole(role)`` — the P20-era ``roles: [...]``
 * per-item filter was retired (an admin-only seed lists the admin
 * items; the tech seed lists only tech items).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { defaultQuickPinsForRole } from "@/nav/defaultQuickPins";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../nav/defaultQuickPins.js"),
  "utf-8",
);


describe("QuickPinsRail · Leads sidebar quick-link (K75 · Step B — source of truth in defaultQuickPins.js)", () => {
  it("registers the /leads route with the user_plus iconKey", () => {
    // Source of truth is the ``ADMIN_DEFAULTS_RAW`` literal.
    expect(SRC).toMatch(
      /key:\s*"leads"[\s\S]{0,120}to:\s*"\/leads"[\s\S]{0,120}iconKey:\s*"user_plus"/,
    );
  });

  it("gates the item to admin / super_admin / manager (tech + customer never see it)", () => {
    const adminPins = defaultQuickPinsForRole("admin");
    const managerPins = defaultQuickPinsForRole("manager");
    const superPins = defaultQuickPinsForRole("super_admin");
    const techPins = defaultQuickPinsForRole("technician");
    const customerPins = defaultQuickPinsForRole("customer");

    for (const pins of [adminPins, managerPins, superPins]) {
      expect(pins.some((p) => p.to === "/leads"), "admin+ should see /leads").toBe(true);
    }
    expect(techPins.some((p) => p.to === "/leads"), "tech should NOT see /leads").toBe(false);
    expect(customerPins.some((p) => p.to === "/leads"), "customer should NOT see /leads").toBe(false);
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

  it("iconKey resolves through the K75 whitelist", () => {
    const pins = defaultQuickPinsForRole("admin");
    const leads = pins.find((p) => p.to === "/leads");
    expect(leads).toBeTruthy();
    expect(leads.iconKey).toBe("user_plus");
    // ``Icon`` was hydrated by ``resolveIcon`` — it's a lucide
    // component (ForwardRef object with a ``render`` fn), not
    // undefined.
    expect(leads.Icon).toBeTruthy();
    expect(typeof leads.Icon === "function" || typeof leads.Icon === "object")
      .toBe(true);
  });
});
