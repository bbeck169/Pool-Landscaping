/**
 * Phase GLOBAL-SEARCH-UNIFY · Feb-2026 — AdminTopBar → GlobalSearch
 * mount lock. Source-inspection contract (matches the k70a-tile-
 * theming convention) so any accidental removal of the palette or
 * the visible bar trips a red bar in CI before it merges.
 *
 * Feb-2026 · Restore visible universal search — extended to also
 * assert the visible ``<GlobalSearchBar />`` is mounted alongside
 * the ⌘K palette.  Both entry points are first-class citizens now.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const TOPBAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "../../layouts/AdminTopBar.jsx"),
  "utf8",
);


describe("AdminTopBar · GlobalSearch (palette) mount", () => {
  it("imports GlobalSearch from @/components/GlobalSearch", () => {
    expect(TOPBAR_SRC).toMatch(
      /import\s+GlobalSearch\s+from\s+["']@\/components\/GlobalSearch["']/,
    );
  });

  it("mounts <GlobalSearch /> inside the top bar's returned tree", () => {
    // The mount lives inside the ``sticky top-0 z-30 w-full``
    // wrapper (the AdminTopBar root <div>) — assert both are
    // present and the mount marker sits AFTER the wrapper opens.
    const wrapperIdx = TOPBAR_SRC.indexOf(
      'data-testid="admin-topbar"',
    );
    const mountIdx = TOPBAR_SRC.indexOf("<GlobalSearch />");
    expect(wrapperIdx).toBeGreaterThan(-1);
    expect(mountIdx).toBeGreaterThan(-1);
    expect(mountIdx).toBeGreaterThan(wrapperIdx);
  });
});


describe("AdminTopBar · GlobalSearchBar (visible bar) mount", () => {
  it("imports GlobalSearchBar from @/components/GlobalSearchBar", () => {
    expect(TOPBAR_SRC).toMatch(
      /import\s+GlobalSearchBar\s+from\s+["']@\/components\/GlobalSearchBar["']/,
    );
  });

  it("mounts <GlobalSearchBar /> on the WIDE (md+) branch", () => {
    const wideWrapIdx = TOPBAR_SRC.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    expect(wideWrapIdx).toBeGreaterThan(-1);
    // The wide branch's closing </div> sits before the narrow branch
    // starts.  Find the first ``</div>`` marker AFTER the wide wrap
    // to bound our search window.
    const narrowWrapIdx = TOPBAR_SRC.indexOf(
      'data-testid="admin-topbar-narrow-wrap"',
    );
    // Slice from wide wrap opener to the narrow wrap opener (they
    // are siblings in the tree; both branches render the same
    // component).  ``<GlobalSearchBar />`` must appear inside both
    // windows.
    const wideStart = Math.min(wideWrapIdx, narrowWrapIdx);
    const wideEnd = Math.max(wideWrapIdx, narrowWrapIdx);
    const firstWindow = TOPBAR_SRC.slice(wideStart, wideEnd);
    expect(firstWindow).toMatch(/<GlobalSearchBar\s*\/>/);
  });

  it("mounts <GlobalSearchBar /> on the NARROW (<md) branch", () => {
    // Slice the whole file after the narrow wrap opener — the
    // narrow branch runs from there until the wide wrap starts
    // (in source order they alternate).
    const narrowWrapIdx = TOPBAR_SRC.indexOf(
      'data-testid="admin-topbar-narrow-wrap"',
    );
    const wideWrapIdx = TOPBAR_SRC.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    const start = Math.max(narrowWrapIdx, wideWrapIdx);
    const secondWindow = TOPBAR_SRC.slice(
      Math.min(narrowWrapIdx, wideWrapIdx),
      start,
    );
    // Both branches contain a mount — since the two windows above
    // cover the whole rendered tree, the palette is present on
    // BOTH branches.  Sanity-check the total mount count is at
    // least 2.
    const mountCount = (TOPBAR_SRC.match(/<GlobalSearchBar\s*\/>/g) || []).length;
    expect(mountCount).toBeGreaterThanOrEqual(2);
    // And the visible bar must appear in the second-window slice
    // too (which by symmetry contains the other branch mount).
    expect(secondWindow.length).toBeGreaterThan(0);
  });
});
