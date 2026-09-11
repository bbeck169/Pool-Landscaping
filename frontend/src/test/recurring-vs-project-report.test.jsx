/**
 * Feb-2026 · Phase 5a.2 — Recurring vs. Project · FE tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import RecurringVsProjectReport from "@/pages/reports/RecurringVsProjectReport";

const _env = ({ rows = null, trailing = null } = {}) => ({
  summary: { total_revenue: 1000, recurring_amount: 300,
             project_amount: 700, recurring_pct: 30 },
  rows: rows ?? [
    { month: "2026-02", recurring_amount: 300,
      project_amount: 700, total: 1000 },
  ],
  chart: {
    donut: { recurring: 300, project: 700 },
    trailing_12mo: trailing ?? [
      { month: "2025-11", recurring_amount: 100, project_amount: 200 },
      { month: "2025-12", recurring_amount: 150, project_amount: 300 },
      { month: "2026-01", recurring_amount: 250, project_amount: 400 },
      { month: "2026-02", recurring_amount: 300, project_amount: 700 },
    ],
  },
});

const _render = (url = "/reports/recurring-vs-project-revenue?start=2026-02-01&end=2026-02-28") =>
  render(<MemoryRouter initialEntries={[url]}>
    <RecurringVsProjectReport />
  </MemoryRouter>);

describe("RecurringVsProjectReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders tiles, donut, trailing chart, monthly rows", async () => {
    api.get.mockResolvedValueOnce(_env());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-total-revenue-primary").textContent)
        .toMatch(/\$1,000\.00/));
    expect(screen.getByTestId("tile-recurring-primary").textContent)
      .toMatch(/\$300\.00/);
    expect(screen.getByTestId("tile-project-primary").textContent)
      .toMatch(/\$700\.00/);
    expect(screen.getByTestId("tile-recurring-pct-primary").textContent)
      .toMatch(/30%/);
    expect(screen.getByTestId("rvp-donut-svg")).toBeDefined();
    expect(screen.getByTestId("rvp-report-trailing-svg")).toBeDefined();
    expect(screen.getByTestId("rvp-row-2026-02")).toBeDefined();
  });

  it("renders truthful trailing-empty state", async () => {
    api.get.mockResolvedValueOnce(_env({ trailing: [] }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("rvp-report-trailing-empty")).toBeDefined());
  });

  it("renders error banner on API failure", async () => {
    api.get.mockRejectedValueOnce(new Error("boom"));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("rvp-report-error")).toBeDefined());
  });
});
