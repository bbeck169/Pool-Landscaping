/**
 * Feb-2026 · Clock-in gate hook — landscape-tech role-detection +
 * cached status probe.  Task = "Landscaper clock-in gate".
 *
 * Locks the two exported hooks in ``@/hooks/useClockInGate``:
 *   • ``useClockInStatus()``  — synchronous ``{isGated, isClockedIn,
 *      isChecking, refresh}`` for render-time button gating.
 *   • ``useClockInGate(user)`` — imperative opener wrapper that
 *      surfaces the ``<ClockInGateDialog />`` when a landscape tech
 *      tries to open a job before clocking in.
 *
 * The tests deliberately mount both hooks via ``renderHook`` and
 * mock ``@/auth`` + ``@/api`` so we can exercise the full matrix
 * (landscape tech · pool tech · admin · manager · super_admin ·
 * customer) without touching the network or React Router.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";


// ─── Hoisted mocks ──────────────────────────────────────────────
const _h = vi.hoisted(() => ({
  currentUser: null,
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: _h.currentUser }),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...args) => _h.apiGet(...args),
    post: (...args) => _h.apiPost(...args),
  },
}));


// Import AFTER mocks so the hook sees them.
// eslint-disable-next-line import/first
import {
  useClockInStatus,
  useClockInGate,
  __resetClockInStatusCacheForTests,
} from "@/hooks/useClockInGate";


const _wrap = ({ children }) => (
  <MemoryRouter>{children}</MemoryRouter>
);

const _landscapeTech = {
  id: "u-luis", role: "technician", department: "landscape_tech",
};
const _landscapingCanonical = {
  id: "u-jose", role: "technician", department: "landscaping",
};
const _bothTech = {
  id: "u-cross", role: "technician", department: "both",
};
const _poolTech = {
  id: "u-alex", role: "technician", department: "pool",
};
const _admin = { id: "u-a", role: "admin", department: "both" };
const _manager = { id: "u-m", role: "manager", department: "landscaping" };


beforeEach(() => {
  _h.currentUser = null;
  _h.apiGet.mockReset();
  _h.apiPost.mockReset();
  __resetClockInStatusCacheForTests();
});
afterEach(() => {
  __resetClockInStatusCacheForTests();
});


describe("useClockInStatus — role detection matrix", () => {
  it("non-landscape role (admin) → isGated false without a network call", async () => {
    _h.currentUser = _admin;
    const { result } = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    // Admin's isClockedIn defaults to true (no gate applies).
    expect(result.current.isGated).toBe(false);
    expect(result.current.isClockedIn).toBe(true);
    // Zero API hits — the gate short-circuits before fetching.
    expect(_h.apiGet).not.toHaveBeenCalled();
  });

  it("non-landscape role (manager) → isGated false, no API call", () => {
    _h.currentUser = _manager;
    const { result } = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    expect(result.current.isGated).toBe(false);
    expect(_h.apiGet).not.toHaveBeenCalled();
  });

  it("non-landscape role (pool tech) → isGated false, no API call", () => {
    _h.currentUser = _poolTech;
    const { result } = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    expect(result.current.isGated).toBe(false);
    expect(_h.apiGet).not.toHaveBeenCalled();
  });

  it("landscape tech (dept=landscape_tech) + not clocked in → isGated true", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false, punch_count: 0 });
    const { result } = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    await waitFor(() => expect(result.current.isChecking).toBe(false));
    expect(result.current.isClockedIn).toBe(false);
    expect(result.current.isGated).toBe(true);
    expect(_h.apiGet).toHaveBeenCalledWith("/timeclock/mine-status");
  });

  it("landscape tech (dept=landscaping canonical) + clocked in → isGated false", async () => {
    _h.currentUser = _landscapingCanonical;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: true, punch_count: 1 });
    const { result } = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    await waitFor(() => expect(result.current.isChecking).toBe(false));
    expect(result.current.isClockedIn).toBe(true);
    expect(result.current.isGated).toBe(false);
  });

  it("cross-trained tech (dept=both) → gated the same way", async () => {
    _h.currentUser = _bothTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false, punch_count: 0 });
    const { result } = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    await waitFor(() => expect(result.current.isChecking).toBe(false));
    expect(result.current.isGated).toBe(true);
  });

  it("N mounts of the hook share ONE round-trip (cache de-dupes)", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false, punch_count: 0 });
    const a = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    const b = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    const c = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    await waitFor(() => expect(a.result.current.isChecking).toBe(false));
    await waitFor(() => expect(b.result.current.isChecking).toBe(false));
    await waitFor(() => expect(c.result.current.isChecking).toBe(false));
    expect(_h.apiGet).toHaveBeenCalledTimes(1);
  });

  it("API failure fails OPEN — user never locked out over a network blip", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockRejectedValueOnce(new Error("network down"));
    const { result } = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    await waitFor(() => expect(result.current.isChecking).toBe(false));
    // Fail-open: isClockedIn=true so gates are lifted.
    expect(result.current.isClockedIn).toBe(true);
    expect(result.current.isGated).toBe(false);
  });
});


describe("useClockInGate — opener flow", () => {
  it("non-landscape role → openJob invokes cb immediately, no dialog, no fetch", async () => {
    _h.currentUser = _admin;
    const cb = vi.fn();
    const { result } = renderHook(() => useClockInGate(_admin), { wrapper: _wrap });
    await act(async () => { await result.current.openJob("job-1", cb); });
    expect(cb).toHaveBeenCalledTimes(1);
    expect(result.current.pendingJob).toBeNull();
    expect(_h.apiGet).not.toHaveBeenCalled();
  });

  it("landscape tech + already clocked in → openJob invokes cb, no dialog", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: true });
    const cb = vi.fn();
    const { result } = renderHook(() => useClockInGate(_landscapeTech), { wrapper: _wrap });
    await act(async () => { await result.current.openJob("job-2", cb); });
    expect(cb).toHaveBeenCalledTimes(1);
    expect(result.current.pendingJob).toBeNull();
  });

  it("landscape tech + NOT clocked in → cb withheld, pendingJob set", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false });
    const cb = vi.fn();
    const { result } = renderHook(() => useClockInGate(_landscapeTech), { wrapper: _wrap });
    await act(async () => { await result.current.openJob("job-3", cb); });
    expect(cb).not.toHaveBeenCalled();
    expect(result.current.pendingJob).toEqual(expect.objectContaining({
      jobId: "job-3",
    }));
  });

  it("clockInAndProceed → POSTs punch and fires the pending cb", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false });
    _h.apiPost.mockResolvedValueOnce({ ok: true });
    // No geolocation → hook falls through with denied=true.
    Object.defineProperty(globalThis, "navigator", {
      writable: true, configurable: true, value: {},
    });
    const cb = vi.fn();
    const { result } = renderHook(() => useClockInGate(_landscapeTech), { wrapper: _wrap });
    await act(async () => { await result.current.openJob("job-4", cb); });
    await act(async () => { await result.current.clockInAndProceed(); });
    expect(_h.apiPost).toHaveBeenCalledWith(
      "/timeclock/punch",
      expect.objectContaining({
        punch_type: "in",
        source: "web",
        geo_denied: true,
      }),
    );
    expect(cb).toHaveBeenCalledTimes(1);
    expect(result.current.pendingJob).toBeNull();
  });

  it("clockInAndProceed success warms the shared status cache", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false });
    _h.apiPost.mockResolvedValueOnce({ ok: true });
    Object.defineProperty(globalThis, "navigator", {
      writable: true, configurable: true, value: {},
    });
    const gate = renderHook(() => useClockInGate(_landscapeTech), { wrapper: _wrap });
    await act(async () => { await gate.result.current.openJob("job-5", vi.fn()); });
    await act(async () => { await gate.result.current.clockInAndProceed(); });
    // Now mount a fresh status hook — it must read ``clocked_in=true``
    // from the cache without a new network round trip.
    const status = renderHook(() => useClockInStatus(), { wrapper: _wrap });
    await waitFor(() => expect(status.result.current.isChecking).toBe(false));
    expect(status.result.current.isClockedIn).toBe(true);
    // Still one GET total (the initial ``mine-status`` probe).
    expect(_h.apiGet).toHaveBeenCalledTimes(1);
  });

  it("cancel closes the dialog without calling cb", async () => {
    _h.currentUser = _landscapeTech;
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false });
    const cb = vi.fn();
    const { result } = renderHook(() => useClockInGate(_landscapeTech), { wrapper: _wrap });
    await act(async () => { await result.current.openJob("job-6", cb); });
    expect(result.current.pendingJob).not.toBeNull();
    act(() => { result.current.cancel(); });
    expect(result.current.pendingJob).toBeNull();
    expect(cb).not.toHaveBeenCalled();
  });
});
