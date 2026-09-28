/**
 * DTP-1 · Feb-2026 — PortalHome dark-theme source guard.
 *
 * PortalHome is a 1265-line component that fetches on mount from
 * several endpoints — mounting it end-to-end under jsdom hangs.
 * Instead we source-grep the file to lock the theme-swap contract:
 *
 *   * ``portalColors`` is imported (aliased or explicit).
 *   * The alias re-binds ``colors`` to ``portalColors`` so every
 *     pre-existing ``colors.X`` read resolves to the dark palette
 *     without a JSX-body diff.
 *   * The DTP-2 sweep can add more portal pages by copying this
 *     one-line import swap.
 *
 * A companion test (portal-service-detail-lightbox.test.jsx) verifies
 * the pilot pages actually render end-to-end.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");
const HOME = read("src/pages/portal/PortalHome.jsx");

describe("PortalHome · DTP-1 dark theme (source guard)", () => {
  it("imports portalColors from @/theme (aliased as colors)", () => {
    expect(HOME).toMatch(
      /import\s*\{[^}]*portalColors\s+as\s+colors[^}]*\}\s*from\s*['"]@\/theme['"]/,
    );
  });

  it("no longer imports the raw ``colors`` symbol without the portalColors alias", () => {
    // Must not have ``import { colors, ... }`` or ``import { ..., colors, ...}``
    // WITHOUT the ``portalColors as colors`` alias form. We test by
    // asserting the FIRST theme import is the aliased form (which the
    // positive test above already covers) and that a bare ``colors``
    // token doesn't appear in an import from ``@/theme``.
    const themeImports = HOME.match(
      /import\s*\{[^}]*\}\s*from\s*['"]@\/theme['"]/g,
    ) || [];
    expect(themeImports.length).toBeGreaterThan(0);
    for (const line of themeImports) {
      // The line must EITHER not mention ``colors`` at all, OR mention it
      // only via the ``portalColors as colors`` alias.
      const hasBareColors = /(^|[,\s{])colors\b/.test(line);
      const hasAliasedColors = /portalColors\s+as\s+colors/.test(line);
      expect(hasBareColors && !hasAliasedColors).toBe(false);
    }
  });

  it("existing colors.X reads survive (alias flip is body-diff-free)", () => {
    // At least a handful of colors.<key> references must still be present —
    // the point of aliasing is that the JSX doesn't need edits.
    expect((HOME.match(/colors\.[a-zA-Z]/g) || []).length).toBeGreaterThan(20);
  });
});
