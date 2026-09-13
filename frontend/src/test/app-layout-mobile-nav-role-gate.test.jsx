/**
 * app-layout-mobile-nav-role-gate · Feb-2026
 *
 * Locks the contract established in
 * ``AUDIT_WEB_MOBILE_NAV_DUPLICATE.md`` § 5: the legacy Row 1 mobile
 * <header> in ``AppLayout.jsx`` (identified by
 * ``data-testid="shell-logout-button-mobile"``) is rendered ONLY
 * for roles that do NOT mount ``<AdminTopBar>``. Roles that mount
 * AdminTopBar (admin / super_admin / manager / technician) get its
 * narrow-branch mobile chrome and would otherwise stack two navs
 * on <768px viewports.
 *
 * Uses a source-string smoke pattern (identical to k50-theming) so
 * the test doesn't drag in the whole shell + routing tree.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const APP_LAYOUT = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AppLayout.jsx"),
  "utf8",
);


describe("AppLayout · mobile nav role gate", () => {
  it("Row 1 mobile <header> is wrapped in a role-scoped conditional", () => {
    // The Batch-B tightening surrounds the ``<header>`` that carries
    // the ``shell-logout-button-mobile`` testid with a conditional
    // that returns ``!_mountsAdminTopBar``. Assert the two hallmarks:
    //   1. The full role tuple that mounts AdminTopBar is present
    //      just above the <header>.
    //   2. The header block is closed by the ``) : null}`` ternary
    //      arm — proof it isn't rendered unconditionally anymore.
    const idx = APP_LAYOUT.indexOf('data-testid="shell-logout-button-mobile"');
    expect(idx).toBeGreaterThan(-1);
    const before = APP_LAYOUT.slice(0, idx);
    // Role tuple present.
    expect(before).toMatch(
      /\["admin",\s*"super_admin",\s*"manager",\s*"technician"\][\s\S]{0,200}\.includes\(_effRole\)/,
    );
    // Header is a ternary-consequent (must have `) ? (` between the
    // role gate and the header open).
    const gateSlice = before.slice(before.lastIndexOf("_mountsAdminTopBar"));
    expect(gateSlice).toMatch(/\?\s*\(/);
    // Closes on `) : null}` after </header>.
    const after = APP_LAYOUT.slice(idx);
    expect(after).toMatch(/<\/header>\s*\)\s*:\s*null\s*\}/);
  });

  it("Row 1 role gate uses the same role tuple as AdminTopBar mount", () => {
    // The audit called for "mirror the exact role-gate AdminTopBar
    // uses, inverted". Confirm both call-sites reference the same
    // 4-role tuple in the same order.
    const adminTopBarMount = APP_LAYOUT.match(
      /\["admin",\s*"super_admin",\s*"manager",\s*"technician"\]\.includes\([\s\S]{1,120}?\)\s*&&\s*\(\s*<AdminTopBar/,
    );
    expect(adminTopBarMount).not.toBeNull();
    const row1Gate = APP_LAYOUT.match(
      /const\s+_mountsAdminTopBar\s*=\s*\["admin",\s*"super_admin",\s*"manager",\s*"technician"\]/,
    );
    expect(row1Gate).not.toBeNull();
  });

  it("Row 1 header still uses ``colors.nav.bg`` (K50 theming preserved)", () => {
    // The gate change must not have altered the styling inside —
    // K50 theming lock still applies for customer / customer_portal /
    // unknown roles that DO paint Row 1.
    const idx = APP_LAYOUT.indexOf('data-testid="shell-logout-button-mobile"');
    const headerStart = APP_LAYOUT.slice(0, idx).lastIndexOf("<header");
    const header = APP_LAYOUT.slice(headerStart).split("</header>")[0];
    expect(header).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
  });
});
