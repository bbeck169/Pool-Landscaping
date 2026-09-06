/**
 * Breakpoint hooks — Phase Hygiene B / Phase I1.5.a bonus · Feb-2026.
 *
 * Three hooks share the same ``window.matchMedia`` +
 * ``useSyncExternalStore`` substrate so any caller pays exactly
 * one media-query subscription per breakpoint:
 *
 *   • ``useIsNarrow(bp)``   — true when width < bp
 *   • ``useIsWide(bp)``     — true when width >= bp
 *   • ``useBreakpoint()``   — current Tailwind label:
 *                              "base" | "sm" | "md" | "lg" | "xl" | "2xl"
 *
 * All three are SSR-safe (return the wide-layout defaults on the
 * server) and JSDOM-safe (fall back to false / "base" when
 * ``window.matchMedia`` isn't installed by the test harness).
 *
 * The equivalent media query for the narrow branch is
 * ``(max-width: {bp - 0.02}px)`` — the 0.02px shim matches
 * Tailwind's default ``md:`` breakpoint (Tailwind uses
 * ``@media (min-width: 768px)`` for ``md:``, so the NARROW branch
 * is ``max-width: 767.98px``).
 *
 * ``useBreakpoint()`` uses Tailwind's canonical breakpoint pixel
 * anchors (locked in ``use-breakpoint-hooks.test.jsx``):
 *
 *   sm  ≥ 640px
 *   md  ≥ 768px
 *   lg  ≥ 1024px
 *   xl  ≥ 1280px
 *   2xl ≥ 1536px
 *
 * Any width below ``sm`` returns ``"base"``.
 */
import { useSyncExternalStore } from "react";


function _narrowQuery(bp) {
  const px = Math.max(0, Number(bp) || 0) - 0.02;
  return `(max-width: ${px}px)`;
}


function _wideQuery(bp) {
  const px = Math.max(0, Number(bp) || 0);
  return `(min-width: ${px}px)`;
}


function _subscribeQuery(query) {
  return (cb) => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return () => {};
    }
    const mq = window.matchMedia(query);
    if (mq.addEventListener) {
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    }
    // Safari <14 fallback.
    mq.addListener(cb);
    return () => mq.removeListener(cb);
  };
}


function _matchesQuery(query) {
  return () => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(query).matches;
  };
}


function _falseServer() {
  // Assume wide layout on the server so hydration doesn't flash
  // the mobile fallback on desktop.
  return false;
}


export function useIsNarrow(breakpoint = 768) {
  const q = _narrowQuery(breakpoint);
  return useSyncExternalStore(
    _subscribeQuery(q),
    _matchesQuery(q),
    _falseServer,
  );
}


export function useIsWide(breakpoint = 768) {
  const q = _wideQuery(breakpoint);
  return useSyncExternalStore(
    _subscribeQuery(q),
    _matchesQuery(q),
    _falseServer,
  );
}


// Tailwind canonical anchors — do not reorder without updating the
// contract test.
const _TAILWIND_STEPS = [
  ["2xl", 1536],
  ["xl", 1280],
  ["lg", 1024],
  ["md", 768],
  ["sm", 640],
];


function _subscribeAny(cb) {
  if (typeof window === "undefined" || !window.matchMedia) {
    return () => {};
  }
  const cleanups = _TAILWIND_STEPS.map(([, px]) => {
    const mq = window.matchMedia(`(min-width: ${px}px)`);
    if (mq.addEventListener) {
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    }
    mq.addListener(cb);
    return () => mq.removeListener(cb);
  });
  return () => cleanups.forEach((fn) => fn());
}


function _readBreakpoint() {
  if (typeof window === "undefined" || !window.matchMedia) return "base";
  for (const [label, px] of _TAILWIND_STEPS) {
    if (window.matchMedia(`(min-width: ${px}px)`).matches) return label;
  }
  return "base";
}


function _serverBreakpoint() {
  // Wide-layout assumption for SSR parity with useIsNarrow /
  // useIsWide defaults.
  return "lg";
}


export function useBreakpoint() {
  return useSyncExternalStore(
    _subscribeAny,
    _readBreakpoint,
    _serverBreakpoint,
  );
}


export default useIsNarrow;
