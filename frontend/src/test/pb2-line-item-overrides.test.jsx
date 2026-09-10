/**
 * Feb-2026 · Pricebook × Profit-Reporting Phase 2 —
 * K71LineItemsEditor override coverage.
 *
 * Vitest coverage:
 *   1. Editable row renders the 4 new override inputs +
 *      live margin display + reset buttons per spec test-ids.
 *   2. Live margin recomputes on any override change (uses
 *      override-first resolution against snapshots).
 *   3. Reset button clears an override back to "" (renders no
 *      reset button when empty).
 *   4. Save fans out the 4 override fields (null when empty)
 *      through onLinesUpdated.
 *   5. Category-select overrides populate from CategoryPicker.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === "/income-categories") {
        return { items: [
          { id: "inc-1", name: "Service Revenue", color: "#22C55E" },
          { id: "inc-2", name: "Recurring", color: "#0EA5E9" },
        ] };
      }
      if (url === "/service-categories") {
        return { items: [
          { id: "svc-1", name: "Pool Cleaning", color: "#0EA5E9" },
          { id: "svc-2", name: "Repair", color: "#F97316" },
        ] };
      }
      return { items: [] };
    }),
    post: vi.fn(), put: vi.fn(),
  },
}));

import K71LineItemsEditor from "@/components/quotes/K71LineItemsEditor";
import { invalidateCategoryCache }
  from "@/components/income/CategoryPicker";

beforeEach(() => { invalidateCategoryCache(); });

const linePb2 = {
  description: "Chem treatment",
  quantity: 2,
  unit_price: 100,
  service_category_id: "svc-1",
  income_category_id: "inc-1",
  retail_price_snapshot: 100,
  wholesale_price_snapshot: 30,
  labor_cost_snapshot: 20,
};


describe("Phase 2 · line-item override editor", () => {
  it("renders the 4 override inputs + margin display when row enters edit mode", async () => {
    const doc = { line_items: [linePb2], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    await waitFor(() =>
      expect(screen.getByTestId("line-item-wholesale-override-0")).toBeTruthy(),
    );
    expect(screen.getByTestId("line-item-labor-override-0")).toBeTruthy();
    expect(screen.getByTestId("line-item-service-category-select-0")).toBeTruthy();
    expect(screen.getByTestId("line-item-income-category-select-0")).toBeTruthy();
    // Margin using snapshots only (no overrides): retail=200, cost=100 → 50%.
    const margin = screen.getByTestId("line-item-margin-display-0").textContent;
    expect(margin).toMatch(/50\.0%/);
  });

  it("recomputes margin live when wholesale override changes", async () => {
    const doc = { line_items: [linePb2], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    await waitFor(() =>
      expect(screen.getByTestId("line-item-wholesale-override-0")).toBeTruthy(),
    );
    // Bump wholesale override to 60 → cost = (60+20)*2 = 160; margin = 40/200 = 20%.
    fireEvent.change(screen.getByTestId("line-item-wholesale-override-0"), {
      target: { value: "60" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("line-item-margin-display-0").textContent)
        .toMatch(/20\.0%/),
    );
  });

  it("reset button appears only when override is set + clears it on click", async () => {
    const doc = { line_items: [linePb2], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    await waitFor(() =>
      expect(screen.getByTestId("line-item-wholesale-override-0")).toBeTruthy(),
    );
    // No override → no reset button.
    expect(screen.queryByTestId("line-item-reset-wholesale-0")).toBeNull();
    // Set override, reset button surfaces.
    fireEvent.change(screen.getByTestId("line-item-wholesale-override-0"), {
      target: { value: "45" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("line-item-reset-wholesale-0")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("line-item-reset-wholesale-0"));
    // Reset back to empty → back to snapshot-based margin (50%).
    await waitFor(() =>
      expect(screen.getByTestId("line-item-margin-display-0").textContent)
        .toMatch(/50\.0%/),
    );
    expect(screen.getByTestId("line-item-wholesale-override-0").value).toBe("");
  });

  it("save propagates overrides + null for empty fields via onLinesUpdated", async () => {
    const onLinesUpdated = vi.fn().mockResolvedValue(true);
    const doc = { line_items: [linePb2], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={onLinesUpdated} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    await waitFor(() =>
      expect(screen.getByTestId("line-item-wholesale-override-0")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("line-item-wholesale-override-0"), {
      target: { value: "35.5" },
    });
    fireEvent.change(screen.getByTestId("line-item-labor-override-0"), {
      target: { value: "22.75" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("k71-save-0"));
    });
    expect(onLinesUpdated).toHaveBeenCalled();
    const [nextLines] = onLinesUpdated.mock.calls[0];
    expect(nextLines[0].wholesale_cost_override).toBe(35.5);
    expect(nextLines[0].labor_cost_override).toBe(22.75);
    // Unset overrides serialise as null (not undefined, not "").
    expect(nextLines[0].service_category_id_override).toBeNull();
    expect(nextLines[0].income_category_id_override).toBeNull();
    // Snapshots pass through untouched.
    expect(nextLines[0].wholesale_price_snapshot).toBe(30);
    expect(nextLines[0].labor_cost_snapshot).toBe(20);
  });

  it("negative override values fail commit (no onLinesUpdated call)", async () => {
    const onLinesUpdated = vi.fn().mockResolvedValue(true);
    const doc = { line_items: [linePb2], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={onLinesUpdated} />);
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    await waitFor(() =>
      expect(screen.getByTestId("line-item-wholesale-override-0")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("line-item-wholesale-override-0"), {
      target: { value: "-5" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("k71-save-0"));
    });
    expect(onLinesUpdated).not.toHaveBeenCalled();
  });
});
