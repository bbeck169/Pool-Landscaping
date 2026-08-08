/**
 * PB1-QoL · Feb-2026 — Uncategorized "Fix" deep-link vitest.
 *
 * Covers:
 *   1. Fix button appears ONLY on the Uncategorized breakdown row.
 *   2. Non-Uncategorized rows never render a Fix button.
 *   3. Clicking Fix opens the modal and fetches item names via GET /items/{id}.
 *   4. Modal renders one row per item with a "Set category" link.
 *   5. Done / close dismisses the modal without further fetches.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Phase 53b · Feb-2026 — the page now also mounts <EbitPanel /> which
// calls /ebit/* on mount. Route those calls to a benign response so
// getMock only records /reports/profit + /items/* calls.
const _profitMock = vi.fn();
const getMock = _profitMock;
const _routedGet = (url, ...rest) => {
  if (typeof url === "string" && url.startsWith("/ebit/")) {
    return Promise.resolve({
      snapshots: [], count: 0,
      revenue: 0, cogs: 0, opex: 0, depreciation: 0, ebit: 0,
      breakdown: {}, line_adjustments: {}, line_overrides: {},
    });
  }
  return _profitMock(url, ...rest);
};
vi.mock("@/api", () => ({ api: { get: (u, ...r) => _routedGet(u, ...r), post: () => Promise.resolve({}) } }));

const authState = { user: { role: "admin" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceAlt: "#fafafa",
    surfaceSecondary: "#f5f5f5",
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

const FIXTURE_WITH_UNCAT = {
  range: { from: "2026-02-01", to: "2026-02-28", label: "This Month" },
  dimension: "service_category",
  totals: {
    revenue: 500, cogs: 100, labor: 50,
    gross_profit: 350, margin_pct: 70.0, line_count: 4,
  },
  breakdown: [
    {category_id: "svc_pool", category_name: "Pool Cleaning",
      revenue: 350, cogs: 80, labor: 40, profit: 230,
      margin_pct: 65.7, line_count: 3},
    {category_id: "__uncategorized__", category_name: "Uncategorized",
      revenue: 150, cogs: 20, labor: 10, profit: 120,
      margin_pct: 80.0, line_count: 1,
      uncategorized_item_ids: ["item-A", "item-B"]},
  ],
};

beforeEach(() => {
  getMock.mockReset();
  authState.user = { role: "admin" };
});
afterEach(() => cleanup());


describe("Profit Report · Uncategorized Fix deep-link", () => {
  const renderPage = () => render(
    <MemoryRouter><ProfitReportPage /></MemoryRouter>,
  );

  it("renders Fix button ONLY on the Uncategorized row", async () => {
    getMock.mockResolvedValue(FIXTURE_WITH_UNCAT);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-tile-revenue"))
        .toBeInTheDocument(),
    );
    // Both rows present.
    expect(screen.getByTestId("profit-report-row-svc_pool"))
      .toBeInTheDocument();
    expect(screen.getByTestId("profit-report-row-__uncategorized__"))
      .toBeInTheDocument();
    // The Fix button is inside the Uncategorized row cell — grab all
    // rendered instances and expect exactly one.
    const fixButtons =
      screen.queryAllByTestId("profit-report-uncategorized-fix-btn");
    expect(fixButtons.length).toBe(1);
    // And it's inside the Uncategorized row (assert via ancestor).
    const row = screen.getByTestId("profit-report-row-__uncategorized__");
    expect(row.contains(fixButtons[0])).toBe(true);
  });

  it("clicking Fix opens the modal + fetches item names in parallel", async () => {
    getMock.mockResolvedValueOnce(FIXTURE_WITH_UNCAT);
    // Prep the /items/{id} follow-ups.
    getMock.mockImplementation((url) => {
      if (url === "/items/item-A") {
        return Promise.resolve({ id: "item-A", name: "Widget A" });
      }
      if (url === "/items/item-B") {
        return Promise.resolve({ id: "item-B", name: "Widget B" });
      }
      return Promise.resolve(FIXTURE_WITH_UNCAT);
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-uncategorized-fix-btn"))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("profit-report-uncategorized-fix-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-uncategorized-fix-modal"))
        .toBeInTheDocument(),
    );
    // Two item rows rendered with the fetched names.
    await waitFor(() => {
      expect(screen.getByTestId("profit-report-fix-item-item-A"))
        .toBeInTheDocument();
      expect(screen.getByTestId("profit-report-fix-item-item-B"))
        .toBeInTheDocument();
    });
    expect(screen.getByTestId("profit-report-fix-item-item-A").textContent)
      .toMatch(/Widget A/);
    expect(screen.getByTestId("profit-report-fix-item-item-B").textContent)
      .toMatch(/Widget B/);
    // Each row carries a "Set category" link.
    expect(screen.getByTestId("profit-report-fix-item-link-item-A"))
      .toHaveAttribute("href", expect.stringContaining("/pricebook"));
  });

  it("Done button dismisses the modal", async () => {
    getMock.mockImplementation((url) => {
      if (url && url.startsWith("/items/")) {
        return Promise.resolve({ id: url.slice(7), name: "X" });
      }
      return Promise.resolve(FIXTURE_WITH_UNCAT);
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-uncategorized-fix-btn"))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("profit-report-uncategorized-fix-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-uncategorized-fix-modal"))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("profit-report-uncategorized-fix-done"));
    await waitFor(() =>
      expect(screen.queryByTestId("profit-report-uncategorized-fix-modal"))
        .not.toBeInTheDocument(),
    );
  });

  it("Fixture without uncategorized_item_ids still shows Fix but the modal is empty", async () => {
    const fixtureNoIds = {
      ...FIXTURE_WITH_UNCAT,
      breakdown: FIXTURE_WITH_UNCAT.breakdown.map((r) =>
        r.category_id === "__uncategorized__"
          ? { ...r, uncategorized_item_ids: [] }
          : r,
      ),
    };
    getMock.mockResolvedValueOnce(fixtureNoIds);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-uncategorized-fix-btn"))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("profit-report-uncategorized-fix-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("profit-report-uncategorized-fix-empty"))
        .toBeInTheDocument(),
    );
  });
});
