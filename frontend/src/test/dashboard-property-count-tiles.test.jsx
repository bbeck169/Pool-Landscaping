/**
 * Feb-2026 · P2 #6 property pivot — Commit 5 vitest suite.
 *
 * Locks the behaviour of the 4 property-level KPI tiles that now
 * form the operator-labelled "Customers" row at the bottom of the
 * KPI grid (data source unchanged — still per-tenant property
 * counts; the labels were renamed in the P2 Dashboard tile
 * cleanup):
 *
 *   1. All 4 tiles render with the correct counts from the
 *      /dashboard response.
 *   2. Active Accounts tile deep-links to
 *      /properties?is_active=true.
 *   3. Pool / Landscaping / Both tiles deep-link to the
 *      Properties list filtered to the matching category.
 *   4. Zero-count tiles still render (do not hide).
 *   5. The customer-count tiles ``kpi-active-customers`` /
 *      ``kpi-pool-customers`` / ``kpi-landscaping-customers``
 *      have been REMOVED (operator cleanup) — assert they do NOT
 *      render.  ``kpi-inactive-customers`` is preserved.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, waitFor, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


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
  // Ticket U · Feb-2026 — Dashboard "Pool/Landscaping/Both Service
  // Customers" tiles now consume these customer-count fields
  // instead of the ``*_properties_count`` fields (which stay in
  // the response for one deprecation window per BE comment).
  pool_customers_count: 90,
  landscaping_customers_count: 38,
  both_customers_count: 11,
  active_accounts_count: 128,
  // Deprecated (kept in fixture to prove tiles ignore them).
  pool_properties_count: 42,
  landscaping_properties_count: 17,
  both_properties_count: 5,
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


describe("Dashboard · Property-count tiles (P2 #6)", () => {
  it("renders all 4 tiles with counts from /dashboard", async () => {
    await _renderDashboard();
    const active = await screen.findByTestId("kpi-active-accounts");
    const pool = await screen.findByTestId("kpi-pool-properties");
    const land = await screen.findByTestId(
      "kpi-landscaping-properties",
    );
    const both = await screen.findByTestId("kpi-both-properties");
    expect(active.textContent).toMatch(/128/);
    // Ticket U · Feb-2026 — the Pool / Landscaping / Both Service
    // Customers tiles now read the ``*_customers_count`` fields
    // (90 / 38 / 11), NOT the deprecated ``*_properties_count``
    // fields (42 / 17 / 5) which are kept in the fixture to prove
    // the tiles ignore them.
    expect(pool.textContent).toMatch(/90/);
    expect(land.textContent).toMatch(/38/);
    expect(both.textContent).toMatch(/11/);
    // Negative assertion — deprecated property counts MUST NOT
    // appear in these tiles.
    expect(pool.textContent).not.toMatch(/42/);
    expect(land.textContent).not.toMatch(/17/);
    expect(both.textContent).not.toMatch(/5/);
  });

  it("Active Accounts tile deep-links to /properties?is_active=true",
     async () => {
    await _renderDashboard();
    const tile = await screen.findByTestId("kpi-active-accounts");
    fireEvent.click(tile);
    expect(navigateMock).toHaveBeenCalledWith("/properties?is_active=true");
  });

  it("Pool Customers tile deep-links to /customers?service_category=pool&is_active=true",
     async () => {
    // Ticket U · Feb-2026 — deep-link flipped from
    // ``/properties?is_active=true&service_category=pool`` to
    // ``/customers?service_category=pool&is_active=true`` so the
    // tile count equals the Customer-list filter cardinality
    // exactly (unified data source).
    await _renderDashboard();
    fireEvent.click(await screen.findByTestId("kpi-pool-properties"));
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers?service_category=pool&is_active=true",
    );
  });

  it("Landscaping Customers tile deep-links to /customers?service_category=landscaping&is_active=true",
     async () => {
    await _renderDashboard();
    fireEvent.click(
      await screen.findByTestId("kpi-landscaping-properties"),
    );
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers?service_category=landscaping&is_active=true",
    );
  });

  it("Both Service Customers tile deep-links to /customers?service_category=both&is_active=true",
     async () => {
    await _renderDashboard();
    fireEvent.click(await screen.findByTestId("kpi-both-properties"));
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers?service_category=both&is_active=true",
    );
  });

  it("zero-count tiles still render (do not hide)", async () => {
    _applyPayload({
      active_accounts_count: 0,
      pool_customers_count: 0,
      landscaping_customers_count: 0,
      both_customers_count: 0,
      // Keep deprecated fields non-zero to prove the tile hides
      // on the Customers field (post Ticket U), not the Properties
      // field.
      pool_properties_count: 99,
      landscaping_properties_count: 99,
      both_properties_count: 99,
    });
    await _renderDashboard();
    expect(await screen.findByTestId("kpi-active-accounts"))
      .toBeInTheDocument();
    const pool = await screen.findByTestId("kpi-pool-properties");
    const land = await screen.findByTestId("kpi-landscaping-properties");
    const both = await screen.findByTestId("kpi-both-properties");
    expect(pool).toBeInTheDocument();
    expect(land).toBeInTheDocument();
    expect(both).toBeInTheDocument();
    // Confirm the tiles read 0 from ``*_customers_count`` and NOT
    // 99 from the deprecated ``*_properties_count`` fallbacks.
    expect(pool.textContent).not.toMatch(/99/);
    expect(land.textContent).not.toMatch(/99/);
    expect(both.textContent).not.toMatch(/99/);
  });

  it("renders the renamed Customers labels on the property-count tiles (Pool/Landscaping/Both Service)",
     async () => {
    await _renderDashboard();
    const pool = await screen.findByTestId("kpi-pool-properties");
    const land = await screen.findByTestId("kpi-landscaping-properties");
    const both = await screen.findByTestId("kpi-both-properties");
    // Labels renamed in the P2 Dashboard tile cleanup — data
    // source + testids unchanged.
    expect(pool.textContent).toMatch(/Pool Customers/);
    expect(land.textContent).toMatch(/Landscaping Customers/);
    // Note the singular "Service" per operator spec.
    expect(both.textContent).toMatch(/Both Service Customers/);
    // Old labels must NOT appear in these tiles.
    expect(pool.textContent).not.toMatch(/Pool Properties/);
    expect(land.textContent).not.toMatch(/Landscaping Properties/);
    expect(both.textContent).not.toMatch(/Both Services Properties/);
  });

  it("removed customer-count tiles are gone (P2 Dashboard tile cleanup)",
     async () => {
    await _renderDashboard();
    // Anchor on a surviving sibling before asserting absence.
    await screen.findByTestId("kpi-inactive-customers");
    expect(screen.queryByTestId("kpi-active-customers"))
      .not.toBeInTheDocument();
    expect(screen.queryByTestId("kpi-pool-customers"))
      .not.toBeInTheDocument();
    expect(screen.queryByTestId("kpi-landscaping-customers"))
      .not.toBeInTheDocument();
    // Inactive Customers is PRESERVED.
    expect(screen.queryByTestId("kpi-inactive-customers"))
      .toBeInTheDocument();
  });
});
