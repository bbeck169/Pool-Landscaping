/**
 * Feb-2026 · Phase 5a.2 — Revenue by Service · FE tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import RevenueByServiceReport from "@/pages/reports/RevenueByServiceReport";

const _env = ({ rows = null, top = null } = {}) => ({
  summary: {
    total_billed: 750, total_collected: 250,
    top_service_by_revenue: { name: "Deck Repair", amount: 500 },
  },
  rows: rows ?? [
    { service_name: "Deck Repair", service_id: "deck-repair",
      billed_amount: 500, collected_amount: 0,
      job_count: 1, avg_ticket: 500 },
    { service_name: "Weekly Pool Service", service_id: "weekly-pool-service",
      billed_amount: 250, collected_amount: 250,
      job_count: 2, avg_ticket: 125 },
  ],
  chart: { top_services: top ?? [
    { service_name: "Deck Repair", billed_amount: 500 },
    { service_name: "Weekly Pool Service", billed_amount: 250 },
  ] },
  tenant_id: "T1", start_date: "2026-02-01", end_date: "2026-02-28",
  computed_at: "2026-02-27T09:00:00+00:00",
});

const _render = (url = "/reports/revenue-by-service?start=2026-02-01&end=2026-02-28") =>
  render(<MemoryRouter initialEntries={[url]}>
    <RevenueByServiceReport />
  </MemoryRouter>);

describe("RevenueByServiceReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders tiles + chart bars + rows after fetch", async () => {
    api.get.mockResolvedValueOnce(_env());
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("tile-total-billed-primary").textContent)
        .toMatch(/\$750\.00/);
    });
    expect(screen.getByTestId("tile-total-collected-primary").textContent)
      .toMatch(/\$250\.00/);
    expect(screen.getByTestId("tile-top-service-primary").textContent)
      .toMatch(/Deck Repair/);
    expect(screen.getByTestId("rbs-bar-Deck Repair")).toBeDefined();
    expect(screen.getByTestId("rbs-row-deck-repair")).toBeDefined();
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(
      /reports\/revenue-by-service\?start_date=2026-02-01&end_date=2026-02-28/));
  });

  it("renders truthful empty state", async () => {
    api.get.mockResolvedValueOnce({
      summary: { total_billed: 0, total_collected: 0,
                  top_service_by_revenue: { name: null, amount: 0 } },
      rows: [], chart: { top_services: [] },
    });
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("rbs-report-chart-empty")).toBeDefined());
    expect(screen.getByTestId("rbs-report-table-empty")).toBeDefined();
  });

  it("renders error banner on API failure", async () => {
    api.get.mockRejectedValueOnce(new Error("500 nope"));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("rbs-report-error")).toBeDefined());
    expect(screen.queryByTestId("rbs-report-tiles")).toBeNull();
  });
});
