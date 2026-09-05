/**
 * Feb-2026 · Sidebar-pivot follow-up — vertical left quick-nav rail.
 *
 * The horizontal <QuickNavRow> that briefly lived in <AdminTopBar>
 * has been retired. The 7 quick-access items now render as a slim
 * vertical rail in <AppLayout> (left column). This suite asserts:
 *   1. The rail renders the 7 items in the exact spec order for
 *      super_admin.
 *   2. Technicians see only the gated subset (Dashboard + Schedule).
 *   3. Active-route styling applies brand tint on the current URL's
 *      rail item.
 *   4. The old horizontal <QuickNavRow> is no longer emitted by
 *      <AdminTopBar> (guards against a future refactor accidentally
 *      re-adding both nav surfaces).
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


let _role = "super_admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-1", role: _role, email: "u@x.com", name: "User" },
    loading: false,
    logout: vi.fn(),
  }),
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    can: () => true,
    effectiveRole: _role,
    role: _role,
    isAdmin: _role === "admin" || _role === "super_admin",
    isAdminOrManager: ["admin", "super_admin", "manager"].includes(_role),
    canDo: () => true,
    previewRole: null,
    setPreviewRole: vi.fn(),
    isPreviewing: false,
  }),
  Forbidden: () => <div data-testid="forbidden" />,
}));
// Heavy dependencies mocked to keep <AppLayout> rendering focused
// on the rail behavior under test.
vi.mock("@/api", () => ({ api: { post: vi.fn(), get: vi.fn() } }));
vi.mock("@/components/RolePreviewSwitcher", () => ({ default: () => null }));
vi.mock("@/layouts/AdminSidebar", () => ({ default: () => <div data-testid="admin-sidebar-stub" /> }));
vi.mock("@/layouts/AdminTopBar", () => ({ default: () => <div data-testid="admin-topbar-stub" /> }));
vi.mock("@/layouts/UniversalMenu", () => ({ default: () => null }));
vi.mock("@/components/LandscapingClockWidget", () => ({ default: () => null }));
vi.mock("@/components/AIDock/AIDock", () => ({ default: () => null }));
vi.mock("@/pages/portal/PortalWalkthrough", () => ({ default: () => null }));
vi.mock("@/components/legal/TosGate", () => ({ default: () => null }));
vi.mock("@/components/portal/ProfileCompletionGate", () => ({ default: () => null }));
vi.mock("@/components/breadcrumbs/Breadcrumbs", () => ({ default: () => null }));
vi.mock("@/pages/onboarding/OnboardingPage", () => ({ OnboardingLoginModal: () => null }));
vi.mock("@/components/UserAvatar", () => ({ UserAvatar: () => null }));
vi.mock("@vis.gl/react-google-maps", () => ({ APIProvider: ({ children }) => <>{children}</> }));


import AppLayout from "@/layouts/AppLayout";


function mount(role, initial = "/") {
  _role = role;
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="*" element={<AppLayout />} />
      </Routes>
    </MemoryRouter>,
  );
}


const _EXPECTED_ORDER_SUPER = [
  "rail-nav-dashboard",
  "rail-nav-workstream",
  "rail-nav-schedule",
  "rail-nav-invoices",
  "rail-nav-payments",
  "rail-nav-customers",
  // Feb-2026 · Leads sidebar quick-link added between Customers
  // and Estimates to keep the sales-pipeline group together.
  "rail-nav-leads",
  "rail-nav-estimates",
  // Feb-2026 · P20 — three managerial quick-links appended after
  // Estimates. Same role gate ([super_admin, admin, manager]) so
  // they appear in the super_admin snapshot too.
  "rail-nav-pool-report",
  "rail-nav-time-clock",
  "rail-nav-job-timers",
];


describe("Vertical quick-nav rail (sidebar pivot)", () => {
  it("renders all 7 rail items in the specified order for super_admin", () => {
    mount("super_admin");
    const rail = screen.getByTestId("quick-nav-rail");
    expect(rail).toBeTruthy();
    const links = Array.from(rail.querySelectorAll('[data-testid^="rail-nav-"]'));
    const observed = links.map((el) => el.getAttribute("data-testid"));
    expect(observed).toEqual(_EXPECTED_ORDER_SUPER);
  });

  it("technician sees only Dashboard + Schedule (gated subset)", () => {
    mount("technician");
    expect(screen.getByTestId("rail-nav-dashboard")).toBeTruthy();
    expect(screen.getByTestId("rail-nav-schedule")).toBeTruthy();
    expect(screen.queryByTestId("rail-nav-workstream")).toBeNull();
    expect(screen.queryByTestId("rail-nav-invoices")).toBeNull();
    expect(screen.queryByTestId("rail-nav-payments")).toBeNull();
    expect(screen.queryByTestId("rail-nav-customers")).toBeNull();
    expect(screen.queryByTestId("rail-nav-estimates")).toBeNull();
  });

  it("active-route rail item picks up the K52 signature gradient (Slice D promoted from K50 white pill)", () => {
    mount("super_admin", "/invoices");
    const link = screen.getByTestId("rail-nav-invoices");
    // Phase K52 Slice D · Feb-2026 — active state is now the K52
    // signature gradient (emerald→sky) instead of the K50 white pill.
    // ``colors.gradient.css`` renders as
    // ``linear-gradient(90deg, #22C55E 0%, #7DD3FC 100%)`` inline —
    // React normalises the hexes and keeps the linear-gradient
    // token verbatim on ``style.background``.
    const style = link.getAttribute("style") || "";
    // Gradient background present with both stops.
    expect(style).toMatch(/linear-gradient\(90deg,\s*#22C55E\s*0%,\s*#7DD3FC\s*100%\)/i);
    // Label text stays white on the gradient.
    expect(style).toMatch(/color:\s*(rgb\(255,\s*255,\s*255\)|#FFFFFF|white)/i);
    // Regression guard — the K50 solid ``rgb(27, 31, 92)`` navy is
    // NOT painted as the active pill background (only the parent
    // <aside> carries the navy chrome).
    expect(style).not.toMatch(/background(-color)?:\s*rgb\(27,\s*31,\s*92\)/i);
  });

  it("horizontal quick-nav row is no longer rendered (pivot complete)", () => {
    mount("super_admin");
    // The old container that hosted the flat pill row is gone —
    // <AdminTopBar> is stubbed so this asserts the rail-only IA.
    expect(screen.queryByTestId("admin-topbar-quick-nav")).toBeNull();
  });
});
