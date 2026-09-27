/**
 * PDF-FIX-B · Feb-2026 — Line-items expandable-row detail panel.
 *
 * Locks the detail-panel contract shipped with PDF-FIX-B:
 *
 *   1. Toggle chevron in the Invoice # cell reveals a second
 *      ``<tr>`` (``colSpan={5}``) containing an inner table
 *      of the extracted line items — Item Name, Description,
 *      Qty, Unit, Line $.
 *   2. Empty / missing ``line_items`` → muted "No line items
 *      extracted" placeholder inside the expanded panel.
 *   3. Toggle collapses on second click — the expanded panel
 *      is unmounted (not just hidden).
 *   4. Per-row expansion state is owned by ``PreviewSurface``
 *      as a ``Set<source_doc_index>`` — matches the existing
 *      ``expandedIds`` pattern at the page level (line ~511).
 *      Two rows on the same file can be independently expanded.
 *   5. Fallback semantics (rulings §2):
 *      - name + desc  → both cells render populated.
 *      - name only    → "—" in the Description cell.
 *      - desc only    → description renders in the Item Name
 *                       cell (fallback), "—" in the Description
 *                       cell.
 *      - neither      → line item DROPS from view (silent —
 *                       no warning banner).
 *   6. Prices formatted via ``formatCurrency`` — never raw
 *      numeric literals.
 *   7. Chevron icon SWAP (``ChevronUp`` vs ``ChevronDown``) is
 *      the visual indicator of expansion state, matching the
 *      ``FileRow`` pattern at ~L995.
 *
 * Test seam: ``PreviewRow`` is a named export.  We wrap it in a
 * ``<table><tbody>`` shell + drive ``expanded`` / ``onToggle``
 * as controlled props so we can assert both states without
 * mounting the full page.
 */
import React, { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
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


function makePreview(lineItems, { sourceIdx = 0 } = {}) {
  return {
    source_doc_index: sourceIdx,
    doc_kind: "invoice",
    mapped_target: "quote_in",
    customer_resolution: "matched",
    matched_customer_id: "cust-a1",
    quote_in: {
      doc_number: `INV-100${sourceIdx}`,
      doc_date: "2026-02-01",
      customer_name: "Acme Pools",
      grand_total: 400.00,
      line_items: lineItems,
    },
  };
}


/** Render a PreviewRow with a controlled ``expanded`` state
    driven by a tiny wrapper so button clicks toggle the panel. */
function renderControlledRow(lineItems, { fileId = "f1", sourceIdx = 0 } = {}) {
  function Wrapper() {
    const [expanded, setExpanded] = useState(false);
    return (
      <table>
        <tbody>
          <PreviewRow
            preview={makePreview(lineItems, { sourceIdx })}
            duplicate={null}
            fileId={fileId}
            expanded={expanded}
            onToggle={() => setExpanded((prev) => !prev)}
          />
        </tbody>
      </table>
    );
  }
  return render(<Wrapper />);
}


function renderStaticRow(lineItems, {
  fileId = "f1", sourceIdx = 0, expanded = false, onToggle = () => {},
} = {}) {
  return render(
    <table>
      <tbody>
        <PreviewRow
          preview={makePreview(lineItems, { sourceIdx })}
          duplicate={null}
          fileId={fileId}
          expanded={expanded}
          onToggle={onToggle}
        />
      </tbody>
    </table>,
  );
}


describe("PDF Import · Line-items expandable panel (PDF-FIX-B)", () => {
  it("(a) toggle expands and reveals 3 line items with name/description/qty/price", () => {
    const items = [
      { item_name: "SKU-1", description: "Chlorine tabs",  quantity: 4, unit_price: 25.00 },
      { item_name: "SKU-2", description: "Shock treatment", quantity: 2, unit_price: 50.00 },
      { item_name: "SKU-3", description: "Test strips",     quantity: 1, unit_price: 12.50 },
    ];
    renderControlledRow(items);

    const toggle = screen.getByTestId("pdf-import-line-items-toggle-f1-0");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Panel is not in the DOM before expansion.
    expect(screen.queryByTestId("pdf-import-line-items-expanded-f1-0")).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("pdf-import-line-items-expanded-f1-0")).toBeInTheDocument();

    // Row 0 · name = "SKU-1", desc = "Chlorine tabs"
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-name")).toHaveTextContent("SKU-1");
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-description"))
      .toHaveTextContent("Chlorine tabs");
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-qty")).toHaveTextContent("4");
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-price").textContent)
      .toMatch(/^\$25\.00$/);
    // Line total is computed: 4 × $25.00 = $100.00.
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-line-total").textContent)
      .toMatch(/^\$100\.00$/);

    // Row 2 · qty=1, unit=$12.50, line=$12.50
    expect(screen.getByTestId("pdf-import-line-item-f1-0-2-line-total").textContent)
      .toMatch(/^\$12\.50$/);
  });

  it("(b) empty line_items → 'No line items extracted' placeholder", () => {
    renderStaticRow([], { expanded: true });
    expect(screen.getByTestId("pdf-import-line-items-empty-f1-0"))
      .toHaveTextContent("No line items extracted");
    // No line-item rows should render.
    expect(screen.queryByTestId("pdf-import-line-item-f1-0-0-name")).toBeNull();
  });

  it("(c) toggle collapses on second click — panel unmounts", () => {
    const items = [
      { item_name: "SKU-1", description: "Widget", quantity: 1, unit_price: 10.00 },
    ];
    renderControlledRow(items);
    const toggle = screen.getByTestId("pdf-import-line-items-toggle-f1-0");
    fireEvent.click(toggle);
    expect(screen.getByTestId("pdf-import-line-items-expanded-f1-0")).toBeInTheDocument();
    fireEvent.click(toggle);
    // Panel gone from DOM (not just hidden).
    expect(screen.queryByTestId("pdf-import-line-items-expanded-f1-0")).toBeNull();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("(d) two rows expand independently — state does not cross-contaminate", () => {
    // Drive two rows with independent controlled state to prove
    // toggling row A doesn't affect row B.
    function TwoRowWrapper() {
      const [expandedIds, setExpandedIds] = useState(new Set());
      const onToggle = (idx) => setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(idx)) next.delete(idx); else next.add(idx);
        return next;
      });
      const itemsA = [{ item_name: "A", description: "x", quantity: 1, unit_price: 1 }];
      const itemsB = [{ item_name: "B", description: "y", quantity: 2, unit_price: 2 }];
      return (
        <table>
          <tbody>
            <PreviewRow
              preview={makePreview(itemsA, { sourceIdx: 0 })}
              duplicate={null}
              fileId="f1"
              expanded={expandedIds.has(0)}
              onToggle={onToggle}
            />
            <PreviewRow
              preview={makePreview(itemsB, { sourceIdx: 1 })}
              duplicate={null}
              fileId="f1"
              expanded={expandedIds.has(1)}
              onToggle={onToggle}
            />
          </tbody>
        </table>
      );
    }
    render(<TwoRowWrapper />);

    // Expand row A only.
    fireEvent.click(screen.getByTestId("pdf-import-line-items-toggle-f1-0"));
    expect(screen.getByTestId("pdf-import-line-items-expanded-f1-0")).toBeInTheDocument();
    // Row B panel MUST NOT render.
    expect(screen.queryByTestId("pdf-import-line-items-expanded-f1-1")).toBeNull();

    // Now expand B — A should still be expanded.
    fireEvent.click(screen.getByTestId("pdf-import-line-items-toggle-f1-1"));
    expect(screen.getByTestId("pdf-import-line-items-expanded-f1-0")).toBeInTheDocument();
    expect(screen.getByTestId("pdf-import-line-items-expanded-f1-1")).toBeInTheDocument();

    // Collapse A — B stays open.
    fireEvent.click(screen.getByTestId("pdf-import-line-items-toggle-f1-0"));
    expect(screen.queryByTestId("pdf-import-line-items-expanded-f1-0")).toBeNull();
    expect(screen.getByTestId("pdf-import-line-items-expanded-f1-1")).toBeInTheDocument();
  });

  it("(e) item with name only → Description cell shows '—'", () => {
    const items = [
      { item_name: "SKU-NAMEONLY", description: "", quantity: 3, unit_price: 15.00 },
    ];
    renderStaticRow(items, { expanded: true });
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-name"))
      .toHaveTextContent("SKU-NAMEONLY");
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-description"))
      .toHaveTextContent("—");
  });

  it("(f) item with description only → description fills name col; desc col shows '—'", () => {
    const items = [
      { item_name: null, description: "Chlorine — 4 gallon", quantity: 1, unit_price: 42.00 },
    ];
    renderStaticRow(items, { expanded: true });
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-name"))
      .toHaveTextContent("Chlorine — 4 gallon");
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-description"))
      .toHaveTextContent("—");
  });

  it("(g) item with neither name nor description drops silently from the panel", () => {
    const items = [
      { item_name: null, description: "",   quantity: 1, unit_price: 10 },  // dropped
      { item_name: "OK", description: "Ok", quantity: 2, unit_price: 20 },  // kept
    ];
    renderStaticRow(items, { expanded: true });
    // The dropped item does NOT render — the "kept" item lands
    // at index 0 in the rendered list.
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-name")).toHaveTextContent("OK");
    // No index-1 line item.
    expect(screen.queryByTestId("pdf-import-line-item-f1-0-1-name")).toBeNull();
    // Empty placeholder MUST NOT render since we have one kept item.
    expect(screen.queryByTestId("pdf-import-line-items-empty-f1-0")).toBeNull();
  });

  it("(h) prices render via formatCurrency ($X.XX, not bare number)", () => {
    const items = [
      { item_name: "SKU-1", description: "widget", quantity: 1, unit_price: 100.00 },
    ];
    renderStaticRow(items, { expanded: true });
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-price").textContent)
      .toMatch(/^\$100\.00$/);
    expect(screen.getByTestId("pdf-import-line-item-f1-0-0-line-total").textContent)
      .toMatch(/^\$100\.00$/);
  });

  it("(i) chevron icon swaps on toggle (visual indicator)", () => {
    const items = [
      { item_name: "SKU", description: "x", quantity: 1, unit_price: 1 },
    ];
    renderControlledRow(items);
    const toggle = screen.getByTestId("pdf-import-line-items-toggle-f1-0");
    // Collapsed state: SVG has "chevron-down" identifier
    // baked into lucide-react's rendered <svg>. Assert via the
    // accessible name + aria-expanded state, which is the
    // stable contract; icon SVG internals are lucide-owned.
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-label", "Expand line items");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-label", "Collapse line items");
  });
});
