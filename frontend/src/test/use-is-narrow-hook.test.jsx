/**
 * useIsNarrow — contract test.  Phase Hygiene B · Feb-2026.
 *
 * Locks the four documented behaviours:
 *   1. Returns ``true`` when the media query matches (narrow viewport).
 *   2. Returns ``false`` when the media query doesn't match (wide).
 *   3. Falls back to ``false`` when ``window.matchMedia`` is absent
 *      (SSR / stripped-down jsdom shims).
 *   4. Uses ``(max-width: {bp - 0.02}px)`` — matches Tailwind's ``md:``
 *      breakpoint semantics.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import useIsNarrow from "@/hooks/useIsNarrow";


function _installMatchMedia({ matches = false } = {}) {
  const listeners = new Set();
  const mm = vi.fn((q) => ({
    media: q,
    matches,
    addEventListener: (_e, cb) => listeners.add(cb),
    removeEventListener: (_e, cb) => listeners.delete(cb),
    addListener: (cb) => listeners.add(cb),
    removeListener: (cb) => listeners.delete(cb),
    dispatchEvent: () => true,
    onchange: null,
  }));
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: mm,
  });
  return mm;
}


describe("useIsNarrow(breakpoint)", () => {
  let origMM;

  beforeEach(() => {
    origMM = window.matchMedia;
  });

  afterEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: origMM,
    });
  });

  it("returns true when the media query matches", () => {
    _installMatchMedia({ matches: true });
    const { result } = renderHook(() => useIsNarrow(768));
    expect(result.current).toBe(true);
  });

  it("returns false when the media query doesn't match", () => {
    _installMatchMedia({ matches: false });
    const { result } = renderHook(() => useIsNarrow(768));
    expect(result.current).toBe(false);
  });

  it("falls back to false when window.matchMedia is absent", () => {
    // Remove matchMedia altogether.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: undefined,
    });
    const { result } = renderHook(() => useIsNarrow(768));
    expect(result.current).toBe(false);
  });

  it("passes a ``(max-width: {bp-0.02}px)`` query to matchMedia (Tailwind md: parity)", () => {
    const mm = _installMatchMedia({ matches: false });
    renderHook(() => useIsNarrow(768));
    // ``768 - 0.02 = 767.98`` — the exact Tailwind ``md:`` breakpoint
    // shim. Any call to matchMedia must use this query.
    const calls = mm.mock.calls.map((c) => c[0]);
    expect(calls.some((q) => q === "(max-width: 767.98px)")).toBe(true);
  });
});
