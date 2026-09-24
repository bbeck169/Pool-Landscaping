/**
 * Task E · Feb-2026 · Commit 7/8 — Payments Ledger consolidation
 * source-body contract.
 *
 * Pins:
 *   • Stat-card grid drops from 4-col → 2-col.  Records + Total
 *     collected stay as pure summary tiles.  Method + Status
 *     Card wrappers are removed entirely (they only contained a
 *     select; no summary display to preserve).
 *   • New <NavyFilterBar> above the table Card carries Search,
 *     Method select, Status select, and the Export-CSV button.
 *     Search + selects drive the same URL-param wiring
 *     (``method``, ``status``, ``q``) via the existing
 *     ``useEffect(load, [...])``.
 *   • Every legacy testid still resolves — no consumer had to
 *     be renamed on migration (grep confirmed zero external
 *     references to ``method-select`` / ``status-select`` inner
 *     testids; the outer Card testids
 *     ``payments-filter-method`` / ``payments-filter-status``
 *     migrate onto the new NavyFilterBar.Select controls
 *     verbatim).
 *   • Table Card starts directly with the table body — the
 *     border-top search/export row above the table body is
 *     gone (its two controls now live in the navy strip).
 *   • Date range still comes from <DateRangePicker /> inside
 *     <Header right={…} /> — no visible payments-filter-start /
 *     payments-filter-end pickers on the strip.  Task E leaves
 *     the header-embedded range unchanged.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/finance/FinancePages.jsx"),
  "utf-8",
);


describe("Task E · Commit 7 — Payments Ledger consolidation contract", () => {
  it("drops the stat-card grid from 4-col → 2-col and keeps only the two summary tiles", () => {
    // The new grid uses ``md:grid-cols-2`` (was ``md:grid-cols-4``).
    // The two remaining Cards are Records + Total collected.
    expect(SRC).toMatch(/grid grid-cols-1 md:grid-cols-2 gap-3 mb-4/);
    expect(SRC).not.toMatch(/grid grid-cols-2 md:grid-cols-4 gap-3 mb-4/);
    expect(SRC).toMatch(/testId="payments-total-count"/);
    expect(SRC).toMatch(/testId="payments-total-amount"/);
  });

  it("removes the Method + Status Card wrappers entirely (filters live in the navy strip now)", () => {
    // The pre-migration ``<Card testId="payments-filter-method"``
    // / ``<Card testId="payments-filter-status"`` wrappers are
    // gone.  Their testids migrate onto the NavyFilterBar.Select
    // controls (checked in the next test).
    expect(SRC).not.toMatch(/<Card testId="payments-filter-method"/);
    expect(SRC).not.toMatch(/<Card testId="payments-filter-status"/);
  });

  it("mounts NavyFilterBar with K52.1 marker + payments-filters testid + all 4 controls", () => {
    expect(SRC).toMatch(
      /<NavyFilterBar[\s\S]{0,200}data-testid="payments-filters"/
    );
    expect(SRC).toMatch(/data-k52-navy-strip="true"/);
    // Search delegated to .Search.
    expect(SRC).toMatch(
      /<NavyFilterBar\.Search[\s\S]{0,400}data-testid="payments-search"/
    );
    // Method + Status selects delegated to .Select with their
    // pre-migration outer testids preserved verbatim.
    expect(SRC).toMatch(
      /<NavyFilterBar\.Select[\s\S]{0,400}data-testid="payments-filter-method"/
    );
    expect(SRC).toMatch(
      /<NavyFilterBar\.Select[\s\S]{0,400}data-testid="payments-filter-status"/
    );
    // Export-CSV button lives in the strip's right slot
    // (``ml-auto``).
    const exportIdx = SRC.indexOf('data-testid="payments-export"');
    expect(exportIdx).toBeGreaterThan(-1);
    const exportBlock = SRC.slice(Math.max(0, exportIdx - 500), exportIdx + 60);
    expect(exportBlock).toMatch(/ml-auto/);
  });

  it("still resets page to 1 when method or status changes (page-jump behaviour preserved)", () => {
    // Both selects wrap the pre-migration ``setPage(1)`` reset
    // inside their ``onChange`` handler bodies — a lint/refactor
    // regression here would silently break the pagination sync.
    expect(SRC).toMatch(
      /onChange=\{\(v\) => \{ setMethod\(v\); setPage\(1\); \}\}/
    );
    expect(SRC).toMatch(
      /onChange=\{\(v\) => \{ setStatus\(v\); setPage\(1\); \}\}/
    );
  });

  it("keeps the DateRangePicker inside <Header right={…} /> (no visible date pickers on the strip)", () => {
    // Task E's grep report noted date state lives in
    // ``useDateRange`` but there was no visible
    // payments-filter-start / payments-filter-end picker on the
    // pre-migration filter surface — the range comes from the
    // shared <DateRangePicker /> inside <Header />.  Leaving that
    // untouched per the halt-and-report decision.
    expect(SRC).toMatch(/<Header title="Payments Ledger"[\s\S]{0,200}right=\{<DateRangePicker \/>\}/);
    expect(SRC).not.toMatch(/data-testid="payments-filter-start"/);
    expect(SRC).not.toMatch(/data-testid="payments-filter-end"/);
  });
});
