/**
 * TIMECARDS-BE-WIDEN · Feb-2026 — companion test (supersedes the
 * ROUTE-GUARD-WIDEN companion of the same filename).
 *
 * The LIST + bulk endpoints on ``/time-entries`` were widened
 * backend-side from ``require_admin`` to ``require_admin_or_manager``.
 * The FE route is flipped to a new ``AdminManagerOrOwner`` wrapper
 * matching the backend\'s 4-role set exactly.
 *
 * We retire the single-use ``AdminOrOwner`` wrapper from the
 * previous atomic to avoid dead code.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const APP_JS = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf8",
);

describe("TIMECARDS-BE-WIDEN · AdminManagerOrOwner", () => {
  it("AdminManagerOrOwner wrapper exists in App.js", () => {
    const match = APP_JS.match(/function AdminManagerOrOwner\([\s\S]*?\n\}/);
    expect(match).toBeTruthy();
  });

  it("AdminManagerOrOwner admits exactly admin / super_admin / manager / owner", () => {
    const match = APP_JS.match(/function AdminManagerOrOwner\([\s\S]*?\n\}/);
    const body = match[0];
    expect(body).toMatch(/"admin"/);
    expect(body).toMatch(/"super_admin"/);
    expect(body).toMatch(/"manager"/);
    expect(body).toMatch(/"owner"/);
  });

  it("/admin/time-entries is wrapped in <AdminManagerOrOwner>", () => {
    const positive = /path="admin\/time-entries"\s+element=\{<AdminManagerOrOwner>/;
    expect(positive.test(APP_JS)).toBe(true);
    const admin_only = /path="admin\/time-entries"\s+element=\{<AdminOnly>/;
    const admin_or_owner = /path="admin\/time-entries"\s+element=\{<AdminOrOwner>/;
    const admin_or_manager = /path="admin\/time-entries"\s+element=\{<AdminOrManager>/;
    expect(admin_only.test(APP_JS)).toBe(false);
    expect(admin_or_owner.test(APP_JS)).toBe(false);
    expect(admin_or_manager.test(APP_JS)).toBe(false);
  });

  it("retired AdminOrOwner wrapper has been fully removed", () => {
    expect(APP_JS).not.toMatch(/function AdminOrOwner\(/);
    expect(APP_JS).not.toMatch(/<AdminOrOwner>/);
    expect(APP_JS).not.toMatch(/<\/AdminOrOwner>/);
  });

  it("only /admin/time-entries uses <AdminManagerOrOwner>", () => {
    const uses = APP_JS.match(/<AdminManagerOrOwner>/g) || [];
    expect(uses.length).toBe(1);
  });

  it("legacy <AdminOnly> + <AdminOrManager> wrappers still intact", () => {
    expect(APP_JS).toMatch(/function AdminOnly\(/);
    expect(APP_JS).toMatch(/function AdminOrManager\(/);
    const adminOnlyUses = APP_JS.match(/<AdminOnly>/g) || [];
    const adminOrManagerUses = APP_JS.match(/<AdminOrManager>/g) || [];
    expect(adminOnlyUses.length).toBeGreaterThan(50);
    expect(adminOrManagerUses.length).toBeGreaterThan(5);
  });
});
