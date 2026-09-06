/**
 * Phase R0.1 · Feb-2026 — RevenueByCityPanel tests.
 *
 * Covers:
 *   1. Loading placeholder renders while fetch is pending.
 *   2. Populated rows render a Top-20 table + summary count.
 *   3. City rows are intentionally non-interactive (no onClick).
 *   4. Show-All toggle flips label and reveals paginator.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

import { RevenueByCityPanel } from "../components/reports/RevenueByCityPanel";

vi.mock("react-apexcharts", () => ({
  __esModule: true,
  default: () => React.createElement("div", { "data-testid": "apex-stub" }),
}));

vi.mock("@/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/api";

function makeCities(n) {
  return Array.from({ length: n }, (_, i) => ({
    city: `City ${i + 1}`,
    customer_count: 1 + i,
    revenue: (n - i) * 500,
  }));
}

function Harness({ children }) {
  const [params, setParams] = React.useState(new URLSearchParams());
  const filters = { period: "mtd", lens: "invoiced" };
  return (
    <MemoryRouter>
      {children({ params, setParams, filters })}
    </MemoryRouter>
  );
}

function mountPanel(rows) {
  api.get.mockResolvedValue({
    metric_key: "revenue_by_city",
    lens: "invoiced",
    total: rows.reduce((s, r) => s + r.revenue, 0),
    row_count: rows.length,
    rows,
  });
  return render(
    <Harness>
      {({ params, setParams, filters }) => (
        <RevenueByCityPanel filters={filters} params={params} setParams={setParams} />
      )}
    </Harness>
  );
}

describe("R0.1 · RevenueByCityPanel", () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it("renders a loading state before the fetch resolves", () => {
    api.get.mockReturnValue(new Promise(() => {}));
    render(
      <Harness>
        {({ params, setParams, filters }) => (
          <RevenueByCityPanel filters={filters} params={params} setParams={setParams} />
        )}
      </Harness>
    );
    expect(screen.getByTestId("revenue-by-city-panel")).toBeTruthy();
    expect(screen.getByTestId("revenue-by-city-table").textContent).toContain("Loading");
  });

  it("renders city rows and summary count", async () => {
    mountPanel(makeCities(3));
    await waitFor(() => {
      expect(screen.getByTestId("revenue-by-city-row-City 1")).toBeTruthy();
    });
    expect(screen.getByTestId("revenue-by-city-panel").textContent).toContain("3 cities");
  });

  it("uses singular 'city' when row_count is 1", async () => {
    mountPanel(makeCities(1));
    await waitFor(() => screen.getByTestId("revenue-by-city-row-City 1"));
    expect(screen.getByTestId("revenue-by-city-panel").textContent).toContain("1 city");
    // No trailing "cities" copy when the count is exactly 1.
    expect(screen.getByTestId("revenue-by-city-panel").textContent).not.toContain("1 cities");
  });

  it("city rows are non-interactive by design (no onClick handler)", async () => {
    mountPanel(makeCities(3));
    await waitFor(() => screen.getByTestId("revenue-by-city-row-City 1"));
    const row = screen.getByTestId("revenue-by-city-row-City 1");
    // R0.1 design constraint — no ``cursor-pointer`` styling and no
    // click handler that would fabricate a /customers?city=... URL.
    expect(row.className).not.toMatch(/cursor-pointer/);
  });

  it("show-all toggle reveals paginator when result count exceeds Top-20", async () => {
    mountPanel(makeCities(30));
    await waitFor(() => screen.getByTestId("revenue-by-city-row-City 1"));
    fireEvent.click(screen.getByTestId("revenue-by-city-show-all"));
    await waitFor(() => {
      expect(screen.getByTestId("revenue-by-city-paginator")).toBeTruthy();
    });
  });

  it("renders an empty-state row when the API returns zero cities", async () => {
    mountPanel([]);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-by-city-empty")).toBeTruthy();
    });
  });
});
