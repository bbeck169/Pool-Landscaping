/**
 * Feb-2026 · PDF Import Hub Bug Fixes vitests.
 *
 * Covers the three preview-row UX concerns from the Joe Kail
 * estimate QA report. Exercises ``DocKindPill`` + ``PreviewRow``
 * directly (both exported from PdfInvoiceImportPage.jsx) so the
 * tests don't require the full page-load harness.
 *
 *   1. Operator picks "Estimate" → row Type pill reads "Estimate"
 *      and the "AI said: Invoice" secondary chip renders when
 *      ``quote_in.doc_type_user_override === true``.
 *   2. Row with ≥1 line item → chevron is enabled.
 *   3. Row with 0 line items → chevron is disabled with the
 *      "No line items extracted" tooltip.
 *   4. Row with ``customer_extraction_confidence === "low"`` shows
 *      the amber warning triangle next to the customer name with
 *      a tooltip.
 *   5. Expanded row with ``line_total_subtotal_mismatch_cents > 1``
 *      renders the amber mismatch warning inside the panel.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  DocKindPill, PreviewRow,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


describe("DocKindPill · Bug 1 'AI said' secondary chip", () => {
  it("renders 'AI said: Invoice' chip when override differs from auto", () => {
    render(
      <DocKindPill
        docKind="estimate"
        autoDetectedDocKind="invoice"
        testid="pill-under-test"
      />,
    );
    const pill = screen.getByTestId("pill-under-test");
    expect(pill.textContent).toBe("Estimate");
    const aiBadge = screen.getByTestId("pill-under-test-ai-said");
    expect(aiBadge.textContent).toContain("AI said: Invoice");
    expect(aiBadge.getAttribute("title")).toContain("overridden");
  });

  it("hides 'AI said' chip when override matches auto-detected", () => {
    render(
      <DocKindPill
        docKind="estimate"
        autoDetectedDocKind="estimate"
        testid="pill-match"
      />,
    );
    expect(
      screen.queryByTestId("pill-match-ai-said"),
    ).not.toBeInTheDocument();
  });

  it("hides 'AI said' chip when autoDetectedDocKind is absent", () => {
    render(<DocKindPill docKind="invoice" testid="pill-no-auto" />);
    expect(
      screen.queryByTestId("pill-no-auto-ai-said"),
    ).not.toBeInTheDocument();
  });
});


function _buildPreview({
  line_items = null,
  customer_name = "Alice Example",
  customer_extraction_confidence = null,
  customer_name_suspect_value = null,
  doc_type = "quote",
  doc_type_user_override = false,
  auto_detected_doc_type = null,
  line_total_subtotal_mismatch_cents = 0,
  customer_resolution = "matched",
  doc_kind = "estimate",
  source_doc_index = 0,
} = {}) {
  return {
    source_doc_index,
    doc_kind,
    mapped_target: "quote_in",
    customer_resolution,
    quote_in: {
      customer_name,
      doc_number: "346",
      doc_date: null,
      doc_type,
      auto_detected_doc_type,
      doc_type_user_override,
      customer_extraction_confidence,
      customer_name_suspect_value,
      line_total_subtotal_mismatch_cents,
      line_items: line_items === null
        ? [{
            item_name: "Weekly Pool Service",
            description: "Weekly Pool Service",
            quantity: 1, unit_price: 150, line_total: 150,
          }]
        : line_items,
      grand_total: 150, total_due: 150, subtotal: 150, amount_paid: 0,
    },
  };
}


function _renderRow(preview, overrides = {}) {
  return render(
    <table><tbody>
      <PreviewRow
        preview={preview}
        duplicate={false}
        fileId="f1"
        expanded={Boolean(overrides.expanded)}
        onToggle={() => {}}
      />
    </tbody></table>,
  );
}


describe("PreviewRow · Bug 2 defensive · chevron disabled on 0 line items", () => {
  it("chevron is disabled with tooltip when line_items.length === 0", () => {
    _renderRow(_buildPreview({ line_items: [] }));
    const btn = screen.getByTestId("pdf-import-line-items-toggle-f1-0");
    expect(btn).toBeDisabled();
    expect(btn.getAttribute("title")).toBe("No line items extracted");
    expect(btn.getAttribute("data-no-line-items")).toBe("true");
  });

  it("chevron is enabled when ≥1 renderable line item exists", () => {
    _renderRow(_buildPreview());
    const btn = screen.getByTestId("pdf-import-line-items-toggle-f1-0");
    expect(btn).not.toBeDisabled();
    expect(btn.getAttribute("data-no-line-items")).toBe("false");
  });
});


describe("PreviewRow · Bug 3 · low-confidence customer warning triangle", () => {
  it("renders warning triangle when customer_extraction_confidence='low'", () => {
    _renderRow(_buildPreview({
      customer_name: "—",
      customer_extraction_confidence: "low",
      customer_name_suspect_value: "346",
    }));
    const warning = screen.getByTestId(
      "pdf-import-preview-row-0-customer-low-confidence",
    );
    expect(warning).toBeInTheDocument();
    const title = warning.getAttribute("title") || "";
    expect(title).toContain("review");
    expect(title).toContain("346");
  });

  it("does NOT render warning when extraction confidence is absent", () => {
    _renderRow(_buildPreview());
    expect(
      screen.queryByTestId(
        "pdf-import-preview-row-0-customer-low-confidence",
      ),
    ).not.toBeInTheDocument();
  });
});


describe("PreviewRow · Bug 2 defensive · subtotal mismatch amber banner", () => {
  it("renders mismatch banner inside expanded panel when delta > $0.01", () => {
    _renderRow(
      _buildPreview({ line_total_subtotal_mismatch_cents: -500 }),
      { expanded: true },
    );
    const banner = screen.getByTestId(
      "pdf-import-line-items-subtotal-mismatch-f1-0",
    );
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("5.00");
  });

  it("hides mismatch banner when delta is within $0.01", () => {
    _renderRow(
      _buildPreview({ line_total_subtotal_mismatch_cents: 1 }),
      { expanded: true },
    );
    expect(
      screen.queryByTestId("pdf-import-line-items-subtotal-mismatch-f1-0"),
    ).not.toBeInTheDocument();
  });
});


describe("PreviewRow · Bug 1 end-to-end · type pill reflects override", () => {
  it("shows 'Estimate' + 'AI said: Invoice' when operator overrode classifier", () => {
    _renderRow(_buildPreview({
      doc_type: "quote",
      doc_type_user_override: true,
      auto_detected_doc_type: "invoice",
      doc_kind: "invoice",   // MapperReport-level stayed as auto.
    }));
    const pill = screen.getByTestId(
      "pdf-import-preview-row-f1-0-type-pill",
    );
    expect(pill.textContent).toBe("Estimate");
    const aiBadge = screen.getByTestId(
      "pdf-import-preview-row-f1-0-type-pill-ai-said",
    );
    expect(aiBadge.textContent).toContain("AI said: Invoice");
  });
});
