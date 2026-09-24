/**
 * Task E · Feb-2026 · Commit 8a — Cross-page symmetry regression
 * guard.
 *
 * Source-body sweep across all 6 migrated filter bars.  Pins:
 *   • Every page mounts <NavyFilterBar> from
 *     ``@/components/ui/NavyFilterBar``.
 *   • Every page's filter bar root carries a UNIQUE
 *     page-scoped ``data-testid``.
 *   • The K52.1 marker ``data-k52-navy-strip="true"`` appears
 *     exactly once on each page's filter bar (or twice on
 *     Invoices — CustomerFilterBar above the strip is unaffected).
 *   • The pre-migration testid roster for each page still resolves
 *     verbatim as a source-file match (DOM regression coverage
 *     lives in each page's own vitest suite).
 *
 * Source-body scan, not DOM render — keeps the cross-page guard
 * fast and free of per-page mock boilerplate.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


function readSrc(rel) {
  return fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");
}


const PAGES = [
  {
    label: "Customers",
    file: "src/pages/customers/CustomersList.jsx",
    rootTestid: "customers-filters",
    controlTestids: [
      "customers-search",
      "customers-filter-tag",
      "customers-filter-sort",
      "customers-filter-portal-status",
      "customers-filter-city",
      "customers-filter-missing-card",
      "customers-more-filters-dropdown",
    ],
    // Testids generated inside JSX template literals — check the
    // template prefix + the interpolation shape separately.
    templateTestids: [
      { prefix: "customers-scope-", interpolation: "s.k" },
    ],
  },
  {
    label: "Invoices",
    file: "src/pages/invoices/InvoicesList.jsx",
    rootTestid: "invoices-filters",
    controlTestids: [
      "inv-search",
      "inv-filter-status",
      "inv-filter-late-fee",
      "docs-filter-has-declined-items",
      "inv-filter-card",
      "inv-filter-category",
      "inv-filter-category-select",
      "inv-category-clear",
    ],
    templateTestids: [
      { prefix: "inv-category-chip-", interpolation: "c" },
      { prefix: "inv-category-chip-remove-", interpolation: "c" },
    ],
  },
  {
    label: "Pricebook",
    file: "src/pages/ops/OpsHub.jsx",
    rootTestid: "pricebook-filters",
    controlTestids: [
      "pricebook-search-input",
      "pb-supplier-filter",
    ],
    templateTestids: [],
  },
  {
    label: "Recurring Jobs",
    file: "src/pages/admin/RecurringJobs.jsx",
    rootTestid: "recurring-jobs-filters",
    controlTestids: [
      "recurring-search-input",
      "recurring-jobs-service-category-filter",
    ],
    templateTestids: [],
  },
  {
    label: "Work Stream",
    file: "src/pages/workstream/WorkstreamPage.jsx",
    rootTestid: "workstream-filter-bar",
    controlTestids: [
      "ws-filter-since",
      "ws-filter-until",
      "ws-filter-customer",
      "ws-sort",
    ],
    templateTestids: [],
  },
  {
    label: "Payments Ledger",
    file: "src/pages/finance/FinancePages.jsx",
    rootTestid: "payments-filters",
    controlTestids: [
      "payments-search",
      "payments-filter-method",
      "payments-filter-status",
      "payments-export",
    ],
    templateTestids: [],
  },
];


describe("Task E · Cross-page symmetry — every migrated filter bar wears the shared chrome", () => {
  it("imports NavyFilterBar from @/components/ui/NavyFilterBar on every migrated page", () => {
    for (const p of PAGES) {
      const SRC = readSrc(p.file);
      expect(
        SRC,
        `${p.label} — should import NavyFilterBar from @/components/ui/NavyFilterBar`
      ).toMatch(/from ['"]@\/components\/ui\/NavyFilterBar['"]/);
    }
  });

  it("mounts <NavyFilterBar> with a unique page-scoped root data-testid on every page", () => {
    const seen = new Set();
    for (const p of PAGES) {
      const SRC = readSrc(p.file);
      // NavyFilterBar mount carries the page's root testid.
      const rootPattern = new RegExp(
        `<NavyFilterBar[\\s\\S]{0,200}data-testid="${p.rootTestid}"`
      );
      expect(SRC, `${p.label} — <NavyFilterBar> should carry data-testid="${p.rootTestid}"`).toMatch(rootPattern);
      // Uniqueness across pages.
      expect(seen.has(p.rootTestid), `${p.rootTestid} — duplicate root testid`).toBe(false);
      seen.add(p.rootTestid);
    }
  });

  it("carries the K52.1 marker (data-k52-navy-strip) on every migrated filter bar", () => {
    for (const p of PAGES) {
      const SRC = readSrc(p.file);
      const rootIdx = SRC.indexOf(`data-testid="${p.rootTestid}"`);
      expect(rootIdx, `${p.label} — root testid must be present`).toBeGreaterThan(-1);
      // Search a small window around the root testid for the marker.
      const block = SRC.slice(rootIdx, rootIdx + 400);
      expect(block, `${p.label} — K52.1 marker present on the strip`).toMatch(/data-k52-navy-strip="true"/);
    }
  });

  it("preserves every pre-migration filter-control data-testid on every page (roster check)", () => {
    for (const p of PAGES) {
      const SRC = readSrc(p.file);
      for (const testid of p.controlTestids) {
        // Match either the plain data-testid literal OR a
        // ``testid=…`` prop passed through a shared component
        // (e.g. Work Stream's CustomerCombobox uses ``testid=``).
        const pattern = new RegExp(
          `(?:data-)?testid=["'\`]${testid.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'\`]`
        );
        expect(
          SRC,
          `${p.label} — filter-control testid ${testid} must still resolve in the source`
        ).toMatch(pattern);
      }
      // Template-generated testids (e.g. ``customers-scope-${s.k}``)
      // — assert the template prefix + interpolation appear
      // together inside a template literal.
      for (const t of p.templateTestids) {
        const escapedPrefix = t.prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const escapedInterpolation = t.interpolation.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const pattern = new RegExp(
          `data-testid=\\{\`${escapedPrefix}\\$\\{${escapedInterpolation}\\}\`\\}`
        );
        expect(
          SRC,
          `${p.label} — template testid ${t.prefix}\${${t.interpolation}} must still resolve in the source`
        ).toMatch(pattern);
      }
    }
  });

  it("bans stale inline-strip patterns on migrated pages (guard against a partial-migration regression)", () => {
    // If ever someone drops a raw ``backgroundColor:
    // colors.nav.bg`` inline style back into one of these six
    // pages while the delegated <NavyFilterBar> is also present,
    // we'd have two competing paint sources. Guard against that
    // by asserting the raw pattern does NOT appear on the same
    // line/attribute as ``data-testid="…root testid…"``.
    for (const p of PAGES) {
      const SRC = readSrc(p.file);
      const rootIdx = SRC.indexOf(`data-testid="${p.rootTestid}"`);
      expect(rootIdx).toBeGreaterThan(-1);
      // Scan a ~500-char window preceding the root testid — this
      // is where an inline style prop would live if someone
      // reintroduced a raw <div style={…}> around the strip.
      const preceding = SRC.slice(Math.max(0, rootIdx - 500), rootIdx);
      // Only <NavyFilterBar tokens allowed in that window; raw
      // ``<div className="…navy…"`` inline strips are banned.
      expect(preceding, `${p.label} — no raw <div navy-strip> above <NavyFilterBar>`).not.toMatch(
        /<div[\s\S]{0,400}backgroundColor:\s*colors\.nav\.bg[\s\S]{0,400}$/
      );
    }
  });
});
