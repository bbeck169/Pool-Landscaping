/**
 * Phase K71 · Feb-2026 — K71LineItemsEditor · frontend contract tests.
 * Phase K80.a · Feb-2026 — Extended with add-line + delete-with-undo
 * coverage.
 *
 * Coverage:
 *   1. Column header renamed from "Description" → "Item".
 *   2. Bold Item name + secondary muted long_description line rendered.
 *   3. Legacy line item shows "Uncategorized" badge; K71 line does not.
 *   4. Missing-categories banner appears when any K71-touched line
 *      is missing a category.
 *   5. Pencil edit button visible only when canEdit prop is true.
 *   6. Clicking pencil swaps the row into an inline form containing
 *      Item / Qty / Unit / Description / Service picker / Income
 *      picker + Save / Cancel buttons.
 *   K80.a:
 *   7. "+ Add line" button visible only when canEdit.
 *   8. Trash icon per row visible only when canEdit.
 *   9. Clicking "+ Add line" appends an empty row and enters edit mode.
 *  10. Clicking Cancel on a NEW line removes it entirely.
 *  11. Adding a line + saving without categories → inline validation
 *      errors, no onLinesUpdated call.
 *  12. Clicking trash on an existing row hides it and shows the undo
 *      toast; onLinesUpdated NOT called until the 5s timeout fires.
 *  13. Clicking Undo within the window restores the row at its original
 *      index and cancels the pending commit.
 *  14. Timeout elapsing commits onLinesUpdated with the deleted row
 *      removed.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === "/income-categories") {
        return { items: [{ id: "inc-1", name: "Service Revenue",
                            color: "#22C55E" }] };
      }
      if (url === "/service-categories") {
        return { items: [{ id: "svc-1", name: "Pool Cleaning",
                            color: "#0EA5E9" }] };
      }
      return { items: [] };
    }),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import K71LineItemsEditor from "@/components/quotes/K71LineItemsEditor";
import { invalidateCategoryCache }
  from "@/components/income/CategoryPicker";
// Phase P16.1 · Feb-2026 — invalidate the MasterServiceCombobox
// module-level cache between tests so a prior test's empty
// ``/master-services`` fetch doesn't leak into this one.
import { invalidateMasterServicesCache }
  from "@/components/services/MasterServiceCombobox";

beforeEach(() => {
  invalidateCategoryCache();
  invalidateMasterServicesCache();
});

const legacyLine = {
  description: "Pool cleaning · March",
  quantity: 1,
  unit_price: 150,
  category: "Pool",
};

const k71LineComplete = {
  description: "Chemical treatment",
  long_description: "Full shock + algaecide bundle",
  quantity: 2,
  unit_price: 80,
  service_category_id: "svc-1",
  income_category_id: "inc-1",
};

const k71LineMissingIncome = {
  description: "Repair",
  quantity: 1,
  unit_price: 400,
  service_category_id: "svc-1",
  income_category_id: "",
};


describe("Phase K71 · K71LineItemsEditor", () => {
  it("renames the column header from Description to Item", () => {
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    expect(screen.getByTestId("k71-th-item").textContent).toBe("Item");
  });

  it("shows Uncategorized badge on legacy lines only", () => {
    const doc = {
      line_items: [legacyLine, k71LineComplete], status: "draft",
    };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    const badges = screen.getAllByTestId("k71-uncategorized-badge");
    expect(badges).toHaveLength(1);
  });

  it("renders long_description as a secondary muted line", () => {
    const doc = { line_items: [k71LineComplete], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    expect(screen.getByTestId("k71-longdesc-0").textContent).toContain(
      "Full shock + algaecide bundle"
    );
  });

  it("shows the missing-categories banner when a K71 line is incomplete", () => {
    const doc = {
      line_items: [k71LineComplete, k71LineMissingIncome], status: "draft",
    };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    expect(screen.getByTestId("k71-gap-banner")).toBeTruthy();
    expect(screen.getByTestId("k71-gap-banner").textContent)
      .toContain("Missing categories");
  });

  it("hides the pencil button when canEdit is false", () => {
    const doc = { line_items: [legacyLine], status: "sent" };
    render(
      <K71LineItemsEditor doc={doc} canEdit={false}
                            onLinesUpdated={vi.fn()} />
    );
    expect(screen.queryByTestId("k71-edit-btn-0")).toBeNull();
  });

  it("swaps into inline form when the pencil is clicked", () => {
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    expect(screen.getByTestId("k71-row-edit-0")).toBeTruthy();
    expect(screen.getByTestId("k71-input-item-0")).toBeTruthy();
    expect(screen.getByTestId("k71-input-qty-0")).toBeTruthy();
    expect(screen.getByTestId("k71-input-price-0")).toBeTruthy();
    expect(screen.getByTestId("k71-input-longdesc-0")).toBeTruthy();
    expect(screen.getByTestId("k71-save-0")).toBeTruthy();
    expect(screen.getByTestId("k71-cancel-0")).toBeTruthy();
  });

  it("blocks save when required categories are missing", () => {
    const onLinesUpdated = vi.fn();
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit
                                   onLinesUpdated={onLinesUpdated} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    fireEvent.click(screen.getByTestId("k71-save-0"));
    // No update should fire since Service + Income categories are empty
    // (legacy line — pickers start blank).
    expect(onLinesUpdated).not.toHaveBeenCalled();
    // Inline error surfaces on Service picker.
    expect(screen.getByTestId("k71-error-service-0")).toBeTruthy();
    expect(screen.getByTestId("k71-error-income-0")).toBeTruthy();
  });

  it("cancels the inline edit and restores the read row", () => {
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    fireEvent.click(screen.getByTestId("k71-cancel-0"));
    expect(screen.queryByTestId("k71-row-edit-0")).toBeNull();
    expect(screen.getByTestId("k71-row-0")).toBeTruthy();
  });
});


// ═════════════════════════════════════════════════════════════════════
// Phase K80.a — Add + Delete line-item affordances.
// ═════════════════════════════════════════════════════════════════════

describe("Phase K80.a · K71LineItemsEditor · Add + Delete affordances", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the Add line button when canEdit is true", () => {
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    expect(screen.getByTestId("k71-add-line-btn")).toBeTruthy();
  });

  it("hides the Add line button when canEdit is false", () => {
    const doc = { line_items: [legacyLine], status: "sent" };
    render(
      <K71LineItemsEditor doc={doc} canEdit={false}
                            onLinesUpdated={vi.fn()} />
    );
    expect(screen.queryByTestId("k71-add-line-btn")).toBeNull();
  });

  it("shows the trash icon on each row when canEdit is true", () => {
    const doc = {
      line_items: [legacyLine, k71LineComplete], status: "draft",
    };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    expect(screen.getByTestId("k71-delete-btn-0")).toBeTruthy();
    expect(screen.getByTestId("k71-delete-btn-1")).toBeTruthy();
  });

  it("hides the trash icon on each row when canEdit is false", () => {
    const doc = { line_items: [legacyLine], status: "sent" };
    render(
      <K71LineItemsEditor doc={doc} canEdit={false}
                            onLinesUpdated={vi.fn()} />
    );
    expect(screen.queryByTestId("k71-delete-btn-0")).toBeNull();
  });

  it("appends an empty row in edit mode when Add line is clicked", () => {
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    // Before click: only legacy row present.
    expect(screen.getByTestId("k71-row-0")).toBeTruthy();
    expect(screen.queryByTestId("k71-row-edit-1")).toBeNull();

    fireEvent.click(screen.getByTestId("k71-add-line-btn"));

    // After click: new editable row appears at index 1, existing row
    // stays at index 0 in read mode.
    expect(screen.getByTestId("k71-row-edit-1")).toBeTruthy();
    // Phase P16.1 · Feb-2026 — the Item field is now a
    // MasterServiceCombobox whose inner <input> exposes
    // ``k71-input-item-{i}-input``; the wrapper div carries the
    // legacy ``k71-input-item-{i}`` testid.  Assert on the inner
    // input so ``.value`` still resolves.
    const itemInput = screen.getByTestId("k71-input-item-1-input");
    expect(itemInput.value).toBe("");
  });

  it("removes the new line entirely when Cancel is clicked on it", () => {
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k71-add-line-btn"));
    expect(screen.getByTestId("k71-row-edit-1")).toBeTruthy();

    fireEvent.click(screen.getByTestId("k71-cancel-1"));

    // The added draft row is gone; original row 0 remains.
    expect(screen.queryByTestId("k71-row-edit-1")).toBeNull();
    expect(screen.queryByTestId("k71-row-1")).toBeNull();
    expect(screen.getByTestId("k71-row-0")).toBeTruthy();
  });

  it("blocks save on an added line missing categories (validation reused)", () => {
    const onLinesUpdated = vi.fn();
    const doc = { line_items: [legacyLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit
                                   onLinesUpdated={onLinesUpdated} />);
    fireEvent.click(screen.getByTestId("k71-add-line-btn"));
    // Provide a description but leave both category pickers blank.
    // Phase P16.1 · Feb-2026 — target the combobox's INNER input
    // (``-input`` suffix) so ``fireEvent.change`` fires on an
    // actual <input>.
    fireEvent.change(screen.getByTestId("k71-input-item-1-input"),
                       { target: { value: "New service" } });
    fireEvent.click(screen.getByTestId("k71-save-1"));

    expect(onLinesUpdated).not.toHaveBeenCalled();
    expect(screen.getByTestId("k71-error-service-1")).toBeTruthy();
    expect(screen.getByTestId("k71-error-income-1")).toBeTruthy();
  });

  it("hides the row and shows the undo toast on trash click", () => {
    vi.useFakeTimers();
    const onLinesUpdated = vi.fn(async () => true);
    const doc = { line_items: [legacyLine, k71LineComplete], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit
                                   onLinesUpdated={onLinesUpdated} />);
    // Delete row 0.
    fireEvent.click(screen.getByTestId("k71-delete-btn-0"));

    // Row 0 (the deleted one) is hidden from the table — what USED to
    // be row 1 is now rendered as row 0. The visible row is the K71
    // complete line (Chemical treatment).
    expect(screen.getByTestId("k71-undo-toast")).toBeTruthy();
    expect(screen.getByTestId("k71-row-0").textContent)
      .toContain("Chemical treatment");
    // No commit has fired yet — the 5s window has not elapsed.
    expect(onLinesUpdated).not.toHaveBeenCalled();
  });

  it("restores the row when Undo is clicked within the window", () => {
    vi.useFakeTimers();
    const onLinesUpdated = vi.fn(async () => true);
    const doc = { line_items: [legacyLine, k71LineComplete], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit
                                   onLinesUpdated={onLinesUpdated} />);
    fireEvent.click(screen.getByTestId("k71-delete-btn-0"));
    expect(screen.getByTestId("k71-undo-toast")).toBeTruthy();

    fireEvent.click(screen.getByTestId("k71-undo-btn"));

    // Undo restores at the original index — legacy line is back at row 0.
    expect(screen.queryByTestId("k71-undo-toast")).toBeNull();
    expect(screen.getByTestId("k71-row-0").textContent)
      .toContain("Pool cleaning");
    expect(screen.getByTestId("k71-row-1").textContent)
      .toContain("Chemical treatment");

    // Advancing time past 5s should NOT commit — the timer was cleared.
    act(() => { vi.advanceTimersByTime(6000); });
    expect(onLinesUpdated).not.toHaveBeenCalled();
  });

  it("commits onLinesUpdated after 5s if not undone (deleted row excluded)",
    async () => {
    vi.useFakeTimers();
    const onLinesUpdated = vi.fn(async () => true);
    const doc = { line_items: [legacyLine, k71LineComplete], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit
                                   onLinesUpdated={onLinesUpdated} />);
    fireEvent.click(screen.getByTestId("k71-delete-btn-0"));

    await act(async () => { vi.advanceTimersByTime(UNDO_WINDOW_MS_TEST); });

    expect(onLinesUpdated).toHaveBeenCalledTimes(1);
    const committed = onLinesUpdated.mock.calls[0][0];
    // The deleted legacy line is NOT in the committed array.
    expect(committed).toHaveLength(1);
    expect(committed[0].description).toBe("Chemical treatment");
  });
});

// Match the constant used inside the component.  Keeping it in the
// test file (as opposed to importing from the module) so a future
// change to the window duration is caught here.
const UNDO_WINDOW_MS_TEST = 5000;
