/**
 * Feb-2026 · Customers List Navy Hero
 * ────────────────────────────────────────────────────────────────
 * Regression coverage for the two-row navy hero strip on
 * ``CustomersList.jsx``.
 *
 * Layout contract:
 *   • NavyFilterBar remains the container (Task E migration
 *     stays intact — no fork).
 *   • Two direct-child ``<div>`` wrappers with ``w-full`` force
 *     the flex-wrap parent to break between them:
 *       - Top row  ``data-testid="customers-filters-row-top"``:
 *         Search (full-width via NavyFilterBar.Search's own
 *         ``flex-1``), All / Unscheduled / Waitlist chips,
 *         Sort dropdown.
 *       - Bottom row ``data-testid="customers-filters-row-bottom"``:
 *         Portal, Missing Card, Tags, More Filters, City.
 *   • Missing Card + More Filters buttons swap
 *     ``colors.surfaceSecondary / onSurfaceSecondary / border``
 *     for ``colors.nav.bg / nav.fg / nav.border`` on their
 *     inactive state so they blend into the strip.
 *   • Cohort Tabs (Active | Inactive | Muted) stay in their
 *     own surface container ABOVE the NavyFilterBar — NOT
 *     inside it.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname,
  "../pages/customers/CustomersList.jsx");
const pageSrc = readFileSync(PAGE_PATH, "utf8");


describe("CustomersList · navy hero two-row layout", () => {
  it("wraps the filter surface in NavyFilterBar (unchanged)", () => {
    expect(pageSrc).toMatch(
      /<NavyFilterBar[\s\S]*?data-testid="customers-filters"/);
    expect(pageSrc).toContain("</NavyFilterBar>");
  });

  it("emits a full-width top row with search + chips + sort", () => {
    const topIdx = pageSrc.indexOf(
      'data-testid="customers-filters-row-top"');
    expect(topIdx).toBeGreaterThan(-1);
    // Take a bounded forward slice to the bottom-row testid so
    // we know we're only inspecting the top-row block.
    const bottomIdx = pageSrc.indexOf(
      'data-testid="customers-filters-row-bottom"', topIdx);
    expect(bottomIdx).toBeGreaterThan(topIdx);
    const topBlock = pageSrc.slice(topIdx, bottomIdx);

    // Row container carries w-full so flex-wrap parent breaks
    // between top + bottom rows.
    const openIdx = pageSrc.lastIndexOf("<div", topIdx);
    const rowOpen = pageSrc.slice(openIdx, topIdx + 60);
    expect(rowOpen).toMatch(/w-full/);
    expect(rowOpen).toMatch(/flex[- ]row/);

    // Top-row contents.
    expect(topBlock).toContain('data-testid="customers-search"');
    // Chips are rendered from an array with template testid so
    // assert on the k: values that drive the testid + the label
    // text used on-screen.
    expect(topBlock).toMatch(/k:\s*"all"[\s\S]*label:\s*"All"/);
    expect(topBlock).toMatch(/k:\s*"unscheduled"[\s\S]*label:\s*"Unscheduled"/);
    expect(topBlock).toMatch(/k:\s*"waitlist"[\s\S]*label:\s*"Waitlist"/);
    // Runtime testid template — belt-and-suspenders.
    expect(topBlock).toMatch(/`customers-scope-\$\{s\.k\}`/);
    expect(topBlock).toContain('data-testid="customers-filter-sort"');
  });

  it("emits a full-width bottom row with portal + missing card + tags + more filters + city", () => {
    const bottomIdx = pageSrc.indexOf(
      'data-testid="customers-filters-row-bottom"');
    expect(bottomIdx).toBeGreaterThan(-1);
    // Row container carries w-full so it breaks onto its own line.
    const openIdx = pageSrc.lastIndexOf("<div", bottomIdx);
    const rowOpen = pageSrc.slice(openIdx, bottomIdx + 60);
    expect(rowOpen).toMatch(/w-full/);
    expect(rowOpen).toMatch(/flex[- ]row/);

    // Forward slice from the bottom row testid to the closing
    // </NavyFilterBar> covers the row body verbatim.
    const closeIdx = pageSrc.indexOf("</NavyFilterBar>", bottomIdx);
    expect(closeIdx).toBeGreaterThan(bottomIdx);
    const rowBlock = pageSrc.slice(bottomIdx, closeIdx);

    // All 5 bottom-row filters must appear in the block.
    expect(rowBlock).toContain(
      'data-testid="customers-filter-portal-status"');
    expect(rowBlock).toContain(
      'data-testid="customers-filter-missing-card"');
    expect(rowBlock).toContain('data-testid="customers-filter-tag"');
    expect(rowBlock).toContain(
      'data-testid="customers-more-filters-dropdown"');
    expect(rowBlock).toContain(
      'data-testid="customers-filter-city"');
  });

  it("Missing Card + More Filters buttons blend into navy (inactive state)", () => {
    // Missing Card — the inactive style pulls from colors.nav.bg
    // + colors.nav.fg + colors.nav.border.
    const mcIdx = pageSrc.indexOf(
      'data-testid="customers-filter-missing-card"');
    expect(mcIdx).toBeGreaterThan(-1);
    // Slice forward through the style={{ }} block; the inactive
    // branch ("missingCardOnly ? … : …") holds the tokens.
    const mcSlice = pageSrc.slice(mcIdx, mcIdx + 800);
    expect(mcSlice).toMatch(/missingCardOnly\s*\?\s*"#FEF3C7"\s*:\s*colors\.nav\.bg/);
    expect(mcSlice).toMatch(/missingCardOnly\s*\?\s*"#92400E"\s*:\s*colors\.nav\.fg/);
    expect(mcSlice).toMatch(/missingCardOnly\s*\?\s*"#FDE68A"\s*:\s*colors\.nav\.border/);

    // Explicit anti-regression — the button's INACTIVE token
    // must NOT reference surfaceSecondary / onSurfaceSecondary /
    // the flat border token.  We assert on the exact inactive
    // slots so an unrelated future surfaceSecondary elsewhere
    // in the file can't false-positive.
    expect(mcSlice).not.toMatch(/:\s*colors\.surfaceSecondary/);
    expect(mcSlice).not.toMatch(/:\s*colors\.onSurfaceSecondary/);

    // More Filters — same swap on the inactive state.
    const mfIdx = pageSrc.indexOf(
      'data-testid="customers-more-filters-dropdown"');
    expect(mfIdx).toBeGreaterThan(-1);
    // The style={{ … }} block lives BELOW the testid attribute on
    // the <button> — slice forward.
    const mfSlice = pageSrc.slice(mfIdx, mfIdx + 800);
    expect(mfSlice).toMatch(/active\s*>\s*0\s*\?\s*"#DBEAFE"\s*:\s*colors\.nav\.bg/);
    expect(mfSlice).toMatch(/active\s*>\s*0\s*\?\s*"#1E3A8A"\s*:\s*colors\.nav\.fg/);
    expect(mfSlice).toMatch(/active\s*>\s*0\s*\?\s*"#93C5FD"\s*:\s*colors\.nav\.border/);
  });

  it("Search input keeps its white-card / blue-border styling", () => {
    // NavyFilterBar.Search paints the input with
    // ``colors.surface`` bg + permanent ``colors.inputBorder``
    // border via the shared primitive — asserting the primitive
    // still resolves those tokens is a belt-and-suspenders guard
    // against a future accidental navy swap on the search input.
    const NAVY_BAR = readFileSync(
      resolve(__dirname, "../components/ui/NavyFilterBar.jsx"),
      "utf8");
    const searchIdx = NAVY_BAR.indexOf(
      "NavyFilterBar.Search = function");
    expect(searchIdx).toBeGreaterThan(-1);
    const searchBlock = NAVY_BAR.slice(searchIdx, searchIdx + 2000);
    expect(searchBlock).toMatch(
      /backgroundColor:\s*colors\.surface/);
    expect(searchBlock).toMatch(
      /border:\s*`1px solid \$\{colors\.inputBorder\}`/);
  });

  it("Cohort tabs stay OUTSIDE the navy strip", () => {
    // The Cohort tabs (Active / Inactive / Muted) render above
    // the NavyFilterBar as sibling elements.  Assert the pattern
    // by locating the tab strip's ``tab === t.k`` chip fill AND
    // the NavyFilterBar open, and verifying the chips sit ABOVE
    // the NavyFilterBar in source order.
    const chipIdx = pageSrc.indexOf(
      "tab === t.k ? \"rgba(255,255,255,0.35)\" : colors.surfaceSecondary");
    const barIdx = pageSrc.indexOf(
      '<NavyFilterBar\n        data-testid="customers-filters"');
    expect(chipIdx).toBeGreaterThan(-1);
    expect(barIdx).toBeGreaterThan(chipIdx);
    // And the chip container's ``t.testid`` reference must NOT
    // appear inside the NavyFilterBar body.
    const closeIdx = pageSrc.indexOf("</NavyFilterBar>", barIdx);
    const barBlock = pageSrc.slice(barIdx, closeIdx);
    expect(barBlock).not.toContain(
      'data-testid={`${t.testid}-count`}');
  });
});
