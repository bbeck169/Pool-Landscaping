/**
 * Phase 56-b · Aug-2026 — Price Book modal supplier prices grid.
 *
 * Contract:
 *   • Add-item modal shows an Income Category dropdown.
 *   • Selecting Pool renders the 4 pool suppliers as grid rows.
 *   • Selecting Landscaping switches the grid + wipes the draft.
 *   • Save posts a ``supplier_prices`` payload with only the
 *     non-empty inputs (cents-normalized).
 *   • Per-row Prices modal pre-populates from the item's persisted
 *     ``supplier_prices``.
 *   • Deleted supplier on an existing item shows a "Deleted supplier"
 *     pill and a read-only input.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();
const delMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    del: (...a) => delMock(...a),
  },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", email: "a@x" } }),
  AuthProvider: ({ children }) => children,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));

import { PriceBook } from "@/pages/ops/OpsHub";


const SERVICE_CATS = [
  { id: "sc-1", name: "Pool", is_archived: false },
];
const INCOME_CATS = [
  { id: "cat-pool", name: "Pool", is_archived: false },
  { id: "cat-land", name: "Landscaping", is_archived: false },
];
const POOL_SUPPLIERS = [
  { id: "s1", slug: "scp", display_name: "SCP",
    income_category_id: "cat-pool", is_active: true, deleted_at: null },
  { id: "s2", slug: "epoolsupply", display_name: "ePoolSupply",
    income_category_id: "cat-pool", is_active: true, deleted_at: null },
  { id: "s3", slug: "heritage", display_name: "Heritage",
    income_category_id: "cat-pool", is_active: true, deleted_at: null },
  { id: "s4", slug: "pwp", display_name: "PWP",
    income_category_id: "cat-pool", is_active: true, deleted_at: null },
];
const LAND_SUPPLIERS = [
  { id: "s5", slug: "home_depot", display_name: "Home Depot",
    income_category_id: "cat-land", is_active: true, deleted_at: null },
  { id: "s6", slug: "horizon", display_name: "Horizon",
    income_category_id: "cat-land", is_active: true, deleted_at: null },
  { id: "s7", slug: "siteone", display_name: "SiteOne",
    income_category_id: "cat-land", is_active: true, deleted_at: null },
];
const ALL_SUPPLIERS = [...POOL_SUPPLIERS, ...LAND_SUPPLIERS];


function seed(rows) {
  getMock.mockImplementation(async (path) => {
    if (path === "/items") return rows;
    if (path === "/service-categories") return SERVICE_CATS;
    if (path === "/income-categories") return { items: INCOME_CATS };
    if (path === "/pricebook/suppliers") return ALL_SUPPLIERS;
    return [];
  });
}

function mount() {
  return render(
    <MemoryRouter>
      <PriceBook />
    </MemoryRouter>,
  );
}


describe("PriceBook · Add-item modal · supplier grid · Phase 56-b", () => {
  beforeEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });
  afterEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });

  it("shows Income Category picker but hides supplier grid until a category is picked", async () => {
    seed([]);
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    await screen.findByTestId("pb-new-income-category");
    expect(screen.queryByTestId("pb-new-supplier-grid")).not.toBeInTheDocument();
  });

  it("renders 4 pool supplier inputs after selecting Pool as income category", async () => {
    seed([]);
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    await screen.findByTestId("pb-new-income-category");
    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-income-category"), {
        target: { value: "cat-pool" },
      });
    });
    await screen.findByTestId("pb-new-supplier-grid");
    expect(screen.getByTestId("pb-new-supplier-input-scp")).toBeInTheDocument();
    expect(screen.getByTestId("pb-new-supplier-input-epoolsupply")).toBeInTheDocument();
    expect(screen.getByTestId("pb-new-supplier-input-heritage")).toBeInTheDocument();
    expect(screen.getByTestId("pb-new-supplier-input-pwp")).toBeInTheDocument();
    // Landscape suppliers are NOT rendered when Pool is picked.
    expect(screen.queryByTestId("pb-new-supplier-input-home_depot")).not.toBeInTheDocument();
  });

  it("switching income category from Pool to Landscaping wipes the draft + swaps the grid", async () => {
    seed([]);
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    await screen.findByTestId("pb-new-income-category");
    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-income-category"), {
        target: { value: "cat-pool" },
      });
    });
    // Enter a scp value, then flip category.
    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-supplier-input-scp"), {
        target: { value: "18.50" },
      });
    });
    expect(screen.getByTestId("pb-new-supplier-input-scp").value).toBe("18.50");

    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-income-category"), {
        target: { value: "cat-land" },
      });
    });
    // Pool supplier grid is gone; Landscape grid appears.
    expect(screen.queryByTestId("pb-new-supplier-input-scp")).not.toBeInTheDocument();
    expect(screen.getByTestId("pb-new-supplier-input-home_depot")).toBeInTheDocument();
  });

  it("Save posts supplier_prices only for filled inputs (cents-normalized)", async () => {
    seed([]);
    postMock.mockResolvedValueOnce({ id: "new-item" });
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    await screen.findByTestId("pb-new-income-category");
    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-name"), {
        target: { value: "Chlorine Tabs" },
      });
      fireEvent.change(screen.getByTestId("pb-new-service-category"), {
        target: { value: "sc-1" },
      });
      fireEvent.change(screen.getByTestId("pb-new-income-category"), {
        target: { value: "cat-pool" },
      });
    });
    // Fill 2 of 4 supplier inputs; leave heritage + pwp blank.
    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-supplier-input-scp"), {
        target: { value: "18.50" },
      });
      fireEvent.change(screen.getByTestId("pb-new-supplier-input-epoolsupply"), {
        target: { value: "19.00" },
      });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("pb-new-save"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [path, payload] = postMock.mock.calls[0];
    expect(path).toBe("/items");
    expect(payload.income_category_id).toBe("cat-pool");
    // Payload's supplier_prices contains ONLY the two filled slugs,
    // cents-normalized. Blanks (heritage/pwp) are excluded.
    expect(payload.supplier_prices).toEqual([
      { supplier_slug: "scp", cost_cents: 1850 },
      { supplier_slug: "epoolsupply", cost_cents: 1900 },
    ]);
  });

  it("per-row Prices modal pre-populates from the item's persisted supplier_prices", async () => {
    const item = {
      id: "item-1", name: "Chlorine Tabs",
      category: "Pool", unit: "each", unit_price: 25,
      income_category_id: "cat-pool",
      supplier_prices: [
        { supplier_slug: "scp", cost_cents: 1850 },
        { supplier_slug: "epoolsupply", cost_cents: 1900 },
      ],
    };
    seed([item]);
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("pb-row-item-1"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("pb-prices-item-1"));
    });
    const modal = await screen.findByTestId("pb-prices-modal");
    expect(within(modal).getByTestId("pb-prices-modal-category").textContent)
      .toBe("Pool");
    // Pre-populated values.
    expect(within(modal).getByTestId("pb-prices-modal-input-scp").value)
      .toBe("18.50");
    expect(within(modal).getByTestId("pb-prices-modal-input-epoolsupply").value)
      .toBe("19.00");
    // Heritage + PWP are blank (they have no persisted price).
    expect(within(modal).getByTestId("pb-prices-modal-input-heritage").value)
      .toBe("");
    expect(within(modal).getByTestId("pb-prices-modal-input-pwp").value)
      .toBe("");
  });

  it("deleted supplier on an existing item shows a pill + read-only input", async () => {
    const item = {
      id: "item-2", name: "Legacy Item",
      category: "Pool", unit: "each", unit_price: 25,
      income_category_id: "cat-pool",
      supplier_prices: [
        { supplier_slug: "scp", cost_cents: 1850 },
        // "old_vendor" is not in the active pricebook_suppliers list —
        // deleted since the item was created.
        { supplier_slug: "old_vendor", cost_cents: 2200 },
      ],
    };
    seed([item]);
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("pb-row-item-2"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("pb-prices-item-2"));
    });
    const modal = await screen.findByTestId("pb-prices-modal");
    // Orphan row appears with a deleted-supplier pill + read-only input.
    expect(within(modal).getByTestId("pb-prices-modal-orphan-old_vendor")).toBeInTheDocument();
    expect(within(modal).getByTestId("pb-prices-modal-orphan-pill-old_vendor")).toBeInTheDocument();
    const roInput = within(modal).getByTestId("pb-prices-modal-orphan-input-old_vendor");
    expect(roInput.value).toBe("22.00");
    expect(roInput.readOnly || roInput.disabled).toBe(true);
    // Active supplier scp still renders as editable.
    expect(within(modal).getByTestId("pb-prices-modal-input-scp").disabled).toBe(false);
  });
});
