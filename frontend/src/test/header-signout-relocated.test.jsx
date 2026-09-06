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
  // Phase Hygiene B · Feb-2026 — K76.1 flips branch selection from a
  // JS resize-listener to a pure CSS ``md:`` gate. Both the narrow
  // wrap (``md:hidden``) and wide wrap (``hidden md:flex``) render
  // into the DOM in every environment — CSS decides visibility. In
  // jsdom, CSS is not applied, so both branches produce a
  // ``header-signout`` node. The test's contract is "exactly one
  // instance is inside the topbar" which is still true; we simply
  // pick the first match and assert it lives under ``admin-topbar``.
  it("renders the header-signout button in the topbar", () => {
    mount();
    const topbar = screen.getByTestId("admin-topbar");
    const btns = screen.getAllByTestId("header-signout");
    expect(btns.length).toBeGreaterThanOrEqual(1);
    const btn = btns[0];
    expect(btn).toBeTruthy();
    // Every rendered instance must live inside the topbar container.
    btns.forEach((b) => expect(topbar.contains(b)).toBe(true));
    expect(btn.getAttribute("aria-label")).toBe("Sign out");
    expect(btn.textContent).toMatch(/Sign out/);
  });

  it("clicking header-signout calls useAuth().logout", () => {
    mount();
    // Both narrow + wide branches render the button under K76.1's
    // CSS gate; either instance triggers logout on click.
    fireEvent.click(screen.getAllByTestId("header-signout")[0]);
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });

  it("the old sidebar-footer testid ``shell-logout-button`` is NOT rendered", () => {
    mount();
    // Guards the revert — if a future refactor re-adds the sidebar
    // logout, this test fails visibly rather than silently.
    expect(screen.queryByTestId("shell-logout-button")).toBeNull();
  });
});
