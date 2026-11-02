/**
 * Nov-2026 · TD-invoice-outstanding-balance-phantom-field-fix —
 * FE label rename regression lock.
 *
 * Locks the two label-render sites in
 * ``frontend/src/components/InvoiceView.jsx``:
 *   * Header kv-table — Prior Balance (was "Outstanding Balance").
 *   * Payment-stub table — Prior Balance (was "Outstanding Balance").
 *
 * The JSON key ``header.outstanding_balance`` is unchanged — only
 * the DISPLAYED LABEL changed.  So the data-flow regression is
 * covered by the pytest backend suite; this file only locks the
 * FE label text.
 *
 * Source-level inspection following the shipped idiom at
 * ``view-as-customer-popup-blocker-fix.test.jsx`` — the InvoiceView
 * component depends on a tangle of layout CSS + print paths that
 * render-based tests struggle with.  Grep + string assertions give
 * crisp regression-lock without the setup cost.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PATH = resolve(__dirname, "../components/InvoiceView.jsx");
const src = readFileSync(PATH, "utf8");


describe("InvoiceView · Prior Balance label rename", () => {
  it("header kv-row uses 'Prior Balance' label", () => {
    // The header kv-row is rendered inside a <tr><td className=
    // "iv-kv-label">Prior Balance</td>...</tr>.  Match loosely on
    // the label-cell shape so a className reorder doesn't break
    // the test.
    expect(src).toMatch(
      /className="iv-kv-label">Prior Balance<\/td>/,
    );
  });

  it("payment-stub table uses 'Prior Balance' label", () => {
    // The payment-stub row is a compact <tr><td>Prior Balance</td>
    // <td>{...}</td></tr>.  Match on the exact label shape.
    expect(src).toMatch(
      /<tr><td>Prior Balance<\/td><td>\{formatCurrency\(header\.outstanding_balance\)\}<\/td><\/tr>/,
    );
  });

  it("old 'Outstanding Balance' label is NOT present in render code", () => {
    // Pre-ticket the label was 'Outstanding Balance' at both sites.
    // Post-ticket this string must NOT appear anywhere in the FE
    // component (comments permitted since the component carries
    // no ``//`` or ``/*`` block referencing the old label).
    expect(src).not.toContain("Outstanding Balance");
  });

  it("JSON key ``header.outstanding_balance`` is still consumed (API contract preserved)", () => {
    // Rename is label-only.  The response field key stays stable
    // so other consumers aren't broken.
    expect(src).toMatch(/header\.outstanding_balance/);
    // And the ``invoice-outstanding-balance`` testid stays stable
    // so existing e2e / automation that targets this cell by
    // testid keeps working.
    expect(src).toContain('data-testid="invoice-outstanding-balance"');
  });
});
