/**
 * universal-search-hero.test.jsx — Feb-2026
 *
 * Locks the Phase BANNER-RELOCATE restyle:
 *   * ``AppLayout.jsx`` renders a full-width ``#1B1F5C`` hero strip
 *     with the ``admin-hero-banner`` + ``universal-search-hero`` +
 *     ``universal-search-pill`` nested testids.
 *   * ``GlobalSearchBar.jsx`` renders exactly ONE visible search
 *     pill (``global-search-bar-hero``) with a white background,
 *     rounded-full shape, left search icon, and right ⌘K / Ctrl+K
 *     keyboard hint.
 *   * The pre-restyle "baby-blue" shape (``#0284C7`` + ``rounded-xl``)
 *     is GONE — negative assertion locks the regression.
 *
 * Follows the AppLayout.heroBanner source-inspection convention for
 * the ``AppLayout.jsx`` assertions (full mount is heavy on vitest).
 * Full mount is still used for the ``<GlobalSearchBar>`` component
 * on its own — matches the ``GlobalSearchBar.test.jsx`` pattern.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── Shared mocks ────────────────────────────────────────────────
const useGlobalSearchResultsMock = vi.fn();
vi.mock("@/hooks/useGlobalSearchResults", () => ({
  useGlobalSearchResults: (...a) => useGlobalSearchResultsMock(...a),
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

function _mockResults(partial = {}) {
  useGlobalSearchResultsMock.mockReturnValue({
    pages: [], customers: [], jobs: [], invoices: [],
    quotes: [], leads: [], loading: false, ...partial,
  });
}


// ═══════════════════════════════════════════════════════════════════
// AppLayout source-inspection — hero wrapper + new testids
// ═══════════════════════════════════════════════════════════════════
const APP_LAYOUT_SRC = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AppLayout.jsx"),
  "utf8",
);


describe("AppLayout · universal-search hero wrapper", () => {
  it("preserves the pre-existing admin-hero-banner testid", () => {
    expect(APP_LAYOUT_SRC).toMatch(/data-testid=["']admin-hero-banner["']/);
  });

  it("renders the new universal-search-hero testid inside the strip", () => {
    expect(APP_LAYOUT_SRC).toMatch(/data-testid=["']universal-search-hero["']/);
  });

  it("renders the new universal-search-pill testid on the pill container", () => {
    expect(APP_LAYOUT_SRC).toMatch(/data-testid=["']universal-search-pill["']/);
  });

  it("carries the data-bg-color='#1B1F5C' marker for e2e visual regression", () => {
    expect(APP_LAYOUT_SRC).toMatch(/data-bg-color=["']#1B1F5C["']/);
  });

  it("hero strip background is still #1B1F5C", () => {
    const idx = APP_LAYOUT_SRC.indexOf('data-testid="admin-hero-banner"');
    expect(idx).toBeGreaterThan(-1);
    const ctx = APP_LAYOUT_SRC.slice(Math.max(0, idx - 400), idx + 400);
    expect(ctx).toMatch(/#1B1F5C/);
  });

  it("<GlobalSearchBar /> mounts inside the universal-search-pill wrapper", () => {
    const idx = APP_LAYOUT_SRC.indexOf('data-testid="universal-search-pill"');
    expect(idx).toBeGreaterThan(-1);
    const after = APP_LAYOUT_SRC.slice(idx, idx + 500);
    expect(after).toMatch(/<GlobalSearchBar\s*\/>/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// GlobalSearchBar component — white pill + Ctrl+K hint + negatives
// ═══════════════════════════════════════════════════════════════════
import GlobalSearchBar from "@/components/GlobalSearchBar";


afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useGlobalSearchResultsMock.mockReset();
});


function _renderBar() {
  return render(
    <MemoryRouter>
      <GlobalSearchBar />
    </MemoryRouter>,
  );
}


describe("<GlobalSearchBar /> · white pill restyle", () => {
  beforeEach(() => _mockResults());

  it("renders exactly ONE search input (negative: no secondary bar)", () => {
    _renderBar();
    const inputs = screen.getAllByTestId("global-search-bar-input");
    expect(inputs).toHaveLength(1);
  });

  it("pill wrapper paints WHITE (not pre-restyle brand blue)", () => {
    _renderBar();
    const hero = screen.getByTestId("global-search-bar-hero");
    // POSITIVE — white background.
    expect(hero.style.backgroundColor).toMatch(
      /rgb\(255,\s*255,\s*255\)|#fff|#FFFFFF/i,
    );
    // NEGATIVE — the pre-restyle brand-blue (#0284C7 = rgb(2,132,199))
    // must NOT be the background. Locks the "baby-blue bar gone"
    // acceptance criterion.
    expect(hero.style.backgroundColor).not.toMatch(/rgb\(2,\s*132,\s*199\)/);
  });

  it("pill is fully rounded (rounded-full), not the pre-restyle rounded-xl", () => {
    _renderBar();
    const hero = screen.getByTestId("global-search-bar-hero");
    expect(hero.className).toMatch(/rounded-full/);
    expect(hero.className).not.toMatch(/rounded-xl/);
  });

  it("renders the left search icon + the right ⌘K/Ctrl+K keyboard hint", () => {
    _renderBar();
    // Left icon is a lucide Search inside the hero wrapper.
    const hero = screen.getByTestId("global-search-bar-hero");
    expect(hero.querySelector("svg")).not.toBeNull();
    // Right kbd hint pill.
    const kbd = screen.getByTestId("global-search-bar-kbd-hint");
    expect(kbd).toBeInTheDocument();
    expect(kbd.textContent).toMatch(/\u2318K|Ctrl\+K/);
    // Hidden on <sm (640px) via the ``hidden sm:inline-flex`` pair —
    // vitest renders in jsdom w/o mediaquery evaluation, but the
    // className captures the responsive intent.
    expect(kbd.className).toMatch(/hidden/);
    expect(kbd.className).toMatch(/sm:inline-flex/);
  });

  it("preserves all pre-restyle testids on the search component", () => {
    _renderBar();
    expect(screen.getByTestId("global-search-bar-root")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-bar-hero")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-bar-input")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-bar-mobile-toggle"))
      .toBeInTheDocument();
  });

  it("typing in the input updates the query (search functionality intact)", () => {
    _renderBar();
    const input = screen.getByTestId("global-search-bar-input");
    act(() => { fireEvent.change(input, { target: { value: "pat" } }); });
    expect(input).toHaveValue("pat");
    // Hook is re-invoked each render with the new query.
    const calls = useGlobalSearchResultsMock.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1][0]).toBe("pat");
  });

  it("clear button appears once query is non-empty and clears on click", () => {
    _renderBar();
    const input = screen.getByTestId("global-search-bar-input");
    act(() => { fireEvent.change(input, { target: { value: "x" } }); });
    const clear = screen.getByTestId("global-search-bar-clear");
    expect(clear).toBeInTheDocument();
    act(() => { fireEvent.click(clear); });
    expect(input).toHaveValue("");
  });
});
