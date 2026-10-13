/**
 * Phase K75 · Step B · Feb-2026 P2 interrupt — Quick Access
 * long-press → edit-mode UX contract.
 *
 * Covers the 14 cases enumerated in the audit + user-approved
 * additions (pointer guardrails + ARIA live region):
 *
 *   1. Non-edit baseline: × has opacity-0 + pointer-events-none;
 *      NavLink click navigates.
 *   2. Long-press entry: 500 ms pointerdown w/o movement → edit
 *      mode on, × unconditionally visible, pins carry jiggle.
 *   3. Short press (<500 ms) does NOT enter edit mode.
 *   4. In edit mode, clicking × still opens RemovePinConfirm
 *      (non-regression of the K75 CRUD remove flow).
 *   5. In edit mode, NavLink click DOES navigate (override of
 *      initial audit — nav is non-destructive) and the click
 *      resets edit mode (naturally exits).
 *   6. "Done" button exits edit mode: × hidden again, jiggle off,
 *      +Add pin restored.
 *   7. pointerdown outside the rail exits edit mode.
 *   8. Escape key exits edit mode.
 *   9. The "Edit pins" header button toggles edit mode (keyboard
 *      a11y entry path).
 *  10. prefers-reduced-motion is honored via the Tailwind
 *      ``motion-reduce:animate-none`` utility (source-grep).
 *  11. ARIA live region (role=status, aria-live=polite) with the
 *      exact exit instruction text is rendered when editMode true.
 *  12. pointermove > 10 px during the hold cancels the timer → no
 *      edit mode.
 *  13. pointercancel mid-hold cancels the timer → no edit mode.
 *  14. Right-click (button=2) pointerdown does nothing.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import fs from "node:fs";
import path from "node:path";


// jsdom 25 ships a bare ``PointerEvent`` that doesn't carry the
// ``button`` / ``clientX`` / ``clientY`` MouseEvent properties
// through React's synthetic event layer. Dispatching a native
// MouseEvent with the pointer event-type routes correctly to
// React's ``onPointerDown`` / etc. props without needing a global
// polyfill (which would leak across unrelated tests in the same
// worker — Phase 41.1 cleanup posture).
function _firePointer(el, type, { button = 0, clientX = 100, clientY = 100 } = {}) {
  const ev = new MouseEvent(type, {
    bubbles: true, cancelable: true, button, clientX, clientY,
  });
  el.dispatchEvent(ev);
}


const _apiGet = vi.fn();
const _apiPut = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => _apiGet(...a), put: (...a) => _apiPut(...a) },
}));
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [
    { key: "operations", label: "Operations", icon: () => null, entries: [
      { to: "/schedule", label: "Schedule", icon: () => null, feature: "schedule" },
    ]},
  ],
  NAV_FLAT: [],
  KEYBOARD_SHORTCUTS: [],
  SHORTCUT_TARGETS: {},
  filterNavByIndustries: (entries) => entries,
}));


import QuickPinsRail from "@/components/nav/QuickPinsRail";


function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc-probe">{loc.pathname}</div>;
}


function mount(role = "admin", initial = "/") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <QuickPinsRail role={role} />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}


const SEEDED_TWO = [
  { to: "/schedule",  label: "Schedule",  iconKey: "calendar_days" },
  { to: "/customers", label: "Customers", iconKey: "users" },
];


beforeEach(() => {
  _apiGet.mockReset();
  _apiPut.mockReset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});


async function _enterEditModeViaLongPress(container) {
  const pin = container.querySelector('[data-testid="rail-pin-schedule"]');
  // Primary button + no movement.
  await act(async () => {
    _firePointer(pin, "pointerdown", { button: 0, clientX: 100, clientY: 100 });
    vi.advanceTimersByTime(600);
  });
  // Simulate finger-lift that follows a successful long-press in a
  // real browser. The native click dispatched on pointerup is the
  // event that the capture-phase handler consumes to reset the
  // ``longPressFiredRef`` back to false — without this, subsequent
  // clicks on × / NavLink would get swallowed by the same guard.
  await act(async () => {
    _firePointer(pin, "pointerup");
    fireEvent.click(pin);
  });
}


describe("K75 edit-mode · Case 1 — non-edit baseline", () => {
  it("× is opacity-0 + pointer-events-none; NavLink navigates", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    mount("admin", "/");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());

    const removeBtn = screen.getByTestId("rail-pin-remove-schedule");
    const cls = removeBtn.getAttribute("class") || "";
    expect(cls).toMatch(/opacity-0/);
    expect(cls).toMatch(/pointer-events-none/);
    expect(cls).not.toMatch(/opacity-100/);

    // NavLink navigation still works.
    const nav = screen.getByTestId("rail-nav-schedule");
    fireEvent.click(nav);
    expect(screen.getByTestId("loc-probe").textContent).toBe("/schedule");
  });
});


describe("K75 edit-mode · Case 2 — long-press entry", () => {
  it("500 ms pointerdown w/o movement enters edit mode, × visible, jiggle on", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());

    await _enterEditModeViaLongPress(container);

    // Done button is present (replaces +Add).
    expect(screen.getByTestId("rail-edit-done-btn")).toBeTruthy();
    expect(screen.queryByTestId("rail-pin-add-btn")).toBeNull();

    // × is now opacity-100 and pointer-events-auto.
    const removeBtn = screen.getByTestId("rail-pin-remove-schedule");
    const cls = removeBtn.getAttribute("class") || "";
    expect(cls).toMatch(/opacity-100/);
    expect(cls).toMatch(/pointer-events-auto/);
    expect(cls).not.toMatch(/opacity-0/);

    // Pin wrapper carries the jiggle class + reduced-motion guard.
    const pin = screen.getByTestId("rail-pin-schedule");
    const pinCls = pin.getAttribute("class") || "";
    expect(pinCls).toMatch(/animate-pin-jiggle/);
    expect(pinCls).toMatch(/motion-reduce:animate-none/);
  });
});


describe("K75 edit-mode · Case 3 — short press no-op", () => {
  it("<500 ms pointerdown → no edit mode", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());

    const pin = container.querySelector('[data-testid="rail-pin-schedule"]');
    _firePointer(pin, "pointerdown", { button: 0, clientX: 100, clientY: 100 });
    await act(async () => { vi.advanceTimersByTime(200); });
    _firePointer(pin, "pointerup");
    await act(async () => { vi.advanceTimersByTime(400); });

    expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull();
    expect(screen.getByTestId("rail-pin-add-btn")).toBeTruthy();
  });
});


describe("K75 edit-mode · Case 4 — edit-mode × click opens confirm", () => {
  it("non-regression of the K75 CRUD remove flow in edit mode", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());
    await _enterEditModeViaLongPress(container);

    fireEvent.click(screen.getByTestId("rail-pin-remove-schedule"));
    expect(await screen.findByTestId("remove-pin-confirm")).toBeTruthy();
  });
});


describe("K75 edit-mode · Case 5 — NavLink navigates + resets edit mode", () => {
  it("clicking a pin in edit mode navigates and naturally exits edit mode", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin", "/");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());
    await _enterEditModeViaLongPress(container);
    expect(screen.getByTestId("rail-edit-done-btn")).toBeTruthy();

    // Click NavLink → navigation DOES fire + edit mode resets.
    fireEvent.click(screen.getByTestId("rail-nav-schedule"));
    expect(screen.getByTestId("loc-probe").textContent).toBe("/schedule");
    expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull();
    expect(screen.getByTestId("rail-pin-add-btn")).toBeTruthy();
  });
});


describe("K75 edit-mode · Case 6 — Done button exits", () => {
  it("Done click → × hidden, jiggle off, +Add restored", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());
    await _enterEditModeViaLongPress(container);

    fireEvent.click(screen.getByTestId("rail-edit-done-btn"));

    expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull();
    expect(screen.getByTestId("rail-pin-add-btn")).toBeTruthy();
    const pin = screen.getByTestId("rail-pin-schedule");
    expect(pin.getAttribute("class") || "").not.toMatch(/animate-pin-jiggle/);
    const removeBtn = screen.getByTestId("rail-pin-remove-schedule");
    expect(removeBtn.getAttribute("class") || "").toMatch(/opacity-0/);
  });
});


describe("K75 edit-mode · Case 7 — click-outside exits", () => {
  it("pointerdown outside the rail exits edit mode", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());
    await _enterEditModeViaLongPress(container);
    expect(screen.getByTestId("rail-edit-done-btn")).toBeTruthy();

    // Dispatch pointerdown on document.body (outside the rail).
    await act(async () => {
      _firePointer(document.body, "pointerdown");
    });

    await waitFor(() =>
      expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull()
    );
  });
});


describe("K75 edit-mode · Case 8 — Escape exits", () => {
  it("Escape keydown exits edit mode", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());
    await _enterEditModeViaLongPress(container);

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull()
    );
  });
});


describe("K75 edit-mode · Case 9 — Edit pins header button toggles mode", () => {
  it("keyboard-accessible edit entry is reachable + toggles", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());

    const toggle = screen.getByTestId("rail-edit-enter-btn");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("rail-edit-done-btn")).toBeTruthy();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull();
  });
});


describe("K75 edit-mode · Case 10 — reduced-motion guard (source-grep)", () => {
  it("the jiggle class is coupled with motion-reduce:animate-none in source", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../components/nav/QuickPinsRail.jsx"),
      "utf-8",
    );
    // Both tokens must appear on the SAME className expression —
    // locked here as a substring match to guarantee that a future
    // refactor cannot strip the reduced-motion guard without
    // breaking this test.
    expect(src).toMatch(/animate-pin-jiggle\s+motion-reduce:animate-none/);
  });
});


describe("K75 edit-mode · Case 11 — ARIA live region", () => {
  it("renders role=status + aria-live=polite with exit instruction text", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());
    await _enterEditModeViaLongPress(container);

    const live = screen.getByTestId("rail-edit-mode-live");
    expect(live.getAttribute("role")).toBe("status");
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toBe("Edit mode on. Press Escape to exit.");

    // Rail wires aria-describedby to the live region id.
    const rail = screen.getByTestId("quick-nav-rail");
    expect(rail.getAttribute("aria-describedby")).toBe("rail-edit-mode-status");
  });
});


describe("K75 edit-mode · Case 12 — pointermove > 10 px cancels timer", () => {
  it("drag intent takes precedence; no edit mode", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());

    const pin = container.querySelector('[data-testid="rail-pin-schedule"]');
    _firePointer(pin, "pointerdown", { button: 0, clientX: 100, clientY: 100 });
    // Move 15 px (>10 px threshold) BEFORE the 500 ms deadline.
    await act(async () => { vi.advanceTimersByTime(100); });
    _firePointer(pin, "pointermove", { clientX: 115, clientY: 100 });
    await act(async () => { vi.advanceTimersByTime(600); });

    expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull();
    expect(screen.getByTestId("rail-pin-add-btn")).toBeTruthy();
  });
});


describe("K75 edit-mode · Case 13 — pointercancel clears timer", () => {
  it("mid-hold pointercancel → no edit mode", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());

    const pin = container.querySelector('[data-testid="rail-pin-schedule"]');
    _firePointer(pin, "pointerdown", { button: 0, clientX: 100, clientY: 100 });
    await act(async () => { vi.advanceTimersByTime(200); });
    _firePointer(pin, "pointercancel");
    await act(async () => { vi.advanceTimersByTime(600); });

    expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull();
    expect(screen.getByTestId("rail-pin-add-btn")).toBeTruthy();
  });
});


describe("K75 edit-mode · Case 14 — right-click no-op", () => {
  it("non-primary button pointerdown does not arm the timer", async () => {
    _apiGet.mockResolvedValue({ pins: SEEDED_TWO });
    const { container } = mount("admin");
    await waitFor(() => expect(_apiGet).toHaveBeenCalled());

    const pin = container.querySelector('[data-testid="rail-pin-schedule"]');
    _firePointer(pin, "pointerdown", { button: 2, clientX: 100, clientY: 100 });
    await act(async () => { vi.advanceTimersByTime(800); });

    expect(screen.queryByTestId("rail-edit-done-btn")).toBeNull();
    expect(screen.getByTestId("rail-pin-add-btn")).toBeTruthy();
  });
});
