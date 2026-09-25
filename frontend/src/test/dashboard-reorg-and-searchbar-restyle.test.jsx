/**
 * Feb-2026 · Dashboard reorg + GlobalSearchBar restyle · source-
 * inspection contract tests.
 *
 * Locks the top-of-page section order (Mass Messaging → Global
 * Search Bar → Revenue Insights → DashboardActionCards → topline
 * tiles) shipped in the Feb-2026 Dashboard reorg, plus the
 * GlobalSearchBar high-contrast blue-navy standard (solid
 * ``colors.inputBorder`` border, ``colors.nav.bg`` input text,
 * ``placeholder:text-[#1B1F5C]`` placeholder color).
 *
 * Source-lint style — no full-mount / DOM-render (matches the
 * ``k70a-tile-theming.test.jsx`` convention).  Any future accidental
 * re-order or theme-token drift trips a red bar in CI before it
 * merges.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const DASH_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/Dashboard.jsx"),
  "utf8",
);
const SEARCH_BAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/dashboard/GlobalSearchBar.jsx"),
  "utf8",
);


describe("Dashboard reorg — section order", () => {
  it("Test 1 · MassMessagingCard appears BEFORE GlobalSearchBar in render tree", () => {
    const mmIdx = DASH_SRC.indexOf("<MassMessagingCard />");
    const gsIdx = DASH_SRC.indexOf("<GlobalSearchBar />");
    expect(mmIdx).toBeGreaterThan(-1);
    expect(gsIdx).toBeGreaterThan(-1);
    expect(mmIdx).toBeLessThan(gsIdx);
  });

  it("Test 2 · GlobalSearchBar appears BEFORE the revenue-tiles-section", () => {
    const gsIdx = DASH_SRC.indexOf("<GlobalSearchBar />");
    const revIdx = DASH_SRC.indexOf('data-testid="revenue-tiles-section"');
    expect(gsIdx).toBeGreaterThan(-1);
    expect(revIdx).toBeGreaterThan(-1);
    expect(gsIdx).toBeLessThan(revIdx);
  });

  it("Test 6 · full reorder chain: MassMessagingCard → GlobalSearchBar → revenue-tiles-section", () => {
    // Single indexOf-chain regression guard — same pattern as
    // ``k70a-tile-theming.test.jsx`` uses for section scoping.
    // A future refactor that shuffles ANY of these three back
    // out of order trips this assertion.
    const mmIdx = DASH_SRC.indexOf("<MassMessagingCard />");
    const gsIdx = DASH_SRC.indexOf("<GlobalSearchBar />");
    const revIdx = DASH_SRC.indexOf('data-testid="revenue-tiles-section"');
    expect(mmIdx).toBeGreaterThan(-1);
    expect(gsIdx).toBeGreaterThan(-1);
    expect(revIdx).toBeGreaterThan(-1);
    expect(mmIdx).toBeLessThan(gsIdx);
    expect(gsIdx).toBeLessThan(revIdx);
  });
});


describe("GlobalSearchBar — high-contrast blue-navy restyle", () => {
  it("Test 3 · wrapper inline style references colors.inputBorder", () => {
    // The wrapper's border string uses ``colors.inputBorder`` (the
    // #3B82F6 blue token), not the muted ``colors.border``.
    expect(SEARCH_BAR_SRC).toMatch(/border:\s*`1px solid \$\{colors\.inputBorder\}`/);
    // Negative guard — the OLD ``colors.border`` reference must be
    // gone from the wrapper.  Grep is scoped to the wrapper block
    // since the panel below the input still uses ``colors.border``
    // for its own outline.
    const wrapperStart = SEARCH_BAR_SRC.indexOf("className=\"flex items-center gap-2 rounded-xl");
    const wrapperEnd = SEARCH_BAR_SRC.indexOf(">", wrapperStart);
    const wrapperBlock = SEARCH_BAR_SRC.slice(wrapperStart, wrapperEnd);
    expect(wrapperBlock).not.toMatch(/colors\.border/);
  });

  it("Test 4 · input inline style references colors.nav.bg", () => {
    // The <input> uses ``colors.nav.bg`` (#1B1F5C) for its text
    // color, replacing the pre-reorg ``colors.onSurface``.
    expect(SEARCH_BAR_SRC).toMatch(/style=\{\{\s*color:\s*colors\.nav\.bg\s*\}\}/);
  });

  it("Test 5 · input className includes placeholder:text-[#1B1F5C]", () => {
    // Tailwind's inline placeholder-color arbitrary variant.
    // Locked verbatim per the reorg spec so the placeholder text
    // renders at the same navy hue as the typed text.
    expect(SEARCH_BAR_SRC).toMatch(/placeholder:text-\[#1B1F5C\]/);
  });
});
