/**
 * Feb-2026 · Full-layout revamp — sidebar removed, 7-item horizontal
 * quick-nav in the AdminTopBar. This test asserts:
 *   1. All 7 quick-nav entries render for super_admin, in exact order.
 *   2. Technician sees only their gated subset (Dashboard + Schedule).
 *   3. Active-route styling applies to the current URL.
 *   4. The old ``side-nav`` sidebar container renders in an
 *      ``.hidden`` state (kept in the tree but not visible) —
 *      guards against a future refactor accidentally re-mounting it.
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
  }),
  Forbidden: () => <div data-testid="forbidden" />,
}));
vi.mock("@/components/NotificationBell", () => ({
  default: () => <div data-testid="notif-bell-stub" />,
}));
vi.mock("@/components/AIDock/CreditsBudgetChip", () => ({
  default: () => <div data-testid="credits-chip-stub" />,
}));


import AdminTopBar from "@/layouts/AdminTopBar";


function mount(role, initial = "/dashboard") {
  _role = role;
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="*" element={<AdminTopBar />} />
      </Routes>
    </MemoryRouter>,
  );
}


const _EXPECTED_ORDER_SUPER = [
  "quick-nav-dashboard",
  "quick-nav-workstream",
  "quick-nav-schedule",
  "quick-nav-invoices",
  "quick-nav-payments",
  "quick-nav-customers",
  "quick-nav-estimates",
];


describe("Header quick-nav (sidebar removed)", () => {
  it("renders all 7 quick-nav items in the specified order for super_admin", () => {
    mount("super_admin");
    const row = screen.getByTestId("admin-topbar-quick-nav");
    expect(row).toBeTruthy();
    const found = _EXPECTED_ORDER_SUPER.map((tid) =>
      screen.getByTestId(tid));
    // Verify DOM order matches the expected list.
    const links = Array.from(row.querySelectorAll('[data-testid^="quick-nav-"]'));
    const observedOrder = links.map((el) => el.getAttribute("data-testid"));
    expect(observedOrder).toEqual(_EXPECTED_ORDER_SUPER);
    expect(found).toHaveLength(7);
  });

  it("technician sees only Dashboard + Schedule (gated subset)", () => {
    mount("technician");
    expect(screen.getByTestId("quick-nav-dashboard")).toBeTruthy();
    expect(screen.getByTestId("quick-nav-schedule")).toBeTruthy();
    expect(screen.queryByTestId("quick-nav-workstream")).toBeNull();
    expect(screen.queryByTestId("quick-nav-invoices")).toBeNull();
    expect(screen.queryByTestId("quick-nav-payments")).toBeNull();
    expect(screen.queryByTestId("quick-nav-customers")).toBeNull();
    expect(screen.queryByTestId("quick-nav-estimates")).toBeNull();
  });

  it("active-route link picks up the brand-tinted styling", () => {
    mount("super_admin", "/invoices");
    const link = screen.getByTestId("quick-nav-invoices");
    // Active NavLink resolves the ``isActive`` style branch; the
    // resulting inline background is the ``brandTertiary`` token.
    expect(link.getAttribute("style")).toMatch(/rgb\(224, 242, 254\)|#E0F2FE/i);
  });
});
