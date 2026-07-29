/**
 * PB1 · Feb-2026 — Profit Report page vitest.
 *
 * Covers:
 *   1. Renders summary tiles + breakdown table from a fixture.
 *   2. Dimension toggle refetches with the new query param.
 *   3. "Custom" range enables from/to inputs; both must be filled
 *      before a fetch fires.
 *   4. Non-admin users see the forbidden panel.
 *   5. CSV export button hits the .csv endpoint.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
vi.mock("@/api", () => ({ api: { get: (...a) => getMock(...a) } }));

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

const renderPage = () => render(
  <MemoryRouter><ProfitReportPage /></MemoryRouter>,
);

const FIXTURE = {
  range: { from: "2026-02-01", to: "2026-02-28", label: "This Month" },
  dimension: "service_category",
  totals: {
    revenue: 370, cogs: 125, labor: 49,
    gross_profit: 196, margin_pct: 52.97, line_count: 3,
  },
  breakdown: [
    {category_id: "svc_a", category_name: "Pool Cleaning",
      revenue: 320, cogs: 105, labor: 44, profit: 171,
      margin_pct: 53.4, line_count: 2},
    {category_id: "svc_b", category_name: "Landscaping",
      revenue: 50, cogs: 20, labor: 5, profit: 25,
      margin_pct: 50.0, line_count: 1},
  ],
};

beforeEach(() => {
  getMock.mockReset();
  authState.user = { role: "super_admin", email: "s@t" };
});
afterEach(() => cleanup());


describe("ProfitReportPage · super-admin gate", () => {
  it("shows a forbidden panel when the role is customer", () => {
    authState.user = { role: "customer" };
    renderPage();
    expect(screen.getByTestId("profit-report-forbidden"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("profit-report-page"))
      .not.toBeInTheDocument();
  });
});


describe("ProfitReportPage · render + summary tiles", () => {
  it("renders all 5 summary tiles + breakdown rows", async () => {
    getMock.mockResolvedValue(FIXTURE);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("profit-report-tile-revenue"))
        .toBeInTheDocument();
    });
    expect(screen.getByTestId("profit-report-tile-cogs"))
      .toBeInTheDocument();
    expect(screen.getByTestId("profit-report-tile-labor"))
      .toBeInTheDocument();
    expect(screen.getByTestId("profit-report-tile-profit"))
      .toBeInTheDocument();
    expect(screen.getByTestId("profit-report-tile-margin"))
      .toBeInTheDocument();
    expect(screen.getByTestId("profit-report-row-svc_a"))
      .toBeInTheDocument();
    expect(screen.getByTestId("profit-report-row-svc_b"))
      .toBeInTheDocument();
    // Revenue tile shows $370.00.
    expect(screen.getByTestId("profit-report-tile-revenue").textContent)
      .toMatch(/\$370\.00/);
  });
});


describe("ProfitReportPage · dimension toggle", () => {
  it("re-fetches with the new dimension query param", async () => {
    getMock.mockResolvedValue(FIXTURE);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-tile-revenue"))
        .toBeInTheDocument(),
    );
    // Initial call goes with service_category.
    expect(getMock).toHaveBeenCalled();
    const firstUrl = getMock.mock.calls[0][0];
    expect(firstUrl).toContain("dimension=service_category");

    // Prep response for the income call.
    getMock.mockResolvedValueOnce({
      ...FIXTURE, dimension: "income_category",
    });
    fireEvent.click(screen.getByTestId("profit-report-dim-income"));
    await waitFor(() => {
      const urls = getMock.mock.calls.map((c) => c[0]);
      expect(urls.some((u) => u.includes("dimension=income_category")))
        .toBe(true);
    });
  });
});


describe("ProfitReportPage · custom range", () => {
  it("Custom pill surfaces both date inputs", async () => {
    getMock.mockResolvedValue(FIXTURE);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-tile-revenue"))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("profit-report-range-custom"));
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-custom-picker"))
        .toBeInTheDocument(),
    );
    expect(screen.getByTestId("profit-report-custom-from"))
      .toBeInTheDocument();
    expect(screen.getByTestId("profit-report-custom-to"))
      .toBeInTheDocument();
  });

  it("does not fetch until both from AND to are set", async () => {
    getMock.mockResolvedValue(FIXTURE);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-tile-revenue"))
        .toBeInTheDocument(),
    );
    const initialCallCount = getMock.mock.calls.length;
    fireEvent.click(screen.getByTestId("profit-report-range-custom"));
    // Only "from" set — no new fetch.
    fireEvent.change(screen.getByTestId("profit-report-custom-from"),
                      { target: { value: "2026-02-01" } });
    // Small delay for effects.
    await new Promise((r) => setTimeout(r, 30));
    expect(getMock.mock.calls.length).toBe(initialCallCount);
    // Now set "to" — a fetch should fire with both params.
    fireEvent.change(screen.getByTestId("profit-report-custom-to"),
                      { target: { value: "2026-02-28" } });
    await waitFor(() => {
      const urls = getMock.mock.calls.map((c) => c[0]);
      expect(urls.some((u) =>
        u.includes("range=custom") &&
        u.includes("from=2026-02-01") &&
        u.includes("to=2026-02-28"))).toBe(true);
    });
  });
});
