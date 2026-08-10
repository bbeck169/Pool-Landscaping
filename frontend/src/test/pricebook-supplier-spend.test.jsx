/**
 * Phase 56-d · Aug-2026 — Supplier Spend / Margin report contract.
 *
 * Guards:
 *   • Renders rows from the mocked endpoint with correct margin
 *     tier coloring + totals row.
 *   • Date range change refetches with the new date_from/date_to.
 *   • Empty response renders the empty-state hint.
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

import SupplierSpendReport from "@/pages/reports/SupplierSpendReport";

const INCOME_CATS = [
  { id: "cat-pool", name: "Pool", is_archived: false },
  { id: "cat-land", name: "Landscaping", is_archived: false },
];


function mount() {
  return render(
    <MemoryRouter>
      <SupplierSpendReport />
    </MemoryRouter>,
  );
}

describe("SupplierSpendReport · Phase 56-d", () => {
  beforeEach(() => { getMock.mockReset(); });
  afterEach(() => { getMock.mockReset(); });

  it("renders rows + totals from a mocked response with tier coloring", async () => {
    getMock.mockImplementation(async (path) => {
      if (path === "/income-categories") return { items: INCOME_CATS };
      if (path.startsWith("/reports/supplier-spend")) {
        return {
          rows: [
            { supplier_slug: "scp", display_name: "SCP",
              income_category_name: "Pool",
              line_item_count: 12, quantity_sum: 24,
              spend_cents: 43200, revenue_cents: 60000,
              margin_cents: 16800, margin_pct: 28.0 },
            { supplier_slug: "home_depot", display_name: "Home Depot",
              income_category_name: "Landscaping",
              line_item_count: 3, quantity_sum: 10,
              spend_cents: 5000, revenue_cents: 8000,
              margin_cents: 3000, margin_pct: 37.5 },
            { supplier_slug: null, display_name: "Uncategorized",
              income_category_name: "—",
              line_item_count: 5, quantity_sum: 5,
              spend_cents: 0, revenue_cents: 5000,
              margin_cents: 5000, margin_pct: 100.0 },
          ],
          totals: {
            line_item_count: 20, quantity_sum: 39,
            spend_cents: 48200, revenue_cents: 73000,
            margin_cents: 24800, margin_pct: 33.97,
          },
          date_from: "2026-06-01", date_to: "2026-08-31",
        };
      }
      return [];
    });
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("ssp-row-scp"));

    // Row names.
    expect(screen.getByTestId("ssp-row-name-scp").textContent).toBe("SCP");
    expect(screen.getByTestId("ssp-row-name-home_depot").textContent).toBe("Home Depot");
    expect(screen.getByTestId("ssp-row-name-__uncategorized__").textContent)
      .toBe("Uncategorized");
    // Margin tier — 28% is neutral (10-30), 37.5% is green (≥30),
    // 100% is green.
    expect(screen.getByTestId("ssp-row-margin-pill-scp").style.backgroundColor)
      .toBe("rgb(241, 245, 249)");  // #F1F5F9 neutral
    expect(screen.getByTestId("ssp-row-margin-pill-home_depot").style.backgroundColor)
      .toBe("rgb(220, 252, 231)");  // #DCFCE7 green
    // Totals row present.
    expect(screen.getByTestId("ssp-totals-row")).toBeInTheDocument();
    expect(screen.getByTestId("ssp-totals-spend").textContent).toBe("$482.00");
    expect(screen.getByTestId("ssp-totals-revenue").textContent).toBe("$730.00");
    expect(screen.getByTestId("ssp-totals-margin-pct").textContent).toBe("34.0%");
  });

  it("changing the date range refetches with the new date_from / date_to", async () => {
    getMock.mockImplementation(async (path) => {
      if (path === "/income-categories") return { items: INCOME_CATS };
      if (path.startsWith("/reports/supplier-spend")) {
        return { rows: [], totals: null };
      }
      return [];
    });
    await act(async () => mount());
    // Initial fetch happens on mount.
    await waitFor(() => {
      const spendCalls = getMock.mock.calls.filter(
        (c) => typeof c[0] === "string"
              && c[0].startsWith("/reports/supplier-spend"),
      );
      expect(spendCalls.length).toBeGreaterThanOrEqual(1);
    });
    // Change date_from.
    await act(async () => {
      fireEvent.change(screen.getByTestId("ssp-date-from"), {
        target: { value: "2025-01-01" },
      });
    });
    await waitFor(() => {
      const hasNewDate = getMock.mock.calls.some(
        (c) => typeof c[0] === "string" && c[0].includes("date_from=2025-01-01"),
      );
      expect(hasNewDate).toBe(true);
    });
  });

  it("empty response renders the empty-state hint pointing back to Price Book", async () => {
    getMock.mockImplementation(async (path) => {
      if (path === "/income-categories") return { items: INCOME_CATS };
      if (path.startsWith("/reports/supplier-spend")) {
        return { rows: [], totals: {} };
      }
      return [];
    });
    await act(async () => mount());
    await waitFor(() => screen.getByTestId("ssp-empty"));
    expect(screen.getByTestId("ssp-empty").textContent)
      .toMatch(/No supplier-linked line items in this range/i);
    expect(screen.queryByTestId("ssp-table")).not.toBeInTheDocument();
    // CSV export disabled.
    expect(screen.getByTestId("ssp-csv-export").disabled).toBe(true);
  });
});
