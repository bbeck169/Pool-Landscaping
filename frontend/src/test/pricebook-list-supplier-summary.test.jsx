/**
 * Phase 56-b · Aug-2026 — Price Book list summary line.
 *
 * Contract:
 *   • Item with ≥1 supplier_prices renders a compact "N supplier
 *     prices · min $X · max $Y" one-liner.
 *   • Item with 0 supplier_prices renders a muted "No supplier
 *     prices set" hint.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
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


function seed(rows) {
  getMock.mockImplementation(async (path) => {
    if (path === "/items") return rows;
    if (path === "/service-categories") return [];
    if (path === "/income-categories") return { items: [] };
    if (path === "/pricebook/suppliers") return [];
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


describe("PriceBook · list summary line · Phase 56-b", () => {
  beforeEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });
  afterEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });

  it("item with supplier_prices shows 'N prices · min $X · max $Y'", async () => {
    const item = {
      id: "i1", name: "Chlorine Tabs", category: "Pool", unit: "each",
      unit_price: 25,
      supplier_prices: [
        { supplier_slug: "scp", cost_cents: 1813 },
        { supplier_slug: "epoolsupply", cost_cents: 2700 },
        { supplier_slug: "heritage", cost_cents: 1900 },
      ],
    };
    seed([item]);
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("pb-row-i1"));

    const summary = screen.getByTestId("pb-supplier-summary-i1");
    expect(summary.textContent).toBe("3 supplier prices · min $18.13 · max $27.00");
  });

  it("item with 0 supplier_prices shows muted 'No supplier prices set'", async () => {
    const item = {
      id: "i2", name: "Legacy Item", category: "Pool", unit: "each",
      unit_price: 25,
      // no supplier_prices field OR empty list — both must render the
      // encouragement hint.
    };
    seed([item]);
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("pb-row-i2"));

    const summary = screen.getByTestId("pb-supplier-summary-i2");
    expect(summary.textContent).toBe("No supplier prices set");
  });
});
