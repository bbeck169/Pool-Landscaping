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

  it("does NOT mount RolePreviewSwitcher in the wide-branch (no duplication)", () => {
    // The wide (desktop) branch already renders the switcher via
    // AdminSidebar → we must not double-mount it in the AdminTopBar
    // desktop cluster too.
    const anchor = ATOP_BAR.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    expect(anchor).toBeGreaterThan(-1);
    // Slice to the end of that <div> block only.
    const wideBranch = ATOP_BAR.slice(anchor).split("</>")[0];
    // The narrow-branch match above and this negative one together
    // guarantee "exactly one mount site" in the file.
    const total = (ATOP_BAR.match(/<RolePreviewSwitcher\s*\/>/g) || []).length;
    expect(total).toBe(1);
    // And it's NOT inside the wide branch.
    expect(wideBranch).not.toMatch(/<RolePreviewSwitcher\s*\/>/);
  });
});
