/**
 * TD-estimate-to-invoice-conversion-doctype-and-balance · Feb-2026 — Vitest.
 *
 * Row-level regression lock for Bug 1 (operator-reported
 * ``INV-2026-00076`` displayed "Estimate" in the InvoicesList
 * "Invoice" column).  The frontend ``InvoicesList.jsx:1070``
 * renders every row's title via
 * ``resolveImportedInvoiceTitleFromLineItem`` (TD-94 pure helper
 * at ``@/lib/portalInvoiceTitle``), so the backend's Fix A
 * (``services/invoice_builder.py`` placeholder-title normalisation)
 * flows through to the UI iff this helper doesn't rewrite the
 * post-fix "Invoice" string.  This test proves it doesn't.
 *
 * Scope deliberately TIGHT — the full InvoicesList component is
 * router + api-driven and hangs under jsdom (same reason the
 * convert-quote-to-invoice vitest covers the handler via a local
 * reimplementation rather than mounting QuoteInvoiceDetail).
 */
import { describe, it, expect } from "vitest";

import { resolveImportedInvoiceTitleFromLineItem }
  from "@/lib/portalInvoiceTitle";


describe("TD-estimate-to-invoice conversion · InvoicesList title column", () => {
  it("post-fix converted invoice (title='Invoice') renders as 'Invoice'", () => {
    // Shape mirrors what the backend's Fix A emits — a converted
    // invoice whose source estimate had a placeholder title gets
    // normalised to ``title="Invoice"`` by the builder.
    const row = {
      id: "inv-converted-001",
      doc_type: "invoice",
      title: "Invoice",
      invoice_number: "INV-2026-00076",
      source: "convert_from_estimate",
      status: "issued",
      line_items: [
        { id: "li1", description: "Pool repair", quantity: 1,
          unit_price: 3855.0 },
      ],
    };
    expect(resolveImportedInvoiceTitleFromLineItem(row)).toBe("Invoice");
    expect(resolveImportedInvoiceTitleFromLineItem(row))
      .not.toBe("Estimate");
  });

  it("pre-fix converted invoice (title='Estimate') would have leaked 'Estimate' — regression repro", () => {
    // This is the operator-reported bug reproduction. Before Fix A,
    // the backend copied source title verbatim and the "Invoice"
    // column rendered the string the admin typed on the estimate
    // (often the "Estimate" default). The helper doesn't launder
    // placeholder titles — that's the BE's job (Fix A). We lock
    // this behaviour so a future refactor doesn't accidentally
    // tie title normalisation to the FE resolver (which would
    // mask the BE regression).
    const legacyRow = {
      id: "inv-legacy-pre-fix",
      doc_type: "invoice",
      title: "Estimate",
      invoice_number: "INV-2026-00076",
      source: "convert_from_estimate",
      status: "draft",
      line_items: [{ id: "li1", description: "Pool repair" }],
    };
    expect(resolveImportedInvoiceTitleFromLineItem(legacyRow))
      .toBe("Estimate");
  });

  it("preserves custom titles verbatim post-conversion", () => {
    // Fix A deliberately only rewrites a tight placeholder set
    // ({"", "estimate", "quote", "proposal", "new estimate",
    // "new quote", "untitled"}). Custom titles pass through
    // backend AND frontend.
    const row = {
      id: "inv-converted-002",
      doc_type: "invoice",
      title: "Pool Repair — Main pump",
      invoice_number: "INV-2026-00077",
      source: "convert_from_quote",
      status: "issued",
      line_items: [{ id: "li1", description: "Pool repair" }],
    };
    expect(resolveImportedInvoiceTitleFromLineItem(row))
      .toBe("Pool Repair — Main pump");
  });
});
