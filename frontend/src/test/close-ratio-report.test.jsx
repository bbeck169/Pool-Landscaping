/**
 * Feb-2026 · Phase 5b.1 — Close Ratio · FE tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import CloseRatioReport from "@/pages/reports/CloseRatioReport";

const _env = ({ rows = null, chart = null } = {}) => ({
  summary: { close_ratio_pct: 75, leads_created: 5,
             leads_closed_won: 3, leads_closed_lost: 1 },
  rows: rows ?? [
    { month: "2026-01", leads_created: 3, closed_won: 1,
      closed_lost: 1, close_ratio_pct: 50 },
    { month: "2026-02", leads_created: 5, closed_won: 3,
      closed_lost: 1, close_ratio_pct: 75 },
  ],
  chart: { monthly_close_ratio: chart ?? [
    { month: "2026-01", close_ratio_pct: 50 },
    { month: "2026-02", close_ratio_pct: 75 },
  ] },
});

const _render = (url = "/reports/close-ratio?start=2025-11-13&end=2026-02-11") =>
  render(<MemoryRouter initialEntries={[url]}>
    <CloseRatioReport />
  </MemoryRouter>);

describe("CloseRatioReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders 4 tiles + line chart + monthly rows", async () => {
    api.get.mockResolvedValueOnce(_env());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-close-ratio-primary").textContent)
        .toMatch(/75%/));
    expect(screen.getByTestId("tile-leads-created-primary").textContent)
      .toMatch(/5/);
    expect(screen.getByTestId("tile-won-primary").textContent).toMatch(/3/);
    expect(screen.getByTestId("tile-lost-primary").textContent).toMatch(/1/);
    expect(screen.getByTestId("cr-chart-point-2026-01")).toBeDefined();
    expect(screen.getByTestId("cr-chart-point-2026-02")).toBeDefined();
    expect(screen.getByTestId("cr-row-2026-01")).toBeDefined();
    expect(screen.getByTestId("cr-row-2026-02")).toBeDefined();
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(
      /reports\/close-ratio\?start_date=2025-11-13&end_date=2026-02-11/));
  });

  it("renders truthful empty state", async () => {
    api.get.mockResolvedValueOnce(_env({ rows: [], chart: [] }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("cr-report-chart-empty")).toBeDefined());
    expect(screen.getByTestId("cr-report-table-empty")).toBeDefined();
  });

  it("renders error banner on API failure", async () => {
    api.get.mockRejectedValueOnce(new Error("boom"));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("cr-report-error")).toBeDefined());
  });
});
