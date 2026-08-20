/**
 * Feb-2026 · Customer-portal Sign-out header button.
 *
 * The button is mounted inside ``<UniversalMenu variant="floating" />``
 * which is the shell surface for customer / customer_admin roles
 * (mounted at ``AppLayout.jsx`` L546–L548 when the user's role does
 * NOT match {admin, super_admin, manager, technician}).
 *
 * Guarantees this file locks in:
 *   1. ``portal-signout`` testid is present in the portal shell.
 *   2. Sign Out DOM-order is BEFORE ``NotificationBell`` and the
 *      hamburger ``web-menu-trigger`` (left-of-cluster).
 *   3. Clicking calls ``useAuth().logout`` and navigates to
 *      ``/portal/login`` via ``useNavigate().replace``.
 *   4. Only renders in ``variant="floating"`` (i.e., customer
 *      surface). The ``inline`` variant (mounted inside
 *      ``AdminTopBar`` for admin roles) MUST NOT render the pill
 *      — admin already has its own ``header-signout``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/* ── Hoisted mocks ─────────────────────────────────────────────── */

const _h = vi.hoisted(() => ({
  logout: vi.fn(),
  navigate: vi.fn(),
  user: { id: "u-cust-1", role: "customer", first_name: "Rob" },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: _h.user, logout: _h.logout }),
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    can: () => true,
    effectiveRole: _h.user?.role || null,
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => _h.navigate };
});

// Nav is exercised only for RBAC filtering — one section with one entry
// keeps ``flat.length > 0`` so ``UniversalMenu`` doesn't early-return.
vi.mock("@/nav/roleNav", () => ({
  navForRoleAndDept: () => ([
    { key: "portal", label: "Portal", entries: [
      { to: "/portal/home", label: "Home" },
    ]},
  ]),
}));

// Bell is a passive icon — stub keeps the DOM light and lets us
// assert Sign Out sits BEFORE it in DOM order.
vi.mock("@/components/NotificationBell", () => ({
  default: () => (
    <div data-testid="portal-bell-stub">bell</div>
  ),
}));

// Radix DropdownMenu — simplified passthrough so we can find the
// trigger by testid without opening the sheet.
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children, ...rest }) => (
    <button {...rest}>{children}</button>
  ),
  DropdownMenuContent: () => null,
}));

import UniversalMenu from "@/layouts/UniversalMenu";

/* ── Helpers ───────────────────────────────────────────────────── */

function renderMenu(props = { variant: "floating" }) {
  return render(
    <MemoryRouter initialEntries={["/portal/home"]}>
      <UniversalMenu {...props} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  _h.logout.mockClear();
  _h.navigate.mockClear();
  _h.user = { id: "u-cust-1", role: "customer", first_name: "Rob" };
});

/* ── Tests ─────────────────────────────────────────────────────── */

describe("Portal Sign-out header button", () => {

  it("renders the portal-signout button in the floating (customer) variant", () => {
    renderMenu({ variant: "floating" });
    const btn = screen.getByTestId("portal-signout");
    expect(btn).toBeTruthy();
    expect(btn.getAttribute("aria-label")).toBe("Sign out");
    expect(btn.textContent).toMatch(/Sign out/);
  });

  it("Sign Out is BEFORE NotificationBell + hamburger in DOM order (left-of-cluster)", () => {
    const { container } = renderMenu({ variant: "floating" });
    const html = container.innerHTML;
    const iSign = html.indexOf('data-testid="portal-signout"');
    const iBell = html.indexOf('data-testid="portal-bell-stub"');
    const iMenu = html.indexOf('data-testid="web-menu-trigger"');
    expect(iSign).toBeGreaterThan(-1);
    expect(iBell).toBeGreaterThan(-1);
    expect(iMenu).toBeGreaterThan(-1);
    // Left-of-cluster requires: signout appears before bell, bell before menu.
    expect(iSign).toBeLessThan(iBell);
    expect(iBell).toBeLessThan(iMenu);
  });

  it("uses fixed floating position that clears the bell at right-14 (right-[6.5rem])", () => {
    renderMenu({ variant: "floating" });
    const btn = screen.getByTestId("portal-signout");
    // Right anchor is right-[6.5rem] = 104 px → sits to the LEFT of
    // the bell (which is at right-14 = 56 px anchor + w-10 = 40 px
    // wide, so bell left-edge = 96 px, giving an 8 px gap).
    expect(btn.className).toMatch(/fixed/);
    expect(btn.className).toMatch(/top-3/);
    expect(btn.className).toMatch(/right-\[6\.5rem\]/);
    // Above the bell (z-40 shared with bell + hamburger).
    expect(btn.className).toMatch(/z-40/);
  });

  it("clicking Sign Out calls useAuth().logout AND navigates to /portal/login (replace)", async () => {
    renderMenu({ variant: "floating" });
    await act(async () => {
      fireEvent.click(screen.getByTestId("portal-signout"));
    });
    expect(_h.logout).toHaveBeenCalledTimes(1);
    expect(_h.navigate).toHaveBeenCalledWith(
      "/portal/login",
      { replace: true },
    );
  });

  it("does NOT render the pill in the inline (admin) variant — admin has its own header-signout", () => {
    _h.user = { id: "u-adm-1", role: "admin" };
    renderMenu({ variant: "inline" });
    expect(screen.queryByTestId("portal-signout")).toBeNull();
    // The hamburger + bell stubs still render — we only skipped the
    // sign-out pill for the inline shell.
    expect(screen.getByTestId("portal-bell-stub")).toBeTruthy();
    expect(screen.getByTestId("web-menu-trigger")).toBeTruthy();
  });

  it("does NOT render when the user is signed-out (defensive guard)", () => {
    _h.user = null;
    renderMenu({ variant: "floating" });
    expect(screen.queryByTestId("portal-signout")).toBeNull();
  });
});
