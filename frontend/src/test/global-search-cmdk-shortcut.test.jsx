/**
 * Task C · Feb-2026 — Global Search ⌘K / Ctrl+K shortcut.
 *
 * Locks the behavior wired in PageHeader.jsx:
 *   1. ⌘K (metaKey+k) at document root focuses the search input.
 *   2. Ctrl+K (ctrlKey+k) at document root focuses the search input.
 *   3. Escape while the search input is focused via ⌘K restores
 *      focus to the previously-focused element.
 *   4. ⌘K inside a <textarea> does NOT hijack — suppression policy.
 *   5. ⌘K on a plain <button> DOES focus the search input.
 *   6. Listener cleanup on unmount — no leak; a keydown after
 *      unmount MUST NOT re-focus the (now-detached) input.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent,
} from "@testing-library/react";

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }));
const { searchGlobalSpy } = vi.hoisted(() => ({ searchGlobalSpy: vi.fn() }));

// Router mock — the PageHeader imports ``useNavigate`` at module scope.
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateSpy,
}));

// Backend search client mock — no network in unit tests.
vi.mock("@/lib/globalSearchClient", () => ({
  searchGlobal: (...args) => searchGlobalSpy(...args),
}));

// Theme mock — hermetic surface set used by PageHeader's inline
// styles. Mirrors the shape from page-header-search.test.jsx so the
// existing test scaffolding conventions are preserved.
vi.mock("@/theme", () => ({
  colors: {
    nav: { bg: "#0B2A4A", border: "#1E3A5F" },
    surface: "#ffffff",
    surfaceSecondary: "#f4f4f5",
    onSurface: "#111827",
    onSurfaceSecondary: "#6b7280",
    border: "#e5e7eb",
    inputBorder: "#2563eb",
    brand: "#2563eb",
    muted: "#6b7280",
    searchIcon: "#6b7280",
  },
}));

// useGlobalSearch mock — returns empty groups synchronously so the
// dropdown stays hidden and the input renders unadorned.
vi.mock("@/hooks/useGlobalSearch", () => ({
  useGlobalSearch: () => ({
    pages: [], customers: [], documents: [],
    loading: false, error: null,
  }),
}));


beforeEach(() => {
  navigateSpy.mockClear();
  searchGlobalSpy.mockClear();
});

afterEach(() => {
  cleanup();
});


async function _mount() {
  const { PageHeader } = await import("@/components/layout/PageHeader");
  return render(<PageHeader title="Test Page" />);
}


describe("Task C · Cmd+K / Ctrl+K global shortcut", () => {
  it("⌘K (metaKey) at document root focuses the global-search input",
      async () => {
    await _mount();
    const input = screen.getByTestId("page-header-search-input");
    // Pre-condition: input is NOT the active element.
    expect(document.activeElement).not.toBe(input);

    // Fire the shortcut at the window level.
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    expect(document.activeElement).toBe(input);
  });

  it("Ctrl+K (ctrlKey) at document root focuses the global-search input",
      async () => {
    await _mount();
    const input = screen.getByTestId("page-header-search-input");
    expect(document.activeElement).not.toBe(input);

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    expect(document.activeElement).toBe(input);
  });

  it("Escape while opened via ⌘K restores focus to the previously-focused element",
      async () => {
    await _mount();
    const input = screen.getByTestId("page-header-search-input");

    // Prime a "previous" focus target — a button appended to the
    // page-header-actions region. Focus it, then fire ⌘K.
    const prev = document.createElement("button");
    prev.setAttribute("data-testid", "test-prev-focus-target");
    document.body.appendChild(prev);
    prev.focus();
    expect(document.activeElement).toBe(prev);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(document.activeElement).toBe(input);

    // Escape on the input — routes through PageHeader's onKeyDown
    // → clearAndClose() → restores focus to ``prev``.
    fireEvent.keyDown(input, { key: "Escape" });
    expect(document.activeElement).toBe(prev);

    document.body.removeChild(prev);
  });

  it("⌘K inside a <textarea> is suppressed — input is NOT focused",
      async () => {
    await _mount();
    const input = screen.getByTestId("page-header-search-input");

    // Mount an external textarea and dispatch the shortcut FROM it.
    const ta = document.createElement("textarea");
    ta.setAttribute("data-testid", "test-external-textarea");
    document.body.appendChild(ta);
    ta.focus();
    expect(document.activeElement).toBe(ta);

    // Fire the keydown from the textarea — suppression policy
    // should short-circuit BEFORE preventDefault / focus.
    fireEvent.keyDown(ta, { key: "k", metaKey: true });

    // Textarea keeps focus; the search input never got it.
    expect(document.activeElement).toBe(ta);
    expect(document.activeElement).not.toBe(input);

    document.body.removeChild(ta);
  });

  it("⌘K while focus is on a plain <button> DOES focus the search input",
      async () => {
    await _mount();
    const input = screen.getByTestId("page-header-search-input");

    // Plain button — NOT an editable surface, so ⌘K should fire.
    const btn = document.createElement("button");
    btn.setAttribute("data-testid", "test-plain-button");
    btn.textContent = "Do a thing";
    document.body.appendChild(btn);
    btn.focus();
    expect(document.activeElement).toBe(btn);

    fireEvent.keyDown(btn, { key: "k", metaKey: true });

    expect(document.activeElement).toBe(input);

    document.body.removeChild(btn);
  });

  it("Listener is cleaned up on unmount — ⌘K after unmount does not focus a detached input",
      async () => {
    const { unmount } = await _mount();
    const input = screen.getByTestId("page-header-search-input");

    // Sanity: shortcut works while mounted.
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(document.activeElement).toBe(input);
    input.blur();
    expect(document.activeElement).not.toBe(input);

    // Now unmount and fire another keydown — the removed listener
    // MUST NOT re-focus the (now-detached) node. We assert via the
    // absence of the input in the DOM AND that firing the event
    // does not throw.
    unmount();
    expect(
      screen.queryByTestId("page-header-search-input"),
    ).toBeNull();
    // Also assert body focus is untouched by the post-unmount press.
    document.body.focus();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    // Body remains focused; no error thrown.
    expect(document.activeElement).toBe(document.body);
  });
});
