/**
 * Phase 13 · Feb-2026 — EBIT LABOR row + expand/breakdown UI tests.
 *
 * Covers the 7 cases from the Phase 13 Ticket B brief:
 *
 *   1. LABOR row renders with ``labor_cost_total`` value.
 *   2. Expand chevron is present.
 *   3. Click expand reveals Hourly + per-pool sub-row with correct
 *      value from ``labor_cost``.
 *   4. Click expand reveals Recurring sub-row with correct value
 *      from ``recurring_labor_cost``.
 *   5. ``by_entry`` sub-items render with label + cost each.
 *   6. Collapse re-hides the sub-rows.
 *   7. If ``labor_cost_total = 0``, LABOR row still renders
 *      (shows "$0.00"), no crash.
 *
 * Mocks ``@/api`` so no network traffic fires. Mirrors the test
 * harness used by ``ebit-panel.test.jsx`` (same auth-state hook
 * mock pattern) so the panel renders in editable super_admin mode.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    put: () => Promise.resolve({}),
    patch: () => Promise.resolve({}),
    delete: () => Promise.resolve({}),
  },
}));
const authState = { user: { role: "super_admin", id: "u1" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));


import EbitPanel from "@/components/admin/EbitPanel";


const _BY_ENTRY = [
  { id: "rlc-1", label: "Office manager salary",
    monthly_amount: 4800, months_in_window: 1, cost_in_window: 4800 },
  { id: "rlc-2", label: "Bookkeeper contract",
    monthly_amount: 1500, months_in_window: 1, cost_in_window: 1500 },
];


const LIVE_WITH_LABOR = {
  range_from: "2026-02-01", range_to: "2026-02-28",
  revenue_basis: "cash",
  revenue: 10000, cogs: 2000, opex: 3000, depreciation: 500,
  // Phase 11 arithmetic: 10000 - 2000 - 3000 - 500 - 8500 = -4000.
  labor_cost: 2200,
  recurring_labor_cost: 6300,
  labor_cost_total: 8500,
  ebit: -4000,
  breakdown: {
    invoice_count: 2, line_count: 2,
    opex_payroll: 0, opex_other: 3000,
    opex_by_category: [], depreciation_by_category: [], wages_by_role: {},
    labor_cost_breakdown: {
      totals: { total_labor_cost: 2200 },
      by_technician: [],
    },
    recurring_labor_breakdown: {
      by_entry: _BY_ENTRY,
      total: 6300,
      range: { start: "2026-02-01", end: "2026-02-28" },
    },
  },
  line_adjustments: { revenue: 0, cogs: 0, opex: 0, depreciation: 0 },
  line_overrides:   { revenue: null, cogs: null, opex: null, depreciation: null },
};


const LIVE_ZERO_LABOR = {
  ...LIVE_WITH_LABOR,
  labor_cost: 0, recurring_labor_cost: 0, labor_cost_total: 0,
  // 10000 - 2000 - 3000 - 500 - 0 = 4500.
  ebit: 4500,
  breakdown: {
    ...LIVE_WITH_LABOR.breakdown,
    recurring_labor_breakdown: {
      by_entry: [], total: 0,
      range: { start: "2026-02-01", end: "2026-02-28" },
    },
  },
};


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  authState.user = { role: "super_admin", email: "s@t", id: "u1" };
});
afterEach(() => cleanup());


describe("EbitPanel · Phase 13 LABOR row", () => {
  // 1
  it("renders a LABOR row showing labor_cost_total", async () => {
    getMock.mockResolvedValueOnce(LIVE_WITH_LABOR);
    render(<EbitPanel />);
    await waitFor(() =>
      expect(screen.getByTestId("ebit-row-labor")).toBeTruthy());
    const total = screen.getByTestId("ebit-row-labor-total");
    expect(total.textContent).toContain("8,500");
  });

  // 2
  it("exposes the expand/collapse toggle button", async () => {
    getMock.mockResolvedValueOnce(LIVE_WITH_LABOR);
    render(<EbitPanel />);
    await waitFor(() =>
      expect(screen.getByTestId("ebit-row-labor-toggle"))
        .toBeTruthy());
    const toggle = screen.getByTestId("ebit-row-labor-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    // Collapsed by default — breakdown section not visible yet.
    expect(screen.queryByTestId("ebit-row-labor-breakdown"))
      .toBeNull();
  });

  // 3
  it("Click expand reveals Hourly + per-pool sub-row with value",
      async () => {
        getMock.mockResolvedValueOnce(LIVE_WITH_LABOR);
        render(<EbitPanel />);
        await waitFor(() => screen.getByTestId("ebit-row-labor"));
        fireEvent.click(screen.getByTestId("ebit-row-labor-toggle"));
        expect(screen.getByTestId("ebit-row-labor-hourly"))
          .toBeTruthy();
        expect(
          screen.getByTestId("ebit-row-labor-hourly-value").textContent,
        ).toContain("2,200");
      });

  // 4
  it("Click expand reveals Recurring sub-row with value",
      async () => {
        getMock.mockResolvedValueOnce(LIVE_WITH_LABOR);
        render(<EbitPanel />);
        await waitFor(() => screen.getByTestId("ebit-row-labor"));
        fireEvent.click(screen.getByTestId("ebit-row-labor-toggle"));
        expect(screen.getByTestId("ebit-row-labor-recurring"))
          .toBeTruthy();
        expect(
          screen.getByTestId("ebit-row-labor-recurring-value").textContent,
        ).toContain("6,300");
      });

  // 5
  it("by_entry sub-items render with label + cost each", async () => {
    getMock.mockResolvedValueOnce(LIVE_WITH_LABOR);
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-row-labor"));
    fireEvent.click(screen.getByTestId("ebit-row-labor-toggle"));
    const list = screen.getByTestId("ebit-row-labor-by-entry");
    expect(list.textContent).toContain("Office manager salary");
    expect(list.textContent).toContain("Bookkeeper contract");
    expect(list.textContent).toContain("4,800");
    expect(list.textContent).toContain("1,500");
    expect(screen.getByTestId("ebit-row-labor-entry-0"))
      .toBeTruthy();
    expect(screen.getByTestId("ebit-row-labor-entry-1"))
      .toBeTruthy();
  });

  // 6
  it("Collapse hides the breakdown section", async () => {
    getMock.mockResolvedValueOnce(LIVE_WITH_LABOR);
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-row-labor"));
    const toggle = screen.getByTestId("ebit-row-labor-toggle");
    fireEvent.click(toggle);
    expect(screen.getByTestId("ebit-row-labor-breakdown"))
      .toBeTruthy();
    fireEvent.click(toggle);
    expect(screen.queryByTestId("ebit-row-labor-breakdown"))
      .toBeNull();
    expect(screen.queryByTestId("ebit-row-labor-hourly"))
      .toBeNull();
  });

  // 7
  it("renders $0.00 when labor_cost_total is zero (no crash)",
      async () => {
        getMock.mockResolvedValueOnce(LIVE_ZERO_LABOR);
        render(<EbitPanel />);
        await waitFor(() =>
          expect(screen.getByTestId("ebit-row-labor")).toBeTruthy());
        const total = screen.getByTestId("ebit-row-labor-total");
        expect(total.textContent).toContain("0");
        fireEvent.click(screen.getByTestId("ebit-row-labor-toggle"));
        // by_entry list is absent when empty; hourly + recurring
        // sub-rows still render at $0.
        expect(screen.queryByTestId("ebit-row-labor-by-entry"))
          .toBeNull();
        expect(
          screen.getByTestId("ebit-row-labor-hourly-value").textContent,
        ).toContain("0");
        expect(
          screen.getByTestId("ebit-row-labor-recurring-value").textContent,
        ).toContain("0");
      });
});


describe("EbitPanel · Phase 13 bottom-line arithmetic", () => {
  it("effective EBIT subtracts labor_cost_total (10000-2000-3000-500-8500=-4000)",
      async () => {
        getMock.mockResolvedValueOnce(LIVE_WITH_LABOR);
        render(<EbitPanel />);
        await waitFor(() => screen.getByTestId("ebit-total-value"));
        const txt = screen.getByTestId("ebit-total-value").textContent;
        expect(txt).toContain("-4,000");
      });

  it("effective EBIT with zero labor equals the no-labor sum (4500)",
      async () => {
        getMock.mockResolvedValueOnce(LIVE_ZERO_LABOR);
        render(<EbitPanel />);
        await waitFor(() => screen.getByTestId("ebit-total-value"));
        expect(
          screen.getByTestId("ebit-total-value").textContent,
        ).toContain("4,500");
      });
});
