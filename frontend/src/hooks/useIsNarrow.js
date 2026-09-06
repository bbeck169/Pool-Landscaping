/**
 * useIsNarrow(breakpoint) — Phase Hygiene B · Feb-2026.
 *
 * A React hook that returns ``true`` when the viewport width is
 * strictly below ``breakpoint`` (px). Backed by the platform's
 * ``window.matchMedia`` + ``useSyncExternalStore`` so:
 *
 *   • No JS ``resize`` listener needed — ``matchMedia`` covers every
 *     browser that ever fires resize plus the ones that don't
 *     (Mobile Safari in some contexts, embedded WebViews). This is
 *     the same K76.1 regression fix that motivated the extraction.
 *   • SSR-safe — the "getServerSnapshot" branch returns ``false``
 *     so pre-hydration render always assumes the wide layout. On
 *     mount the store re-subscribes and snaps to the real value.
 *   • JSDOM-safe — vitest boots without a real matchMedia; the
 *     hook falls back to ``false`` and stays deterministic.
 *
 * Usage:
 *
 *   const isNarrow = useIsNarrow(768);
 *   if (isNarrow) return <MobileGuard />;
 *   return <DesktopSurface />;
 *
 * The equivalent media query is ``(max-width: {breakpoint - 0.02}px)``
 * — the 0.02px shim matches Tailwind's default ``md:`` breakpoint
 * (Tailwind uses ``@media (min-width: 768px)`` for ``md:``, so the
 * NARROW branch is ``max-width: 767.98px``).
 *
 * Callers must pass a stable numeric breakpoint. Passing a
 * different number on re-render will re-subscribe.
 */
import { useSyncExternalStore } from "react";


function _query(bp) {
  const px = Math.max(0, Number(bp) || 0) - 0.02;
  return `(max-width: ${px}px)`;
}


function _subscribe(bp) {
  return (cb) => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return () => {};
    }
    const mq = window.matchMedia(_query(bp));
    if (mq.addEventListener) {
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    }
    // Safari <14 fallback.
    mq.addListener(cb);
    return () => mq.removeListener(cb);
  };
}


function _getSnapshot(bp) {
  return () => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(_query(bp)).matches;
  };
}


function _getServerSnapshot() {
  // Assume wide layout on the server so hydration doesn't flash
  // the mobile fallback on desktop.
  return false;
}


export function useIsNarrow(breakpoint = 768) {
  return useSyncExternalStore(
    _subscribe(breakpoint),
    _getSnapshot(breakpoint),
    _getServerSnapshot,
  );
}


export default useIsNarrow;
