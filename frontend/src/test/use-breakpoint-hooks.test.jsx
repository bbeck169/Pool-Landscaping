/**
 * Breakpoint hooks — contract test.  Phase I1.5.a bonus · Feb-2026.
 * (Renamed from ``use-is-narrow-hook.test.jsx``.)
 *
 * Locks the documented behaviour for all three sibling hooks
 * (``useIsNarrow`` · ``useIsWide`` · ``useBreakpoint``):
 *
 *   1. ``useIsNarrow`` — true/false based on ``(max-width: bp-0.02)``.
 *   2. ``useIsWide``   — true/false based on ``(min-width: bp)``.
 *   3. ``useBreakpoint`` — Tailwind label:
 *      "base" | "sm" | "md" | "lg" | "xl" | "2xl", falls back to
 *      "base" when matchMedia is absent.
 *   4. All three fall back safely when ``window.matchMedia`` is
 *      absent (SSR / stripped jsdom).
 *   5. Query shape parity with Tailwind (max-width: {bp-0.02}px for
 *      narrow; min-width: {bp}px for wide).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import useIsNarrow, {
  useIsNarrow as useIsNarrowNamed,
  useIsWide,
  useBreakpoint,
} from "@/hooks/useIsNarrow";


function _installMatchMedia(resolver) {
  const listeners = new Set();
  const mm = vi.fn((q) => ({
    media: q,
    matches: typeof resolver === "function" ? resolver(q) : !!resolver,
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


// ── useIsNarrow ──────────────────────────────────────────────────
describe("useIsNarrow(breakpoint)", () => {
  let origMM;
  beforeEach(() => { origMM = window.matchMedia; });
  afterEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true, configurable: true, value: origMM,
    });
  });

  it("has a default export equal to the named export", () => {
    expect(useIsNarrow).toBe(useIsNarrowNamed);
  });

  it("returns true when the media query matches", () => {
    _installMatchMedia(true);
    const { result } = renderHook(() => useIsNarrow(768));
    expect(result.current).toBe(true);
  });

  it("returns false when the media query doesn't match", () => {
    _installMatchMedia(false);
    const { result } = renderHook(() => useIsNarrow(768));
    expect(result.current).toBe(false);
  });

  it("falls back to false when window.matchMedia is absent", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true, configurable: true, value: undefined,
    });
    const { result } = renderHook(() => useIsNarrow(768));
    expect(result.current).toBe(false);
  });

  it("passes ``(max-width: {bp-0.02}px)`` (Tailwind md: parity)", () => {
    const mm = _installMatchMedia(false);
    renderHook(() => useIsNarrow(768));
    const calls = mm.mock.calls.map((c) => c[0]);
    expect(calls.some((q) => q === "(max-width: 767.98px)")).toBe(true);
  });
});


// ── useIsWide ────────────────────────────────────────────────────
describe("useIsWide(breakpoint)", () => {
  let origMM;
  beforeEach(() => { origMM = window.matchMedia; });
  afterEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true, configurable: true, value: origMM,
    });
  });

  it("returns true when the min-width query matches", () => {
    _installMatchMedia(true);
    const { result } = renderHook(() => useIsWide(768));
    expect(result.current).toBe(true);
  });

  it("returns false when the min-width query doesn't match", () => {
    _installMatchMedia(false);
    const { result } = renderHook(() => useIsWide(768));
    expect(result.current).toBe(false);
  });

  it("falls back to false when matchMedia is absent", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true, configurable: true, value: undefined,
    });
    const { result } = renderHook(() => useIsWide(1024));
    expect(result.current).toBe(false);
  });

  it("passes ``(min-width: {bp}px)`` (Tailwind md: parity)", () => {
    const mm = _installMatchMedia(false);
    renderHook(() => useIsWide(768));
    const calls = mm.mock.calls.map((c) => c[0]);
    expect(calls.some((q) => q === "(min-width: 768px)")).toBe(true);
  });

  it("is the complement of useIsNarrow at the same breakpoint", () => {
    // Simulate a wide viewport: min-width queries match, max-width
    // queries don't.
    _installMatchMedia((q) => q.startsWith("(min-width:"));
    const { result: wide } = renderHook(() => useIsWide(768));
    const { result: narrow } = renderHook(() => useIsNarrow(768));
    expect(wide.current).toBe(true);
    expect(narrow.current).toBe(false);
  });
});


// ── useBreakpoint ────────────────────────────────────────────────
describe("useBreakpoint()", () => {
  let origMM;
  beforeEach(() => { origMM = window.matchMedia; });
  afterEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true, configurable: true, value: origMM,
    });
  });

  const _at = (widthPx) =>
    (q) => {
      const m = q.match(/min-width:\s*(\d+)px/);
      if (!m) return false;
      return widthPx >= Number(m[1]);
    };

  it("returns 'base' below 640px", () => {
    _installMatchMedia(_at(500));
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("base");
  });

  it("returns 'sm' at 640-767", () => {
    _installMatchMedia(_at(700));
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("sm");
  });

  it("returns 'md' at 768-1023", () => {
    _installMatchMedia(_at(800));
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("md");
  });

  it("returns 'lg' at 1024-1279", () => {
    _installMatchMedia(_at(1100));
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("lg");
  });

  it("returns 'xl' at 1280-1535", () => {
    _installMatchMedia(_at(1400));
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("xl");
  });

  it("returns '2xl' at 1536+", () => {
    _installMatchMedia(_at(1700));
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("2xl");
  });

  it("falls back to 'base' when matchMedia is absent", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true, configurable: true, value: undefined,
    });
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("base");
  });

  it("subscribes to all five Tailwind anchors on mount", () => {
    const mm = _installMatchMedia(_at(1400));
    renderHook(() => useBreakpoint());
    const calls = mm.mock.calls.map((c) => c[0]);
    for (const px of [640, 768, 1024, 1280, 1536]) {
      expect(calls.some((q) => q === `(min-width: ${px}px)`)).toBe(true);
    }
  });
});
