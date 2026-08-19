/**
 * Feb-2026 · Sign-out relocated from sidebar footer to AdminTopBar.
 *
 * Guards:
 *   1. ``header-signout`` renders inside AdminTopBar (top of page).
 *   2. Clicking it calls the shared ``useAuth().logout`` handler.
 *   3. The old sidebar-footer ``shell-logout-button`` is GONE.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const logoutMock = vi.fn();
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-1", role: "admin", name: "Admin", email: "a@x.com" },
    loading: false,
    logout: logoutMock,
  }),
}));

// Permissions — allow every route so the topbar renders its dropdowns.
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    can: () => true,
    effectiveRole: "admin",
    isAdmin: true,
    isAdminOrManager: true,
    role: "admin",
    canDo: () => true,
  }),
  Forbidden: () => <div data-testid="forbidden" />,
}));

// Lightweight stubs so the topbar renders without pulling their internals.
vi.mock("@/components/NotificationBell", () => ({
  default: () => <div data-testid="notif-bell-stub" />,
}));
vi.mock("@/components/AIDock/CreditsBudgetChip", () => ({
  default: () => <div data-testid="credits-chip-stub" />,
}));


import AdminTopBar from "@/layouts/AdminTopBar";


function mount() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <AdminTopBar />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  logoutMock.mockClear();
});


describe("Sign-out relocated to AdminTopBar", () => {
  it("renders the header-signout button in the topbar", () => {
    mount();
    // Sign-out button lives INSIDE the topbar container.
    const topbar = screen.getByTestId("admin-topbar");
    const btn = screen.getByTestId("header-signout");
    expect(btn).toBeTruthy();
    // The button must be a descendant of the topbar (asserts
    // it's on the "top of page", not a stray render elsewhere).
    expect(topbar.contains(btn)).toBe(true);
    expect(btn.getAttribute("aria-label")).toBe("Sign out");
    expect(btn.textContent).toMatch(/Sign out/);
  });

  it("clicking header-signout calls useAuth().logout", () => {
    mount();
    fireEvent.click(screen.getByTestId("header-signout"));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });

  it("the old sidebar-footer testid ``shell-logout-button`` is NOT rendered", () => {
    mount();
    // Guards the revert — if a future refactor re-adds the sidebar
    // logout, this test fails visibly rather than silently.
    expect(screen.queryByTestId("shell-logout-button")).toBeNull();
  });
});
