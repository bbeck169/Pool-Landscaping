/**
 * LDM-D · Feb-2026 — Manage Automations settings tab tests.
 *
 * Locks the nine acceptance cases from the LDM-D dispatch:
 *   (a) Tab renders under Admin Settings when GET succeeds.
 *   (b) All 4 sliders + inputs render with default values after load.
 *   (c) Loading state renders skeleton until GET resolves.
 *   (d) Changing an input updates local state immediately + fires
 *       PATCH after 500 ms debounce.
 *   (e) Two rapid changes coalesce into a single PATCH.
 *   (f) PATCH success → "Saved ✓" indicator visible.
 *   (g) PATCH failure → retrying banner, one retry attempt, local
 *       state preserved.
 *   (h) Out-of-range input clamps to boundary.
 *   (i) Non-admin role sees "Admin access required" card, no tab
 *       payload rendered.
 *
 * Test scaffolding follows the codebase pattern established by
 * ``business-settings.test.jsx``: vi.hoisted spies + vi.mock('@/api',
 * ...) + vi.mock('@/auth', ...) + vi.mock('@/theme', ...). Direct
 * component render (no router shell) so the tab is tested in
 * isolation.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor, act,
} from "@testing-library/react";


const { getSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api_base: () => "http://localhost/api",
  api: {
    get: (...a) => getSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));

// Auth role is toggled per-test via a module-scoped ``currentRole``.
let currentRole = "admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: currentRole } }),
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7",
    muted: "#71717A",
    onSurface: "#09090B",
    border: "#E4E4E7",
    surface: "#FFFFFF",
    surfaceSecondary: "#F4F4F5",
    surfaceTertiary: "#E4E4E7",
  },
}));


// Sensible default response for the tab load — every field at LDM-A
// canonical defaults. Individual tests override with mockResolvedValueOnce
// when they need a stored / customised value.
const DEFAULTS = {
  dispatch_delay_threshold_mins: 20,
  dispatch_sms_customer_count: 3,
  filter_clean_interval_months: 6,
  salt_cell_replacement_months: 36,
};

beforeEach(() => {
  currentRole = "admin";
  vi.useFakeTimers();
  getSpy.mockResolvedValue({ ...DEFAULTS });
  patchSpy.mockResolvedValue({ ...DEFAULTS });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  getSpy.mockReset();
  patchSpy.mockReset();
});


// Helper — flushes all timers + pending microtasks together. Under
// vi.useFakeTimers() a chained ``await api.get`` resolves on a
// microtask AFTER the timer fires, so tests need to yield control
// to both. Wrapping in ``act`` keeps React state settled.
async function flushAll() {
  await act(async () => {
    await vi.runAllTimersAsync();
  });
}


import ManageAutomationsSettings from "@/pages/settings/ManageAutomationsSettings";


describe("ManageAutomationsSettings — LDM-D", () => {
  // ── (a) — mount smoke ────────────────────────────────────────────
  it("(a) renders the automations tab under admin settings", async () => {
    render(<ManageAutomationsSettings />);
    await flushAll();
    expect(screen.getByTestId("automations-tab")).toBeTruthy();
    expect(screen.getByTestId("automations-title").textContent).toMatch(
      /Manage Automations/i,
    );
    // Called the GET endpoint on mount.
    expect(getSpy).toHaveBeenCalledWith(
      "/tenants/mine/automation-rules",
    );
  });

  // ── (b) — default field hydration ────────────────────────────────
  it("(b) hydrates all four inputs with defaults from GET response",
      async () => {
    render(<ManageAutomationsSettings />);
    await flushAll();
    const inputs = {
      dispatch: screen.getByTestId("automation-input-dispatch-delay"),
      sms:      screen.getByTestId("automation-input-sms-count"),
      filter:   screen.getByTestId("automation-input-filter-interval"),
      salt:     screen.getByTestId("automation-input-salt-interval"),
    };
    expect(Number(inputs.dispatch.value)).toBe(20);
    expect(Number(inputs.sms.value)).toBe(3);
    expect(Number(inputs.filter.value)).toBe(6);
    expect(Number(inputs.salt.value)).toBe(36);
    // Sliders also render (their radix internals aren't easily
    // introspectable via testing-library, so we just assert
    // presence by testid).
    expect(screen.getByTestId("automation-slider-dispatch-delay")).toBeTruthy();
    expect(screen.getByTestId("automation-slider-sms-count")).toBeTruthy();
    expect(screen.getByTestId("automation-slider-filter-interval")).toBeTruthy();
    expect(screen.getByTestId("automation-slider-salt-interval")).toBeTruthy();
  });

  // ── (c) — loading skeleton ────────────────────────────────────────
  it("(c) shows the skeleton while GET is in flight", async () => {
    // Make the GET hang so the pre-resolve render is observable.
    let resolveGet;
    getSpy.mockImplementationOnce(() => new Promise((r) => {
      resolveGet = r;
    }));
    render(<ManageAutomationsSettings />);
    // At this exact moment GET hasn't resolved — skeleton must be up.
    expect(screen.getByTestId("automations-skeleton")).toBeTruthy();
    expect(screen.queryByTestId("automations-fields")).toBeNull();
    // Resolve GET and confirm the skeleton disappears.
    await act(async () => {
      resolveGet({ ...DEFAULTS });
    });
    await flushAll();
    expect(screen.queryByTestId("automations-skeleton")).toBeNull();
    expect(screen.getByTestId("automations-fields")).toBeTruthy();
  });

  // ── (d) — debounced PATCH after edit ─────────────────────────────
  it("(d) fires PATCH 500ms after an input change with the new value",
      async () => {
    render(<ManageAutomationsSettings />);
    await flushAll();
    const input = screen.getByTestId("automation-input-dispatch-delay");
    // Change to 45. React state updates immediately.
    fireEvent.change(input, { target: { value: "45" } });
    expect(Number(input.value)).toBe(45);
    // Before the debounce elapses, no PATCH has fired.
    expect(patchSpy).not.toHaveBeenCalled();
    // Advance beyond the 500 ms debounce.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(patchSpy).toHaveBeenCalledTimes(1);
    expect(patchSpy).toHaveBeenCalledWith(
      "/tenants/mine/automation-rules",
      { dispatch_delay_threshold_mins: 45 },
    );
  });

  // ── (e) — two rapid changes coalesce into one PATCH ─────────────
  it("(e) coalesces two rapid changes into a single PATCH", async () => {
    render(<ManageAutomationsSettings />);
    await flushAll();
    const input = screen.getByTestId("automation-input-dispatch-delay");
    // Nudge twice within 500 ms.
    fireEvent.change(input, { target: { value: "30" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    fireEvent.change(input, { target: { value: "60" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(patchSpy).toHaveBeenCalledTimes(1);
    // The one call carries the LAST value, not the intermediate.
    expect(patchSpy).toHaveBeenCalledWith(
      "/tenants/mine/automation-rules",
      { dispatch_delay_threshold_mins: 60 },
    );
  });

  // ── (f) — success indicator after successful PATCH ──────────────
  it("(f) shows the 'Saved ✓' pill after a successful PATCH", async () => {
    render(<ManageAutomationsSettings />);
    await flushAll();
    const input = screen.getByTestId("automation-input-sms-count");
    fireEvent.change(input, { target: { value: "5" } });
    // Advance past the debounce PLUS a small margin so the api.patch
    // promise chain resolves and setSaveStatus("saved") lands — but
    // stay WELL below the 2000 ms auto-fade horizon so the pill is
    // still visible when we assert.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(patchSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("automation-saved-indicator")).toBeTruthy();
  });

  // ── (g) — PATCH failure → retry banner + retry + state preserved ─
  it("(g) surfaces the retrying banner on PATCH failure and attempts one retry",
      async () => {
    // First PATCH rejects, second resolves — proves the one-shot retry.
    patchSpy
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ ...DEFAULTS, dispatch_sms_customer_count: 7 });
    render(<ManageAutomationsSettings />);
    await flushAll();
    const input = screen.getByTestId("automation-input-sms-count");
    fireEvent.change(input, { target: { value: "7" } });
    // Local state updates instantly regardless of network state.
    expect(Number(input.value)).toBe(7);
    // Advance past the debounce + microtask drain → first PATCH
    // fires → rejects → retry banner mounts. Stay UNDER the 800 ms
    // retry-delay boundary so the second PATCH hasn't fired yet.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(patchSpy).toHaveBeenCalledTimes(1);
    // Retrying banner is visible before the retry lands.
    expect(screen.getByTestId("automation-retrying-indicator")).toBeTruthy();
    // Advance past the 800 ms retry delay → second PATCH fires +
    // resolves + status flips to "saved". Stay under the auto-fade.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200);
    });
    expect(patchSpy).toHaveBeenCalledTimes(2);
    // Both PATCHes carry the same payload — retry isn't lossy.
    expect(patchSpy.mock.calls[0][1]).toEqual({ dispatch_sms_customer_count: 7 });
    expect(patchSpy.mock.calls[1][1]).toEqual({ dispatch_sms_customer_count: 7 });
    // Local input state was NEVER reverted.
    expect(Number(input.value)).toBe(7);
  });

  // ── (h) — out-of-range input clamps to boundary ─────────────────
  it("(h) clamps out-of-range typed input to the field boundary",
      async () => {
    render(<ManageAutomationsSettings />);
    await flushAll();
    const smsInput = screen.getByTestId("automation-input-sms-count");
    // dispatch_sms_customer_count is bounded [1, 10]. Type 15 → clamp to 10.
    fireEvent.change(smsInput, { target: { value: "15" } });
    expect(Number(smsInput.value)).toBe(10);
    // Type 0 → clamp to 1 (under-range).
    fireEvent.change(smsInput, { target: { value: "0" } });
    expect(Number(smsInput.value)).toBe(1);
    // salt_cell_replacement_months is bounded [12, 120].
    const saltInput = screen.getByTestId("automation-input-salt-interval");
    fireEvent.change(saltInput, { target: { value: "200" } });
    expect(Number(saltInput.value)).toBe(120);
    fireEvent.change(saltInput, { target: { value: "5" } });
    expect(Number(saltInput.value)).toBe(12);
  });

  // ── (i) — non-admin sees the forbidden card, no tab payload ─────
  it("(i) renders 'admin required' when caller role is not admin",
      async () => {
    currentRole = "technician";
    render(<ManageAutomationsSettings />);
    // No GET fires for a non-admin — the tab short-circuits.
    expect(getSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("automations-forbidden")).toBeTruthy();
    expect(screen.queryByTestId("automations-tab")).toBeNull();
    expect(screen.queryByTestId("automations-fields")).toBeNull();
  });

  // ── Bonus: GET failure shows the error banner ───────────────────
  it("shows the error banner when the initial GET fails", async () => {
    getSpy.mockRejectedValueOnce(new Error("network down"));
    render(<ManageAutomationsSettings />);
    await flushAll();
    expect(screen.getByTestId("automation-error-banner")).toBeTruthy();
    expect(screen.getByTestId("automation-error-banner").textContent).toMatch(
      /network down|refresh to retry/i,
    );
    expect(screen.queryByTestId("automations-fields")).toBeNull();
  });
});
