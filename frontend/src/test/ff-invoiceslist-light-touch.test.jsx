/**
 * Ticket FF · Feb-2026 · Commit E — Main admin InvoicesList
 * light-touch update.
 *
 * Scope locks (source-level — the full mount hangs jsdom per the
 * notes in ``InvoiceAgingReport.jsx`` and ``InvoicesList.td93*``
 * sibling tests):
 *   1. Title source: ``resolveImportedInvoiceTitleFromLineItem``
 *      replaced by shared ``getInvoiceDisplayTitle`` — FF
 *      case-reorder (Commit A) + first-line-item-name retroactive
 *      behaviour propagates here too.
 *   2. Status badge: inline per-status ternary replaced with the
 *      shared ``getInvoiceStatusTone`` mapper (same draft→red
 *      override + paid→green + unpaid→red + else-neutral rule as
 *      the admin tab + portal).
 *   3. Customer column: ``hidden md:table-cell`` removed from
 *      both the header AND the row cell — always visible.
 *
 * Preserved (NOT touched):
 *   * Bulk-select checkbox column (Phase 34 · BB).
 *   * Sortable headers (``_SortableTh`` throughout).
 *   * ``Viewed`` indicator column (Phase K47 · TD-95).
 *   * ``Card on file`` column.
 *   * All filtering (CustomerFilterBar, status chips).
 *   * Row click → ``/invoices/${id}``.
 *   * Due date column + bulk-charge dialog table block.
 *
 * See ``TD-invoice-main-list-7col-strip`` for the follow-up
 * decision on whether to collapse this 9-col surface to the
 * operator's 7-col shape (would regress bulk + sort + viewed +
 * card-on-file UX — intentionally deferred).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/invoices/InvoicesList.jsx"),
  "utf-8",
);

describe("Ticket FF · Commit E — InvoicesList light-touch locks", () => {
  it("title source migrated: getInvoiceDisplayTitle in, TD-94 resolver out", () => {
    expect(SRC).toMatch(
      /import\s+\{\s*getInvoiceDisplayTitle\s*\}\s+from\s+"@\/utils\/invoiceTitle"/,
    );
    expect(SRC).toMatch(/getInvoiceDisplayTitle\(r\)/);
    // Negative — the TD-94 helper is no longer imported or
    // CALLED in this file (a code comment on the migration is
    // allowed and expected).
    expect(SRC).not.toMatch(
      /import\s*\{[^}]*resolveImportedInvoiceTitleFromLineItem/,
    );
    expect(SRC).not.toMatch(/resolveImportedInvoiceTitleFromLineItem\(r\)/);
  });

  it("status badge wired through shared getInvoiceStatusTone", () => {
    expect(SRC).toMatch(
      /import\s+\{\s*getInvoiceStatusTone\s*\}\s+from\s+"@\/utils\/invoiceStatusTone"/,
    );
    expect(SRC).toMatch(/getInvoiceStatusTone\(r\)/);
    // Negative — the pre-FF three-way ternary tone map on
    // ``payment_status === "paid" ? "success" ...`` is gone.
    expect(SRC).not.toMatch(
      /tone=\{\s*r\.payment_status\s*===\s*"paid"\s*\?\s*"success"\s*:\s*r\.payment_status\s*===\s*"partial"\s*\?\s*"warning"\s*:\s*"danger"\s*\}/,
    );
  });

  it("Customer column is always visible (hidden md:table-cell removed)", () => {
    // Header: no ``hidden md:table-cell`` on the Customer <_SortableTh>.
    expect(SRC).toMatch(
      /_SortableTh\s+label="Customer"\s+col="customer_name"\s+sort=\{sort\}\s+setSort=\{setSort\}\s*\/>/,
    );
    // Row cell: locate the single-line <td> that carries the
    // invoice-row-customer testid and lint for absence of the
    // responsive-hide class on that line.
    const rowCellLine = SRC
      .split("\n")
      .find((l) => l.includes("data-testid={`invoice-row-customer-${r.id}`}"));
    expect(rowCellLine).toBeTruthy();
    expect(rowCellLine).not.toMatch(/hidden md:table-cell/);
    expect(rowCellLine).toMatch(/<CustomerLink/);
  });

  it("Phase 34 bulk-select column + K47 Viewed column preserved (no strip)", () => {
    // Positive locks confirming we did NOT regress the 7-col
    // operator-shape strip (deferred to TD-invoice-main-list-7col-strip).
    expect(SRC).toMatch(/data-testid="bulk-select-all"/);
    expect(SRC).toMatch(/_SortableTh\s+label="Viewed"/);
    expect(SRC).toMatch(/data-testid=\{`invoice-card-\$\{r\.id\}`\}/);
  });
});
