/**
 * N4' · Feb-2026 — ``useGlobalSearch`` hook regression suite.
 *
 * Covers the hook's contract in isolation from the ``<PageHeader>``
 * component:
 *
 *   1. Returns ``pages`` synchronously from the local navIndex
 *      (no backend call needed on the sync path).
 *   2. Skips the backend fetch entirely when ``query.trim().length < 2``.
 *   3. Debounces backend fetch by 300 ms — a keystroke at t=0
 *      followed by another at t=200 fires ONE fetch (for the
 *      second value) at t=500.
 *   4. Aborts stale requests — a superseded keystroke's fetch
 *      call receives ``controller.abort()`` before the new fetch
 *      is scheduled.
 *   5. On API error, ``error`` is populated AND prior successful
 *      ``customers`` / ``documents`` are preserved (no flash-empty).
 *   6. On subsequent success after error, ``error`` clears back to
 *      ``null``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";


// Local navIndex mock — 1 page match for any query beginning with
// "i" so the sync branch is testable without touching the real
// adminNav.js fixture.
vi.mock("@/lib/navIndex", () => ({
  searchNavIndex: (q) => {
    if (!q) return [];
    if (String(q).toLowerCase().startsWith("i")) {
      return [{ path: "/invoices", title: "Invoices" }];
    }
    return [];
  },
}));

// Backend client mock — captured spy so per-test behaviour can
// be tuned (return, throw, hang, etc.). Every call receives
// ``(query, { signal, limit })``.
const searchGlobalSpy = vi.fn();
vi.mock("@/lib/globalSearchClient", () => ({
  searchGlobal: (...args) => searchGlobalSpy(...args),
}));


let useGlobalSearch;

beforeEach(async () => {
  vi.useFakeTimers();
  searchGlobalSpy.mockReset();
  ({ useGlobalSearch } = await import("@/hooks/useGlobalSearch"));
});

afterEach(() => {
  vi.useRealTimers();
});


describe("useGlobalSearch", () => {
  it("returns pages synchronously from navIndex on first render", () => {
    const { result } = renderHook(() => useGlobalSearch("invoi"));
    expect(result.current.pages).toEqual([
      { path: "/invoices", title: "Invoices" },
    ]);
    expect(searchGlobalSpy).not.toHaveBeenCalled();
  });

  it("skips the backend fetch when query is under 2 chars", async () => {
    const { rerender } = renderHook(({ q }) => useGlobalSearch(q),
                                       { initialProps: { q: "" } });
    // Simulate 1 keystroke.
    rerender({ q: "a" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(searchGlobalSpy).not.toHaveBeenCalled();
  });

  it("debounces the backend fetch by 300ms", async () => {
    searchGlobalSpy.mockResolvedValue({ customers: [], documents: [] });
    const { rerender } = renderHook(({ q }) => useGlobalSearch(q),
                                       { initialProps: { q: "" } });
    rerender({ q: "sm" });
    // Before the timer elapses, no call yet.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(searchGlobalSpy).not.toHaveBeenCalled();
    // After the full 300 ms window.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(searchGlobalSpy).toHaveBeenCalledTimes(1);
    expect(searchGlobalSpy.mock.calls[0][0]).toBe("sm");
  });

  it("aborts stale requests when a newer keystroke supersedes", async () => {
    // Capture the AbortSignals passed to each call to assert on abort state.
    const signals = [];
    searchGlobalSpy.mockImplementation((_q, { signal }) => {
      signals.push(signal);
      return new Promise(() => { /* never resolves */ });
    });
    const { rerender } = renderHook(({ q }) => useGlobalSearch(q),
                                       { initialProps: { q: "sm" } });
    // Fire the first debounced fetch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    expect(searchGlobalSpy).toHaveBeenCalledTimes(1);
    expect(signals[0].aborted).toBe(false);
    // New keystroke arrives — the pending in-flight fetch's signal
    // must abort before the next debounce elapses.
    rerender({ q: "smi" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(signals[0].aborted).toBe(true);
    // The new fetch fires 300 ms later.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    expect(searchGlobalSpy).toHaveBeenCalledTimes(2);
    expect(searchGlobalSpy.mock.calls[1][0]).toBe("smi");
  });

  it("preserves prior results and exposes error on API failure", async () => {
    // Testing-library's ``waitFor`` uses real setTimeout internally
    // for its polling loop, which hangs under fake timers. Switch
    // to real timers for this test — 300 ms debounce is fine.
    vi.useRealTimers();
    searchGlobalSpy.mockResolvedValueOnce({
      customers: [{ id: "c1", name: "Alpha" }],
      documents: [],
    });
    const { result, rerender } = renderHook(({ q }) => useGlobalSearch(q),
                                               { initialProps: { q: "al" } });
    await waitFor(() => {
      expect(result.current.customers).toEqual([{ id: "c1", name: "Alpha" }]);
    });
    // 2nd keystroke → backend fails; prior customer array is preserved.
    searchGlobalSpy.mockRejectedValueOnce(new Error("500 backend"));
    rerender({ q: "alp" });
    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
    // Preserved from before the failure.
    expect(result.current.customers).toEqual([{ id: "c1", name: "Alpha" }]);
  });

  it("clears the error on the next successful fetch", async () => {
    // See the note above — real timers so ``waitFor`` polls.
    vi.useRealTimers();
    searchGlobalSpy.mockRejectedValueOnce(new Error("boom"));
    const { result, rerender } = renderHook(({ q }) => useGlobalSearch(q),
                                               { initialProps: { q: "sm" } });
    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
    searchGlobalSpy.mockResolvedValueOnce({
      customers: [{ id: "c2", name: "Beta" }],
      documents: [],
    });
    rerender({ q: "smi" });
    await waitFor(() => {
      expect(result.current.customers).toEqual([{ id: "c2", name: "Beta" }]);
    });
    expect(result.current.error).toBeNull();
  });
});
