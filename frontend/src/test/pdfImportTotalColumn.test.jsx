/**
 * PDF-FIX-A · Feb-2026 — Preview table "Total" column priority.
 *
 * Locks the display contract shipped alongside the mapper's
 * ``quote_in.grand_total`` field-add — the FE Preview column
 * now reads:
 *
 *   formatCurrency(
 *     q.grand_total
 *     ?? q.total_due
 *     ?? q.amount_paid
 *     ?? 0
 *   )
 *
 * Priority chain
 * ──────────────
 *   1. ``grand_total`` — extractor's stated total (the "Total"
 *      or "Total Due" line on the source PDF). Wins even when
 *      ``total_due`` is $0.00 on a fully-paid invoice.
 *   2. ``total_due`` — legacy field. What the customer owes.
 *   3. ``amount_paid`` — kept for Sub-phase B's fully-paid
 *      receipt case (invoice sans grand_total sans total_due
 *      but with a captured payment amount).
 *   4. ``0`` — safe default. ``formatCurrency(0)`` renders as
 *      "$0.00" — never crashes on missing fields.
 *
 * ``??`` (nullish coalescing) treats ``0`` as a valid value, so
 * a legitimately-waived invoice (``grand_total === 0``) still
 * renders as "$0.00" verbatim per PDF-FIX rulings §1 — NOT a
 * fallback trigger.
 *
 * Test seam: ``PreviewRow`` is exported as a named symbol so
 * we can drive it directly with canned envelopes (same pattern
 * used for ``CommittedSummary`` / ``WarningsBanner`` in
 * ``pdfImportUnifiedUI.test.jsx``). ``<tr>`` cannot render
 * outside a ``<table>``, so each render wraps it in a
 * ``<table><tbody>`` shell.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  },
}));

import { PreviewRow } from "@/pages/admin/imports/PdfInvoiceImportPage";


function renderRow(quote_in, { fileId = "f1", sourceIdx = 0 } = {}) {
  const preview = {
    source_doc_index: sourceIdx,
    doc_kind: "invoice",
    mapped_target: "quote_in",
    customer_resolution: "matched",
    matched_customer_id: "cust-a1",
    quote_in,
  };
  return render(
    <table>
      <tbody>
        <PreviewRow preview={preview} duplicate={null} fileId={fileId} />
      </tbody>
    </table>,
  );
}


function totalCellText(fileId = "f1", sourceIdx = 0) {
  const el = screen.getByTestId(
    `pdf-import-preview-row-${fileId}-${sourceIdx}-total`,
  );
  return el.textContent.trim();
}


describe("PDF Import · Preview Total column priority (PDF-FIX-A)", () => {
  it("(a) grand_total wins over total_due on a fully-paid invoice", () => {
    renderRow({
      doc_number: "INV-1001",
      doc_date: "2026-02-01",
      customer_name: "Acme Pools",
      grand_total: 400.00,
      total_due: 0.00,           // fully paid — legacy field is $0
      amount_paid: 400.00,
    });
    // Format: "$400.00". Locale may inject a non-breaking space
    // between the symbol and digits in some browsers; accept both.
    expect(totalCellText()).toMatch(/^\$400\.00/);
  });

  it("(b) falls back to total_due when grand_total is absent", () => {
    renderRow({
      doc_number: "INV-1002",
      doc_date: "2026-02-02",
      customer_name: "Blue Wave",
      // no grand_total
      total_due: 250.00,
    });
    expect(totalCellText()).toMatch(/^\$250\.00/);
  });

  it("(c) preserves grand_total = 0 verbatim (not a fallback trigger)", () => {
    renderRow({
      doc_number: "INV-1003",
      doc_date: "2026-02-03",
      customer_name: "Sunshine Landscaping",
      grand_total: 0.00,          // legitimately waived invoice
      total_due: 250.00,          // MUST NOT win
    });
    // If the code used || (truthiness), this would render as
    // $250.00. ?? correctly returns 0.
    expect(totalCellText()).toMatch(/^\$0\.00/);
  });

  it("(d) renders $0.00 safe default when no total fields present", () => {
    renderRow({
      doc_number: "INV-1004",
      doc_date: "2026-02-04",
      customer_name: "Palms & Pines Co",
      // no grand_total, no total_due, no amount_paid
    });
    // Tail ``?? 0`` in the chain guarantees a numeric input to
    // formatCurrency, which then renders "$0.00" (not "—").
    expect(totalCellText()).toMatch(/^\$0\.00/);
  });

  it("(bonus) falls back to amount_paid when grand_total + total_due absent", () => {
    // Sub-phase B legacy behaviour — a payment-receipt-style
    // preview row without grand_total OR total_due still surfaces
    // the captured payment amount rather than $0.00.
    renderRow({
      doc_number: "PMT-1005",
      doc_date: "2026-02-05",
      customer_name: "Fully Paid LLC",
      amount_paid: 175.00,
    });
    expect(totalCellText()).toMatch(/^\$175\.00/);
  });
});
