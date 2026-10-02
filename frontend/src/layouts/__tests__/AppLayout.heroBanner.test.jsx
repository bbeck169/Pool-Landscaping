/**
 * Phase BANNER-RELOCATE · Feb-2026 — Admin hero banner mount lock.
 *
 * Source-inspection contract (mirrors the AdminTopBar.globalSearch
 * convention) so any accidental removal of the navy hero banner —
 * or the search-bar mount inside it — trips a red bar in CI before
 * it merges. Full-mount tests were avoided to keep collection fast
 * and to dodge the vitest full-shell hang documented in
 * vitest.config.js (Tasks OO / PP).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const APP_LAYOUT_SRC = fs.readFileSync(
  path.resolve(__dirname, "../AppLayout.jsx"),
  "utf8",
);


describe("AppLayout · Phase BANNER-RELOCATE · admin hero banner", () => {
  it("imports GlobalSearchBar from @/components/GlobalSearchBar", () => {
    expect(APP_LAYOUT_SRC).toMatch(
      /import\s+GlobalSearchBar\s+from\s+["']@\/components\/GlobalSearchBar["']/,
    );
  });

  it("renders a <div data-testid='admin-hero-banner' /> element", () => {
    expect(APP_LAYOUT_SRC).toMatch(
      /data-testid=["']admin-hero-banner["']/,
    );
  });

  it("hero banner carries the navy #1B1F5C background", () => {
    const bannerIdx = APP_LAYOUT_SRC.indexOf(
      'data-testid="admin-hero-banner"',
    );
    expect(bannerIdx).toBeGreaterThan(-1);
    const ctx = APP_LAYOUT_SRC.slice(
      Math.max(0, bannerIdx - 400),
      bannerIdx + 400,
    );
    expect(ctx).toMatch(/#1B1F5C/);
  });

  it("GlobalSearchBar is mounted inside the hero banner", () => {
    const bannerIdx = APP_LAYOUT_SRC.indexOf(
      'data-testid="admin-hero-banner"',
    );
    expect(bannerIdx).toBeGreaterThan(-1);
    const after = APP_LAYOUT_SRC.slice(bannerIdx, bannerIdx + 500);
    expect(after).toMatch(/<GlobalSearchBar\s*\/>/);
  });

  it("hero banner mounts inside the same role gate as AdminTopBar", () => {
    const bannerIdx = APP_LAYOUT_SRC.indexOf(
      'data-testid="admin-hero-banner"',
    );
    expect(bannerIdx).toBeGreaterThan(-1);
    const preBanner = APP_LAYOUT_SRC.slice(0, bannerIdx);
    const lastGateIdx = preBanner.lastIndexOf(
      '["admin", "super_admin", "manager", "technician"]',
    );
    expect(lastGateIdx).toBeGreaterThan(-1);
    const windowBetween = preBanner.slice(lastGateIdx);
    expect(windowBetween).not.toMatch(/<PortalThemeShell/);
  });
});
