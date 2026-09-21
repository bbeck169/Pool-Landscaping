/**
 * Phase P14 · Feb-2026 · Item 4 — UI polish source-shape contract.
 *
 * Locks in the two shape invariants:
 *   1. Edit Recurring Job modal content has ``max-h-[90vh]`` on
 *      its shell + the body uses ``overflow-y-auto flex-1
 *      min-h-0`` so Save stays reachable on short viewports.
 *   2. The Recurring Jobs table wrapper carries ``overflow-x-auto``
 *      so the Edit column stays reachable on narrow viewports.
 *
 * Source-scan is the pragmatic tool here — ``RecurringJobs.jsx``
 * is a ~1700 LOC surface with heavy customer / crew / category
 * fetch orchestration that makes a full JSDOM mount slow and
 * brittle. If someone refactors either invariant out, these
 * assertions fail loudly.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC_PATH = path.resolve(
  __dirname, "../pages/admin/RecurringJobs.jsx",
);
const src = fs.readFileSync(SRC_PATH, "utf8");


describe("Phase P14 · Item 4 · Edit Recurring Job modal height cap", () => {
  it("modal shell carries max-h-[90vh] on the flex container", () => {
    // The modal's outermost card gets the height cap so the
    // footer stays visible on short viewports.
    expect(src).toMatch(
      /className="w-full max-w-lg rounded-2xl max-h-\[90vh\] flex flex-col"/,
    );
  });

  it("modal body scrolls via overflow-y-auto flex-1 min-h-0 (safari flex-overflow fix)", () => {
    // ``min-h-0`` is the critical bit — without it the scroll
    // never kicks in inside a flex parent (a known Safari gotcha).
    expect(src).toMatch(
      /overflow-y-auto flex-1 min-h-0/,
    );
  });

  it("modal header and footer are shrink-0 (Save button never scrolls out of view)", () => {
    // Two occurrences expected — header + footer.
    const matches = src.match(/shrink-0/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });
});


describe("Phase P14 · Item 4 · Recurring Jobs table wrapper", () => {
  it("table is wrapped in a div carrying overflow-x-auto", () => {
    // Locate the ``<table data-testid="recurring-jobs-table">`` line
    // and peek at the ~200 chars BEFORE it — the parent div lives
    // right above.
    const idx = src.indexOf('data-testid="recurring-jobs-table"');
    expect(idx).toBeGreaterThan(0);
    const before = src.slice(Math.max(0, idx - 300), idx);
    expect(before).toMatch(/className="[^"]*overflow-x-auto[^"]*"/);
  });

  it("table itself keeps w-full text-sm (no column-width changes)", () => {
    expect(src).toMatch(
      /<table className="w-full text-sm" data-testid="recurring-jobs-table">/,
    );
  });
});


describe("Phase P14 · Item 2 · Purge-orphans banner wiring", () => {
  it("banner renders when EITHER orphanPreview.orphan_count OR purgePreview.count > 0", () => {
    // Guard: the yellow banner still shows on backfill-only cases
    // (existing behaviour) AND on purge-only cases (new).
    expect(src).toMatch(
      /\(orphanPreview && orphanPreview\.orphan_count > 0\)[\s\n]*\|\|[\s\n]*\(purgePreview && purgePreview\.count > 0\)/,
    );
  });

  it("red purge button carries the ``recurring-jobs-purge-btn`` testid", () => {
    expect(src).toContain('data-testid="recurring-jobs-purge-btn"');
  });

  it("confirm dialog gates on typing DELETE (client + server both check)", () => {
    // The commit button is disabled until purgeInput === "DELETE".
    expect(src).toMatch(
      /purgeBusy \|\| \(purgeInput \|\| ""\)\.trim\(\) !== "DELETE"/,
    );
    // And the POST body carries ``confirm: "DELETE"``.
    expect(src).toMatch(
      /post\(\s*"\/recurring-jobs\/purge-orphans"\s*,\s*\{\s*confirm:\s*"DELETE"\s*\}/,
    );
  });

  it("purge-preview fetch runs after main load (best-effort)", () => {
    expect(src).toMatch(/api\.get\("\/recurring-jobs\/purge-orphans-preview"\)/);
  });
});
