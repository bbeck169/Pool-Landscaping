/**
 * Feb-2026 · Phase 21 · Addition D — AddCustomerButton in the admin
 * top bar.
 *
 * Covers:
 * * Renders for admin + super_admin.
 * * Hidden for technician + customer.
 * * Click routes to `/customers/new` (reuses the shipped CustomerForm).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mocks: auth + router navigate + all the AdminTopBar sub-deps we
// don't care about testing here.
let currentRole = "admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u", role: currentRole, email: "x@y.z" } }),
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useLocation: () => ({ pathname: "/" }),
  };
});

// Neutralise nav data + peripheral components so we only care about
// the AddCustomerButton branch of AdminTopBar. Provide one nav group
// so the `visible.length === 0` short-circuit doesn't null out the bar.
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [{
    key: "ops", label: "Ops", icon: () => null,
    entries: [{ to: "/dashboard", feature: "dashboard", label: "Dashboard" }],
  }],
}));
vi.mock("@/hooks/usePermissions", () => ({
  // Phase Hygiene B · Feb-2026 — AdminTopBar's ``useVisibleGroups``
  // hook filters the nav array against ``effectiveRole`` and returns
  // an empty visible list when the role isn't in
  // ``{admin, super_admin, manager}``. Without an explicit
  // ``effectiveRole`` here the wide+narrow branches both collapse
  // to the ``!hasAnyNav`` tech-only fallback, which drops
  // AddCustomerButton entirely. Return the role currently under
  // test so the admin/super_admin branch keeps rendering.
  usePermissions: () => ({
    can: () => true,
    cannot: () => false,
    effectiveRole: currentRole,
    role: currentRole,
    isAdmin: currentRole === "admin" || currentRole === "super_admin",
    isAdminOrManager: true,
    canDo: () => true,
  }),
}));
vi.mock("@/components/NotificationBell", () => ({
  default: () => null,
}));
vi.mock("@/components/AIDock/CreditsBudgetChip", () => ({
  default: () => null,
}));

// Import after mocks.
import AdminTopBar from "@/layouts/AdminTopBar";


function renderBar() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <AdminTopBar />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
});


describe("AdminTopBar · AddCustomerButton", () => {
  // Phase Hygiene B · Feb-2026 — K76.1 dual-render (see
  // header-signout-relocated for the full rationale). Both narrow
  // and wide branches always render into the DOM under jsdom, so
  // the button testid resolves to two nodes when it's role-visible.
  // Use ``getAllByTestId(...)[0]`` to keep the contract behaviorally
  // identical (renders + navigates on click) without touching product.
  it("renders for admin and routes to /customers/new on click", () => {
    currentRole = "admin";
    renderBar();
    const btns = screen.getAllByTestId("topbar-add-customer-btn");
    expect(btns.length).toBeGreaterThanOrEqual(1);
    const btn = btns[0];
    expect(btn).toBeInTheDocument();
    expect(btn.textContent).toMatch(/add customer/i);
    fireEvent.click(btn);
    expect(navigateMock).toHaveBeenCalledWith("/customers/new");
  });

  it("renders for super_admin", () => {
    currentRole = "super_admin";
    renderBar();
    const btns = screen.getAllByTestId("topbar-add-customer-btn");
    expect(btns.length).toBeGreaterThanOrEqual(1);
    expect(btns[0]).toBeInTheDocument();
  });

  it("is hidden for technician", () => {
    currentRole = "technician";
    renderBar();
    expect(screen.queryByTestId("topbar-add-customer-btn")).toBeNull();
  });

  it("is hidden for customer", () => {
    currentRole = "customer";
    renderBar();
    expect(screen.queryByTestId("topbar-add-customer-btn")).toBeNull();
  });
});
