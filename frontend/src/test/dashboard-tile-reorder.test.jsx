/**
 * Feb-2026 · Dashboard batch — KPI tile reorder + Data Integrity hide.
 *
 * Locks the two changes shipped by the Dashboard batch ticket:
 *
 *   Change 1 — Reorder the four summary tiles so they sit directly
 *     above the Revenue Forecast / EBIT topline row:
 *       Active Jobs → Pending → Active Customers → Inactive Customers.
 *     Order is asserted via DOM position (document ordering) so a
 *     regression that swaps two tiles or re-anchors them below the
 *     Warranties/Routing/Referral tiles would fail.
 *
 *   Change 2 — Data Integrity section is HIDDEN (not deleted).  The
 *     component import is still in the file for easy revert, but no
 *     DOM node with ``data-testid="admin-data-integrity-tile"``
 *     renders when the dashboard mounts under a super_admin user.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── Shared mocks ───────────────────────────────────────────────
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));
vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: vi.fn(), patch: vi.fn(),
    put: vi.fn(), del: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

// super_admin so the Data Integrity gate (``user?.role === "super_admin"``)
// would otherwise render the tile — proving the hide is effective.
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-sa", role: "super_admin", email: "sa@x", name: "SA" },
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));

// Silence noisy admin sub-widgets that hit real timers or extra APIs.
vi.mock("@/components/Weather/WeatherWidget", () => ({
  default: () => <div data-testid="weather-widget-mock" />,
}));
vi.mock("@/components/mass-messaging/MassMessagingCard", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/TeamCpoReadinessWidget", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/RecommendationsQueueWidget", () => ({
  default: () => null,
}));
vi.mock("@/components/dashboard/RevenueByCategoryTile", () => ({
  default: () => <div data-testid="revenue-by-category-mock" />,
  RANGE_LABELS: { last_month: "Last month" },
}));
vi.mock("@/components/dashboard/IncomeByServiceCategoryTile", () => ({
  default: () => null,
}));
vi.mock("@/components/dashboard/RevenueForecastTile", () => ({
  default: () => <div data-testid="revenue-forecast-tile-mock" />,
}));
vi.mock("@/components/dashboard/EbitTile", () => ({
  default: () => <div data-testid="ebit-tile-mock" />,
}));
vi.mock("@/components/dashboard/RevenueDateRangeFilter", () => ({
  default: () => null,
}));
vi.mock("@/components/dashboard/DashboardActionCards", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/BulkOpsAuditTile", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/SoshiePublishingTile", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/CrewProductivityTile", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/RoutingCostTile", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/WarrantiesExpiringTile", () => ({
  default: () => null,
}));
// Guard — this is the component the hide is meant to remove from
// the DOM.  If someone un-hides it in the dashboard page, we WANT
// this mock to fire and render the marker so the tests catch it.
vi.mock("@/components/admin/DataIntegrityTile", () => ({
  default: () => (
    <div data-testid="admin-data-integrity-tile">Data Integrity mock</div>
  ),
}));


const _DASHBOARD_PAYLOAD = {
  role: "super_admin",
  revenue: 0, outstanding: 0,
  active_jobs: 7, pending_jobs: 4, completed_jobs: 10, requested_jobs: 0,
  total_customers: 150,
  active_customers_count: 100,
  inactive_customers_count: 50,
  total_technicians: 4,
  total_leads: 0, open_leads: 0,
  recent_jobs: [], revenue_series: [], revenue_by_service: [],
  recurring_vs_project: { recurring: 0, project: 0 },
  pool_revenue: 0, landscape_revenue: 0, mixed_revenue: 0,
};


beforeEach(() => {
  apiGetMock.mockReset();
  apiGetMock.mockImplementation(async (path) => {
    if (path === "/dashboard") return _DASHBOARD_PAYLOAD;
    if (path.startsWith("/aeo/last-run")) return null;
    if (path.startsWith("/dashboard/next-service")) return null;
    return {};
  });
});
afterEach(() => { cleanup(); });


async function _renderDashboard() {
  const { default: Dashboard } = await import(
    "@/pages/admin/Dashboard.jsx"
  );
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}


describe("Admin Dashboard · Feb-2026 KPI reorder + Data Integrity hide", () => {
  it("renders the 4 KPI tiles in the exact Active Jobs → Pending → Active Customers → Inactive Customers order", async () => {
    await _renderDashboard();

    // Wait for the KPI grid to hydrate.
    await waitFor(() => screen.getByTestId("kpi-active-jobs"));

    const expected = [
      "kpi-active-jobs",
      "kpi-pending",
      "kpi-active-customers",
      "kpi-inactive-customers",
    ];
    const nodes = expected.map((id) => screen.getByTestId(id));

    // Each successive tile must come AFTER its predecessor in the DOM.
    for (let i = 1; i < nodes.length; i += 1) {
      const prev = nodes[i - 1];
      const curr = nodes[i];
      const pos = prev.compareDocumentPosition(curr);
      // Node.DOCUMENT_POSITION_FOLLOWING === 4
      expect(pos & 4).toBe(4);
    }
  });

  it("places the KPI tiles directly above the Revenue Forecast / EBIT topline row", async () => {
    await _renderDashboard();

    await waitFor(() => screen.getByTestId("kpi-active-jobs"));

    const kpiGrid = screen.getByTestId("dashboard-kpi-grid");
    const toplineRow = screen.getByTestId("dashboard-topline-tiles");

    // KPI grid precedes the topline row.
    const pos = kpiGrid.compareDocumentPosition(toplineRow);
    expect(pos & 4).toBe(4);

    // And it is a DIRECT sibling (no other dashboard section wedged
    // between them).  Enforced by walking ``kpiGrid.nextElementSibling``
    // and finding the topline row via its testid — tolerates a
    // whitespace text node by stepping past non-element nodes.
    let next = kpiGrid.nextSibling;
    while (next && next.nodeType !== 1) next = next.nextSibling;
    expect(next).not.toBeNull();
    expect(next.getAttribute("data-testid"))
      .toBe("dashboard-topline-tiles");
  });

  it("renders the KPI tiles AFTER the Revenue Insights section", async () => {
    await _renderDashboard();
    await waitFor(() => screen.getByTestId("kpi-active-jobs"));

    const revenueSection = screen.getByTestId("revenue-tiles-section");
    const kpiGrid = screen.getByTestId("dashboard-kpi-grid");

    const pos = revenueSection.compareDocumentPosition(kpiGrid);
    expect(pos & 4).toBe(4);
  });

  it("does NOT render the Data Integrity tile even for a super_admin viewer", async () => {
    await _renderDashboard();

    // Wait until the KPI grid hydrates so we know the Dashboard has
    // mounted and settled before asserting absence.
    await waitFor(() => screen.getByTestId("kpi-active-jobs"));

    // The import is still in Dashboard.jsx (easy revert) but the
    // JSX block is commented out — the component mock would surface
    // ``admin-data-integrity-tile`` if the hide broke.
    expect(screen.queryByTestId("admin-data-integrity-tile"))
      .toBeNull();
  });
});
