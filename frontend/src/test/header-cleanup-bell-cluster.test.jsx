/**
 * Feb-2026 · Header cleanup — post AdminTopBar reorder + bell
 * cluster inversion.
 *
 * Source-inspection guard for the current post-cleanup contract:
 *   1. ``<AdminTopBar>`` imports ``NotificationBell`` directly
 *      and mounts it inline in every branch's right-cluster.  The
 *      pre-cleanup routing through ``<UniversalMenu variant="inline">``
 *      has been dropped from AdminTopBar entirely — UniversalMenu
 *      still lives in the codebase (used by the customer-portal
 *      ``AppLayout`` header) but AdminTopBar no longer touches it.
 *   2. ``<AdminTopBar>`` does NOT mount ``<UniversalMenu>`` in any
 *      of its three branches (tech / narrow / wide).  Regression
 *      guard against accidental re-mount.
 *   3. Cluster ordering is ``SettingsSprocket → NotificationBell →
 *      SignOutButton`` in every branch — SignOut is the far-right
 *      element, matching the Feb-2026 cleanup spec.
 *   4. ``<AppLayout>`` no longer double-mounts UniversalMenu for
 *      admin roles.  Contract unchanged by the cleanup; the same
 *      role gate ships.
 *   5. ``<UniversalMenu>`` still supports ``variant='inline'`` +
 *      defaults to ``'floating'`` — component itself untouched by
 *      the cleanup.  Portal consumer at ``AppLayout.jsx`` still
 *      relies on both variants.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const TOPBAR = readFileSync(resolve(__dirname, "../layouts/AdminTopBar.jsx"), "utf8");
const APP    = readFileSync(resolve(__dirname, "../layouts/AppLayout.jsx"),   "utf8");
const UMENU  = readFileSync(resolve(__dirname, "../layouts/UniversalMenu.jsx"), "utf8");


describe("Header cleanup — AdminTopBar direct NotificationBell", () => {
  it("AdminTopBar imports NotificationBell + mounts <NotificationBell variant=\"inline\"> in every branch", () => {
    // Import + JSX both present after the Feb-2026 cleanup.
    expect(TOPBAR).toMatch(/from "@\/components\/NotificationBell"/);
    // Three branches — tech, narrow, wide — each ends with the
    // inline NotificationBell as its bell surface.
    // Feb-2026 · AdminTopBar bell cleanup — regex relaxed to accept
    // the optional ``tone="navy"`` prop; the count-lock at 3 stays.
    const matches = TOPBAR.match(/<NotificationBell\s+variant="inline"(?:\s+tone="navy")?\s*\/>/g) || [];
    expect(matches.length).toBe(3);
  });

  it("AdminTopBar no longer mounts <UniversalMenu> in any branch", () => {
    // The pre-cleanup routing through UniversalMenu is gone from
    // AdminTopBar. Guard against accidental re-mount.
    const menuMounts = TOPBAR.match(/<UniversalMenu\s+variant="inline"\s*\/>/g) || [];
    expect(menuMounts.length).toBe(0);
    // Import also dropped.
    expect(TOPBAR).not.toMatch(/from "@\/layouts\/UniversalMenu"/);
  });

  it("Cluster order is SettingsSprocket → NotificationBell → SignOutButton in every branch (SignOut far-right)", () => {
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
      const bellIdx     = slice.search(/<NotificationBell\s+variant="inline"(?:\s+tone="navy")?\s*\/>/);
      const signOutIdx  = slice.indexOf("<SignOutButton />");
      expect(settingsIdx).toBeGreaterThan(-1);
      expect(bellIdx).toBeGreaterThan(-1);
      expect(signOutIdx).toBeGreaterThan(-1);
      // Strictly ascending — Settings comes before Bell comes
      // before Sign-out.  A future refactor that swaps any pair
      // trips this assertion.
      expect(settingsIdx).toBeLessThan(bellIdx);
      expect(bellIdx).toBeLessThan(signOutIdx);
    }
  });

  it("AppLayout still gates a floating UniversalMenu for non-admin/tech roles", () => {
    // Contract unchanged by the AdminTopBar cleanup.  The gate
    // excludes ALL four staff roles so the floating instance only
    // ships for customer / customer_admin surfaces.
    expect(APP).toMatch(/!\s*\[\s*"admin",\s*"super_admin",\s*"manager",\s*"technician"\s*\]\.includes/);
  });

  it("UniversalMenu still supports variant='inline' + defaults to 'floating' (portal still consumes it)", () => {
    // Prop is destructured with a default so the ``AppLayout``
    // portal caller keeps the previous floating behavior.
    expect(UMENU).toMatch(/UniversalMenu\(\s*\{\s*variant\s*=\s*"floating"/);
    // Phase P38 · Feb-2026 — floating branch stays wrapped in a
    // single cluster container.
    expect(UMENU).toContain("fixed top-3 right-3 z-40 flex items-center gap-2");
    // Both bell variants still ship — floating for AppLayout's
    // customer surface, inline for the portal-header consumer at
    // ``AppLayout.jsx:715``.
    expect(UMENU).toMatch(/<NotificationBell\s+variant="floating"\s*\/>/);
    expect(UMENU).toMatch(/<NotificationBell\s+variant="inline"\s*\/>/);
  });
});
