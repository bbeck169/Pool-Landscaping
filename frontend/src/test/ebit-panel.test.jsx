/**
 * Phase 53b · Feb-2026 — EBIT panel vitest.
 *
 * Covers:
 *   1. Role gate (super/admin/manager/tech/customer)
 *   2. Adjustment mode: delta updates effective + EBIT total
 *   3. Override mode: absolute value replaces computed; clear reverts
 *   4. Time-range picker: switching refetches from /ebit/compute
 *   5. Revenue basis toggle: refetch with basis param
 *   6. Save flow: POST returns new snapshot; version pill updates
 *   7. Version history modal: renders list; load populates read-only
 *   8. CSV + PDF export triggers
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, act, cleanup,
} from "@testing-library/react";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
  },
}));

const authState = { user: { role: "super_admin", email: "s@t", id: "u1" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceAlt: "#fafafa",
    border: "#eee", muted: "#666", brand: "#0891B2",
    onSurface: "#000", onSurfaceSecondary: "#666",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

import EbitPanel from "@/components/admin/EbitPanel";

const LIVE_CASH = {
  range_from: "2026-02-01", range_to: "2026-02-28",
  revenue_basis: "cash",
  revenue: 1500, cogs: 300, opex: 900, depreciation: 200, ebit: 100,
  breakdown: { invoice_count: 2, line_count: 2, opex_payroll: 700,
                opex_other: 200, opex_by_category: [],
                depreciation_by_category: [], wages_by_role: {} },
  line_adjustments: { revenue: 0, cogs: 0, opex: 0, depreciation: 0 },
  line_overrides:   { revenue: null, cogs: null, opex: null, depreciation: null },
};
const LIVE_ACCRUAL = { ...LIVE_CASH, revenue: 2300, ebit: 900, revenue_basis: "accrual" };

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  authState.user = { role: "super_admin", email: "s@t", id: "u1" };
});
afterEach(() => cleanup());

// ═══════════════════════════════════════════════════════════════════
// 1. Role gate
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · role gate", () => {
  it("super_admin sees the editable panel", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    authState.user = { role: "super_admin", id: "u1" };
    render(<EbitPanel />);
    await waitFor(() => expect(screen.getByTestId("ebit-panel")).toBeTruthy());
    expect(screen.getByTestId("ebit-row-revenue-adjustment-mode")).toBeTruthy();
    expect(screen.getByTestId("ebit-save-btn")).toBeTruthy();
  });

  it("admin sees the editable panel", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    authState.user = { role: "admin", id: "u1" };
    render(<EbitPanel />);
    await waitFor(() => expect(screen.getByTestId("ebit-panel")).toBeTruthy());
    expect(screen.getByTestId("ebit-save-btn")).toBeTruthy();
  });

  it("manager sees the panel READ-ONLY (no save button, no adjustment inputs)", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    authState.user = { role: "manager", id: "u1" };
    render(<EbitPanel />);
    await waitFor(() => expect(screen.getByTestId("ebit-panel")).toBeTruthy());
    expect(screen.queryByTestId("ebit-save-btn")).toBeNull();
    expect(screen.queryByTestId("ebit-row-revenue-adjustment-mode")).toBeNull();
    // History + exports remain available.
    expect(screen.getByTestId("ebit-open-versions")).toBeTruthy();
  });

  it("tech is fully forbidden (no fetch, forbidden banner)", async () => {
    authState.user = { role: "tech", id: "u1" };
    render(<EbitPanel />);
    expect(screen.getByTestId("ebit-panel-forbidden")).toBeTruthy();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("customer is fully forbidden", async () => {
    authState.user = { role: "customer", id: "u1" };
    render(<EbitPanel />);
    expect(screen.getByTestId("ebit-panel-forbidden")).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════
// 2. Adjustment mode
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · adjustment mode", () => {
  it("entering a delta updates the effective value and EBIT total", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    render(<EbitPanel />);
    await waitFor(() => expect(screen.getByTestId("ebit-total-value")).toBeTruthy());
    expect(screen.getByTestId("ebit-total-value").textContent).toContain("100.00");

    const input = screen.getByTestId("ebit-row-revenue-adjustment-input");
    fireEvent.change(input, { target: { value: "50" } });

    // Revenue effective 1500 + 50 = 1550 → EBIT 100 + 50 = 150.
    expect(screen.getByTestId("ebit-row-revenue-effective").textContent).toContain("1550.00");
    expect(screen.getByTestId("ebit-total-value").textContent).toContain("150.00");
  });

  it("negative adjustments propagate to EBIT total", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-total-value"));

    fireEvent.change(screen.getByTestId("ebit-row-opex-adjustment-input"),
                     { target: { value: "-100" } });
    // OpEx 900 - 100 = 800. EBIT = 1500 - 300 - 800 - 200 = 200.
    expect(screen.getByTestId("ebit-total-value").textContent).toContain("200.00");
  });
});

// ═══════════════════════════════════════════════════════════════════
// 3. Override mode
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · override mode", () => {
  it("flipping to override replaces computed value; clearing reverts", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-total-value"));

    fireEvent.click(screen.getByTestId("ebit-row-depreciation-flip-override"));

    const ovrInput = screen.getByTestId("ebit-row-depreciation-override-input");
    fireEvent.change(ovrInput, { target: { value: "999" } });
    // Depreciation 999 → EBIT = 1500 - 300 - 900 - 999 = -699.
    expect(screen.getByTestId("ebit-row-depreciation-effective").textContent).toContain("999.00");
    expect(screen.getByTestId("ebit-total-value").textContent).toContain("-699.00");

    fireEvent.click(screen.getByTestId("ebit-row-depreciation-override-clear"));
    // Reverted to computed 200 → EBIT back to 100.
    expect(screen.getByTestId("ebit-row-depreciation-adjustment-mode")).toBeTruthy();
    expect(screen.getByTestId("ebit-total-value").textContent).toContain("100.00");
  });
});

// ═══════════════════════════════════════════════════════════════════
// 4. Time-range picker refetches
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · time-range picker", () => {
  it("switching to quarterly triggers a refetch", async () => {
    getMock
      .mockResolvedValueOnce(LIVE_CASH)     // initial monthly
      .mockResolvedValueOnce(LIVE_CASH);    // quarterly

    render(<EbitPanel />);
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));
    expect(getMock.mock.calls[0][0]).toMatch(/range=monthly/);

    fireEvent.click(screen.getByTestId("ebit-range-quarterly"));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    expect(getMock.mock.calls[1][0]).toMatch(/range=quarterly/);
  });
});

// ═══════════════════════════════════════════════════════════════════
// 5. Revenue basis toggle
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · basis toggle", () => {
  it("switching to accrual refetches with basis=accrual and shows new EBIT", async () => {
    getMock
      .mockResolvedValueOnce(LIVE_CASH)
      .mockResolvedValueOnce(LIVE_ACCRUAL);

    render(<EbitPanel />);
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId("ebit-basis-accrual"));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    expect(getMock.mock.calls[1][0]).toMatch(/revenue_basis=accrual/);

    await waitFor(() =>
      expect(screen.getByTestId("ebit-total-value").textContent).toContain("900.00"));
  });
});

// ═══════════════════════════════════════════════════════════════════
// 6. Save flow
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · save flow", () => {
  it("save posts to /ebit/snapshots and updates the version pill", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    postMock.mockResolvedValueOnce({
      id: "snap-1", version: 3, ebit: 100,
      line_adjustments: {}, line_overrides: {}, saved_at: "2026-02-15",
      revenue_basis: "cash", author_user_id: "u1", note: "test",
    });
    // For the auto-refetch snapshots after save:
    getMock.mockResolvedValueOnce({ snapshots: [] });

    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-save-btn"));

    fireEvent.change(screen.getByTestId("ebit-save-note"), { target: { value: "test" } });
    fireEvent.click(screen.getByTestId("ebit-save-btn"));

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock.mock.calls[0][0]).toBe("/ebit/snapshots");
    const body = postMock.mock.calls[0][1];
    expect(body.range_kind).toBe("monthly");
    expect(body.revenue_basis).toBe("cash");
    expect(body.note).toBe("test");

    await waitFor(() =>
      expect(screen.getByTestId("ebit-panel-loaded-version").textContent).toContain("v3"));
  });
});

// ═══════════════════════════════════════════════════════════════════
// 7. Version history modal
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · version history", () => {
  it("clicking History opens modal, loading a version puts editor in read-only", async () => {
    getMock
      .mockResolvedValueOnce(LIVE_CASH)  // initial compute
      .mockResolvedValueOnce({           // snapshots list
        snapshots: [
          { id: "s1", version: 2, ebit: 150, revenue_basis: "cash",
            saved_at: "2026-02-10", author_user_id: "u1",
            line_adjustments: { revenue: 50, cogs: 0, opex: 0, depreciation: 0 },
            line_overrides: { revenue: null, cogs: null, opex: null, depreciation: null },
            note: "prior" },
          { id: "s0", version: 1, ebit: 100, revenue_basis: "cash",
            saved_at: "2026-02-05", author_user_id: "u1",
            line_adjustments: {}, line_overrides: {}, note: "" },
        ],
      });

    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-total-value"));

    fireEvent.click(screen.getByTestId("ebit-open-versions"));
    await waitFor(() => screen.getByTestId("ebit-versions-modal"));
    expect(screen.getByTestId("ebit-versions-row-s1")).toBeTruthy();
    expect(screen.getByTestId("ebit-versions-row-s0")).toBeTruthy();

    fireEvent.click(screen.getByTestId("ebit-versions-load-s1"));
    // Modal closes, editor read-only with v2 pill and Fork button visible.
    await waitFor(() =>
      expect(screen.queryByTestId("ebit-versions-modal")).toBeNull());
    expect(screen.getByTestId("ebit-panel-loaded-version").textContent).toContain("v2");
    expect(screen.getByTestId("ebit-fork-btn")).toBeTruthy();
    // Save button hidden while read-only.
    expect(screen.queryByTestId("ebit-save-btn")).toBeNull();

    // Fork → editable again.
    fireEvent.click(screen.getByTestId("ebit-fork-btn"));
    expect(screen.getByTestId("ebit-save-btn")).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════
// 8. Export buttons
// ═══════════════════════════════════════════════════════════════════
describe("EbitPanel · exports", () => {
  it("CSV button creates a blob download", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;

    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-export-csv"));
    fireEvent.click(screen.getByTestId("ebit-export-csv"));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blobArg = createObjectURL.mock.calls[0][0];
    expect(blobArg).toBeInstanceOf(Blob);
    expect(blobArg.type).toContain("text/csv");
  });

  it("PDF button calls window.print", async () => {
    getMock.mockResolvedValueOnce(LIVE_CASH);
    const printSpy = vi.fn();
    window.print = printSpy;

    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-export-pdf"));
    fireEvent.click(screen.getByTestId("ebit-export-pdf"));

    expect(printSpy).toHaveBeenCalledTimes(1);
  });
});
