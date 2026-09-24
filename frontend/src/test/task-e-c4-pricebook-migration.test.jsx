/**
 * Task E · Feb-2026 · Commit 4/8 — Pricebook migration source-body
 * safety net.
 *
 * Two-row Pricebook header contract:
 *   Row 1 — <NavyFilterBar> (search + supplier select).
 *   Row 2 — existing "Items · N + checkbox + Manage Categories +
 *           Add new item" summary/action row (UNCHANGED).
 *
 * This suite pins:
 *   • The navy filter strip lives ABOVE the existing header (so
 *     the "Items · N" row keeps its checkbox / count / link /
 *     button shape).
 *   • Both filter testids ("pb-supplier-filter" +
 *     "pricebook-search-input") still resolve.
 *   • The K52.1 marker (``data-k52-navy-strip="true"``) sits on
 *     the new NavyFilterBar root.
 *   • Task C row-body cells (Commits ``5120940e7``..``b83b80507``)
 *     are NOT collateral damage — both ``CategoryComboCell``
 *     instances (service + income) still render on each row with
 *     their ``pb-cell-service-category-${r.id}`` +
 *     ``pb-cell-income-category-${r.id}`` testids intact.
 *
 * Deep click-to-edit behaviour on the two Task C cells lives in
 * ``task-c-pricebook-inline-category-cells.test.jsx`` — this
 * suite only guards the source-body wiring survives the Task E
 * migration.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/ops/OpsHub.jsx"),
  "utf-8",
);


describe("Task E · Commit 4 — Pricebook two-row header contract", () => {
  it("adds NavyFilterBar as a fresh row inside the PriceBook Card", () => {
    // Locate the PriceBook return + assert NavyFilterBar sits
    // BEFORE the "Items · N + checkbox" summary row.
    const priceBookIdx = SRC.indexOf("<Card testid=\"pricebook-page\">");
    expect(priceBookIdx).toBeGreaterThan(-1);
    const cardBlock = SRC.slice(priceBookIdx, priceBookIdx + 3500);
    // NavyFilterBar mount + K52.1 marker forwarded via ...rest.
    expect(cardBlock).toMatch(/<NavyFilterBar[\s\S]{0,200}data-testid="pricebook-filters"/);
    expect(cardBlock).toMatch(/data-k52-navy-strip="true"/);
    // NavyFilterBar closes BEFORE the checkbox summary row.
    const filterBarEnd = cardBlock.indexOf("</NavyFilterBar>");
    const bulkCheckboxIdx = cardBlock.indexOf("data-testid=\"bulk-select-all\"");
    expect(filterBarEnd).toBeGreaterThan(-1);
    expect(bulkCheckboxIdx).toBeGreaterThan(filterBarEnd);
  });

  it("delegates the two Pricebook filter controls to NavyFilterBar sub-primitives", () => {
    expect(SRC).toMatch(
      /<NavyFilterBar\.Search[\s\S]{0,400}data-testid="pricebook-search-input"/
    );
    expect(SRC).toMatch(
      /<NavyFilterBar\.Select[\s\S]{0,400}data-testid="pb-supplier-filter"/
    );
  });

  it("preserves the existing Items·N summary/action row (checkbox + count + Manage Categories + Add new item)", () => {
    // Every testid on the item-list summary row still resolves —
    // the Task E migration must NOT touch that row's shape.
    expect(SRC).toMatch(/data-testid="bulk-select-all"/);
    expect(SRC).toMatch(/data-testid="pricebook-manage-categories-link"/);
    expect(SRC).toMatch(/testid="pb-new"/);
    // "Items · N" caption + "/N total" filter-applied suffix.
    expect(SRC).toMatch(/Items · \{filteredRows\.length\}/);
    expect(SRC).toMatch(/\/ \{\(rows \|\| \[\]\)\.length\} total/);
  });

  it("keeps both Task C row-body category cells intact (Commits 5120940e7..b83b80507)", () => {
    // Task C · Feb-2026 — each Pricebook row renders TWO
    // ``<CategoryComboCell>`` instances (service + income). This
    // assertion guards against an accidental import or scope
    // regression while migrating the header strip.
    expect(SRC).toMatch(/import CategoryComboCell from "@\/components\/recurring\/CategoryComboCell";/);
    // Both cell testids resolve — computed against ``r.id`` per
    // row iteration.
    expect(SRC).toMatch(/data-testid=\{`pb-cell-service-category-\$\{r\.id\}`\}/);
    expect(SRC).toMatch(/data-testid=\{`pb-cell-income-category-\$\{r\.id\}`\}/);
    // Both cells are still driven through the parameterized
    // ``CategoryComboCell`` primitive (not an inline copy-paste
    // reintroduced during the header migration).
    const cellIdx = SRC.indexOf("pb-cell-service-category-");
    expect(cellIdx).toBeGreaterThan(-1);
    const cellBlock = SRC.slice(cellIdx, cellIdx + 800);
    expect(cellBlock).toMatch(/<CategoryComboCell/);
    const incomeCellIdx = SRC.indexOf("pb-cell-income-category-");
    expect(incomeCellIdx).toBeGreaterThan(-1);
    const incomeCellBlock = SRC.slice(incomeCellIdx, incomeCellIdx + 800);
    expect(incomeCellBlock).toMatch(/<CategoryComboCell/);
  });
});
