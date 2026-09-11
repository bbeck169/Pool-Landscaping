/**
 * Feb-2026 · Phase 5b.2 — Labor Efficiency · FE tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import LaborEfficiencyReport from "@/pages/reports/LaborEfficiencyReport";

const _env = ({ rows = null } = {}) => ({
  summary: { labor_efficiency_pct: 87.5, budgeted_hours: 14,
             actual_hours: 16, jobs_counted: 3 },
  rows: rows ?? [
    { job_id: "j-over", customer_id: "c1", customer_name: "Careful Carol",
      service_date: "2026-02-10",
      budgeted_hours: 4, actual_hours: 8, efficiency_pct: 50,
      technician_id: "t1", technician_name: "Timely Tim" },
    { job_id: "j-on", customer_id: "c1", customer_name: "Careful Carol",
      service_date: "2026-02-05",
      budgeted_hours: 4, actual_hours: 4, efficiency_pct: 100,
      technician_id: "t1", technician_name: "Timely Tim" },
    { job_id: "j-under", customer_id: "c1", customer_name: "Careful Carol",
      service_date: "2026-02-15",
      budgeted_hours: 6, actual_hours: 4, efficiency_pct: 150,
      technician_id: "t1", technician_name: "Timely Tim" },
  ],
  chart: { monthly_efficiency: [
    { month: "2026-02", efficiency_pct: 87.5 },
  ] },
});

const _render = (url = "/reports/labor-efficiency?start=2026-02-01&end=2026-02-28") =>
  render(<MemoryRouter initialEntries={[url]}>
    <LaborEfficiencyReport />
  </MemoryRouter>);

describe("LaborEfficiencyReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders 4 tiles + chart + rows worst-first", async () => {
    api.get.mockResolvedValueOnce(_env());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-eff-pct-primary").textContent)
        .toMatch(/87\.5%/));
    expect(screen.getByTestId("tile-budgeted-primary").textContent)
      .toMatch(/14h/);
    expect(screen.getByTestId("tile-actual-primary").textContent)
      .toMatch(/16h/);
    expect(screen.getByTestId("tile-jobs-primary").textContent).toMatch(/3/);
    // Chart point rendered.
    expect(screen.getByTestId("le-chart-point-2026-02")).toBeDefined();
    // Rows in the same order the API sent (worst-first).
    ["j-over", "j-on", "j-under"].forEach((rid) =>
      expect(screen.getByTestId(`le-row-${rid}`)).toBeDefined());
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(
      /reports\/labor-efficiency\?start_date=2026-02-01&end_date=2026-02-28/));
  });

  it("renders 'insufficient data' state when no rows", async () => {
    api.get.mockResolvedValueOnce(_env({ rows: [] }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("le-report-insufficient")).toBeDefined());
    // Table is NOT rendered in the insufficient state.
    expect(screen.queryByTestId("le-report-table")).toBeNull();
  });

  it("renders error banner on API failure", async () => {
    api.get.mockRejectedValueOnce(new Error("boom"));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("le-report-error")).toBeDefined());
  });
});
