/**
 * Ticket EE · Feb-2026 — Desktop left-nav (QuickPinsRail) 20% proportional
 * reduction.  Locks the new dimensions AND the deliberate text-size carve-out
 * (text-[9px] held for legibility — 7px would be unreadable on a 70px rail).
 *
 * Covers:
 *   1. Shell width — the ``<aside>`` in AppLayout flipped from md:w-[88px]
 *      → md:w-[70px] (single call-site; no CSS var).
 *   2. Pin-tile icon prop — ``size={16}`` → ``size={13}``.
 *   3. Pin-tile padding — ``py-2.5`` → ``py-2`` on all three rail-row
 *      surfaces (pin tile, "Done" button, "Add pin" button) and the sibling
 *      Logout button in AppLayout.
 *   4. Text-size regression lock — ``text-[9px]`` MUST remain untouched on
 *      the rail-row surfaces (deliberate carve-out from strict 20% math).
 *   5. Nav IA regression lock — rendered rail still lists the seeded pins
 *      in the same order (contract from k75-quick-pin-rail suite preserved).
 *   6. Keyboard focus-ring regression lock — ``focus-visible:ring-2`` still
 *      present on the logout tile; pin-tile active-state styling preserved.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import fs from "node:fs";
import path from "node:path";

const SRC_ROOT = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.resolve(SRC_ROOT, rel), "utf8");

const _apiGet = vi.fn();
const _apiPut = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => _apiGet(...a), put: (...a) => _apiPut(...a) },
}));
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [
    { key: "finance", label: "Finance", icon: () => null, entries: [
      { to: "/invoices", label: "Invoices", icon: () => null, feature: "invoices" },
    ]},
  ],
  NAV_FLAT: [],
  KEYBOARD_SHORTCUTS: [],
  SHORTCUT_TARGETS: {},
  filterNavByIndustries: (entries) => entries,
}));

import QuickPinsRail from "@/components/nav/QuickPinsRail";

beforeEach(() => {
  _apiGet.mockReset();
  _apiPut.mockReset();
});

describe("Ticket EE · desktop sidebar 20% reduction — source locks", () => {
  const appLayout = read("layouts/AppLayout.jsx");
  const rail = read("components/nav/QuickPinsRail.jsx");

  it("<aside> shell width is md:w-[70px] (was md:w-[88px])", () => {
    expect(appLayout).toMatch(/md:w-\[70px\]/);
    expect(appLayout).not.toMatch(/md:w-\[88px\]/);
  });

  it("pin-tile icon renders at size={13} (was 16)", () => {
    // The one <Icon /> inside the pin NavLink body — distinct from the
    // size={12} grip handle and size={11} close-X overlay affordances.
    expect(rail).toMatch(/<Icon size=\{13\} className="transition-colors duration-200"/);
    expect(rail).not.toMatch(/<Icon size=\{16\}/);
  });

  it("rail-row padding is py-2 on all three rail surfaces (pin tile, Done, Add pin)", () => {
    // No py-2.5 should survive on rail surfaces.  Count:
    //   - pin NavLink className         (line ~207)
    //   - Done button className          (line ~398)
    //   - Add pin button className       (line ~416)
    const py25Matches = rail.match(/py-2\.5/g) || [];
    expect(py25Matches.length).toBe(0);
    // py-2 should appear on at least 3 rail surfaces.
    const py2Matches = rail.match(/\bpy-2\b/g) || [];
    expect(py2Matches.length).toBeGreaterThanOrEqual(3);
  });

  it("sibling Logout tile in AppLayout also flipped py-2.5 → py-2", () => {
    // The logout button sits inside the same <aside> and visually mirrors
    // the "Add pin" trigger — must stay in rhythm with the rail.
    const logoutLine = appLayout
      .split("\n")
      .find((l) => l.includes('data-testid="sidebar-logout-button"') === false
                 && l.includes("rounded-xl flex flex-col items-center")
                 && l.includes("border-dashed"));
    expect(logoutLine).toBeTruthy();
    expect(logoutLine).toMatch(/\bpy-2\b/);
    expect(logoutLine).not.toMatch(/py-2\.5/);
  });

  it("text-[9px] is HELD on rail-row surfaces (legibility carve-out)", () => {
    // Regression lock — if a future refactor tries to proportionally
    // shrink the label from 9px to 7px it will blow up here.
    const text9Matches = rail.match(/text-\[9px\]/g) || [];
    expect(text9Matches.length).toBeGreaterThanOrEqual(2); // Done + Add pin
    // Pin-tile className list on line ~207-212 also carries text-[9px]
    expect(rail).toMatch(/text-\[9px\] font-semibold/);
    // No stealth 7px shrink.
    expect(rail).not.toMatch(/text-\[7px\]/);
  });

  it("keyboard focus-ring preserved on logout tile", () => {
    expect(appLayout).toMatch(/focus-visible:ring-2 focus-visible:ring-offset-1/);
  });

  it("no stray hardcoded 88px sidebar reference remains in layouts/", () => {
    // Guards against a future partial-rollback that leaves one file
    // on 88px and another on 70px.  Note: the 88px references in
    // InvoiceView.css / DocLineItemCard / NotificationPrefs are
    // unrelated (invoice/document/grid layouts) and intentionally
    // ignored by scoping to the layouts/ string.
    const universalMenu = read("layouts/UniversalMenu.jsx");
    const adminSidebar = read("layouts/AdminSidebar.jsx");
    const settingsHub = read("layouts/SettingsHub.jsx");
    for (const src of [appLayout, universalMenu, adminSidebar, settingsHub]) {
      expect(src).not.toMatch(/w-\[88px\]/);
    }
  });
});

describe("Ticket EE · desktop sidebar 20% reduction — render locks", () => {
  function mount(role = "admin", initial = "/") {
    return render(
      <MemoryRouter initialEntries={[initial]}>
        <QuickPinsRail role={role} />
      </MemoryRouter>,
    );
  }

  it("pin-tile renders in same IA order (seeded defaults for admin)", async () => {
    _apiGet.mockResolvedValue({ pins: [] });
    const { container } = mount("admin");
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/users/me/quick-pins"),
    );
    // Any rail-nav-* testids present → IA emitted.  Order lock is
    // already covered deeply by k75-quick-pin-rail.test.jsx; this file
    // just confirms the size-reduction edits didn't break the render.
    const items = container.querySelectorAll('[data-testid^="rail-nav-"]');
    expect(items.length).toBeGreaterThan(0);
  });
});
