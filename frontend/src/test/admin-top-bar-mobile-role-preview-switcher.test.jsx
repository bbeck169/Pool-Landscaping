/**
 * admin-top-bar-mobile-role-preview-switcher · Feb-2026
 *
 * Locks the second half of the Mobile Nav Duplicate Fix (see
 * ``AUDIT_WEB_MOBILE_NAV_DUPLICATE.md`` § 5, item 2): the
 * ``<RolePreviewSwitcher>`` picker is mounted inside AdminTopBar's
 * narrow-branch right-cluster so super_admin keeps one-tap "Test
 * as" access on mobile after Row 1 was gated off.
 *
 * The picker self-gates via ``canPreview`` (super_admin only), so
 * we only need to prove the JSX mount site exists in the narrow
 * branch and that the import + component reference line up.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ATOP_BAR = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);


describe("AdminTopBar · RolePreviewSwitcher mobile mount", () => {
  it("imports RolePreviewSwitcher from @/components/RolePreviewSwitcher", () => {
    expect(ATOP_BAR).toMatch(
      /^import\s+RolePreviewSwitcher\s+from\s+"@\/components\/RolePreviewSwitcher";/m,
    );
  });

  it("mounts RolePreviewSwitcher inside the narrow-branch right-cluster", () => {
    // Locate the narrow-branch wrap via its testid, then confirm the
    // switcher JSX lives between the opening <div> and </div>.
    const anchor = ATOP_BAR.indexOf(
      'data-testid="admin-topbar-narrow-wrap"',
    );
    expect(anchor).toBeGreaterThan(-1);
    const branch = ATOP_BAR.slice(anchor).split("data-testid=\"admin-topbar-wide-wrap\"")[0];
    expect(branch).toMatch(/<RolePreviewSwitcher\s*\/>/);
    // Sanity — it must sit alongside the other right-cluster peers
    // so the layout order matches the audit spec.
    expect(branch).toMatch(/AddCustomerButton[\s\S]*RolePreviewSwitcher[\s\S]*SignOutButton/);
  });

  it("Test C · manager viewport → RolePreviewSwitcher rendered by JSX (self-gates at runtime)", () => {
    // Feb-2026 · Mobile Nav Overflow follow-up — the test that
    // previously asserted "admin does NOT see the picker" was based
    // on an incorrect super_admin-only assumption. The real
    // ``canPreview`` contract in ``hooks/usePermissions.jsx:170`` is
    // ``role === "admin" || role === "super_admin"``, which is a
    // long-standing product decision (admins can impersonate too).
    // The JSX mount is unconditional at the AdminTopBar layer; the
    // component self-gates at runtime. This static-source test
    // therefore only proves the mount exists — the runtime gate is
    // covered by RolePreviewSwitcher's own tests.
    const anchor = ATOP_BAR.indexOf(
      'data-testid="admin-topbar-narrow-wrap"',
    );
    const branch = ATOP_BAR.slice(anchor).split("data-testid=\"admin-topbar-wide-wrap\"")[0];
    // Mount site is present — same as Test B above.
    expect(branch).toMatch(/<RolePreviewSwitcher\s*\/>/);
    // And no ``role === "manager"`` gating logic leaked in around it —
    // gating is the component's responsibility, not the mount site's.
    const inlineGate = branch.match(
      /role\s*===\s*"manager"[\s\S]{0,200}<RolePreviewSwitcher/,
    );
    expect(inlineGate).toBeNull();
  });
});
