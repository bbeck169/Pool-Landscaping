/**
 * Feb-2026 · Phase 5a.2 — Client Lifetime Value · FE tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import ClientLifetimeValueReport from "@/pages/reports/ClientLifetimeValueReport";

const _env = ({ rows = null, buckets = null } = {}) => ({
  summary: {
    avg_ltv_recurring: 6000, avg_ltv_project: 850,
    top_10_pct_revenue_share: 77.9, active_client_count: 3,
  },
  rows: rows ?? [
    { customer_id: "c-1", customer_name: "Big Bertha",
      first_service_date: "2026-01-10", last_service_date: "2026-02-10",
      total_billed: 6000, total_collected: 6000,
      is_active: true, client_type: "recurring" },
    { customer_id: "c-2", customer_name: "Medium Meg",
      first_service_date: "2026-01-20", last_service_date: "2026-01-20",
      total_billed: 1500, total_collected: 1500,
      is_active: true, client_type: "project" },
    { customer_id: "c-3", customer_name: "Small Sam",
      first_service_date: null, last_service_date: null,
      total_billed: 200, total_collected: 200,
      is_active: true, client_type: "project" },
  ],
  chart: { ltv_buckets: buckets ?? [
    { bucket: "$0-500", count: 1 },
    { bucket: "$500-1K", count: 0 },
    { bucket: "$1K-2.5K", count: 1 },
    { bucket: "$2.5K-5K", count: 0 },
    { bucket: "$5K+", count: 1 },
  ] },
});

const _render = () => render(<MemoryRouter>
  <ClientLifetimeValueReport />
</MemoryRouter>);

describe("ClientLifetimeValueReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders 4 tiles, histogram buckets, and rows sorted desc", async () => {
    api.get.mockResolvedValueOnce(_env());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-avg-recurring-primary").textContent)
        .toMatch(/\$6,000\.00/));
    expect(screen.getByTestId("tile-avg-project-primary").textContent)
      .toMatch(/\$850\.00/);
    expect(screen.getByTestId("tile-top-share-primary").textContent)
      .toMatch(/77\.9%/);
    expect(screen.getByTestId("tile-active-count-primary").textContent)
      .toMatch(/3/);
    // Buckets rendered.
    expect(screen.getByTestId("clv-bucket-$0-500")).toBeDefined();
    expect(screen.getByTestId("clv-bucket-$5K+")).toBeDefined();
    // Rows rendered — 3 customers.
    expect(screen.getByTestId("clv-row-c-1")).toBeDefined();
    expect(screen.getByTestId("clv-row-c-2")).toBeDefined();
    expect(screen.getByTestId("clv-row-c-3")).toBeDefined();
    // All-time by default → no date_range in URL.
    expect(api.get).toHaveBeenCalledWith("/reports/client-lifetime-value");
  });

  it("renders truthful empty state", async () => {
    api.get.mockResolvedValueOnce({
      summary: { avg_ltv_recurring: 0, avg_ltv_project: 0,
                  top_10_pct_revenue_share: 0, active_client_count: 0 },
      rows: [], chart: { ltv_buckets: [] },
    });
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("clv-report-chart-empty")).toBeDefined());
    expect(screen.getByTestId("clv-report-table-empty")).toBeDefined();
  });

  it("renders error banner on API failure", async () => {
    api.get.mockRejectedValueOnce(new Error("500 dead"));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("clv-report-error")).toBeDefined());
  });
});
