/**
 * Phase P38 · Feb-2026 — UniversalMenu container wrap.
 *
 * The floating variant of ``<UniversalMenu>`` (customer-portal shell)
 * used to render three separate top-right elements, each carrying its
 * own ``fixed top-3 right-*`` positioning:
 *   • Sign Out pill        (fixed top-3 right-[6.5rem])
 *   • NotificationBell     (fixed top-3 right-14)
 *   • Hamburger trigger    (fixed top-3 right-3)
 *
 * P38 wraps all three in a single container div whose class list
 * carries the fixed positioning + flex row, and strips the per-
 * element ``fixed / top-* / right-*`` classes so the three elements
 * flow horizontally as siblings inside the container.
 *
 * This file locks that structure in place:
 *   1. The wrapper element MUST render with the container classes:
 *      ``fixed top-3 right-3 z-40 flex items-center gap-2``.
 *   2. The three child elements (Sign Out button, NotificationBell,
 *      DropdownMenuTrigger) MUST render without a ``fixed`` class
 *      on their own root — positioning is the container's job now.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/* ── Hoisted mocks ─────────────────────────────────────────────── */

const _h = vi.hoisted(() => ({
  logout: vi.fn(),
  navigate: vi.fn(),
  user: { id: "u-cust-p38", role: "customer", first_name: "P38" },
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

// Minimal single-section nav so ``flat.length > 0`` guard passes.
vi.mock("@/nav/roleNav", () => ({
  navForRoleAndDept: () => ([
    { key: "portal", label: "Portal", entries: [
      { to: "/portal/home", label: "Home" },
    ]},
  ]),
}));

// Stub the bell to a plain div so we can inspect its class list
// without hitting the real component's network calls / hooks.
vi.mock("@/components/NotificationBell", () => ({
  default: () => (
    <div
      data-testid="notification-bell"
      className="inline-flex items-center justify-center w-10 h-10 rounded-lg border shadow-sm bg-white"
    >
      bell
    </div>
  ),
}));

// Radix DropdownMenu — passthrough so we can grab the trigger by
// testid without opening the sheet.
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children, ...rest }) => (
    <button {...rest}>{children}</button>
  ),
  DropdownMenuContent: () => null,
}));

import UniversalMenu from "@/layouts/UniversalMenu";

/* ── Helpers ───────────────────────────────────────────────────── */

function renderFloating() {
  return render(
    <MemoryRouter initialEntries={["/portal/home"]}>
      <UniversalMenu variant="floating" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  _h.logout.mockClear();
  _h.navigate.mockClear();
  _h.user = { id: "u-cust-p38", role: "customer", first_name: "P38" };
});

/* ── Tests ─────────────────────────────────────────────────────── */

describe("P38 · UniversalMenu floating cluster is wrapped in a single container", () => {
  it("wrapper element carries the P38 container classes", () => {
    renderFloating();
    const wrapper = screen.getByTestId("universal-menu-floating-wrap");
    // Every class in the required spec must be present.  We assert
    // via containment (not exact equality) so future additive
    // classes (e.g. a debug marker) don't break this test.
    const classes = wrapper.className.split(/\s+/);
    for (const required of ["fixed", "top-3", "right-3", "z-40", "flex", "items-center", "gap-2"]) {
      expect(classes).toContain(required);
    }
  });

  it("Sign Out, NotificationBell, and the hamburger trigger render WITHOUT their own `fixed` class", () => {
    renderFloating();
    const signOut = screen.getByTestId("portal-signout");
    const bell    = screen.getByTestId("notification-bell");
    const trigger = screen.getByTestId("web-menu-trigger");

    for (const [label, el] of [
      ["portal-signout", signOut],
      ["notification-bell", bell],
      ["web-menu-trigger", trigger],
    ]) {
      const classes = el.className.split(/\s+/);
      expect(classes).not.toContain("fixed");
      // The old per-element right-* / top-* anchors must be gone too.
      expect(classes.some((c) => c === "top-3")).toBe(false);
      expect(classes.some((c) => c.startsWith("right-"))).toBe(false);
    }
  });

  it("wrapper contains all three cluster children in the documented DOM order (signout → bell → hamburger)", () => {
    const { container } = renderFloating();
    const wrapper = container.querySelector('[data-testid="universal-menu-floating-wrap"]');
    expect(wrapper).not.toBeNull();
    // Grab the three testids' DOM indices under the wrapper.
    const html = wrapper.innerHTML;
    const iSign = html.indexOf('data-testid="portal-signout"');
    const iBell = html.indexOf('data-testid="notification-bell"');
    const iMenu = html.indexOf('data-testid="web-menu-trigger"');
    expect(iSign).toBeGreaterThan(-1);
    expect(iBell).toBeGreaterThan(-1);
    expect(iMenu).toBeGreaterThan(-1);
    expect(iSign).toBeLessThan(iBell);
    expect(iBell).toBeLessThan(iMenu);
  });
});
