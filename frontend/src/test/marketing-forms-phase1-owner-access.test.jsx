/**
 * OWNER-ACCESS-MARKETING-FORMS · Feb-2026 — FE route-guard vitest.
 *
 * Phase 1 Commit 2 of the Marketing Forms owner-access ship.
 *
 * Narrowly-scoped: the /admin/marketing/forms route (and only that
 * route) now admits the ``owner`` role via a new
 * ``AdminOrOwnerForMarketingForms`` wrapper. Every other
 * ``AdminOnly``-gated route remains strictly admin + super_admin
 * so the owner role does NOT silently gain write access to
 * un-audited admin surfaces (Email Builder, Templates Library,
 * et al.).
 *
 * Covers (6 cases) — source-parse pattern mirrors
 * ``task-a-route-guard-admin-or-manager.test.jsx`` so the test is
 * fast + resilient to component mocking churn:
 *   1. /admin/marketing/forms is wrapped in
 *      <AdminOrOwnerForMarketingForms> (not <AdminOnly>).
 *   2. The wrapper is defined once in App.js.
 *   3. The wrapper's role whitelist is EXACTLY
 *      {admin, super_admin, owner} — not manager, not marketer,
 *      not technician, not customer.
 *   4. Only ONE route references the new wrapper (prevents a
 *      future atomic from accidentally widening it to Email
 *      Builder / Templates Library — the explicit owner-scoping
 *      design decision).
 *   5. <AdminOnly> stays the gate for Email Builder-adjacent
 *      surfaces (regression gate — "owner cannot write to other
 *      admin surfaces").
 *   6. <AdminOnly> wrapper body remains byte-identical (admin +
 *      super_admin only — ownership stays scoped to the new
 *      wrapper).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const APP_JS = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf8",
);


describe("Phase 1 · Marketing Forms owner-access route guard", () => {
  // ─────────────────────────────────────────────────────────────
  // 1. /admin/marketing/forms uses the new wrapper
  // ─────────────────────────────────────────────────────────────
  it("/admin/marketing/forms is wrapped in <AdminOrOwnerForMarketingForms>", () => {
    const positive = new RegExp(
      'path="admin/marketing/forms"\\s+element=\\{<AdminOrOwnerForMarketingForms>',
    );
    const negative = new RegExp(
      'path="admin/marketing/forms"\\s+element=\\{<AdminOnly>',
    );
    expect(positive.test(APP_JS)).toBe(true);
    expect(negative.test(APP_JS)).toBe(false);
  });

  // ─────────────────────────────────────────────────────────────
  // 2. The wrapper is defined
  // ─────────────────────────────────────────────────────────────
  it("AdminOrOwnerForMarketingForms wrapper is defined in App.js", () => {
    expect(
      APP_JS.includes("function AdminOrOwnerForMarketingForms("),
    ).toBe(true);
  });

  // ─────────────────────────────────────────────────────────────
  // 3. Role whitelist is {admin, super_admin, owner} — nothing else
  // ─────────────────────────────────────────────────────────────
  it("wrapper admits exactly admin / super_admin / owner", () => {
    const match = APP_JS.match(
      /function AdminOrOwnerForMarketingForms\([\s\S]*?\n\}/,
    );
    expect(match).toBeTruthy();
    const src = match[0];
    // Must accept all three.
    expect(src.includes('"admin"')).toBe(true);
    expect(src.includes('"super_admin"')).toBe(true);
    expect(src.includes('"owner"')).toBe(true);
    // Must redirect on unauthorized.
    expect(src.includes("Navigate")).toBe(true);
  });

  it("wrapper does NOT admit manager / marketer / technician / customer / sales", () => {
    const match = APP_JS.match(
      /function AdminOrOwnerForMarketingForms\([\s\S]*?\n\}/,
    );
    const src = match[0];
    // Explicit regression guard: owner must NOT bring the kitchen
    // sink. Each of these would open an unaudited surface.
    expect(src.includes("manager")).toBe(false);
    expect(src.includes("marketer")).toBe(false);
    expect(src.includes("technician")).toBe(false);
    expect(src.includes("customer")).toBe(false);
    expect(src.includes("sales")).toBe(false);
  });

  // ─────────────────────────────────────────────────────────────
  // 4. ONE route only
  // ─────────────────────────────────────────────────────────────
  it("only /admin/marketing/forms uses the new wrapper (no silent widen)", () => {
    const uses =
      APP_JS.match(/<AdminOrOwnerForMarketingForms>/g) || [];
    // The wrapper is used by exactly ONE route in App.js
    // (opening tag). The closing tag doubles the count — the
    // route emits ``<AdminOrOwnerForMarketingForms>...
    // </AdminOrOwnerForMarketingForms>`` on one line.
    // Opening-tag count must be exactly 1.
    expect(uses.length).toBe(1);
  });

  // ─────────────────────────────────────────────────────────────
  // 5. Email Builder-adjacent surfaces stay admin-only
  // ─────────────────────────────────────────────────────────────
  // Regression gate for the explicit scope-isolation decision:
  // widening owner to Marketing Forms must NOT bleed into other
  // admin-only marketing surfaces. These three are the ones that
  // share nav/UX adjacency with Marketing Forms today.
  it.each([
    "marketing/templates",
    "admin/marketing/automations",
    "admin/marketing/suppressions",
  ])(
    "route %s stays wrapped in <AdminOnly> (not the owner wrapper)",
    (route) => {
      const escaped = route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const stillAdminOnly = new RegExp(
        `path="${escaped}"\\s+element=\\{<AdminOnly>`,
      );
      const widenedToOwner = new RegExp(
        `path="${escaped}"\\s+element=\\{<AdminOrOwnerForMarketingForms>`,
      );
      expect(stillAdminOnly.test(APP_JS)).toBe(true);
      expect(widenedToOwner.test(APP_JS)).toBe(false);
    },
  );

  // ─────────────────────────────────────────────────────────────
  // 6. <AdminOnly> wrapper body unchanged — scope stays scoped
  // ─────────────────────────────────────────────────────────────
  it("<AdminOnly> definition remains admin + super_admin only (unchanged)", () => {
    const match = APP_JS.match(/function AdminOnly\([\s\S]*?\n\}/);
    expect(match).toBeTruthy();
    const src = match[0];
    expect(src.includes('"admin"')).toBe(true);
    expect(src.includes('"super_admin"')).toBe(true);
    // Owner MUST NOT be in the generic AdminOnly wrapper — if it
    // sneaks in, every one of the ~80 AdminOnly routes would
    // silently admit owner.  That's the Email Builder blast
    // radius we are explicitly guarding against.
    expect(src.includes('"owner"')).toBe(false);
  });
});
