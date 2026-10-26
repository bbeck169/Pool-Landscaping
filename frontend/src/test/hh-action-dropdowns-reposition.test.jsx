/**
 * Ticket HH · Feb-2026 — Send / + Create / Portal Access
 * dropdowns relocated above the customer H1 name heading
 * inside the identity card.
 *
 * Pre-HH DOM order:
 *   back button → cd-identity-header (pill row → H1 → address) →
 *   cd-action-row (Edit/Merge/Delete command strip) →
 *   cd-command-strip-tabs (``<CustomerActionDropdowns>`` +
 *                           Overview tabs dropdown) → KPI grid
 *
 * Post-HH DOM order:
 *   back button → cd-identity-header (pill row →
 *     ``cd-identity-header-actions`` wrapping
 *     ``<CustomerActionDropdowns>`` → H1 → address) →
 *   cd-action-row → cd-command-strip-tabs (Overview tabs
 *     dropdown ONLY) → KPI grid
 *
 * Pure DOM-order move: same component, same props, same
 * handlers, same testids, same ``navy`` styling.  No logic
 * change.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomerDetail.jsx"),
  "utf-8",
);

describe("Ticket HH · action dropdowns relocated to identity header", () => {
  it("`<CustomerActionDropdowns>` renders INSIDE cd-identity-header", () => {
    const idHeaderIdx = SRC.indexOf('data-testid="cd-identity-header"');
    const idHeaderClose = SRC.indexOf(
      // The identity card closes right before the "Feb-2026 ·
      // Unified navy command strip" comment that opens the
      // Edit/Merge/Delete action row.
      "Feb-2026 · Unified navy command strip", idHeaderIdx);
    expect(idHeaderIdx).toBeGreaterThan(-1);
    expect(idHeaderClose).toBeGreaterThan(idHeaderIdx);
    const idSlice = SRC.slice(idHeaderIdx, idHeaderClose);
    expect(idSlice).toContain("<CustomerActionDropdowns");
    expect(idSlice).toContain('data-testid="cd-identity-header-actions"');
  });

  it("`<CustomerActionDropdowns>` renders BELOW the pill row (customer-since / VIP / ActivationControl)", () => {
    const sinceIdx = SRC.indexOf('data-testid="customer-since-label"');
    const vipIdx = SRC.indexOf('data-testid="customer-vip-toggle"');
    const actionsIdx = SRC.indexOf('data-testid="cd-identity-header-actions"');
    expect(sinceIdx).toBeGreaterThan(-1);
    expect(vipIdx).toBeGreaterThan(-1);
    expect(actionsIdx).toBeGreaterThan(sinceIdx);
    expect(actionsIdx).toBeGreaterThan(vipIdx);
  });

  it("`<CustomerActionDropdowns>` renders ABOVE the H1 name heading", () => {
    const actionsIdx = SRC.indexOf('data-testid="cd-identity-header-actions"');
    const h1Idx = SRC.indexOf(
      'data-testid="customer-detail-inline-h1"');
    expect(actionsIdx).toBeGreaterThan(-1);
    expect(h1Idx).toBeGreaterThan(actionsIdx);
  });

  it("Edit/Merge/Delete command strip (cd-action-row) still renders AFTER the identity header (unchanged position)", () => {
    const idHeaderIdx = SRC.indexOf('data-testid="cd-identity-header"');
    const actionRowIdx = SRC.indexOf('data-testid="cd-action-row"');
    expect(idHeaderIdx).toBeGreaterThan(-1);
    expect(actionRowIdx).toBeGreaterThan(idHeaderIdx);
  });

  it("cd-tabs-row no longer carries `<CustomerActionDropdowns>` (lifted out)", () => {
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    const nextSiblingIdx = SRC.indexOf(
      "{/* Feb-2026 · Tabs — the standalone", tabsRowIdx);
    expect(tabsRowIdx).toBeGreaterThan(-1);
    expect(nextSiblingIdx).toBeGreaterThan(tabsRowIdx);
    const tabsBlock = SRC.slice(tabsRowIdx, nextSiblingIdx);
    expect(tabsBlock).not.toContain("<CustomerActionDropdowns");
    // Overview tab dropdown shell survives in cd-tabs-row.
    expect(tabsBlock).toContain('data-testid="cd-tabs-dropdown-shell"');
    expect(tabsBlock).toContain("<ResponsiveTabs");
  });

  it("Props preserved on `<CustomerActionDropdowns>` (same wiring, same testids)", () => {
    // All four callback props + the ``navy`` styling flag survive
    // the move.  Source-string lint is sufficient since the
    // component is a single-line prop block.
    const callSite = SRC.match(
      /<CustomerActionDropdowns[\s\S]*?navy[\s\S]*?\/>/,
    );
    expect(callSite).not.toBeNull();
    expect(callSite[0]).toContain("customer={customer}");
    expect(callSite[0]).toContain("onSend={openSendModal}");
    expect(callSite[0]).toContain("onQuickTask={openQuickTaskFromDropdown}");
    expect(callSite[0]).toContain("onSendServiceRecordsLink={");
    expect(callSite[0]).toContain("navy");
    // Only ONE call site in the file (no accidental duplicate).
    const count = (SRC.match(/<CustomerActionDropdowns\b/g) || []).length;
    expect(count).toBe(1);
  });

  it("GG regression preserved — Overview content (cd-profile-header) still renders unconditionally after identity card", () => {
    expect(SRC).toMatch(/data-testid="cd-profile-header"/);
    const idHeaderIdx = SRC.indexOf('data-testid="cd-identity-header"');
    const profileIdx = SRC.indexOf('data-testid="cd-profile-header"');
    expect(profileIdx).toBeGreaterThan(idHeaderIdx);
  });

  it("GG regression preserved — TABS array still carries exactly 10 kept keys in order", () => {
    const tabsBlock = SRC.match(/const TABS = \[[\s\S]*?^\];/m);
    expect(tabsBlock).not.toBeNull();
    const kFound = [...tabsBlock[0].matchAll(/k:\s*"(\w+)"/g)].map((m) => m[1]);
    expect(kFound).toEqual([
      "properties", "jobs", "chemical_history", "quotes", "invoices",
      "equipment", "warranties", "credits", "payments", "portal",
    ]);
  });
});
