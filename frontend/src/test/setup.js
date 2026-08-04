import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup, configure } from "@testing-library/react";

// Phase 41.1 (Feb-2026) — Under vitest's parallel worker pool, forks
// compete for CPU during full-suite runs. RTL's default 1000ms
// `waitFor` timeout is too tight for CPU-starved async renders and
// surfaces as sporadic "Unable to find element" failures. Bumping
// to 5000ms is standard practice for CI-under-load; individual tests
// with genuine hangs will still fail within their per-test timeout.
configure({ asyncUtilTimeout: 5000 });

// Every test starts fresh — DOM, spies, cache.
//
// Phase 41.1 (Feb-2026) — under vitest's parallel worker model, multiple
// test files share the same jsdom `document`. Radix Dialog / Popover
// portals mount directly into `document.body` and are NOT removed by
// `cleanup()` (RTL only unmounts the render-container tree). A modal
// left open at the end of one test leaks its portal into the next
// test's `findByTestId`, which surfaces as sporadic "Unable to find
// element" errors that pass in isolation and fail under load.
// Nuking `document.body.innerHTML` after every test kills stray
// portals deterministically.
afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

// jsdom stub — TipTap needs these.
if (!window.matchMedia) {
  window.matchMedia = () => ({
    matches: false, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  });
}

// jsdom stub — cmdk (used by shadcn Command / Combobox) requires
// ResizeObserver; JSDOM doesn't ship one. Minimal noop implementation
// keeps the components mountable in tests.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  class RO {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = RO;
  globalThis.ResizeObserver = RO;
}
