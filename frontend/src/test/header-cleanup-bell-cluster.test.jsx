/**
 * Feb-2026 · Header cleanup — deduplicate bell + reposition cluster.
 *
 * Source-inspection guard for the header rework:
 *   1. Only ONE <NotificationBell> is emitted by the header stack
 *      (AdminTopBar no longer renders its own inline bell; the bell
 *      is now rendered by <UniversalMenu variant="inline"> which is
 *      mounted once inside <AdminTopBar>).
 *   2. <AdminTopBar> renders <UniversalMenu variant="inline"> at the
 *      end of the right-hand cluster in every branch (tech / narrow
 *      / wide).
 *   3. <SignOutButton> is emitted BEFORE <UniversalMenu> in every
 *      branch — Sign Out sits to the LEFT of the bell + hamburger.
 *   4. <AppLayout> no longer mounts a second floating
 *      <UniversalMenu> for admin / super_admin / manager /
 *      technician (would double-mount and re-introduce the floating
 *      cluster that overlapped content).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const TOPBAR = readFileSync(resolve(__dirname, "../layouts/AdminTopBar.jsx"), "utf8");
const APP    = readFileSync(resolve(__dirname, "../layouts/AppLayout.jsx"),   "utf8");
const UMENU  = readFileSync(resolve(__dirname, "../layouts/UniversalMenu.jsx"), "utf8");


describe("Header cleanup — single bell + cluster in row", () => {
  it("AdminTopBar no longer renders its own <NotificationBell>", () => {
    // The old inline bell (Bell A) has been removed. The bell is
    // now rendered exclusively by <UniversalMenu variant='inline'>.
    expect(TOPBAR).not.toMatch(/<NotificationBell\b/);
    // And the import is dropped so eslint stays clean.
    expect(TOPBAR).not.toMatch(/from "@\/components\/NotificationBell"/);
  });

  it("AdminTopBar mounts <UniversalMenu variant=\"inline\"> in every branch", () => {
    // Three branches — tech-only, narrow, wide — each ends with the
    // inline UniversalMenu after Sign Out. Match the self-closing
    // JSX form so a mention of the tag inside a docstring doesn't
    // inflate the count.
    const matches = TOPBAR.match(/<UniversalMenu\s+variant="inline"\s*\/>/g) || [];
    expect(matches.length).toBe(3);
  });

  it("Sign Out is emitted BEFORE UniversalMenu in every branch (left of bell/menu)", () => {
    // For each branch, find the SignOutButton self-closing tag, then
    // the next UniversalMenu self-closing tag after it; assert the
    // UniversalMenu comes after (i.e. Sign Out is to the LEFT in
    // DOM order). Use self-closing forms so tag mentions in
    // docstrings don't confuse the scan.
    const branches = [
      "admin-topbar-tech-wrap",
      "admin-topbar-narrow-wrap",
      "admin-topbar-wide-wrap",
    ];
    for (const testid of branches) {
      const branchIdx = TOPBAR.indexOf(`data-testid="${testid}"`);
      expect(branchIdx).toBeGreaterThan(-1);
      const slice = TOPBAR.slice(branchIdx, branchIdx + 2000);
      const signOutIdx = slice.indexOf("<SignOutButton />");
      const menuIdx    = slice.search(/<UniversalMenu\s+variant="inline"\s*\/>/);
      expect(signOutIdx).toBeGreaterThan(-1);
      expect(menuIdx).toBeGreaterThan(-1);
      expect(signOutIdx).toBeLessThan(menuIdx);
    }
  });

  it("AppLayout no longer double-mounts UniversalMenu for admin roles", () => {
    // Old gate was ``!== "admin"`` which matched super_admin /
    // manager / technician. New gate excludes ALL four roles so the
    // floating instance only ships for customer / customer_admin.
    expect(APP).toMatch(/!\s*\[\s*"admin",\s*"super_admin",\s*"manager",\s*"technician"\s*\]\.includes/);
  });

  it("UniversalMenu supports variant='inline' + defaults to 'floating'", () => {
    // Prop is destructured with a default so existing callers keep
    // the previous floating behavior.
    expect(UMENU).toMatch(/UniversalMenu\(\s*\{\s*variant\s*=\s*"floating"/);
    // Inline branch uses non-fixed positioning; floating branch
    // keeps ``fixed top-3 right-3``.
    expect(UMENU).toMatch(/variant === "inline"[\s\S]{0,200}inline-flex/);
    expect(UMENU).toContain("fixed top-3 right-3");
    // The bell inside UniversalMenu picks its variant from the prop.
    expect(UMENU).toMatch(/NotificationBell variant=\{variant === "inline" \? "inline" : "floating"\}/);
  });
});
