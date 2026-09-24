/**
 * Task E · Feb-2026 · Commit 5/8 — Recurring Jobs migration
 * source-body safety net.
 *
 * Contract:
 *   Row 1 — <NavyFilterBar> (search + service-category select).
 *   Row 2 — the RecurringJobs table (UNCHANGED — Task C inline
 *           category cells preserved on every row).
 *
 * This suite pins:
 *   • Both filter testids ("recurring-search-input" +
 *     "recurring-jobs-service-category-filter") still resolve.
 *   • The optional Clear-X still ships with its legacy
 *     "recurring-search-clear" testid (routed through
 *     NavyFilterBar.Search's ``clearTestid`` override).
 *   • The K52.1 marker (``data-k52-navy-strip="true"``) sits on
 *     the new NavyFilterBar root.
 *   • Task C row-body cells (Commits ``5120940e7``..``b83b80507``)
 *     are NOT collateral damage — both ``CategoryComboCell``
 *     instances (service + income) still render on each row.
 *
 * Deep click-to-edit behaviour on the two Task C cells lives in
 * ``p4-recurring-jobs-category-dropdowns.test.jsx`` — this suite
 * only guards the source-body wiring survives the Task E
 * migration.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/admin/RecurringJobs.jsx"),
  "utf-8",
);


describe("Task E · Commit 5 — Recurring Jobs migration contract", () => {
  it("mounts NavyFilterBar with the K52.1 marker and page testid", () => {
    expect(SRC).toMatch(
      /<NavyFilterBar[\s\S]{0,200}data-testid="recurring-jobs-filters"/
    );
    expect(SRC).toMatch(/data-k52-navy-strip="true"/);
  });

  it("delegates the search input to NavyFilterBar.Search with the legacy testids preserved", () => {
    // Both the input testid AND the Clear-button testid stay on
    // their pre-migration values (``clearTestid`` override).
    expect(SRC).toMatch(
      /<NavyFilterBar\.Search[\s\S]{0,600}data-testid="recurring-search-input"/
    );
    expect(SRC).toMatch(/clearTestid="recurring-search-clear"/);
    // Controlled state hooks unchanged.
    expect(SRC).toMatch(/value=\{searchInput\}/);
    expect(SRC).toMatch(/onChange=\{setSearchInput\}/);
    expect(SRC).toMatch(/onClear=\{\(\) => setSearchInput\(""\)\}/);
  });

  it("delegates the service-category select to NavyFilterBar.Select with the legacy testid preserved", () => {
    expect(SRC).toMatch(
      /<NavyFilterBar\.Select[\s\S]{0,600}data-testid="recurring-jobs-service-category-filter"/
    );
    expect(SRC).toMatch(/value=\{serviceCategoryFilter\}/);
    expect(SRC).toMatch(/onChange=\{setServiceCategoryFilter\}/);
  });

  it("keeps both Task C row-body category cells intact (Commits 5120940e7..b83b80507)", () => {
    // Task C · Feb-2026 — each RecurringJobs row renders TWO
    // ``<CategoryComboCell>`` instances (service + income). This
    // assertion guards against an accidental import/scope
    // regression while migrating the header filter strip.
    expect(SRC).toMatch(/import CategoryComboCell from "@\/components\/recurring\/CategoryComboCell";/);
    expect(SRC).toMatch(/data-testid=\{`recurring-cell-service-category-\$\{r\.id\}`\}/);
    expect(SRC).toMatch(/data-testid=\{`recurring-cell-income-category-\$\{r\.id\}`\}/);
    // Both cells still resolve through the parameterized
    // CategoryComboCell primitive.
    const svcIdx = SRC.indexOf("recurring-cell-service-category-");
    expect(svcIdx).toBeGreaterThan(-1);
    const svcBlock = SRC.slice(svcIdx, svcIdx + 1200);
    expect(svcBlock).toMatch(/<CategoryComboCell/);
    const incIdx = SRC.indexOf("recurring-cell-income-category-");
    expect(incIdx).toBeGreaterThan(-1);
    const incBlock = SRC.slice(incIdx, incIdx + 1200);
    expect(incBlock).toMatch(/<CategoryComboCell/);
  });
});
