/**
 * Feb-2026 · AdminTopBar cleanup · cluster-reorder source guard.
 *
 * Locks the post-cleanup contract on the AdminTopBar right cluster:
 *   1. ``CreditsBudgetChip`` is no longer imported by AdminTopBar.
 *      The component file survives (may be used elsewhere in the
 *      future); AdminTopBar just stops mounting it.
 *   2. ``QuickAddButton`` is no longer imported by AdminTopBar.
 *      Same treatment — file survives, mount is dropped.
 *   3. ``UniversalMenu`` is no longer imported by AdminTopBar.
 *      Defensive supersede of the ``hideHamburger`` prop path we
 *      considered and rejected (see step-1 grep §C).  UniversalMenu
 *      itself is unchanged and still consumed by ``AppLayout``.
 *   4. Cluster ordering ``SettingsSprocket → NotificationBell →
 *      SignOutButton`` in every wrap branch (tech / narrow / wide).
 *      SignOut is the far-right element.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const TOPBAR = readFileSync(
  resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);


describe("AdminTopBar cleanup — imports pruned", () => {
  it("CreditsBudgetChip no longer imported", () => {
    expect(TOPBAR).not.toMatch(
      /from "@\/components\/AIDock\/CreditsBudgetChip"/,
    );
  });

  it("QuickAddButton no longer imported", () => {
    expect(TOPBAR).not.toMatch(
      /from "@\/components\/topbar\/QuickAddButton"/,
    );
  });

  it("UniversalMenu no longer imported", () => {
    // Defensive supersede — even if a future refactor tried to
    // reintroduce a ``hideHamburger``-style prop, the import
    // itself must stay dropped.  Portal consumer at AppLayout
    // is unaffected — different file.
    expect(TOPBAR).not.toMatch(/from "@\/layouts\/UniversalMenu"/);
  });
});


describe("AdminTopBar cleanup — cluster ordering across all 3 wrap branches", () => {
  it("Settings → NotificationBell → SignOut in every wrap branch", () => {
    const branches = [
      "admin-topbar-tech-wrap",
      "admin-topbar-narrow-wrap",
      "admin-topbar-wide-wrap",
    ];
    for (const testid of branches) {
      const branchIdx = TOPBAR.indexOf(`data-testid="${testid}"`);
      expect(branchIdx).toBeGreaterThan(-1);
      const slice = TOPBAR.slice(branchIdx, branchIdx + 3500);
      const settingsIdx = slice.indexOf("<SettingsSprocket />");
      // Feb-2026 · AdminTopBar bell cleanup — NotificationBell now
      // carries an optional ``tone="navy"`` prop (glyph flips to
      // ``colors.nav.fg`` on the navy strip). Relax the regex to
      // accept the prop while still locking ``variant="inline"``.
      const bellIdx     = slice.search(/<NotificationBell\s+variant="inline"(?:\s+tone="navy")?\s*\/>/);
      const signOutIdx  = slice.indexOf("<SignOutButton />");
      expect(settingsIdx).toBeGreaterThan(-1);
      expect(bellIdx).toBeGreaterThan(-1);
      expect(signOutIdx).toBeGreaterThan(-1);
      expect(settingsIdx).toBeLessThan(bellIdx);
      expect(bellIdx).toBeLessThan(signOutIdx);
    }
  });
});
