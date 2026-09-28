/**
 * PDF-HUB · Feb-2026 — Preview table Type column vitest suite.
 *
 * Locks the render contract for the new "Type" column added
 * between "Invoice #" and "Date":
 *
 *   1. ``DocKindPill`` renders the correct label + color class
 *      for each doc_kind (invoice / estimate / payment_receipt).
 *   2. Unknown / missing doc_kind falls back to a neutral pill
 *      so the column never renders blank.
 *   3. Full PreviewRow renders the pill cell with the right
 *      data-testid so the FE integration flow can bind to it.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { DocKindPill, PreviewRow } from "@/pages/admin/imports/PdfInvoiceImportPage";


describe("PDF-HUB · DocKindPill · label + color per doc_kind", () => {
  it("renders 'Invoice' with a blue pill when doc_kind='invoice'", () => {
    render(<DocKindPill docKind="invoice" testid="dk-inv" />);
    const el = screen.getByTestId("dk-inv");
    expect(el.textContent).toBe("Invoice");
    // Tailwind blue-100 / blue-800 classnames applied.
    expect(el.className).toMatch(/bg-blue-100/);
    expect(el.className).toMatch(/text-blue-800/);
    expect(el.getAttribute("data-doc-kind")).toBe("invoice");
  });

  it("renders 'Estimate' with a green (emerald) pill when doc_kind='estimate'", () => {
    render(<DocKindPill docKind="estimate" testid="dk-est" />);
    const el = screen.getByTestId("dk-est");
    expect(el.textContent).toBe("Estimate");
    expect(el.className).toMatch(/bg-emerald-100/);
    expect(el.className).toMatch(/text-emerald-800/);
    expect(el.getAttribute("data-doc-kind")).toBe("estimate");
  });

  it("renders 'Payment' with a purple (violet) pill when " +
     "doc_kind='payment_receipt' (backend internal literal)", () => {
    render(<DocKindPill docKind="payment_receipt" testid="dk-pay" />);
    const el = screen.getByTestId("dk-pay");
    expect(el.textContent).toBe("Payment");
    expect(el.className).toMatch(/bg-violet-100/);
    expect(el.className).toMatch(/text-violet-800/);
    expect(el.getAttribute("data-doc-kind")).toBe("payment_receipt");
  });

  it("accepts the shorter 'payment' alias (FE dropdown value) and " +
     "renders the same purple pill", () => {
    render(<DocKindPill docKind="payment" testid="dk-pay2" />);
    const el = screen.getByTestId("dk-pay2");
    expect(el.textContent).toBe("Payment");
    expect(el.className).toMatch(/bg-violet-100/);
  });

  it("falls back to a neutral 'Unknown' pill for missing / weird " +
     "doc_kind so the column never renders blank", () => {
    for (const val of [null, undefined, "", "totally_unknown_value"]) {
      const { unmount } = render(<DocKindPill docKind={val} testid="dk-fb" />);
      const el = screen.getByTestId("dk-fb");
      expect(el.textContent).toBe("Unknown");
      expect(el.className).toMatch(/bg-slate-100/);
      unmount();
    }
  });
});


describe("PDF-HUB · PreviewRow · Type cell", () => {
  it("wires the pill into the row with the expected data-testid", () => {
    const preview = {
      source_doc_index: 7,
      doc_kind: "invoice",
      mapped_target: "quote_in",
      quote_in: {
        doc_number: "INV-42",
        doc_date: "2026-02-14",
        grand_total: 199.95,
      },
    };
    // PreviewRow renders a ``<tr>``; wrap in a table so the DOM
    // is valid.
    render(
      <table>
        <tbody>
          <PreviewRow
            preview={preview}
            duplicate={null}
            fileId="testfile"
          />
        </tbody>
      </table>
    );
    const cell = screen.getByTestId(
      "pdf-import-preview-row-testfile-7-type-cell"
    );
    expect(cell).toBeTruthy();
    const pill = screen.getByTestId(
      "pdf-import-preview-row-testfile-7-type-pill"
    );
    expect(pill).toBeTruthy();
    expect(pill.textContent).toBe("Invoice");
    expect(pill.className).toMatch(/bg-blue-100/);
  });

  it("renders the Purple/Payment pill when preview.doc_kind = " +
     "'payment_receipt'", () => {
    const preview = {
      source_doc_index: 3,
      doc_kind: "payment_receipt",
      mapped_target: "quote_in",  // filter-friendly for the current table
      quote_in: {
        doc_number: "PMT-99",
        doc_date: "2026-02-14",
        grand_total: 50.0,
      },
    };
    render(
      <table>
        <tbody>
          <PreviewRow
            preview={preview}
            duplicate={null}
            fileId="pay-test"
          />
        </tbody>
      </table>
    );
    const pill = screen.getByTestId(
      "pdf-import-preview-row-pay-test-3-type-pill"
    );
    expect(pill.textContent).toBe("Payment");
    expect(pill.className).toMatch(/bg-violet-100/);
  });
});
