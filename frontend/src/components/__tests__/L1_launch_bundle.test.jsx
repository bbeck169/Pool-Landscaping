/**
 * Phase L1 · Feb-2026 — Launch bundle vitest suite.
 *
 * Covers:
 *   1. QuickAddButton hides for non-admin.
 *   2. QuickAddButton visible for admin; opens dropdown; menu items
 *      navigate to correct routes.
 *   3. DashboardActionCards renders 7 cards with the right counts +
 *      auto-hides zero-count cards (except open_alerts, always-on).
 *   4. DashboardActionCards renders skeleton before data lands.
 *   5. DashboardActionCards card click navigates to the correct href.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor }
       from "@testing-library/react";


const getMock       = vi.fn();
const navigateMock  = vi.fn();
const useAuthMock   = vi.fn();


vi.mock("@/api", () => ({
  api: {
    get:  (...a) => getMock(...a),
    post: () => Promise.resolve({}),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff",  surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7", borderStrong: "#D4D4D8",
    muted: "#71717A",  onSurface: "#09090B",
    onSurfaceSecondary: "#52525B",
    brand: "#0284C7",  error: "#DC2626", warning: "#CA8A04",
    onBrandPrimary: "#FFFFFF",
  },
  gradients: {
    navyToGreen: { css: "linear-gradient(90deg, #1B1F5C, #16A34A)" },
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import QuickAddButton from "@/components/topbar/QuickAddButton";
import DashboardActionCards
       from "@/components/dashboard/DashboardActionCards";


function _render(ui) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}


beforeEach(() => {
  getMock.mockReset();
  navigateMock.mockReset();
  useAuthMock.mockReset();
  getMock.mockResolvedValue({});
});
afterEach(() => cleanup());


describe("QuickAddButton · role gating", () => {
  it("hides for technician", () => {
    useAuthMock.mockReturnValue({ user: { role: "technician" } });
    _render(<QuickAddButton />);
    expect(screen.queryByTestId("topbar-quick-add-btn")).toBeNull();
  });

  it("renders for admin and opens the 4-item menu", () => {
    useAuthMock.mockReturnValue({ user: { role: "admin" } });
    _render(<QuickAddButton />);
    const btn = screen.getByTestId("topbar-quick-add-btn");
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    for (const k of ["lead", "job", "estimate", "customer"]) {
      expect(
        screen.getByTestId(`topbar-quick-add-${k}`),
      ).toBeInTheDocument();
    }
  });

  it("clicking New Job navigates to /jobs/new", () => {
    useAuthMock.mockReturnValue({ user: { role: "admin" } });
    _render(<QuickAddButton />);
    fireEvent.click(screen.getByTestId("topbar-quick-add-btn"));
    fireEvent.click(screen.getByTestId("topbar-quick-add-job"));
    expect(navigateMock).toHaveBeenCalledWith("/jobs/new");
  });

  it("clicking New Estimate navigates to /quotes/new", () => {
    useAuthMock.mockReturnValue({ user: { role: "manager" } });
    _render(<QuickAddButton />);
    fireEvent.click(screen.getByTestId("topbar-quick-add-btn"));
    fireEvent.click(screen.getByTestId("topbar-quick-add-estimate"));
    expect(navigateMock).toHaveBeenCalledWith("/quotes/new");
  });
});


describe("DashboardActionCards", () => {
  it("renders skeleton before data lands", async () => {
    let resolve = null;
    getMock.mockImplementation(() =>
      new Promise((r) => { resolve = r; }));
    _render(<DashboardActionCards />);
    expect(await screen.findByTestId(
      "dashboard-action-cards-skeleton")).toBeInTheDocument();
    resolve?.({});
  });

  it("renders the visible cards + auto-hides zero-count ones", async () => {
    getMock.mockResolvedValue({
      today_routes:          3,
      pending_checkins:      0,
      unpaid_invoices:       0,
      overdue_invoices:      2,
      new_leads_today:       0,
      open_alerts:           1,
      missed_services_today: 0,
      generated_at:          new Date().toISOString(),
    });
    _render(<DashboardActionCards />);
    // Today's Routes + Overdue + Open Alerts should render.
    await waitFor(() => {
      expect(screen.getByTestId(
        "dashboard-action-card-today_routes")).toBeInTheDocument();
    });
    expect(screen.getByTestId(
      "dashboard-action-card-overdue_invoices")).toBeInTheDocument();
    // Open Alerts is always-visible.
    expect(screen.getByTestId(
      "dashboard-action-card-open_alerts")).toBeInTheDocument();
    // Zero-count cards are hidden.
    expect(screen.queryByTestId(
      "dashboard-action-card-pending_checkins")).toBeNull();
    expect(screen.queryByTestId(
      "dashboard-action-card-new_leads_today")).toBeNull();
  });

  it("card click navigates to the correct href", async () => {
    getMock.mockResolvedValue({
      today_routes:          0,
      pending_checkins:      0,
      unpaid_invoices:       0,
      overdue_invoices:      0,
      new_leads_today:       0,
      open_alerts:           7,
      missed_services_today: 0,
      generated_at:          new Date().toISOString(),
    });
    _render(<DashboardActionCards />);
    const card = await screen.findByTestId(
      "dashboard-action-card-open_alerts");
    fireEvent.click(card);
    expect(navigateMock).toHaveBeenCalledWith(
      "/admin/intelligence/alerts");
  });

  it("renders open_alerts card even when its count is 0", async () => {
    getMock.mockResolvedValue({
      today_routes:          0,
      pending_checkins:      0,
      unpaid_invoices:       0,
      overdue_invoices:      0,
      new_leads_today:       0,
      open_alerts:           0,
      missed_services_today: 0,
      generated_at:          new Date().toISOString(),
    });
    _render(<DashboardActionCards />);
    expect(await screen.findByTestId(
      "dashboard-action-card-open_alerts")).toBeInTheDocument();
    // Every other card is hidden — empty tenant.
    for (const k of ["today_routes", "pending_checkins",
                        "unpaid_invoices", "overdue_invoices",
                        "new_leads_today",
                        "missed_services_today"]) {
      expect(screen.queryByTestId(
        `dashboard-action-card-${k}`)).toBeNull();
    }
  });
});
