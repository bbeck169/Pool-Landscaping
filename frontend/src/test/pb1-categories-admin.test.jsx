/**
 * Pricebook × Profit-Reporting Phase 1 · Feb-2026 — Vitest smoke for
 * `CategoriesAdmin` (route `/pricebook/categories`).
 *
 * Covers:
 *   1. Renders both tabs + income table by default,
 *   2. Switching to Service tab loads service categories,
 *   3. Archive click opens the `category-delete-warn-dialog`, fetches
 *      `/references`, renders count summary, and POSTs `/archive`
 *      on confirm.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import CategoriesAdmin from "@/pages/pricebook/CategoriesAdmin";


const INCOME = [
  { id: "i1", name: "Pool Maintenance", description: "Recurring",
    color: "#059669", sort_order: 1, is_archived: false },
  { id: "i2", name: "Repairs", description: "One-off",
    color: "#DC2626", sort_order: 2, is_archived: false },
];
const SERVICE = [
  { id: "s1", name: "Chemicals",   description: null,
    color: "#0EA5E9", sort_order: 1, is_archived: false },
];

function mockGet(url) {
  if (url.startsWith("/income-categories?"))  return Promise.resolve(INCOME);
  if (url.startsWith("/service-categories?")) return Promise.resolve(SERVICE);
  if (url.match(/\/income-categories\/[^/]+\/references$/)) {
    return Promise.resolve({ pricebook_item_count: 3, line_item_count: 7 });
  }
  return Promise.resolve([]);
}

describe("CategoriesAdmin (Pricebook × Profit Phase 1)", () => {
  beforeEach(() => {
    getSpy.mockImplementation(mockGet);
    postSpy.mockResolvedValue({ ok: true });
    patchSpy.mockResolvedValue({ ok: true });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("renders both tabs + income table by default", async () => {
    render(
      <MemoryRouter>
        <CategoriesAdmin />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("categories-admin-page")).toBeInTheDocument();
    expect(screen.getByTestId("categories-admin-tab-income")).toBeInTheDocument();
    expect(screen.getByTestId("categories-admin-tab-service")).toBeInTheDocument();
    // income tab is default
    await waitFor(() => expect(screen.getByTestId("income-categories-table")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("income-category-row-i1")).toBeInTheDocument());
    expect(screen.getByText("Pool Maintenance")).toBeInTheDocument();
  });

  it("switches to Service tab and loads service categories", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <CategoriesAdmin />
      </MemoryRouter>,
    );
    await screen.findByTestId("income-categories-table");
    await user.click(screen.getByTestId("categories-admin-tab-service"));
    await waitFor(() => expect(screen.getByTestId("service-categories-table")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("service-category-row-s1")).toBeInTheDocument());
  });

  it("archive click opens warn dialog with reference counts + archives on confirm", async () => {
    render(
      <MemoryRouter>
        <CategoriesAdmin />
      </MemoryRouter>,
    );
    await screen.findByTestId("income-category-row-i1");

    fireEvent.click(screen.getByTestId("income-category-archive-i1"));
    await waitFor(() => expect(screen.getByTestId("category-delete-warn-dialog")).toBeInTheDocument());

    // Reference counts populate from `/references`.
    await waitFor(() =>
      expect(screen.getByTestId("category-refs-pricebook-count").textContent).toBe("3"),
    );
    expect(screen.getByTestId("category-refs-line-count").textContent).toBe("7");
    // Warn banner is shown because refs > 0.
    expect(screen.getByTestId("category-refs-warn-banner")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("category-delete-warn-confirm"));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith("/income-categories/i1/archive", {}),
    );
  });
});
