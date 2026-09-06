/**
 * Phase R0.1+ · Feb-2026 — RevenueByCustomerPanel prior-period
 * enrichment tests.
 *
 * Covers the on-panel behaviour that lights up when the API
 * returns ``filters_applied.include_prior=true`` + per-row prior
 * fields:
 *
 *   1. Prior Revenue + Δ column headers render.
 *   2. Prior column shows the formatted currency value.
 *   3. DeltaCell tone flips per row (up / down / New / neutral).
 *   4. Prior header tooltip contains the prior window range.
 *   5. CSV export contains the two new columns.
 *   6. When ``include_prior`` is missing/false the table falls
 *      back to the 3-column layout.
 *   7. Show-all keeps the extra columns.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("react-apexcharts", () => ({
  __esModule: true,
  default: () => React.createElement("div", { "data-testid": "apex-stub" }),
}));

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));

import { api } from "@/api";
import { RevenueByCustomerPanel } from "../components/reports/RevenueByCustomerPanel";


function Wrapper({ children }) {
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


// Row factory that stamps in the R0.1+ enrichment fields.
function makeRows() {
  return [
    { customer_id: "c-up",       customer_name: "Growing Customer",
      revenue: 800, invoice_count: 3,
      prior_revenue: 400, delta_abs: 400, delta_pct: 100 },
    { customer_id: "c-down",     customer_name: "Shrinking Customer",
      revenue: 200, invoice_count: 1,
      prior_revenue: 500, delta_abs: -300, delta_pct: -60 },
    { customer_id: "c-new",      customer_name: "Brand New Customer",
      revenue: 300, invoice_count: 2,
      prior_revenue: 0, delta_abs: 300, delta_pct: null },
    { customer_id: "c-flat",     customer_name: "Steady Customer",
      revenue: 100, invoice_count: 1,
      prior_revenue: 100, delta_abs: 0, delta_pct: 0 },
  ];
}

function mountPanel(payload) {
  api.get.mockResolvedValue(payload);
  return render(
    <Wrapper>
      {({ params, setParams, filters }) => (
        <RevenueByCustomerPanel filters={filters} params={params} setParams={setParams} />
      )}
    </Wrapper>
  );
}

beforeEach(() => { api.get.mockReset(); });


describe("R0.1+ · RevenueByCustomerPanel · prior-period columns", () => {
  it("renders Prior + Delta headers when include_prior is true", async () => {
    mountPanel({
      metric_key: "revenue_by_customer",
      lens: "invoiced",
      total: 1400, row_count: 4, rows: makeRows(),
      prior_period: { start: "2026-01-01", end: "2026-02-01" },
      filters_applied: { include_prior: true },
    });
    await waitFor(() =>
      expect(screen.getByTestId("revenue-by-customer-row-c-up")).toBeTruthy(),
    );
    expect(screen.getByTestId("revenue-by-customer-prior-header")).toBeTruthy();
    expect(screen.getByTestId("revenue-by-customer-delta-header")).toBeTruthy();
    // Prior header carries the tooltip window in its ``title`` attr.
    expect(
      screen.getByTestId("revenue-by-customer-prior-header").getAttribute("title"),
    ).toContain("2026-01-01");
    expect(
      screen.getByTestId("revenue-by-customer-prior-header").getAttribute("title"),
    ).toContain("2026-02-01");
  });

  it("populates Prior Revenue currency in each row", async () => {
    mountPanel({
      total: 1400, row_count: 4, rows: makeRows(),
      prior_period: { start: "2026-01-01", end: "2026-02-01" },
      filters_applied: { include_prior: true },
    });
    await waitFor(() =>
      expect(screen.getByTestId("revenue-by-customer-prior-c-up")).toBeTruthy(),
    );
    expect(screen.getByTestId("revenue-by-customer-prior-c-up").textContent)
      .toContain("400");
    expect(screen.getByTestId("revenue-by-customer-prior-c-down").textContent)
      .toContain("500");
    expect(screen.getByTestId("revenue-by-customer-prior-c-new").textContent)
      .toContain("0");
  });

  it("selects up / down / New / neutral tones per row", async () => {
    mountPanel({
      total: 1400, row_count: 4, rows: makeRows(),
      prior_period: { start: "2026-01-01", end: "2026-02-01" },
      filters_applied: { include_prior: true },
    });
    await waitFor(() =>
      expect(screen.getByTestId("revenue-by-customer-delta-cell-c-up")).toBeTruthy(),
    );
    expect(
      screen.getByTestId("revenue-by-customer-delta-cell-c-up").getAttribute("data-tone"),
    ).toBe("up");
    expect(
      screen.getByTestId("revenue-by-customer-delta-cell-c-down").getAttribute("data-tone"),
    ).toBe("down");
    expect(
      screen.getByTestId("revenue-by-customer-delta-cell-c-new").getAttribute("data-tone"),
    ).toBe("new");
    expect(
      screen.getByTestId("revenue-by-customer-delta-cell-c-flat").getAttribute("data-tone"),
    ).toBe("neutral");
  });

  it("falls back to the pre-R0.1+ 3-column layout when include_prior is missing", async () => {
    mountPanel({
      total: 1400, row_count: 4,
      rows: makeRows().map((r) => ({
        customer_id: r.customer_id, customer_name: r.customer_name,
        revenue: r.revenue, invoice_count: r.invoice_count,
      })),
      // NOTE — no ``filters_applied.include_prior`` block.
    });
    await waitFor(() =>
      expect(screen.getByTestId("revenue-by-customer-row-c-up")).toBeTruthy(),
    );
    expect(screen.queryByTestId("revenue-by-customer-prior-header")).toBeNull();
    expect(screen.queryByTestId("revenue-by-customer-delta-header")).toBeNull();
    expect(screen.queryByTestId("revenue-by-customer-prior-c-up")).toBeNull();
  });

  it("CSV export includes the two new columns when prior is enabled", async () => {
    // Capture what downloadCsv writes into the Blob (spy on Blob).
    const parts = [];
    const RealBlob = global.Blob;
    global.Blob = class MockBlob {
      constructor(chunks, opts) { parts.push(chunks.join("")); return new RealBlob(chunks, opts); }
    };
    global.URL.createObjectURL = vi.fn(() => "blob:mock");
    global.URL.revokeObjectURL = vi.fn();
    // Prevent the anchor .click() from opening jsdom navigation.
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      const el = origCreate(tag);
      if (tag === "a") el.click = () => {};
      return el;
    });

    mountPanel({
      total: 1400, row_count: 4, rows: makeRows(),
      prior_period: { start: "2026-01-01", end: "2026-02-01" },
      filters_applied: { include_prior: true },
    });
    await waitFor(() =>
      expect(screen.getByTestId("revenue-by-customer-export")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("revenue-by-customer-export"));
    await waitFor(() => expect(parts.length).toBeGreaterThan(0));
    const csv = parts[parts.length - 1];
    expect(csv).toMatch(/Prior Revenue \(USD\)/);
    expect(csv).toMatch(/Delta \(USD\)/);
    expect(csv).toMatch(/Delta \(%\)/);
    // Prior-window range appears in the header for auditability.
    expect(csv).toContain("2026-01-01");
    // Row body contains the numeric prior/delta values.
    expect(csv).toContain("500.00");        // Shrinking prior
    expect(csv).toContain("-300.00");       // Shrinking delta
    vi.restoreAllMocks();
  });

  it("Show all still renders the extra columns for paginated rows", async () => {
    const many = [];
    for (let i = 0; i < 30; i++) {
      many.push({
        customer_id: `c-${i + 1}`, customer_name: `Customer ${i + 1}`,
        revenue: 100 * (30 - i), invoice_count: 1,
        prior_revenue: 50 * (30 - i),
        delta_abs: 50 * (30 - i),
        delta_pct: 100,
      });
    }
    mountPanel({
      total: many.reduce((s, r) => s + r.revenue, 0),
      row_count: many.length,
      rows: many,
      prior_period: { start: "2026-01-01", end: "2026-02-01" },
      filters_applied: { include_prior: true },
    });
    await waitFor(() =>
      expect(screen.getByTestId("revenue-by-customer-show-all")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("revenue-by-customer-show-all"));
    await waitFor(() =>
      expect(screen.getByTestId("revenue-by-customer-paginator")).toBeTruthy(),
    );
    // First page of the paginator still has the prior column.
    expect(screen.getByTestId("revenue-by-customer-prior-c-1")).toBeTruthy();
    expect(screen.getByTestId("revenue-by-customer-prior-header")).toBeTruthy();
  });
});
