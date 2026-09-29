/**
 * Phase GLOBAL-SEARCH-UNIFY · Feb-2026 — AdminTopBar → GlobalSearch
 * mount lock. Source-inspection contract (matches the k70a-tile-
 * theming convention) so any accidental removal of the palette
 * mount trips a red bar in CI before it merges.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const TOPBAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "../../layouts/AdminTopBar.jsx"),
  "utf8",
);


describe("AdminTopBar · GlobalSearch mount", () => {
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
