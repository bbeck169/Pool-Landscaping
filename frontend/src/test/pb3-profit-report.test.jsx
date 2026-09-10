/**
 * Feb-2026 · Pricebook × Profit-Reporting Phase 3 vitest.
 *
 * Coverage:
 *   1. Renders table + totals + snapshot coverage tile from the
 *      Phase 3 canonical envelope shape.
 *   2. Group-by toggle refetches with the new dimension query param.
 *   3. CSV export button hits ``/api/reports/profit.csv`` with the
 *      same query params + auth header.
 *   4. Uncategorized row surfaces a "Fix" affordance (proxy for the
 *      warning-icon requirement — same admin-only recovery path).
 *   5. Non-admin (manager) sees the forbidden panel — no report /
 *      no health tile / no CSV button.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Mocked api layer routes ``/reports/*`` + benign ``/ebit/*`` ──
const _profitMock = vi.fn();
const _healthMock = vi.fn();
const _routedGet = (url, ...rest) => {
  if (typeof url === "string" && url.startsWith("/ebit/")) {
    return Promise.resolve({
      snapshots: [], count: 0,
      revenue: 0, cogs: 0, opex: 0, depreciation: 0, ebit: 0,
      breakdown: {}, line_adjustments: {}, line_overrides: {},
    });
  }
  if (typeof url === "string" && url.startsWith("/reports/pricebook-health")) {
    return _healthMock(url, ...rest);
  }
  return _profitMock(url, ...rest);
};
vi.mock("@/api", () => ({
  api: {
    get: (u, ...r) => _routedGet(u, ...r),
    post: () => Promise.resolve({}),
  },
}));

const authState = { user: { role: "super_admin", email: "s@t" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceAlt: "#fafafa",
    border: "#eee", muted: "#666", brand: "#0891B2",
    onSurface: "#000", onSurfaceSecondary: "#666",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

vi.mock("@/components/ui-kit", () => ({
  Skeleton: (p) => <div {...p} />,
  PageHeader: () => null,
  Card: ({ children }) => <div>{children}</div>,
}));

import ProfitReportPage from "@/pages/admin/ProfitReportPage";

const _envelope = {
  from: "2026-02-01", to: "2026-02-28",
  group_by: "service_category",
  dimension: "service_category",
  currency: "USD",
  totals: {
    revenue: 650, cogs: 189, labor: 41,
    gross_profit: 420, margin_pct: 64.6, line_count: 8,
  },
  rows: [
    { category_id: "svc-a", category_name: "Pool Cleaning",
      revenue: 450, cogs: 179, labor: 41, profit: 230,
      margin_pct: 51.1, line_count: 4 },
    { category_id: "svc-b", category_name: "Repair",
      revenue: 100, cogs: 40, labor: 20, profit: 40,
      margin_pct: 40.0, line_count: 1 },
    { category_id: "__uncategorized__", category_name: "Uncategorized",
      revenue: 100, cogs: 0, labor: 0, profit: 100,
      margin_pct: 100.0, line_count: 1,
      uncategorized_item_ids: [] },
  ],
  breakdown: [], // filled below to match rows for back-compat
  assumptions: {
    partial_invoices: "prorated by amount_paid/total",
    tax: "excluded (unit_price treated as pre-tax retail)",
    null_snapshots: "bucketed as Uncategorized",
    override_precedence: "override > line-level > item-lookup",
  },
};
_envelope.breakdown = _envelope.rows;

const _health = {
  window_days: 90,
  as_of: new Date().toISOString(),
  lines_total: 8,
  lines_with_wholesale_snapshot: 7,
  lines_with_labor_snapshot: 7,
  lines_with_any_snapshot: 7,
  coverage_pct: { wholesale: 87.5, labor: 87.5, any: 87.5 },
};

beforeEach(() => {
  _profitMock.mockReset();
  _healthMock.mockReset();
  _profitMock.mockResolvedValue(_envelope);
  _healthMock.mockResolvedValue(_health);
  authState.user = { role: "super_admin", email: "s@t" };
});

afterEach(() => cleanup());

const renderPage = () => render(
  <MemoryRouter><ProfitReportPage /></MemoryRouter>,
);


describe("PB3 · Profit Report page", () => {
  it("renders snapshot coverage tile + table + totals from envelope", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-health-tile")).toBeTruthy(),
    );
    // Coverage % surfaces.
    expect(screen.getByTestId("profit-report-health-coverage-pct").textContent)
      .toMatch(/87\.5/);
    // Rows render with 3 data rows.
    await waitFor(() =>
      expect(screen.getAllByTestId(/^profit-report-row-/).length).toBeGreaterThanOrEqual(3),
    );
    // Uncategorized row visible.
    expect(screen.getByTestId("profit-report-row-__uncategorized__")).toBeTruthy();
    // Totals row visible with formatted revenue.
    const totals = screen.getByTestId("profit-report-totals-row");
    expect(totals.textContent).toMatch(/650/);
  });

  it("group-by toggle refetches with income_category param", async () => {
    renderPage();
    await waitFor(() =>
      expect(_profitMock.mock.calls.length).toBeGreaterThanOrEqual(1),
    );
    const initial = _profitMock.mock.calls.length;
    fireEvent.click(screen.getByTestId("profit-report-dim-income"));
    await waitFor(() =>
      expect(_profitMock.mock.calls.length).toBeGreaterThan(initial),
    );
    const lastCall = _profitMock.mock.calls[_profitMock.mock.calls.length - 1][0];
    expect(lastCall).toContain("dimension=income_category");
  });

  it("CSV export button hits /reports/profit.csv with same params", async () => {
    // Stub fetch for CSV blob.
    const _fetch = vi.fn().mockResolvedValue({ blob: () => Promise.resolve(new Blob(["x"])) });
    globalThis.fetch = _fetch;
    // Stub URL.createObjectURL / revokeObjectURL.
    global.URL.createObjectURL = vi.fn(() => "blob:x");
    global.URL.revokeObjectURL = vi.fn();
    // Stub localStorage token.
    Object.defineProperty(globalThis, "localStorage", {
      value: {
        getItem: (k) => (k === "access_token" ? "TOKEN-XYZ" : null),
      },
      configurable: true,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-csv-btn")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("profit-report-csv-btn"));
    await waitFor(() => expect(_fetch).toHaveBeenCalled());
    const [csvUrl, opts] = _fetch.mock.calls[0];
    expect(csvUrl).toContain("/api/reports/profit.csv");
    expect(csvUrl).toContain("dimension=service_category");
    expect(opts.headers.Authorization).toBe("Bearer TOKEN-XYZ");
  });

  it("Uncategorized row exposes admin recovery affordance (Fix)", async () => {
    // Give the uncategorized row a couple of item ids to make Fix relevant.
    _envelope.rows[2].uncategorized_item_ids = ["item-legacy-1", "item-legacy-2"];
    _envelope.breakdown = _envelope.rows;
    _profitMock.mockResolvedValue(_envelope);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-row-__uncategorized__")).toBeTruthy(),
    );
    // Fix button testid — provided by PB1 QoL wire-up on the uncat row.
    const fixBtn = screen.queryByTestId("profit-report-uncategorized-fix");
    expect(fixBtn).toBeTruthy();
  });

  it("non-admin (manager) sees forbidden panel — no table, no health, no CSV", async () => {
    authState.user = { role: "manager", email: "m@t" };
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-forbidden")).toBeTruthy(),
    );
    expect(screen.queryByTestId("profit-report-health-tile")).toBeNull();
    expect(screen.queryByTestId("profit-report-csv-btn")).toBeNull();
    expect(screen.queryAllByTestId(/^profit-report-row-/).length).toBe(0);
  });
});
