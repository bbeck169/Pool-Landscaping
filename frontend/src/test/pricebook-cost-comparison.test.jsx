/**
 * Phase 56-c · Aug-2026 — Pricebook Cost Comparison report contract.
 *
 * Guards:
 *   • Renders rows from the mocked endpoint with correct spread
 *     coloring (min green, max red, spread% pill tier).
 *   • Filter changes (category dropdown) refetch the endpoint with
 *     the correct query param.
 *   • Empty response → renders the empty-state hint.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a) },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", email: "a@x" } }),
  AuthProvider: ({ children }) => children,
}));
vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) => (
    <div><h1>{title}</h1><p>{subtitle}</p></div>
  ),
}));

import PricebookCostComparison from "@/pages/reports/PricebookCostComparison";


const INCOME_CATS = [
  { id: "cat-pool", name: "Pool", is_archived: false },
  { id: "cat-land", name: "Landscaping", is_archived: false },
];


function mount() {
  return render(
    <MemoryRouter>
      <PricebookCostComparison />
    </MemoryRouter>,
  );
}


describe("PricebookCostComparison · Phase 56-c", () => {
  beforeEach(() => { getMock.mockReset(); });
  afterEach(() => { getMock.mockReset(); });

  it("renders rows from a mocked response with correct spread tier pills", async () => {
    getMock.mockImplementation(async (path) => {
      if (path === "/income-categories") return { items: INCOME_CATS };
      if (path.startsWith("/reports/pricebook-cost-comparison")) {
        return {
          total: 3,
          rows: [
            { item_id: "i-hi", item_name: "Big Spread",
              income_category_name: "Pool", supplier_count: 3,
              min_cost_cents: 1000, max_cost_cents: 3000,
              spread_cents: 2000, spread_pct: 200.0,
              supplier_prices: [
                { supplier_slug: "scp", display_name: "SCP",
                  cost_cents: 1000, is_deleted: false },
                { supplier_slug: "heritage", display_name: "Heritage",
                  cost_cents: 3000, is_deleted: false },
              ] },
            { item_id: "i-med", item_name: "Med Spread",
              income_category_name: "Pool", supplier_count: 2,
              min_cost_cents: 1000, max_cost_cents: 1200,
              spread_cents: 200, spread_pct: 20.0,
              supplier_prices: [] },
            { item_id: "i-lo", item_name: "Low Spread",
              income_category_name: "Landscaping", supplier_count: 2,
              min_cost_cents: 1000, max_cost_cents: 1050,
              spread_cents: 50, spread_pct: 5.0,
              supplier_prices: [] },
          ],
        };
      }
      return [];
    });
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("pcc-row-i-hi"));

    // All 3 rows render.
    expect(screen.getByTestId("pcc-row-name-i-hi").textContent).toBe("Big Spread");
    expect(screen.getByTestId("pcc-row-name-i-med").textContent).toBe("Med Spread");
    expect(screen.getByTestId("pcc-row-name-i-lo").textContent).toBe("Low Spread");

    // Spread% tier pills — high (red 30%+), med (amber 10-30%), low (neutral).
    const hiPill = screen.getByTestId("pcc-row-spread-pill-i-hi");
    const medPill = screen.getByTestId("pcc-row-spread-pill-i-med");
    const loPill = screen.getByTestId("pcc-row-spread-pill-i-lo");
    // Colour is applied via inline style; assert the background hue
    // matches the tier documented in scope §2.
    expect(hiPill.style.backgroundColor).toBe("rgb(254, 226, 226)");  // #FEE2E2 red
    expect(medPill.style.backgroundColor).toBe("rgb(254, 243, 199)");  // #FEF3C7 amber
    expect(loPill.style.backgroundColor).toBe("rgb(241, 245, 249)");  // #F1F5F9 neutral

    // Min column is green-tinted, Max red-tinted (locked in scope §2).
    expect(screen.getByTestId("pcc-row-min-i-hi").style.color).toBe("rgb(22, 101, 52)");  // #166534
    expect(screen.getByTestId("pcc-row-max-i-hi").style.color).toBe("rgb(153, 27, 27)");  // #991B1B
  });

  it("changing the category filter refetches with the correct query param", async () => {
    getMock.mockImplementation(async (path) => {
      if (path === "/income-categories") return { items: INCOME_CATS };
      if (path.startsWith("/reports/pricebook-cost-comparison")) {
        return { total: 0, rows: [] };
      }
      return [];
    });
    await act(async () => mount());
    // First fetch (unfiltered) on mount.
    await waitFor(() => {
      const called = getMock.mock.calls.some(
        (c) => typeof c[0] === "string"
              && c[0].startsWith("/reports/pricebook-cost-comparison"),
      );
      expect(called).toBe(true);
    });

    // Change the category filter.
    await act(async () => {
      fireEvent.change(screen.getByTestId("pcc-filter-category"), {
        target: { value: "cat-pool" },
      });
    });

    // A second fetch fires with the ?income_category_id=cat-pool flag.
    await waitFor(() => {
      const withFilter = getMock.mock.calls.some(
        (c) => typeof c[0] === "string"
              && c[0].includes("income_category_id=cat-pool"),
      );
      expect(withFilter).toBe(true);
    });
  });

  it("empty response renders the empty-state hint pointing back to Ops Hub", async () => {
    getMock.mockImplementation(async (path) => {
      if (path === "/income-categories") return { items: INCOME_CATS };
      if (path.startsWith("/reports/pricebook-cost-comparison")) {
        return { total: 0, rows: [] };
      }
      return [];
    });
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("pcc-empty"));
    expect(screen.getByTestId("pcc-empty").textContent)
      .toMatch(/No items have supplier prices set/i);
    expect(screen.queryByTestId("pcc-table")).not.toBeInTheDocument();
    // Export button is disabled when there are no rows.
    expect(screen.getByTestId("pcc-csv-export").disabled).toBe(true);
  });
});
