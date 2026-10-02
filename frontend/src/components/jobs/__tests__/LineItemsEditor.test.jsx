/**
 * Jobs Overhaul · Phase 3c · ``LineItemsEditor`` presentation contract.
 *
 * Mounts the real ``<LineItemsEditor>`` with the ``PricebookItemPicker``
 * module boundary mocked.  The pricebook picker stub renders a single
 * button carrying the ``${testidPrefix}-pricebook-input`` testid; clicking
 * it invokes ``onSelect`` with a canned pricebook row so we can exercise
 * the "add from pricebook" callback contract without the real debounce
 * + cmdk Popover graph.
 *
 * Scope pinned here:
 *   1. Empty state renders ``${testidPrefix}-empty`` and no table.
 *   2. Non-empty renders the table + per-row cells + trash button.
 *   3. ``onUpdateLine`` fires with ``(idx, {description|quantity|unit_price})``
 *      on cell edits.
 *   4. ``onAddBlank`` fires on "Add line" click.
 *   5. ``onAddFromPricebook`` fires with the picked pricebook row AND
 *      ``onPricebookSearchChange`` is cleared to "" afterwards.
 *   6. ``onRemoveLine`` fires with the row index on trash click.
 *   7. Subtotal footer renders ``Subtotal $N.NN`` reflecting Σ qty×price.
 *   8. ``testidPrefix`` prop fully namespaces every testid (JobNew's
 *      ``jf-li`` default is covered; alternate prefix works too).
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, cleanup,
} from "@testing-library/react";


// ─────────────────────── module mocks ────────────────────────────
// Stub the pricebook picker so we don't drag in cmdk + Popover.
// The stub preserves the real contract: a controlled search input
// value (irrelevant for these tests) and a ``onSelect(row)`` fired
// on selection.  Rendering a button with the test's inputTestid
// gives us an obvious click target.
vi.mock("@/components/pricebook/PricebookItemPicker", () => ({
  default: ({ onSelect, inputTestid, wrapperTestid }) => (
    <div data-testid={wrapperTestid}>
      <button
        type="button"
        data-testid={inputTestid}
        onClick={() =>
          onSelect({ id: "pb-1", name: "Pricebook X", unit_price: 42 })
        }
      >
        pick
      </button>
    </div>
  ),
}));

// Theme stub so the tree mounts without the real CSS-var pipeline.
vi.mock("@/theme", () => ({
  colors: {
    muted: "#999", onSurface: "#000", surface: "#fff",
    surfaceSecondary: "#eee", border: "#ccc", brand: "#1E40AF",
    danger: "#DC2626", error: "#DC2626",
  },
}));

// ui-kit Button — minimal stub honoring the ``testid`` + ``onClick`` +
// ``type`` props the real component surfaces.
vi.mock("@/components/ui-kit", () => ({
  Button: ({ testid, onClick, children, type = "button" }) => (
    <button type={type} data-testid={testid} onClick={onClick}>
      {children}
    </button>
  ),
}));

// Pulled dynamically so the mocks apply.
let LineItemsEditor;
beforeEach(async () => {
  cleanup();
  LineItemsEditor = (await import("../LineItemsEditor.jsx")).default;
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });


// ─────────────────────── empty state ─────────────────────────────
describe("LineItemsEditor · empty state", () => {
  it("renders ${testidPrefix}-empty and no table when lines is empty", () => {
    render(
      <LineItemsEditor
        lines={[]}
        onAddBlank={vi.fn()}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={vi.fn()}
        onRemoveLine={vi.fn()}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("jf-li-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("jf-li-table")).toBeNull();
    // Subtotal footer only renders inside the table (hidden on empty).
    expect(screen.queryByTestId("jf-li-subtotal")).toBeNull();
  });

  it("add-blank + pricebook-input affordances render even on empty state", () => {
    render(
      <LineItemsEditor
        lines={[]}
        onAddBlank={vi.fn()}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={vi.fn()}
        onRemoveLine={vi.fn()}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("jf-li-add-blank")).toBeInTheDocument();
    expect(screen.getByTestId("jf-li-pricebook-input")).toBeInTheDocument();
    expect(screen.getByTestId("jf-li-add-pricebook")).toBeInTheDocument();
  });
});


// ─────────────────────── table rendering ─────────────────────────
describe("LineItemsEditor · table render + edits", () => {
  const seed = () => [
    { description: "Chem balance", quantity: 2, unit_price: 25 },
    { description: "", quantity: 1, unit_price: 0 },
  ];

  it("renders a row per line with desc / qty / unit / total testids", () => {
    render(
      <LineItemsEditor
        lines={seed()}
        onAddBlank={vi.fn()}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={vi.fn()}
        onRemoveLine={vi.fn()}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("jf-li-table")).toBeInTheDocument();
    for (let i = 0; i < 2; i += 1) {
      expect(screen.getByTestId(`jf-li-row-${i}`)).toBeInTheDocument();
      expect(screen.getByTestId(`jf-li-desc-${i}`)).toBeInTheDocument();
      expect(screen.getByTestId(`jf-li-qty-${i}`)).toBeInTheDocument();
      expect(screen.getByTestId(`jf-li-unit-${i}`)).toBeInTheDocument();
      expect(screen.getByTestId(`jf-li-total-${i}`)).toBeInTheDocument();
      expect(screen.getByTestId(`jf-li-del-${i}`)).toBeInTheDocument();
    }
    // Row 0 total = 2 × 25 = $50.00.
    expect(screen.getByTestId("jf-li-total-0")).toHaveTextContent("$50.00");
    // Row 1 total = 1 × 0 = $0.00.
    expect(screen.getByTestId("jf-li-total-1")).toHaveTextContent("$0.00");
  });

  it("desc / qty / unit changes trigger onUpdateLine with the correct patch", () => {
    const onUpdateLine = vi.fn();
    render(
      <LineItemsEditor
        lines={seed()}
        onAddBlank={vi.fn()}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={onUpdateLine}
        onRemoveLine={vi.fn()}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId("jf-li-desc-0"), {
      target: { value: "Updated desc" },
    });
    fireEvent.change(screen.getByTestId("jf-li-qty-1"), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByTestId("jf-li-unit-1"), {
      target: { value: "19.95" },
    });
    expect(onUpdateLine).toHaveBeenNthCalledWith(1, 0, {
      description: "Updated desc",
    });
    expect(onUpdateLine).toHaveBeenNthCalledWith(2, 1, { quantity: "3" });
    expect(onUpdateLine).toHaveBeenNthCalledWith(3, 1, {
      unit_price: "19.95",
    });
  });

  it("Add line click fires onAddBlank", () => {
    const onAddBlank = vi.fn();
    render(
      <LineItemsEditor
        lines={seed()}
        onAddBlank={onAddBlank}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={vi.fn()}
        onRemoveLine={vi.fn()}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("jf-li-add-blank"));
    expect(onAddBlank).toHaveBeenCalledTimes(1);
  });

  it("Pricebook pick fires onAddFromPricebook AND clears the search string", () => {
    const onAddFromPricebook = vi.fn();
    const onPricebookSearchChange = vi.fn();
    render(
      <LineItemsEditor
        lines={seed()}
        onAddBlank={vi.fn()}
        onAddFromPricebook={onAddFromPricebook}
        onUpdateLine={vi.fn()}
        onRemoveLine={vi.fn()}
        pricebookSearch="whatever"
        onPricebookSearchChange={onPricebookSearchChange}
      />,
    );
    fireEvent.click(screen.getByTestId("jf-li-pricebook-input"));
    expect(onAddFromPricebook).toHaveBeenCalledWith({
      id: "pb-1", name: "Pricebook X", unit_price: 42,
    });
    // Search string gets cleared.
    expect(onPricebookSearchChange).toHaveBeenCalledWith("");
  });

  it("Trash click fires onRemoveLine with the row index", () => {
    const onRemoveLine = vi.fn();
    render(
      <LineItemsEditor
        lines={seed()}
        onAddBlank={vi.fn()}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={vi.fn()}
        onRemoveLine={onRemoveLine}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("jf-li-del-1"));
    expect(onRemoveLine).toHaveBeenCalledWith(1);
  });

  it("subtotal footer renders Σ qty×price with 2-decimal formatting", () => {
    render(
      <LineItemsEditor
        lines={[
          { description: "A", quantity: 2, unit_price: 25 },
          { description: "B", quantity: 3.5, unit_price: 10 },
        ]}
        onAddBlank={vi.fn()}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={vi.fn()}
        onRemoveLine={vi.fn()}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
      />,
    );
    // 2×25 + 3.5×10 = 50 + 35 = 85.00
    expect(screen.getByTestId("jf-li-subtotal")).toHaveTextContent("Subtotal $85.00");
  });
});


// ─────────────────────── prefix namespacing ──────────────────────
describe("LineItemsEditor · testidPrefix namespacing", () => {
  it("custom prefix drives every internal testid without JobNew drift", () => {
    render(
      <LineItemsEditor
        lines={[{ description: "x", quantity: 1, unit_price: 10 }]}
        onAddBlank={vi.fn()}
        onAddFromPricebook={vi.fn()}
        onUpdateLine={vi.fn()}
        onRemoveLine={vi.fn()}
        pricebookSearch=""
        onPricebookSearchChange={vi.fn()}
        testidPrefix="xyz"
      />,
    );
    expect(screen.getByTestId("xyz-add-blank")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-add-pricebook")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-pricebook-input")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-table")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-desc-0")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-qty-0")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-unit-0")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-total-0")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-del-0")).toBeInTheDocument();
    expect(screen.getByTestId("xyz-subtotal")).toBeInTheDocument();
    // No JobNew-default testids leak.
    expect(screen.queryByTestId("jf-li-table")).toBeNull();
    expect(screen.queryByTestId("jf-li-add-blank")).toBeNull();
  });
});
