/**
 * Feb-2026 · Dashboard KPI tile swap coverage — Active/Inactive
 * Customers.
 *
 * Locks:
 *   1. "Technicians" copy is GONE from the DOM.
 *   2. "Active Customers" tile present + renders numeric value.
 *   3. "Inactive Customers" tile present + renders numeric value.
 *   4. Sum-invariant guard: no leftover "Customers: 150" legacy tile.
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

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-admin", role: "admin", email: "a@x", name: "A" },
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
  total_technicians: 4,  // legacy field, kept for one release
  total_leads: 0, open_leads: 0,
  recent_jobs: [], revenue_series: [], revenue_by_service: [],
  recurring_vs_project: { recurring: 0, project: 0 },
  pool_revenue: 0, landscape_revenue: 0, mixed_revenue: 0,
};


beforeEach(() => {
  apiGetMock.mockReset();
  apiGetMock.mockImplementation(async (path) => {
    if (path === "/dashboard") return _DASHBOARD_PAYLOAD;
    // All the other tiny endpoints the Dashboard hits — return
    // safe empty shapes so the KPI grid path still renders.
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


describe("Admin Dashboard KPI grid · Feb-2026 tile swap", () => {
  it("does NOT render the legacy 'Technicians' tile copy anywhere in the DOM", async () => {
    await _renderDashboard();
    // Wait for the KPI grid to hydrate — data-testid appears once
    // the ``data`` state is populated (skeleton path uses no testid).
    await waitFor(() => screen.getByTestId("kpi-active-customers"));
    // Exact-match on the tile label — the word "technicians" may
    // legitimately appear in a heading elsewhere on the page in
    // the future; the KPI tile's label was "Technicians".
    expect(screen.queryByText(/^Technicians$/i)).toBeNull();
    // Belt-and-suspenders — the old testid must be gone too.
    expect(screen.queryByTestId("kpi-technicians")).toBeNull();
  });

  it("renders 'Active Customers' tile with the numeric active_customers_count", async () => {
    await _renderDashboard();
    const tile = await screen.findByTestId("kpi-active-customers");
    // Label present.
    expect(tile.textContent).toMatch(/Active Customers/i);
    // Numeric value present.
    expect(tile.textContent).toContain("100");
  });

  it("renders 'Inactive Customers' tile with the numeric inactive_customers_count", async () => {
    await _renderDashboard();
    const tile = await screen.findByTestId("kpi-inactive-customers");
    expect(tile.textContent).toMatch(/Inactive Customers/i);
    expect(tile.textContent).toContain("50");
  });

  it("does NOT render a leftover legacy 'Customers: 150' tile (sum-invariant guard)", async () => {
    await _renderDashboard();
    await waitFor(() => screen.getByTestId("kpi-active-customers"));
    // Legacy "Customers" tile removed — must not appear.
    expect(screen.queryByTestId("kpi-customers")).toBeNull();
    // Exact-match "^Customers$" as a KPI label — guards a paste-back
    // regression that would ship all THREE tiles (active + inactive
    // + total) and confuse the user.
    expect(screen.queryByText(/^Customers$/i)).toBeNull();
    // The number 150 (total_customers) must NOT appear as a KPI
    // value on the grid.  It's still in the API response for
    // legacy consumers, but never surfaced to the DOM.
    const active = screen.getByTestId("kpi-active-customers");
    const inactive = screen.getByTestId("kpi-inactive-customers");
    expect(active.textContent).not.toContain("150");
    expect(inactive.textContent).not.toContain("150");
  });
});
