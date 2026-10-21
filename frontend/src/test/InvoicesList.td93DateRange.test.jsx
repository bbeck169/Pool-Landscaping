/**
 * TD-93 · Feb-2026 — Invoices list date-range filter + dynamic
 * summary-tile labels · Vitest.
 *
 * Locks the FE-side contract shipped by `td93d-fe`:
 *
 *   1. URL params `date_from`, `date_to`, `date_field` are read on
 *      mount; `date_field` defaults to `created_at` (canonical
 *      "invoice date" per the TD-72 convention).
 *   2. Filter cluster renders:
 *        • `NavyFilterBar.DatePicker` label="From"
 *          data-testid="inv-filter-date-from"
 *        • `NavyFilterBar.DatePicker` label="To"
 *          data-testid="inv-filter-date-to"
 *        • `NavyFilterBar.Select` label="By" with
 *          <option value="created_at">Invoice date</option>
 *          <option value="due_date">Due date</option>
 *          data-testid="inv-filter-date-field"
 *   3. `loadRows()` forwards `date_from`, `date_to`, and
 *      (when range active) `date_field` to BOTH `/quotes` and
 *      `/payments/summary` endpoints.
 *   4. useEffect deps include the three new keys so UI
 *      interactions trigger re-fetch.
 *   5. Summary tile labels switch dynamically based on
 *      `rangeActive`:
 *        • Collected: "Collected this month" ↔ "Collected in range"
 *        • Outstanding: "Outstanding" ↔ "Outstanding (in range)"
 *        • Overdue: "Overdue count" ↔ "Overdue count (in range)"
 *   6. Setter helpers (`setDateFrom`, `setDateTo`, `setDateField`)
 *      write to URL params via `setParams(s, { replace: true })`
 *      and strip the param when the user clears the picker or
 *      picks the default `date_field`.
 *   7. Default behaviour preserved when no range: `date_field` is
 *      NOT emitted (summary query stays byte-identical when
 *      range inactive).
 *
 * Pattern: source-guard, matching sibling
 * `test/InvoicesList.defaultUnpaidFilter.test.jsx` + the TD-92c
 * static-contract block.  InvoicesList's full mount hangs jsdom
 * (documented in `invoice-draft-send.test.jsx`), so these specs
 * assert on the JSX source directly for O(1) coverage of the
 * TD-93 contract.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (relative) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf-8");

const INVOICES = read("src/pages/invoices/InvoicesList.jsx");


describe("TD-93 · InvoicesList date-range filter", () => {
  // ─── 1 · URL state hydration ────────────────────────────────────
  it("reads date_from / date_to / date_field from URL params", () => {
    expect(INVOICES).toMatch(
      /const dateFrom = params\.get\("date_from"\)\s*\|\|\s*""/,
    );
    expect(INVOICES).toMatch(
      /const dateTo = params\.get\("date_to"\)\s*\|\|\s*""/,
    );
    expect(INVOICES).toMatch(
      /const dateField = params\.get\("date_field"\)\s*\|\|\s*"created_at"/,
    );
  });

  it("rangeActive derives from the presence of either bound", () => {
    expect(INVOICES).toMatch(
      /const rangeActive = Boolean\(dateFrom \|\| dateTo\)/,
    );
  });

  // ─── 2 · Filter cluster renders the picker pair + toggle ───────
  it("renders NavyFilterBar.DatePicker 'From' with inv-filter-date-from testid", () => {
    expect(INVOICES).toMatch(
      /<NavyFilterBar\.DatePicker[\s\S]{0,200}label="From"[\s\S]{0,200}data-testid="inv-filter-date-from"/,
    );
  });

  it("renders NavyFilterBar.DatePicker 'To' with inv-filter-date-to testid", () => {
    expect(INVOICES).toMatch(
      /<NavyFilterBar\.DatePicker[\s\S]{0,200}label="To"[\s\S]{0,200}data-testid="inv-filter-date-to"/,
    );
  });

  it("renders the By-field NavyFilterBar.Select with both whitelist options", () => {
    expect(INVOICES).toMatch(
      /<NavyFilterBar\.Select[\s\S]{0,300}label="By"[\s\S]{0,300}data-testid="inv-filter-date-field"/,
    );
    expect(INVOICES).toMatch(
      /<option value="created_at">Invoice date<\/option>/,
    );
    expect(INVOICES).toMatch(
      /<option value="due_date">Due date<\/option>/,
    );
  });

  // ─── 3 · Fetch forwarding ──────────────────────────────────────
  it("loadRows forwards date_from / date_to to /quotes querystring", () => {
    expect(INVOICES).toMatch(
      /if \(dateFrom\) qs\.set\("date_from", dateFrom\)/,
    );
    expect(INVOICES).toMatch(
      /if \(dateTo\) qs\.set\("date_to", dateTo\)/,
    );
  });

  it("loadRows emits date_field only when the range is active", () => {
    expect(INVOICES).toMatch(
      /if \(rangeActive\) qs\.set\("date_field", dateField\)/,
    );
  });

  it("loadRows forwards the same three params to /payments/summary", () => {
    expect(INVOICES).toMatch(
      /if \(dateFrom\) summaryQs\.set\("date_from", dateFrom\)/,
    );
    expect(INVOICES).toMatch(
      /if \(dateTo\) summaryQs\.set\("date_to", dateTo\)/,
    );
    expect(INVOICES).toMatch(
      /if \(rangeActive\) summaryQs\.set\("date_field", dateField\)/,
    );
  });

  it("summary path falls back to the bare /payments/summary when range inactive", () => {
    expect(INVOICES).toMatch(
      /summaryQs\.toString\(\)[\s\S]{0,200}"\/payments\/summary"/,
    );
  });

  // ─── 4 · Dynamic summary-tile labels ───────────────────────────
  it("Collected tile label switches via rangeActive ternary", () => {
    expect(INVOICES).toMatch(
      /label=\{rangeActive \? "Collected in range" : "Collected this month"\}/,
    );
  });

  it("Outstanding tile label switches via rangeActive ternary", () => {
    expect(INVOICES).toMatch(
      /label=\{rangeActive \? "Outstanding \(in range\)" : "Outstanding"\}/,
    );
  });

  it("Overdue tile label switches via rangeActive ternary", () => {
    expect(INVOICES).toMatch(
      /label=\{rangeActive \? "Overdue count \(in range\)" : "Overdue count"\}/,
    );
  });

  // ─── 5 · Setter helpers write to URL + strip defaults ──────────
  it("setDateFrom writes the param on truthy input and strips on clear", () => {
    expect(INVOICES).toMatch(
      /const setDateFrom[\s\S]{0,220}s\.set\("date_from", v\)[\s\S]{0,80}s\.delete\("date_from"\)/,
    );
  });

  it("setDateTo writes the param on truthy input and strips on clear", () => {
    expect(INVOICES).toMatch(
      /const setDateTo[\s\S]{0,220}s\.set\("date_to", v\)[\s\S]{0,80}s\.delete\("date_to"\)/,
    );
  });

  it("setDateField strips the param when user picks default 'created_at'", () => {
    expect(INVOICES).toMatch(
      /if \(v && v !== "created_at"\)\s*s\.set\("date_field", v\)/,
    );
    expect(INVOICES).toMatch(
      /const setDateField[\s\S]{0,200}s\.delete\("date_field"\)/,
    );
  });
});
