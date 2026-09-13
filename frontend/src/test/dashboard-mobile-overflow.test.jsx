/**
 * dashboard-mobile-overflow · Feb-2026
 *
 * Feb-2026 · Mobile Nav Overflow Fix (regression guard).
 *
 * Locks two contracts introduced by the AdminTopBar mobile fix:
 *
 *   1. The narrow-branch wrap sets ``overflow-x-auto`` so the
 *      internal right-cluster (Add Customer + Credits + Test-as
 *      switcher + Settings + Sign out + Bell) can be wider than the
 *      viewport WITHOUT propagating horizontal overflow to
 *      ``document.documentElement`` — swiping the bar reveals the
 *      bell / signout at the far right instead of blowing out the
 *      whole page.
 *
 *   2. Both flex groups inside the narrow branch carry
 *      ``flex-shrink-0`` so no icon gets squished when the cluster
 *      exceeds viewport width.
 *
 * Guarded via a source-string smoke test (identical pattern to the
 * sibling ``admin-top-bar-mobile-role-preview-switcher`` suite) so
 * the assertion doesn't drag in the full 500-LOC AdminTopBar into a
 * runtime render.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ATOP_BAR = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);


describe("AdminTopBar narrow-branch · mobile overflow guard", () => {
  it("outer narrow wrap declares overflow-x-auto", () => {
    const anchor = ATOP_BAR.indexOf(
      'data-testid="admin-topbar-narrow-wrap"',
    );
    expect(anchor).toBeGreaterThan(-1);
    // Slice back to the opening <div — the className string sits
    // between them.
    const openTag = ATOP_BAR.slice(
      ATOP_BAR.lastIndexOf("<div", anchor), anchor + 200,
    );
    expect(openTag).toMatch(/overflow-x-auto/);
  });

  it("right-cluster flex group carries flex-shrink-0 (no squished icons)", () => {
    const anchor = ATOP_BAR.indexOf(
      'data-testid="admin-topbar-narrow-wrap"',
    );
    // Walk forward from the wrap testid to the inner right-cluster
    // group. The right cluster is the one that contains
    // ``AddCustomerButton`` and ``CreditsBudgetChip`` — its opening
    // <div must include ``flex-shrink-0``.
    const branch = ATOP_BAR.slice(anchor).split(
      "data-testid=\"admin-topbar-wide-wrap\"",
    )[0];
    // First candidate flex-group with AddCustomerButton in its slice.
    const rightGroupMatch = branch.match(
      /<div\s+className="flex\s+items-center\s+gap-2\s+flex-shrink-0"[\s\S]*?AddCustomerButton/,
    );
    expect(rightGroupMatch).not.toBeNull();
  });
});
