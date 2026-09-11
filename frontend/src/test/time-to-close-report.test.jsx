/**
 * Feb-2026 · Phase 5b.1 — Time to Close · FE tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import TimeToCloseReport from "@/pages/reports/TimeToCloseReport";

const _env = ({ rows = null, chart = null } = {}) => ({
  summary: { avg_days_to_close: 10, p50_days: 10,
             p90_days: 14, leads_counted: 3 },
  rows: rows ?? [
    { lead_id: "L-2", customer_id: "c1", customer_name: "Lucky Larry",
      created_at: "2026-02-06T00:00:00+00:00",
      closed_at:  "2026-02-21T00:00:00+00:00",
      days_to_close: 15, outcome: "won" },
    { lead_id: "L-1", customer_id: "c1", customer_name: "Lucky Larry",
      created_at: "2026-02-03T00:00:00+00:00",
      closed_at:  "2026-02-13T00:00:00+00:00",
      days_to_close: 10, outcome: "won" },
    { lead_id: "L-0", customer_id: "c1", customer_name: "Lucky Larry",
      created_at: "2026-02-01T00:00:00+00:00",
      closed_at:  "2026-02-06T00:00:00+00:00",
      days_to_close: 5, outcome: "lost" },
  ],
  chart: { monthly_avg_days: chart ?? [
    { month: "2025-11", avg_days: 6 },
    { month: "2025-12", avg_days: 8 },
    { month: "2026-01", avg_days: 9 },
    { month: "2026-02", avg_days: 10 },
  ] },
});

const _render = (url = "/reports/time-to-close?start=2025-11-13&end=2026-02-11") =>
  render(<MemoryRouter initialEntries={[url]}>
    <TimeToCloseReport />
  </MemoryRouter>);

describe("TimeToCloseReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders 4 tiles + chart + rows sorted desc", async () => {
    api.get.mockResolvedValueOnce(_env());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-avg-days-primary").textContent)
        .toMatch(/10/));
    expect(screen.getByTestId("tile-p50-primary").textContent).toMatch(/10/);
    expect(screen.getByTestId("tile-p90-primary").textContent).toMatch(/14/);
    expect(screen.getByTestId("tile-lead-count-primary").textContent)
      .toMatch(/3/);
    expect(screen.getByTestId("ttc-chart-point-2026-02")).toBeDefined();
    ["L-2", "L-1", "L-0"].forEach((rid) => {
      expect(screen.getByTestId(`ttc-row-${rid}`)).toBeDefined();
    });
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(
      /reports\/time-to-close\?start_date=2025-11-13&end_date=2026-02-11/));
  });

  it("renders truthful empty state", async () => {
    api.get.mockResolvedValueOnce(_env({ rows: [], chart: [] }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("ttc-report-chart-empty")).toBeDefined());
    expect(screen.getByTestId("ttc-report-table-empty")).toBeDefined();
  });

  it("renders error banner on API failure", async () => {
    api.get.mockRejectedValueOnce(new Error("nope"));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("ttc-report-error")).toBeDefined());
  });
});
