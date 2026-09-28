/**
 * FIN-PARITY-B · Feb-2026 — Invoices list defaults to Unpaid.
 *
 * Locks the FE-side contract:
 *
 *   1. Initial mount fetches ``/quotes?payment_status=unpaid`` —
 *      the URL param defaults to ``"unpaid"`` when absent, and
 *      that value is forwarded verbatim to the backend
 *      querystring.
 *   2. Dropdown options are exactly: Unpaid (default) / Partial /
 *      Paid / All (in that order).
 *   3. Changing the dropdown updates the URL via
 *      ``setSearchParams`` and refetches with the new value.
 *   4. The ``setStatus`` writer strips the URL param when the
 *      user picks the default (``unpaid``) so shareable URLs
 *      stay clean.
 *   5. Client-side ``.filter((r) => (status ? ... ))`` is gone —
 *      the backend is the source of truth.
 *   6. The subtitle shows a count that follows the current filter
 *      ("N unpaid invoices" / "N invoices" for All).
 *
 * Pattern: source-guard, matching ``render-path-filter-chip-pages``
 * and ``k40-default-filters``. InvoicesList is router + fetch +
 * modal heavy — mounting it end-to-end hangs jsdom (documented in
 * ``invoice-draft-send.test.jsx``), so we assert on the JSX source
 * directly for O(1) coverage of the payment-status contract.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (relative) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf-8");

const INVOICES = read("src/pages/invoices/InvoicesList.jsx");


describe("FIN-PARITY-B · InvoicesList default unpaid filter", () => {
  // ─── 1. URL default = 'unpaid' ─────────────────────────────
  it("payment_status URL param defaults to 'unpaid' on mount", () => {
    expect(INVOICES).toMatch(
      /const paymentStatusFilter = params\.get\("payment_status"\)\s*\|\|\s*"unpaid"/,
    );
  });

  it("legacy ``status`` URL param no longer reads default '' back", () => {
    expect(INVOICES).not.toMatch(
      /const status = params\.get\("status"\)\s*\|\|\s*""/,
    );
  });


  // ─── 2. Fetch forwards payment_status to the backend ───────
  it("loadRows() emits ``qs.set('payment_status', ...)``", () => {
    expect(INVOICES).toMatch(
      /qs\.set\("payment_status", paymentStatusFilter\)/,
    );
  });

  it("loadRows() calls the ``/quotes`` endpoint with the built qs", () => {
    expect(INVOICES).toMatch(
      /api\.get\(`\/quotes\?\$\{qs\.toString\(\)\}`\)/,
    );
  });


  // ─── 3. useEffect refetches when the filter changes ────────
  it("useEffect deps include paymentStatusFilter so dropdown re-fetches", () => {
    expect(INVOICES).toMatch(
      /\[selectedCategories\.join\("\|"\),\s*customerFilter,\s*paymentStatusFilter\]/,
    );
  });


  // ─── 4. Dropdown options ──────────────────────────────────
  it("dropdown option order is Unpaid / Partial / Paid / All", () => {
    const optionOrder = [
      /<option value="unpaid">Unpaid<\/option>/,
      /<option value="partial">Partial<\/option>/,
      /<option value="paid">Paid<\/option>/,
      /<option value="all">All statuses<\/option>/,
    ];
    // Consume the file sequentially — each regex must match ONCE and
    // in order. This catches a reordering regression that a bare
    // toMatch on each pattern would miss.
    let cursor = 0;
    for (const re of optionOrder) {
      const hit = INVOICES.substring(cursor).search(re);
      expect(hit).toBeGreaterThan(-1);
      cursor += hit + 1;
    }
  });

  it("dropdown ``value`` is bound to paymentStatusFilter (not legacy ``status``)", () => {
    expect(INVOICES).toMatch(
      /value=\{paymentStatusFilter\}[^>]*data-testid="inv-filter-status"/s,
    );
  });


  // ─── 5. setStatus writes ``payment_status`` to URL ────────
  it("setStatus writes ``payment_status`` param on non-default choices", () => {
    expect(INVOICES).toMatch(
      /if\s*\(v && v !== "unpaid"\)\s*s\.set\("payment_status", v\)/,
    );
  });

  it("setStatus strips the param when the user picks default", () => {
    expect(INVOICES).toMatch(
      /else\s+s\.delete\("payment_status"\)/,
    );
  });


  // ─── 6. Client-side status filter is gone ─────────────────
  it("client-side payment_status filter is removed", () => {
    // The pre-FIN-PARITY-B implementation had a runtime filter
    // ``.filter((r) => (status ? (r.payment_status || 'unpaid')
    // === status : true))`` — the backend is the source of truth
    // now.
    expect(INVOICES).not.toMatch(
      /\.filter\(\(r\)\s*=>\s*\(status\s*\?\s*\(r\.payment_status/,
    );
  });


  // ─── 7. Header count reflects current filter ──────────────
  it("subtitle renders the row count suffixed with the filter value", () => {
    // Regex intentionally loose — matches any implementation
    // that concatenates the row count with a payment-status-
    // derived suffix.
    expect(INVOICES).toMatch(
      /\$\{count\}\s+\$\{suffix\}/,
    );
    // AND: the suffix must special-case "all" so it doesn't
    // render "N all invoices" (would look broken to users).
    expect(INVOICES).toMatch(
      /paymentStatusFilter === "all"[\s\S]{0,80}"invoices"/,
    );
  });


  // ─── 8. useSearchParams wiring preserved ──────────────────
  it("uses useSearchParams (not local useState) so URL is shareable", () => {
    expect(INVOICES).toMatch(
      /import \{[^}]*useSearchParams[^}]*\} from "react-router-dom"/,
    );
  });
});
