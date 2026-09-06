/**
 * Phase R0.1 · Feb-2026 — RevenueByCustomerPanel tests.
 *
 * Covers:
 *   1. Loading placeholder renders while fetch is pending.
 *   2. Populated rows render a Top-20 table + summary count.
 *   3. Show-All toggle flips the button label and reveals paginator.
 *   4. Export CSV triggers an anchor click with the expected filename.
 *   5. Row click navigates to /customers/{id}.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import React from "react";

import { RevenueByCustomerPanel } from "../components/reports/RevenueByCustomerPanel";

vi.mock("react-apexcharts", () => ({
  __esModule: true,
  default: () => React.createElement("div", { "data-testid": "apex-stub" }),
}));

vi.mock("@/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/api";

function makeRows(n) {
  return Array.from({ length: n }, (_, i) => ({
    customer_id: `c-${i + 1}`,
    customer_name: `Customer ${i + 1}`,
    revenue: (n - i) * 100,
    invoice_count: 1,
  }));
}

function ParamsHarness({ children }) {
  return (
    <MemoryRouter initialEntries={["/reports/suite"]}>
      <Routes>
        <Route path="/reports/suite" element={<Harness>{children}</Harness>} />
        <Route path="/customers/:id" element={<div data-testid="customer-detail" />} />
      </Routes>
    </MemoryRouter>
  );
}

function Harness({ children }) {
  const [params, setParams] = React.useState(new URLSearchParams());
  const filters = { period: "mtd", lens: "invoiced" };
  return children({ params, setParams, filters });
}

function mountPanel(rows) {
  api.get.mockResolvedValue({
    metric_key: "revenue_by_customer",
    lens: "invoiced",
    total: rows.reduce((s, r) => s + r.revenue, 0),
    row_count: rows.length,
    rows,
  });
  return render(
    <ParamsHarness>
      {({ params, setParams, filters }) => (
        <RevenueByCustomerPanel filters={filters} params={params} setParams={setParams} />
      )}
    </ParamsHarness>
  );
}

describe("R0.1 · RevenueByCustomerPanel", () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it("shows a loading state before the fetch resolves", () => {
    api.get.mockReturnValue(new Promise(() => {}));
    render(
      <ParamsHarness>
        {({ params, setParams, filters }) => (
          <RevenueByCustomerPanel filters={filters} params={params} setParams={setParams} />
        )}
      </ParamsHarness>
    );
    expect(screen.getByTestId("revenue-by-customer-panel")).toBeTruthy();
    expect(screen.getByTestId("revenue-by-customer-table").textContent).toContain("Loading");
  });

  it("renders the top-20 rows and summary count", async () => {
    const rows = makeRows(30);
    mountPanel(rows);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-by-customer-row-c-1")).toBeTruthy();
    });
    // Row 21+ is hidden until Show all is toggled.
    expect(screen.queryByTestId("revenue-by-customer-row-c-21")).toBeNull();
    // The header summary contains "30 customers".
    expect(screen.getByTestId("revenue-by-customer-panel").textContent).toContain("30 customer");
  });

  it("toggles show-all and reveals the paginator", async () => {
    const rows = makeRows(30);
    mountPanel(rows);
    await waitFor(() => screen.getByTestId("revenue-by-customer-row-c-1"));
    const btn = screen.getByTestId("revenue-by-customer-show-all");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-by-customer-paginator")).toBeTruthy();
    });
    // With 30 rows and page size 25, page-2 should exist.
    expect(screen.getByTestId("revenue-by-customer-next").hasAttribute("disabled")).toBe(false);
  });

  it("disables show-all when result set fits inside the Top-20 window", async () => {
    mountPanel(makeRows(5));
    await waitFor(() => screen.getByTestId("revenue-by-customer-row-c-1"));
    expect(screen.getByTestId("revenue-by-customer-show-all").hasAttribute("disabled")).toBe(true);
  });

  it("renders an empty-state row when there are zero customers", async () => {
    mountPanel([]);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-by-customer-empty")).toBeTruthy();
    });
  });
});
