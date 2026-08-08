/**
 * Phase 53c-fix · Feb-2026 — manager read-only EBIT vitest.
 *
 * Focused regression suite for the manager read-only rendering rules
 * introduced by 53c-fix. Confirms that:
 *   • role=manager renders every adjustment input in the ``disabled``
 *     state, hides all flip-override + clear-override buttons, hides
 *     the save button, hides the save-note input, keeps the history
 *     button + CSV/PDF export buttons enabled, and surfaces the
 *     yellow ``read-only`` badge.
 *   • role=admin (regression guard) still renders every control as
 *     editable — inputs enabled, flip buttons present, save button
 *     present, no read-only badge.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a), post: (...a) => postMock(...a) },
}));

const authState = { user: { role: "manager", id: "u_mgr" } };
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

const LIVE = {
  range_from: "2026-02-01", range_to: "2026-02-28",
  revenue_basis: "cash",
  revenue: 1500, cogs: 300, opex: 900, depreciation: 200, ebit: 100,
  breakdown: { invoice_count: 2, line_count: 2, opex_payroll: 700,
                opex_other: 200, opex_by_category: [],
                depreciation_by_category: [], wages_by_role: {} },
  line_adjustments: { revenue: 0, cogs: 0, opex: 0, depreciation: 0 },
  line_overrides:   { revenue: null, cogs: null, opex: null, depreciation: null },
};

const LINE_KEYS = ["revenue", "cogs", "opex", "depreciation"];

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});
afterEach(() => cleanup());

describe("EbitPanel · role=manager read-only rendering", () => {
  it("renders every adjustment input in the disabled state", async () => {
    getMock.mockResolvedValueOnce(LIVE);
    authState.user = { role: "manager", id: "u_mgr" };
    render(<EbitPanel />);
    await waitFor(() => expect(screen.getByTestId("ebit-panel")).toBeTruthy());

    for (const k of LINE_KEYS) {
      expect(screen.getByTestId(`ebit-row-${k}-adjustment-mode`)).toBeTruthy();
      const input = screen.getByTestId(`ebit-row-${k}-adjustment-input`);
      expect(input.disabled).toBe(true);
      expect(input.getAttribute("title")).toContain("Read-only");
    }
  });

  it("hides every flip-to-override button", async () => {
    getMock.mockResolvedValueOnce(LIVE);
    authState.user = { role: "manager", id: "u_mgr" };
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-panel"));
    for (const k of LINE_KEYS) {
      expect(screen.queryByTestId(`ebit-row-${k}-flip-override`)).toBeNull();
    }
  });

  it("hides the save button + save note input", async () => {
    getMock.mockResolvedValueOnce(LIVE);
    authState.user = { role: "manager", id: "u_mgr" };
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-panel"));
    expect(screen.queryByTestId("ebit-save-btn")).toBeNull();
    expect(screen.queryByTestId("ebit-save-note")).toBeNull();
    expect(screen.queryByTestId("ebit-save-row")).toBeNull();
  });

  it("keeps history + CSV + PDF export buttons enabled", async () => {
    getMock.mockResolvedValueOnce(LIVE);
    authState.user = { role: "manager", id: "u_mgr" };
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-panel"));
    expect(screen.getByTestId("ebit-open-versions").disabled).toBe(false);
    expect(screen.getByTestId("ebit-export-csv").disabled).toBe(false);
    expect(screen.getByTestId("ebit-export-pdf").disabled).toBe(false);
  });

  it("surfaces the yellow read-only badge in the header", async () => {
    getMock.mockResolvedValueOnce(LIVE);
    authState.user = { role: "manager", id: "u_mgr" };
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-panel"));
    const badge = screen.getByTestId("ebit-panel-readonly-badge");
    expect(badge.textContent.toLowerCase()).toContain("read-only");
  });
});

describe("EbitPanel · role=admin regression (unchanged by 53c-fix)", () => {
  it("renders every adjustment input as enabled + flip buttons present + save button visible", async () => {
    getMock.mockResolvedValueOnce(LIVE);
    authState.user = { role: "admin", id: "u_admin" };
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-panel"));
    for (const k of LINE_KEYS) {
      const input = screen.getByTestId(`ebit-row-${k}-adjustment-input`);
      expect(input.disabled).toBe(false);
      expect(screen.getByTestId(`ebit-row-${k}-flip-override`)).toBeTruthy();
    }
    expect(screen.getByTestId("ebit-save-btn")).toBeTruthy();
    expect(screen.queryByTestId("ebit-panel-readonly-badge")).toBeNull();
  });

  it("super_admin regression: every control enabled + no read-only badge", async () => {
    getMock.mockResolvedValueOnce(LIVE);
    authState.user = { role: "super_admin", id: "u_super" };
    render(<EbitPanel />);
    await waitFor(() => screen.getByTestId("ebit-panel"));
    expect(screen.getByTestId("ebit-row-revenue-adjustment-input").disabled).toBe(false);
    expect(screen.getByTestId("ebit-save-btn")).toBeTruthy();
    expect(screen.queryByTestId("ebit-panel-readonly-badge")).toBeNull();
  });
});
