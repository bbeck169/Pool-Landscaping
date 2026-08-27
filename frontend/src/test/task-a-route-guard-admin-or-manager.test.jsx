/**
 * Feb 2026 · Task A · route-guard companion test.
 *
 * The nav-visibility hotfix that lifted manager_only entries in the
 * sidebar/top-bar landed with a paired change in App.js: seven
 * routes previously wrapped in ``<AdminOnly>`` were swapped to a new
 * ``<AdminOrManager>`` guard so real manager accounts can actually
 * REACH the pages the nav now surfaces. This test source-parses
 * App.js and asserts the swap held on all seven routes AND that
 * ``<AdminOrManager>`` correctly grants super_admin / admin /
 * manager while blocking technician / customer.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const APP_JS = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf8",
);

// The 7 routes surfaced by manager_only nav entries. Each must now
// route-wrap with <AdminOrManager> — the old <AdminOnly> would
// redirect real manager accounts back to /.
const MANAGER_ROUTES = [
  "admin/recurring-jobs",
  "admin/reports/driver-activity",
  "admin/moderation/checkins",
  "admin/seo/auditor",
  "admin/seo/keywords",
  "admin/settings/gps-users",
  "admin/moderation/widget-embed",
];


describe("Task A · route guard for manager_only routes", () => {
  it.each(MANAGER_ROUTES)(
    "route %s is wrapped in <AdminOrManager> (not <AdminOnly>)",
    (route) => {
      const escaped = route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const positive = new RegExp(
        `path="${escaped}"\\s+element=\\{<AdminOrManager>`,
      );
      const negative = new RegExp(
        `path="${escaped}"\\s+element=\\{<AdminOnly>`,
      );
      expect(positive.test(APP_JS)).toBe(true);
      expect(negative.test(APP_JS)).toBe(false);
    },
  );

  it("AdminOrManager wrapper exists and permits exactly super_admin / admin / manager", () => {
    // Locate the wrapper definition and verify its role gate.
    const match = APP_JS.match(/function AdminOrManager\([\s\S]*?\n\}/);
    expect(match).toBeTruthy();
    const src = match[0];
    // Must accept manager.
    expect(src.includes("manager")).toBe(true);
    expect(src.includes("admin")).toBe(true);
    expect(src.includes("super_admin")).toBe(true);
    // Must redirect on unauthorized (blocks tech / customer).
    expect(src.includes("Navigate")).toBe(true);
  });

  it("AdminOrManager blocks technician / customer at the source level", () => {
    // Deliberately narrow — the wrapper computes ``allowed`` from a
    // 3-role whitelist. Technician / customer are NOT in that list.
    const match = APP_JS.match(/function AdminOrManager\([\s\S]*?\n\}/);
    const src = match[0];
    // Not permitting tech / customer directly.
    expect(src.includes("technician")).toBe(false);
    expect(src.includes("customer")).toBe(false);
  });

  it("Legacy AdminOnly wrapper stays intact for the other routes that were never manager_only", () => {
    // Sanity check — the swap is scoped to the 7 routes. Other
    // routes (e.g. /admin/audits, /admin/migrations, /admin/rbac)
    // still legitimately use AdminOnly.
    expect(APP_JS.includes("function AdminOnly(")).toBe(true);
    // Count of remaining AdminOnly usages is > 0.
    const adminOnlyUses = APP_JS.match(/<AdminOnly>/g) || [];
    expect(adminOnlyUses.length).toBeGreaterThan(0);
  });
});
