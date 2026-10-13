/**
 * Feb-2026 · Pool Service Report — service-name regrouping vitests.
 *
 * Covers:
 *   1. Unassigned row renders at top of the service-name section
 *      with amber accent + correct count.
 *   2. "Other" row is collapsed by default; clicking the chevron
 *      expands the sub-breakdown rows.
 *   3. Sub-rows show service_name + count in the order the backend
 *      provided (which the backend sorts desc by count, name asc).
 *   4. Reconciliation banner hides when
 *      ``service_name_breakdown.reconciliation_delta === 0``.
 *   5. Reconciliation banner surfaces + prefers the new delta when
 *      ``reconciliation_delta > 0``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, fireEvent, waitFor, within,
} from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));
vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    post: vi.fn(),
  },
}));

// Mock the drill-down modal — the page imports + renders it; we
// don't need to exercise its internals here.
vi.mock("@/components/reports/PoolServiceDrilldownModal", () => ({
  default: () => null,
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  getSpy.mockReset();
});

import PoolServiceReport from "@/pages/reports/PoolServiceReport";


function _buildData({
  unassignedCount = 0,
  reconDelta = 0,
  reconMatches = true,
  buckets = null,
} = {}) {
  const sb = {
    buckets: buckets || [
      {
        name: "Weekly Pool Cleaning",
        count: 12,
        techs: [
          { technician_id: "t1", technician_name: "Ethan Smith",
            count: 7 },
          { technician_id: "t2", technician_name: "Alex Jones",
            count: 5 },
        ],
      },
      { name: "Maintenance", count: 3, techs: [] },
      {
        name: "Other",
        count: 10,
        techs: [],
        other_breakdown: [
          { service_name: "Chemical Only",    count: 5 },
          { service_name: "Filter Change",    count: 3 },
          { service_name: "Equipment Repair", count: 2 },
        ],
      },
    ],
    unassigned: { count: unassignedCount },
    total_pool_jobs: 25 + unassignedCount + reconDelta,
    reconciliation_delta: reconDelta,
  };
  return {
    week_start: "2026-02-02",
    week_end:   "2026-02-08",
    period: { start: "2026-02-02", end: "2026-02-08" },
    summary: {
      maintenance_visits: 15,
      repair_visits:       0,
      other_visits:        10,
      total_pool_visits:  25,
    },
    totals: { pools_serviced: 15, repairs_completed: 0 },
    maintenance: [],
    repairs:     [],
    other:       [],
    visits:      [],
    by_technician: [],
    rows: [],
    total_completed:     15,
    total_completed_all: 25,
    total_skipped:       0,
    dropped_count:       0,
    other_label: "Other job types",
    reconciliation: {
      matches: reconMatches,
      delta:   reconDelta,
      counted_total: 25 + unassignedCount,
      actual_total:  25 + unassignedCount + reconDelta,
      dropped_count: 0,
      dropped_sample: [],
    },
    service_name_breakdown: sb,
  };
}


function _mountReport(data) {
  getSpy.mockImplementation((path) => {
    if (path.startsWith("/reports/pool-service")) {
      return Promise.resolve(data);
    }
    return Promise.resolve({});
  });
  return render(
    <MemoryRouter>
      <PoolServiceReport />
    </MemoryRouter>,
  );
}


describe("PoolServiceReport · service-name regrouping", () => {
  it("renders Unassigned row at the top with amber accent + count", async () => {
    _mountReport(_buildData({ unassignedCount: 7 }));
    await waitFor(() =>
      screen.getByTestId("pool-report-service-name-section"),
    );
    const unassigned = screen.getByTestId(
      "pool-report-service-name-unassigned-row",
    );
    expect(unassigned).toBeInTheDocument();
    expect(unassigned.textContent).toContain("Unassigned");
    const count = screen.getByTestId(
      "pool-report-service-name-unassigned-count",
    );
    expect(count.textContent).toContain("7");
    // Amber accent — inline background matches the warning palette
    // (``#FEF3C7`` normalized by jsdom to ``rgb(254, 243, 199)``).
    expect(unassigned.style.background.toLowerCase()).toContain(
      "rgb(254, 243, 199)",
    );
    // Must be the FIRST <li> inside the section (above all buckets).
    const section = screen.getByTestId(
      "pool-report-service-name-section",
    );
    const firstLi = section.querySelector("li");
    expect(firstLi).toBe(unassigned);
  });

  it("hides Unassigned row when count is zero", async () => {
    _mountReport(_buildData({ unassignedCount: 0 }));
    await waitFor(() =>
      screen.getByTestId("pool-report-service-name-section"),
    );
    expect(
      screen.queryByTestId("pool-report-service-name-unassigned-row"),
    ).not.toBeInTheDocument();
  });

  it("Other row is collapsed by default and expands on click", async () => {
    _mountReport(_buildData());
    await waitFor(() =>
      screen.getByTestId("pool-report-service-name-section"),
    );
    const toggle = screen.getByTestId(
      "pool-report-service-name-other-toggle",
    );
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(
      screen.queryByTestId("pool-report-service-name-other-breakdown"),
    ).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(
      screen.getByTestId("pool-report-service-name-other-breakdown"),
    ).toBeInTheDocument();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("sub-rows show service_name + count in backend-provided order", async () => {
    _mountReport(_buildData());
    await waitFor(() =>
      screen.getByTestId("pool-report-service-name-section"),
    );
    fireEvent.click(
      screen.getByTestId("pool-report-service-name-other-toggle"),
    );
    const list = screen.getByTestId(
      "pool-report-service-name-other-breakdown",
    );
    const rows = within(list).getAllByRole("listitem");
    // Backend sorts desc by count, name asc — first row should be
    // "Chemical Only" (count 5).
    expect(rows[0].textContent).toContain("Chemical Only");
    expect(rows[0].textContent).toContain("5");
    expect(rows[1].textContent).toContain("Filter Change");
    expect(rows[1].textContent).toContain("3");
    expect(rows[2].textContent).toContain("Equipment Repair");
    expect(rows[2].textContent).toContain("2");
  });

  it("hides reconciliation banner when service_name_breakdown delta is 0", async () => {
    // Legacy ``reconciliation.matches=false`` ALONE would normally
    // show the banner — but with the new breakdown reporting
    // delta=0 the FE suppresses the banner (per spec: new section
    // accounts for every job).
    _mountReport(_buildData({
      reconDelta: 0,
      reconMatches: false,
    }));
    await waitFor(() =>
      screen.getByTestId("pool-report-service-name-section"),
    );
    expect(
      screen.queryByTestId("pool-report-reconciliation-banner"),
    ).not.toBeInTheDocument();
  });

  it("shows reconciliation banner with new delta when breakdown delta > 0", async () => {
    _mountReport(_buildData({
      reconDelta: 4,
      reconMatches: false,
    }));
    await waitFor(() =>
      screen.getByTestId("pool-report-service-name-section"),
    );
    const banner = await screen.findByTestId(
      "pool-report-reconciliation-banner",
    );
    expect(banner).toBeInTheDocument();
    expect(
      screen.getByTestId("pool-report-reconciliation-delta").textContent,
    ).toBe("4");
  });

  it("Weekly Pool Cleaning bucket renders with its per-tech count sum", async () => {
    // Validates that when a tech (e.g. Ethan Smith) has Weekly Pool
    // Cleaning jobs, the bucket row shows the aggregate (12) — the
    // per-tech drill-down detail lives in the existing modal path.
    _mountReport(_buildData());
    await waitFor(() =>
      screen.getByTestId("pool-report-service-name-section"),
    );
    const row = screen.getByTestId(
      "pool-report-service-name-row-weekly-pool-cleaning",
    );
    expect(row.textContent).toContain("Weekly Pool Cleaning");
    expect(row.textContent).toContain("12");
  });
});
