import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Every test starts fresh — DOM, spies, cache.
afterEach(() => {
  cleanup();
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
