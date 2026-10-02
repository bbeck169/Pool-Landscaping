/**
 * Phase GLOBAL-SEARCH-UNIFY · Feb-2026 — AdminTopBar GlobalSearch
 * mount lock.
 *
 * Phase BANNER-RELOCATE · Feb-2026 — the visible search bar was
 * relocated to a navy hero banner in AppLayout. This suite now
 * asserts the INVERSE for AdminTopBar: the palette singleton
 * (GlobalSearch) still mounts here, but the visible search bar
 * does NOT.
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

  it("mounts GlobalSearch inside the top bar's returned tree", () => {
    const wrapperIdx = TOPBAR_SRC.indexOf(
      'data-testid="admin-topbar"',
    );
    const mountIdx = TOPBAR_SRC.indexOf("<GlobalSearch />");
    expect(wrapperIdx).toBeGreaterThan(-1);
    expect(mountIdx).toBeGreaterThan(-1);
    expect(mountIdx).toBeGreaterThan(wrapperIdx);
  });
});


describe("AdminTopBar · visible search bar relocated to AppLayout", () => {
  it("no visible search-bar mount remains in AdminTopBar", () => {
    const mountCount = (TOPBAR_SRC.match(/<GlobalSearchBar\s*\/>/g) || []).length;
    expect(mountCount).toBe(0);
  });

  it("no GlobalSearchBar import remains in AdminTopBar", () => {
    expect(TOPBAR_SRC).not.toMatch(
      /import\s+GlobalSearchBar\s+from\s+["']@\/components\/GlobalSearchBar["']/,
    );
  });
});
