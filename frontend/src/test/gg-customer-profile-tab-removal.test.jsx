/**
 * Ticket GG · Feb-2026 — Customer profile 7-tab soft-removal.
 *
 * Scope locks (source-string pattern — full CustomerDetail mount
 * hangs jsdom per the ``customer-profile-skeleton-loader.test.jsx``
 * notes):
 *
 *   1. 7 nav labels gone from TABS: overview, documents,
 *      measurements, tasks, notes, subscriptions, reviews.
 *   2. 10 remaining labels preserved IN ORDER: properties, jobs,
 *      chemical_history, quotes, invoices, equipment, warranties,
 *      credits, payments, portal.
 *   3. Initial-state default flipped from "overview" → "properties".
 *   4. URL fallback: an unknown or soft-removed ``?tab=`` value
 *      silently falls back to the default (``TABS.some`` guard).
 *   5. Overview CONTENT (``cd-profile-header``) is rendered
 *      unconditionally above the tab-content switch — preserves
 *      TD-79 / Phase I5 / 48.1 / 9d regression locks.
 *   6. The 6 other content branches (``tab === "documents"``,
 *      "measurements", "tasks", "notes", "subscriptions",
 *      "reviews") are gone from the render tree AND their
 *      component imports dropped from the top of the file.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomerDetail.jsx"),
  "utf-8",
);

const REMOVED = ["overview", "documents", "measurements", "tasks", "notes", "subscriptions", "reviews"];
const KEPT = ["properties", "jobs", "chemical_history", "quotes", "invoices", "equipment", "warranties", "credits", "payments", "portal"];

describe("Ticket GG · TABS array — 7 nav entries removed, 10 kept", () => {
  it("7 removed tab keys are absent from the TABS array", () => {
    // Find the TABS = [...] block and lint keys inside it.
    const tabsBlock = SRC.match(/const TABS = \[[\s\S]*?^\];/m);
    expect(tabsBlock).not.toBeNull();
    for (const k of REMOVED) {
      expect(tabsBlock[0]).not.toMatch(new RegExp(`k:\\s*"${k}"`));
    }
  });

  it("10 kept tab keys present in TABS in exact order", () => {
    const tabsBlock = SRC.match(/const TABS = \[[\s\S]*?^\];/m)[0];
    const kFound = [...tabsBlock.matchAll(/k:\s*"(\w+)"/g)].map((m) => m[1]);
    expect(kFound).toEqual(KEPT);
  });

  it("initial state default flipped to 'properties'", () => {
    expect(SRC).toMatch(/useState\("properties"\)/);
    expect(SRC).not.toMatch(/useState\("overview"\)/);
  });

  it("URL effect validates against TABS and falls back silently", () => {
    expect(SRC).toMatch(
      /const\s+_valid\s*=\s*TABS\.some\(\(t\)\s*=>\s*t\.k\s*===\s*q\);[\s\S]{0,120}if\s*\(_valid\s*&&\s*q\s*!==\s*tab\)\s*_setTab\(q\);/,
    );
  });

  it("setTab URL-strip default is 'properties' (not 'overview')", () => {
    expect(SRC).toMatch(/next\s*!==\s*"properties"/);
    expect(SRC).not.toMatch(/next\s*!==\s*"overview"/);
  });
});

describe("Ticket GG · 6 content branches removed from render tree", () => {
  // Overview is NOT in this list — its content was pulled OUT as
  // always-visible profile header (see next describe).
  for (const k of ["documents", "measurements", "tasks", "notes", "subscriptions", "reviews"]) {
    it(`tab === "${k}" conditional block is gone`, () => {
      expect(SRC).not.toMatch(new RegExp(`tab\\s*===\\s*"${k}"\\s*\\?`));
    });
  }
});

describe("Ticket GG · Overview content pulled OUT as always-visible profile header", () => {
  it("cd-profile-header wrapper renders unconditionally (no tab === 'overview' guard)", () => {
    expect(SRC).toMatch(/data-testid="cd-profile-header"/);
    expect(SRC).not.toMatch(/tab\s*===\s*"overview"\s*\?/);
  });

  it("TD-79 placement preserved — CustomerInvoiceList still between name heading + PaymentMethodTiles", () => {
    const nameIdx = SRC.indexOf('data-testid="cd-customer-name-secondary"');
    const listIdx = SRC.indexOf("<CustomerInvoiceList");
    const paymentIdx = SRC.indexOf("<PaymentMethodTiles");
    expect(nameIdx).toBeGreaterThan(-1);
    expect(listIdx).toBeGreaterThan(nameIdx);
    expect(paymentIdx).toBeGreaterThan(listIdx);
  });

  it("CustomerContactsPanel + CustomerInvoiceList + PaymentMethodTiles still render", () => {
    expect(SRC).toMatch(/<CustomerInvoiceList\s/);
    expect(SRC).toMatch(/<PaymentMethodTiles\s/);
    expect(SRC).toMatch(/<CustomerContactsPanel\s/);
  });
});

describe("Ticket GG · soft-removed component imports dropped", () => {
  it("CustomerDocumentsTab import commented out", () => {
    expect(SRC).not.toMatch(
      /^import\s+CustomerDocumentsTab\s+from\s+"@\/components\/customers\/CustomerDocumentsTab"/m,
    );
  });

  it("CustomerTasksPanel import commented out", () => {
    expect(SRC).not.toMatch(
      /^import\s+CustomerTasksPanel\s+from\s+"@\/components\/customers\/CustomerTasksPanel"/m,
    );
  });

  it("CustomerReviewsTab import commented out", () => {
    expect(SRC).not.toMatch(
      /^import\s+CustomerReviewsTab\s+from\s+"@\/components\/customers\/CustomerReviewsTab"/m,
    );
  });

  it("SubscriptionsPanel import commented out", () => {
    expect(SRC).not.toMatch(
      /^import\s+SubscriptionsPanel\s+from\s+"\.\/SubscriptionsPanel"/m,
    );
  });

  it("CustomerMeasurementsTab symbol dropped, filterCustomerTabs preserved", () => {
    // The module still exports filterCustomerTabs — that named
    // import must survive even though the component import went
    // away.
    expect(SRC).toMatch(
      /import\s+\{\s*filterCustomerTabs\s*\}\s+from\s+"@\/components\/customer\/CustomerMeasurementsTab"/,
    );
    expect(SRC).not.toMatch(/\{\s*CustomerMeasurementsTab\s*,/);
  });
});

describe("Ticket GG · openQuickTaskFromDropdown degrades silently", () => {
  it("setTab('tasks') call removed — silent no-op per fallback rule", () => {
    const fnBlock = SRC.match(
      /const\s+openQuickTaskFromDropdown\s*=\s*\(\)\s*=>\s*\{[\s\S]*?\n\s*\};/,
    );
    expect(fnBlock).not.toBeNull();
    expect(fnBlock[0]).not.toMatch(/setTab\("tasks"\)/);
  });
});
