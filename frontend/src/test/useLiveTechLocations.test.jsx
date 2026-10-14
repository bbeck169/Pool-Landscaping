/**
 * P1 Phase 3 · Feb-2026 — useLiveTechLocations hook vitest.
 *
 * Covers:
 *   1. ``colorForStaleness`` → bucket → hex mapping.
 *   2. ``formatAge`` — seconds / minutes / hours.
 *   3. ``shouldDefaultEnabled`` — admin-role roster.
 *   4. Polling-interval setup / teardown on enable / disable.
 *   5. Visibility pause (``document.visibilityState``).
 *   6. Toggle persistence via localStorage keyed by user_id.
 *
 * The hook pulls ``api.get`` and ``useAuth`` — both mocked here
 * so the test runs without a server or auth context.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, cleanup, act, waitFor,
} from "@testing-library/react";


const { apiGetMock, authUserRef } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  authUserRef: { current: { id: "u-admin", role: "admin" } },
}));


vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: vi.fn(), patch: vi.fn(),
    put: vi.fn(), del: vi.fn(),
  },
}));


vi.mock("@/auth", () => ({
  useAuth: () => ({ user: authUserRef.current }),
}));


async function _loadHook() {
  return await import("@/hooks/useLiveTechLocations");
}


function HookProbe({ hookFn, onState }) {
  const state = hookFn();
  React.useEffect(() => { onState(state); }, [state, onState]);
  return null;
}


beforeEach(() => {
  apiGetMock.mockReset().mockResolvedValue({
    pings: [], server_time: "2026-10-15T18:22:45+00:00",
  });
  authUserRef.current = { id: "u-admin", role: "admin" };
  try { window.localStorage.clear(); } catch { /* jsdom */ }
  // Default visibility to visible so the poller starts.
  Object.defineProperty(document, "visibilityState", {
    configurable: true, get: () => "visible",
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });


// ─── §1 · Pure helpers ───────────────────────────────────────────

describe("useLiveTechLocations · pure helpers", () => {
  it("colorForStaleness returns distinct colors per bucket",
     async () => {
    const mod = await _loadHook();
    const live = mod.colorForStaleness("live");
    const recent = mod.colorForStaleness("recent");
    const stale = mod.colorForStaleness("stale");
    expect(live).not.toBe(recent);
    expect(recent).not.toBe(stale);
    // Unknown bucket falls back to stale.
    expect(mod.colorForStaleness("unknown-bucket"))
      .toBe(mod.colorForStaleness("stale"));
  });

  it("formatAge renders seconds / minutes / hours", async () => {
    const mod = await _loadHook();
    expect(mod.formatAge(5)).toBe("5s ago");
    expect(mod.formatAge(42)).toBe("42s ago");
    expect(mod.formatAge(61)).toBe("1m ago");
    expect(mod.formatAge(600)).toBe("10m ago");
    expect(mod.formatAge(3600)).toBe("1h ago");
    expect(mod.formatAge(5400)).toBe("1h 30m ago");
    // Negative + garbage defensive.
    expect(mod.formatAge(-5)).toBe("0s ago");
    expect(mod.formatAge("nope")).toBe("0s ago");
  });

  it("shouldDefaultEnabled matches admin role roster",
     async () => {
    const mod = await _loadHook();
    expect(mod.shouldDefaultEnabled("admin")).toBe(true);
    expect(mod.shouldDefaultEnabled("super_admin")).toBe(true);
    expect(mod.shouldDefaultEnabled("manager")).toBe(true);
    expect(mod.shouldDefaultEnabled("dispatcher")).toBe(true);
    expect(mod.shouldDefaultEnabled("owner")).toBe(true);
    expect(mod.shouldDefaultEnabled("technician")).toBe(false);
    expect(mod.shouldDefaultEnabled("customer")).toBe(false);
    expect(mod.shouldDefaultEnabled("")).toBe(false);
    expect(mod.shouldDefaultEnabled(null)).toBe(false);
  });
});


// ─── §2 · Polling behaviour ───────────────────────────────────────

describe("useLiveTechLocations · polling", () => {
  it("fetches on mount when enabled + admin role", async () => {
    const mod = await _loadHook();
    const states = [];
    render(
      <HookProbe
        hookFn={mod.useLiveTechLocations}
        onState={(s) => states.push(s)}
      />,
    );
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledWith(
      "/workforce/live-locations",
      expect.objectContaining({ signal: expect.anything() }),
    ));
  });

  it("does NOT fetch on mount when disabled by role default",
     async () => {
    authUserRef.current = { id: "u-tech", role: "technician" };
    const mod = await _loadHook();
    render(
      <HookProbe hookFn={mod.useLiveTechLocations}
                   onState={() => {}} />,
    );
    // Give the effect a tick to run.
    await new Promise((r) => setTimeout(r, 30));
    expect(apiGetMock).not.toHaveBeenCalled();
  });

  it("polls every 30s when enabled", async () => {
    vi.useFakeTimers();
    const mod = await _loadHook();
    render(
      <HookProbe hookFn={mod.useLiveTechLocations}
                   onState={() => {}} />,
    );
    // Boot fetch — flush pending microtasks.
    await act(async () => { await Promise.resolve(); });
    const bootCalls = apiGetMock.mock.calls.length;
    expect(bootCalls).toBeGreaterThanOrEqual(1);
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(apiGetMock.mock.calls.length).toBe(bootCalls + 1);
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(apiGetMock.mock.calls.length).toBe(bootCalls + 2);
  });

  it("pauses polling when the tab is hidden", async () => {
    vi.useFakeTimers();
    const mod = await _loadHook();
    render(
      <HookProbe hookFn={mod.useLiveTechLocations}
                   onState={() => {}} />,
    );
    await act(async () => { await Promise.resolve(); });
    const bootCalls = apiGetMock.mock.calls.length;
    // Hide tab.
    Object.defineProperty(document, "visibilityState", {
      configurable: true, get: () => "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
    await act(async () => { vi.advanceTimersByTime(30_000); });
    // No new polls while hidden.
    expect(apiGetMock.mock.calls.length).toBe(bootCalls);
  });
});


// ─── §3 · Toggle + persistence ────────────────────────────────────

describe("useLiveTechLocations · toggle persistence", () => {
  it("persists disabled state in localStorage keyed by user_id",
     async () => {
    const mod = await _loadHook();
    const states = [];
    render(
      <HookProbe hookFn={mod.useLiveTechLocations}
                   onState={(s) => states.push(s)} />,
    );
    await waitFor(() => expect(states.length).toBeGreaterThan(0));
    await act(async () => { states.at(-1).setEnabled(false); });
    expect(window.localStorage.getItem("live_tech_overlay.u-admin"))
      .toBe("0");
  });

  it("hydrates saved state on next mount", async () => {
    window.localStorage.setItem("live_tech_overlay.u-admin", "0");
    const mod = await _loadHook();
    render(
      <HookProbe hookFn={mod.useLiveTechLocations}
                   onState={() => {}} />,
    );
    await new Promise((r) => setTimeout(r, 30));
    // Disabled → no fetch.
    expect(apiGetMock).not.toHaveBeenCalled();
  });

  it("tech role with saved '1' override still polls", async () => {
    authUserRef.current = { id: "u-tech", role: "technician" };
    window.localStorage.setItem("live_tech_overlay.u-tech", "1");
    const mod = await _loadHook();
    render(
      <HookProbe hookFn={mod.useLiveTechLocations}
                   onState={() => {}} />,
    );
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
  });
});
