/**
 * Phase P20 · Feb-2026 — UniversalMenu bookmark REMOVE confirmation.
 *
 * The Universal Menu's bookmark toggle historically fired remove-pin
 * on a single click. Phase P20 wraps the REMOVE path in the shared
 * ``RemovePinConfirm`` dialog (same modal the Quick Access rail uses)
 * so users get a chance to bail. ADD path stays immediate.
 *
 * This suite locks:
 *   1. Clicking the bookmark toggle on a PINNED item opens the
 *      ``remove-pin-confirm`` dialog (no direct removal).
 *   2. Clicking the dialog's Confirm actually removes the pin from
 *      localStorage — persisted list drops the entry.
 *   3. Clicking Cancel closes the dialog and leaves the pin list
 *      untouched (no removal fired).
 *   4. Clicking the bookmark toggle on an UNPINNED item runs the ADD
 *      immediately — no dialog opens and the pin list grows by one.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/* ── Hoisted mocks ─────────────────────────────────────────────── */

const _h = vi.hoisted(() => ({
  navigate: vi.fn(),
  user: { id: "u-1", role: "admin", first_name: "Rob" },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: _h.user, logout: vi.fn() }),
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

// Deterministic 2-entry nav — one will be seeded as pinned, one as
// unpinned so we can exercise both bookmark paths in one file.
vi.mock("@/nav/roleNav", () => ({
  navForRoleAndDept: () => ([
    { key: "ops", label: "Operations", entries: [
      { to: "/schedule",  label: "Schedule"  },
      { to: "/customers", label: "Customers" },
    ]},
  ]),
}));

vi.mock("@/components/NotificationBell", () => ({
  default: () => <div data-testid="bell-stub" />,
}));

// DropdownMenu passthrough so the sheet's contents (including the
// bookmark toggles) are always in the DOM without simulating the
// Radix open/close dance. ``RemovePinConfirm`` is NOT mocked — the
// real Radix AlertDialog renders through its portal.
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children, ...rest }) => (
    <button {...rest}>{children}</button>
  ),
  DropdownMenuContent: ({ children, ...rest }) => (
    <div {...rest}>{children}</div>
  ),
}));

import UniversalMenu from "@/layouts/UniversalMenu";

/* ── Helpers ───────────────────────────────────────────────────── */

const PINS_KEY = "web-menu-pins-v1::u-1";

function seedPins(paths) {
  window.localStorage.setItem(PINS_KEY, JSON.stringify(paths));
}
function readPins() {
  const raw = window.localStorage.getItem(PINS_KEY);
  return raw ? JSON.parse(raw) : [];
}

function renderMenu() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <UniversalMenu variant="inline" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  _h.navigate.mockClear();
  _h.user = { id: "u-1", role: "admin", first_name: "Rob" };
});

/* ── Tests ─────────────────────────────────────────────────────── */

describe("P20 · UniversalMenu bookmark REMOVE requires confirm", () => {

  it("clicking the bookmark toggle on a PINNED item opens the remove-pin-confirm dialog (no immediate removal)", async () => {
    seedPins(["/schedule"]);
    renderMenu();

    // Precondition: pin is persisted before the click.
    expect(readPins()).toEqual(["/schedule"]);

    // The pinned row's bookmark toggle is present with the "Unpin" label.
    const toggle = screen.getByTestId("web-menu-pin-toggle-schedule");
    expect(toggle.getAttribute("aria-label")).toBe("Unpin Schedule");

    fireEvent.click(toggle);

    // Dialog opens.
    expect(await screen.findByTestId("remove-pin-confirm")).toBeTruthy();
    expect(screen.getByTestId("remove-pin-confirm-btn")).toBeTruthy();

    // Removal has NOT fired yet — localStorage still holds the pin.
    expect(readPins()).toEqual(["/schedule"]);
  });

  it("clicking Confirm in the dialog fires the removal exactly once", async () => {
    seedPins(["/schedule"]);
    renderMenu();

    fireEvent.click(screen.getByTestId("web-menu-pin-toggle-schedule"));
    const confirm = await screen.findByTestId("remove-pin-confirm-btn");

    await act(async () => { fireEvent.click(confirm); });

    // Pin list persisted without the removed entry — the removal
    // callback (togglePin) ran exactly once.
    await waitFor(() => expect(readPins()).toEqual([]));

    // Dialog closed.
    await waitFor(() =>
      expect(screen.queryByTestId("remove-pin-confirm")).toBeNull(),
    );
  });

  it("clicking Cancel closes the dialog and does NOT fire the removal callback", async () => {
    seedPins(["/schedule"]);
    renderMenu();

    fireEvent.click(screen.getByTestId("web-menu-pin-toggle-schedule"));
    const cancel = await screen.findByTestId("remove-pin-cancel");

    await act(async () => { fireEvent.click(cancel); });

    // Dialog closed.
    await waitFor(() =>
      expect(screen.queryByTestId("remove-pin-confirm")).toBeNull(),
    );

    // Pin list untouched — cancel is a no-op on persistence.
    expect(readPins()).toEqual(["/schedule"]);
  });

  it("clicking the bookmark toggle on an UNPINNED item runs the add path immediately (no dialog)", async () => {
    // Only /schedule is pre-pinned; /customers is unpinned.
    seedPins(["/schedule"]);
    renderMenu();

    const addToggle = screen.getByTestId("web-menu-pin-toggle-customers");
    expect(addToggle.getAttribute("aria-label")).toBe("Pin Customers");

    fireEvent.click(addToggle);

    // No confirm dialog opens on the add path.
    expect(screen.queryByTestId("remove-pin-confirm")).toBeNull();

    // Add path persisted the new pin at end of list.
    await waitFor(() =>
      expect(readPins()).toEqual(["/schedule", "/customers"]),
    );
  });

  it("bookmark toggle preserves its testid + aria-label affordance (no visual break)", () => {
    seedPins(["/schedule"]);
    renderMenu();
    // Pinned row → "Unpin …" aria; unpinned row → "Pin …" aria.
    expect(
      screen.getByTestId("web-menu-pin-toggle-schedule")
        .getAttribute("aria-label"),
    ).toBe("Unpin Schedule");
    expect(
      screen.getByTestId("web-menu-pin-toggle-customers")
        .getAttribute("aria-label"),
    ).toBe("Pin Customers");
  });
});
