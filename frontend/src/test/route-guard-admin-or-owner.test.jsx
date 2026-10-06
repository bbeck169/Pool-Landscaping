/**
 * ROUTE-GUARD-WIDEN · Feb-2026 — companion test.
 *
 * Closes a pre-existing drift: ``utils.require_admin`` on the
 * backend permits ``{admin, super_admin, owner}``, but the FE
 * ``<AdminOnly>`` wrapper only admitted ``{admin, super_admin}``.
 * Owners could hit ``/api/time-entries`` via API but could NOT
 * reach ``/admin/time-entries`` via the route.
 *
 * We swap the one route to the new ``<AdminOrOwner>`` wrapper and
 * assert:
 *   1. The wrapper exists in App.js with exactly the 3-role gate
 *      ``{admin, super_admin, owner}`` (and NOT manager — managers
 *      stay blocked until the paired backend widen).
 *   2. ``/admin/time-entries`` is wrapped in ``<AdminOrOwner>``,
 *      not ``<AdminOnly>``.
 *   3. No OTHER route was accidentally migrated to ``<AdminOrOwner>``
 *      in this atomic.
 *
 * Modeled after ``task-a-route-guard-admin-or-manager.test.jsx``.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const APP_JS = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf8",
);

describe("ROUTE-GUARD-WIDEN · AdminOrOwner", () => {
  it("AdminOrOwner wrapper exists in App.js", () => {
    const match = APP_JS.match(/function AdminOrOwner\([\s\S]*?\n\}/);
    expect(match).toBeTruthy();
  });

  it("AdminOrOwner permits exactly admin / super_admin / owner (not manager)", () => {
    const match = APP_JS.match(/function AdminOrOwner\([\s\S]*?\n\}/);
    const body = match[0];
    // Must accept admin + super_admin + owner.
    expect(body).toMatch(/"admin"/);
    expect(body).toMatch(/"super_admin"/);
    expect(body).toMatch(/"owner"/);
    // Must NOT accept manager — manager widen is deferred until the
    // paired backend widen (TIMECARDS-BE-WIDEN).
    expect(body).not.toMatch(/"manager"/);
  });

  it("/admin/time-entries is wrapped in <AdminOrOwner> (not <AdminOnly>)", () => {
    const positive = /path="admin\/time-entries"\s+element=\{<AdminOrOwner>/;
    const negative = /path="admin\/time-entries"\s+element=\{<AdminOnly>/;
    expect(positive.test(APP_JS)).toBe(true);
    expect(negative.test(APP_JS)).toBe(false);
  });

  it("only the time-entries route uses <AdminOrOwner> in this atomic", () => {
    // Count occurrences of the wrapper in element props.  Should
    // be exactly 1 (opening tag on the one widened route).
    const uses = APP_JS.match(/<AdminOrOwner>/g) || [];
    expect(uses.length).toBe(1);
  });

  it("the legacy <AdminOnly> wrapper itself is still defined and used elsewhere", () => {
    // AdminOnly remains the canonical admin-only wrapper for the
    // 280+ other admin routes.  We only migrated one route.
    expect(APP_JS.includes("function AdminOnly(")).toBe(true);
    const uses = APP_JS.match(/<AdminOnly>/g) || [];
    expect(uses.length).toBeGreaterThan(50);
  });
});
