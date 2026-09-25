/**
 * Phase P52 · Feb-2026 — LanguageSelector removal from AdminTopBar.
 *
 * P50 shipped the tenant-scoped default_locale wire (auth.jsx +
 * Global Settings + detector chain).  With the tenant fallback in
 * place, the top-bar globe becomes redundant — a personal-language
 * pref lives in the Settings surface, and the tenant default takes
 * over for everyone who hasn't set a personal pref.  P52 removes
 * the LanguageSelector import + all three render sites from
 * AdminTopBar.
 *
 * File-inspection tests: mounting AdminTopBar pulls in ~15 heavy
 * children (RolePreviewSwitcher, TenantSwitcher, QuickAddButton,
 * SettingsSprocket, AdminBellSlot, UniversalMenu ...) — same
 * profile as the CustomerDetail suite that we intentionally
 * file-inspect for the same reason.
 *
 * The LanguageSelector.jsx file itself is NOT deleted — it is
 * still consumed by ``phase-d3-language-selector.test.jsx`` and
 * ``settings-sprocket-visibility.test.jsx`` per your Q3 answer.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const ATB_SRC = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf-8",
);


describe("P52 · AdminTopBar · LanguageSelector removed", () => {
  it("no import of LanguageSelector — the import line was replaced " +
     "with a P52 rationale comment block", () => {
    // No ``import LanguageSelector`` line anywhere.
    expect(ATB_SRC).not.toMatch(
      /import\s+LanguageSelector\s+from\s+["']@\/components\/i18n\/LanguageSelector["']/,
    );
    // The P52 rationale comment IS present so a future refactor
    // has grep-visible context for why the globe went away.
    expect(ATB_SRC).toMatch(
      /Phase P52[\s\S]{0,80}LanguageSelector removed from the topbar/,
    );
  });

  it("no JSX render of <LanguageSelector /> anywhere in the file — " +
     "all three P50-era render sites removed", () => {
    // Zero occurrences of the tag (self-closing or with-props).
    expect(ATB_SRC).not.toMatch(/<LanguageSelector\b/);
    // Belt: no references to the component name outside the P52
    // rationale comment.  The word ``LanguageSelector`` should
    // ONLY appear in that comment.
    const matches = ATB_SRC.match(/LanguageSelector/g) || [];
    expect(
      matches.length,
      `LanguageSelector referenced ${matches.length} times — ` +
      `expected exactly 1 (the P52 rationale comment)`,
    ).toBe(1);
  });

  it("keeps SignOutButton + right-cluster neighbours — the P52 " +
     "removal did not accidentally drop the neighbour components " +
     "that used to render alongside the LanguageSelector", () => {
    // The three ex-neighbours (SettingsSprocket, SignOutButton,
    // NotificationBell) still render.  Feb-2026 · AdminTopBar
    // cleanup — the inline ``<UniversalMenu>`` was dropped from
    // AdminTopBar in favour of a standalone ``<NotificationBell>``;
    // this assertion tracks the new neighbour.
    expect(ATB_SRC).toMatch(/<SettingsSprocket\s*\/>/);
    expect(ATB_SRC).toMatch(/<SignOutButton\s*\/>/);
    // Feb-2026 · AdminTopBar bell cleanup — regex accepts the
    // optional ``tone="navy"`` prop.
    expect(ATB_SRC).toMatch(/<NotificationBell\s+variant="inline"(?:\s+tone="navy")?\s*\/>/);
  });
});
