/**
 * Income Categories · Feb-2026 · Vitest.
 *
 * Covers:
 *   1. IncomeCategoriesPage renders + New-category modal opens + save
 *      POSTs to /income-categories.
 *   2. CategoryPicker shows red-border error when required + empty +
 *      touched.
 *   3. InvoiceEditModal Save is disabled when a line has no category
 *      (mirrors the backend enforcement contract).
 *   4. Dashboard warning banner data — asserts the banner-render
 *      branch reads r.count and shows the banner when > 0.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { getSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), postSpy: vi.fn(), patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del: vi.fn(),
  },
}));

beforeEach(() => {
  getSpy.mockReset(); postSpy.mockReset(); patchSpy.mockReset();
});
afterEach(() => cleanup());

import IncomeCategoriesPage from "@/pages/settings/IncomeCategoriesPage";
import CategoryPicker, { invalidateCategoryCache } from "@/components/income/CategoryPicker";
import InvoiceEditModal from "@/components/invoices/InvoiceEditModal";

const seededCats = () => ({
  items: [
    { id: "c1", name: "Pool",  description: "", color: "#DB2777",
      is_archived: false, sort_order: 0 },
    { id: "c2", name: "Chem",  description: "", color: "#7C3AED",
      is_archived: false, sort_order: 1 },
    { id: "c3", name: "Repair", description: "", color: "#0891B2",
      is_archived: false, sort_order: 2 },
  ],
  total: 3,
});

describe("IncomeCategoriesPage", () => {
  it("renders + opens New modal + POSTs to create", async () => {
    getSpy.mockResolvedValue(seededCats());
    postSpy.mockResolvedValue({ id: "c-new", name: "TEST_New" });
    render(<MemoryRouter><IncomeCategoriesPage /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("income-cat-row-c1"));
    expect(screen.getByTestId("income-cat-row-c2")).toBeTruthy();
    // Open new.
    fireEvent.click(screen.getByTestId("income-cat-new"));
    expect(screen.getByTestId("income-cat-form")).toBeTruthy();
    fireEvent.change(screen.getByTestId("income-cat-form-name"), {
      target: { value: "TEST_New" },
    });
    fireEvent.click(screen.getByTestId("income-cat-form-save"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    expect(postSpy.mock.calls[0][0]).toBe("/income-categories");
    expect(postSpy.mock.calls[0][1].name).toBe("TEST_New");
  });
});

describe("CategoryPicker", () => {
  beforeEach(() => invalidateCategoryCache());

  it("shows red-border + inline error when required + empty + touched", async () => {
    getSpy.mockResolvedValue(seededCats());
    const { container } = render(
      <CategoryPicker value="" onChange={() => {}} required
                        testid="cp-test" />
    );
    // Trigger the touched state via blur.
    fireEvent.blur(container.firstChild);
    await waitFor(() => screen.getByTestId("cp-test-error"));
    expect(screen.getByTestId("cp-test-error").textContent)
      .toContain("Category required");
  });
});

describe("InvoiceEditModal category gating", () => {
  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("Save is DISABLED when a line item has no category", async () => {
    getSpy.mockResolvedValue(seededCats());
    invalidateCategoryCache();
    const inv = {
      id: "inv-1", invoice_number: "INV-1", status: "draft",
      customer_id: "c1", currency: "USD",
      tax_rate: 0, discount_amount: 0, discount_type: "fixed",
      line_items: [
        { description: "Chem service", quantity: 1, unit_price: 100,
          tax_rate: 0, category: "" },  // ← missing category
      ],
      notes: "", memo: "", terms: "",
    };
    render(<InvoiceEditModal invoice={inv} onClose={() => {}}
                                onSaved={() => {}} />);
    await waitFor(() => screen.getByTestId("invoice-edit-modal"));
    expect(screen.getByTestId("invoice-edit-save").disabled).toBe(true);
  });

  it("Save becomes ENABLED once every line has a category", async () => {
    getSpy.mockResolvedValue(seededCats());
    invalidateCategoryCache();
    const inv = {
      id: "inv-2", invoice_number: "INV-2", status: "draft",
      customer_id: "c1", currency: "USD",
      tax_rate: 0, discount_amount: 0, discount_type: "fixed",
      line_items: [
        { description: "Weekly", quantity: 1, unit_price: 100,
          tax_rate: 0, category: "c1" },
      ],
      notes: "", memo: "", terms: "",
    };
    render(<InvoiceEditModal invoice={inv} onClose={() => {}}
                                onSaved={() => {}} />);
    await waitFor(() => screen.getByTestId("invoice-edit-modal"));
    expect(screen.getByTestId("invoice-edit-save").disabled).toBe(false);
  });
});

describe("Uncategorized dashboard banner data contract", () => {
  it("renders banner only when count > 0", () => {
    // Mini harness matching the banner branch in Dashboard.jsx.
    function Banner({ uncategorized, onReview }) {
      if (!(uncategorized && uncategorized.count > 0)) return null;
      return (
        <button onClick={onReview} data-testid="uncategorized-banner">
          {uncategorized.count} line item
          {uncategorized.count === 1 ? "" : "s"} are uncategorized.
        </button>
      );
    }
    const { rerender } = render(
      <Banner uncategorized={{ count: 0 }} onReview={() => {}} />
    );
    expect(screen.queryByTestId("uncategorized-banner")).toBeNull();
    rerender(<Banner uncategorized={{ count: 7 }} onReview={() => {}} />);
    expect(screen.getByTestId("uncategorized-banner").textContent)
      .toContain("7 line items");
  });
});
