/**
 * Feb-2026 - Dashboard Pool + Landscaping customer tiles.
 *
 * Locks the behaviour of the two new KPI tiles rendered below the
 * Active / Inactive pair:
 *
 *   1. Both tiles render with the correct counts from the
 *      ``/dashboard`` response (``pool_customers_count`` /
 *      ``landscaping_customers_count``).
 *   2. Pool tile deep-links to
 *      ``/customers?is_active=true&service_category=pool`` on click.
 *   3. Landscaping tile deep-links to
 *      ``/customers?is_active=true&service_category=landscaping``.
 *   4. Zero-count tile still renders (do not hide).
 *   5. Loading skeleton renders while the dashboard fetch is in
 *      flight (match existing Active/Inactive pattern).
 *   6. Tile order below Active/Inactive is Pool -> Landscaping.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, waitFor, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// Shared mocks (copied from the sibling tile-swap test file so this
// file is self-contained — same resolution the tile-reorder test
// already uses).
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock, navigateMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: vi.fn(), patch: vi.fn(),
    put: vi.fn(), del: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-admin", role: "admin", email: "a@x", name: "A" },
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));

// Silence sibling admin widgets to keep the test focused on the KPI
// grid. (Same pattern as dashboard-active-inactive-customers.test.jsx.)
vi.mock("@/components/Weather/WeatherWidget", () => ({
  default: () => <div data-testid="weather-mock" />,
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
  default: () => null,
  RANGE_LABELS: { last_month: "Last month" },
}));
vi.mock("@/components/dashboard/RevenueForecastTile", () => ({
  default: () => null,
}));
vi.mock("@/components/dashboard/RevenueDateRangeFilter", () => ({
  default: () => null,
}));


const _DASHBOARD_PAYLOAD = {
  role: "admin",
  revenue: 0, outstanding: 0,
  active_jobs: 3, pending_jobs: 4, completed_jobs: 10, requested_jobs: 0,
  total_customers: 150,
  active_customers_count: 100,
  inactive_customers_count: 50,
  pool_customers_count: 42,
  landscaping_customers_count: 17,
  total_technicians: 4,
  total_leads: 0, open_leads: 0,
  recent_jobs: [], revenue_series: [], revenue_by_service: [],
  recurring_vs_project: { recurring: 0, project: 0 },
  pool_revenue: 0, landscape_revenue: 0, mixed_revenue: 0,
};


function _applyPayload(overrides = {}) {
  apiGetMock.mockReset();
  const payload = { ..._DASHBOARD_PAYLOAD, ...overrides };
  apiGetMock.mockImplementation(async (path) => {
    if (path === "/dashboard") return payload;
    if (path.startsWith("/aeo/last-run")) return null;
    if (path.startsWith("/dashboard/next-service")) return null;
    return {};
  });
}


async function _renderDashboard() {
  const Dashboard = (await import("@/pages/admin/Dashboard")).default;
  render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}


beforeEach(() => { navigateMock.mockReset(); _applyPayload(); });
afterEach(() => { cleanup(); });


describe("Dashboard · Pool + Landscaping customer tiles", () => {
  it("renders both tiles with the counts from the /dashboard response", async () => {
    await _renderDashboard();
    const pool = await screen.findByTestId("kpi-pool-customers");
    const land = await screen.findByTestId("kpi-landscaping-customers");
    expect(pool.textContent).toContain("Pool Customers");
    expect(pool.textContent).toContain("42");
    expect(land.textContent).toContain("Landscaping Customers");
    expect(land.textContent).toContain("17");
  });

  it("Pool tile deep-links to the active-pool filtered customers list", async () => {
    await _renderDashboard();
    const pool = await screen.findByTestId("kpi-pool-customers");
    fireEvent.click(pool);
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers?is_active=true&service_category=pool",
    );
  });

  it("Landscaping tile deep-links to the active-landscaping filtered list", async () => {
    await _renderDashboard();
    const land = await screen.findByTestId("kpi-landscaping-customers");
    fireEvent.click(land);
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers?is_active=true&service_category=landscaping",
    );
  });

  it("renders both tiles even when their counts are zero", async () => {
    _applyPayload({
      pool_customers_count: 0,
      landscaping_customers_count: 0,
    });
    await _renderDashboard();
    const pool = await screen.findByTestId("kpi-pool-customers");
    const land = await screen.findByTestId("kpi-landscaping-customers");
    expect(pool.textContent).toContain("0");
    expect(land.textContent).toContain("0");
  });

  it("renders loading skeletons while the dashboard fetch is in flight", async () => {
    // Return a never-resolving promise so the KPI grid stays in
    // skeleton state.  Same pattern the sibling tile-swap test
    // uses to exercise the loading surface.  Non-dashboard paths
    // still return a resolved Promise so other sub-widgets that
    // chain .then() don't crash while the main grid skeleton
    // renders.
    apiGetMock.mockReset();
    apiGetMock.mockImplementation(async (path) => {
      if (path === "/dashboard") return new Promise(() => {});
      if (path.startsWith("/aeo/last-run")) return null;
      if (path.startsWith("/dashboard/next-service")) return null;
      return {};
    });
    await _renderDashboard();
    // The KPI grid skeleton loop renders Skeleton nodes while
    // ``data`` is null.  Assert the grid itself is present AND
    // the Pool/Landscaping tiles are NOT in the DOM yet (loading
    // state surface).
    const grid = await screen.findByTestId("dashboard-kpi-grid");
    expect(grid).toBeInTheDocument();
    expect(screen.queryByTestId("kpi-pool-customers"))
      .not.toBeInTheDocument();
    expect(screen.queryByTestId("kpi-landscaping-customers"))
      .not.toBeInTheDocument();
  });

  it("renders Pool before Landscaping, both after Inactive Customers", async () => {
    await _renderDashboard();
    await screen.findByTestId("kpi-active-jobs");
    const expected = [
      "kpi-active-jobs",
      "kpi-pending",
      "kpi-active-customers",
      "kpi-inactive-customers",
      "kpi-pool-customers",
      "kpi-landscaping-customers",
    ];
    const nodes = expected.map((id) => screen.getByTestId(id));
    for (let i = 1; i < nodes.length; i += 1) {
      const prev = nodes[i - 1];
      const curr = nodes[i];
      // Node.DOCUMENT_POSITION_FOLLOWING === 4
      expect(prev.compareDocumentPosition(curr) & 4).toBe(4);
    }
  });
});
