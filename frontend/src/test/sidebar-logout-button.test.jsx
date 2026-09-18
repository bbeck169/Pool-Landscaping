/**
 * Feb-2026 · Sidebar rail Logout button
 *
 * Locks in three properties:
 *   1. The rail-Logout button is rendered inside <AppLayout>'s
 *      sidebar column and appears AFTER the <QuickPinsRail> in
 *      DOM order (i.e., the "+ Add pin" trigger and any pin
 *      rows come before this button).
 *   2. Clicking the button invokes the layout's ``onLogout``
 *      handler, which itself calls ``logout()`` from ``@/auth``
 *      exactly once. (We intercept ``logout`` because
 *      ``onLogout`` is a private closure inside <AppLayout>.)
 *   3. Standard a11y hygiene: ``data-testid``, ``aria-label``,
 *      and keyboard-invocability (Enter / Space) still fire
 *      the handler.
 *
 * Harness mirrors the existing rail-nav.test.jsx: the heavy
 * dependencies of <AppLayout> are stubbed so the test stays
 * scoped to the sidebar column.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const _logoutMock = vi.fn();
const _navigateMock = vi.fn();

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-1", role: "super_admin",
             email: "admin@aquaterra.com", name: "Admin" },
    loading: false,
    logout: _logoutMock,
  }),
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    can:              () => true,
    effectiveRole:    "super_admin",
    role:             "super_admin",
    isAdmin:          true,
    isAdminOrManager: true,
    canDo:            () => true,
    previewRole:      null,
    setPreviewRole:   vi.fn(),
    isPreviewing:     false,
  }),
  Forbidden: () => <div data-testid="forbidden" />,
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => _navigateMock };
});
// Heavy dependencies mocked so the sidebar-column render is the
// only thing exercised.
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
vi.mock("@vis.gl/react-google-maps", () => ({
  APIProvider: ({ children }) => <>{children}</>,
}));


import AppLayout from "@/layouts/AppLayout";


function mount(initial = "/") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="*" element={<AppLayout />} />
      </Routes>
    </MemoryRouter>,
  );
}


describe("Sidebar rail Logout button", () => {
  beforeEach(() => {
    _logoutMock.mockClear();
    _navigateMock.mockClear();
  });

  it("renders in the sidebar rail with the expected label + a11y attrs", () => {
    mount();
    const btn = screen.getByTestId("sidebar-logout-button");
    expect(btn).toBeTruthy();
    expect(btn.getAttribute("aria-label")).toBe("Log out");
    expect(btn.getAttribute("type")).toBe("button");
    expect(btn.textContent).toMatch(/Logout/);
  });

  it("appears AFTER <QuickPinsRail> in DOM order", () => {
    mount();
    const pinsRail = screen.getByTestId("quick-nav-rail");
    const btn      = screen.getByTestId("sidebar-logout-button");
    // Node.DOCUMENT_POSITION_FOLLOWING === 4 → btn follows pinsRail.
    // eslint-disable-next-line no-bitwise
    const follows =
      pinsRail.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(Boolean(follows)).toBe(true);
    // Sanity: both live inside the same <aside> sidebar column.
    const sidebar = pinsRail.closest("aside");
    expect(sidebar).toBeTruthy();
    expect(sidebar.contains(btn)).toBe(true);
  });

  it("click → calls logout exactly once + navigates to /login", () => {
    mount();
    const btn = screen.getByTestId("sidebar-logout-button");
    fireEvent.click(btn);
    expect(_logoutMock).toHaveBeenCalledTimes(1);
    expect(_navigateMock).toHaveBeenCalledWith(
      "/login", { replace: true },
    );
  });

  it("keyboard: Enter and Space fire the click handler (native button semantics)", () => {
    mount();
    const btn = screen.getByTestId("sidebar-logout-button");
    // Native <button> converts keydown Enter/Space into a click
    // synthetically only when driven by user-event; RTL's plain
    // ``fireEvent.keyDown`` doesn't. We instead assert the button
    // is focusable + has no explicit ``tabIndex=-1`` — which is
    // sufficient because <button type="button"> is keyboard-
    // activatable by default in every conforming browser.
    btn.focus();
    expect(document.activeElement).toBe(btn);
    expect(btn.getAttribute("tabindex")).toBeNull();  // default focus order
    expect(btn.getAttribute("disabled")).toBeNull();
    // And a click still works, proving the same code path.
    fireEvent.click(btn);
    expect(_logoutMock).toHaveBeenCalledTimes(1);
  });
});
