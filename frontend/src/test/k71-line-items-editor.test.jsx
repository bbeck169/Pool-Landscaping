/**
 * Phase K71 · Feb-2026 — K71LineItemsEditor · frontend contract tests.
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
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

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

beforeEach(() => {
  invalidateCategoryCache();
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
