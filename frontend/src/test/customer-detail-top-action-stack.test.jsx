/**
 * Feb-2026 · Customer detail — top action stack order.
 *
 * Locks in the layout invariant that on the admin Customer detail
 * page the "Add card on file" (CardOnFileWarningBanner) button and
 * the "Send Portal Invite" (PortalInviteQuickAction) button live in
 * a single vertical stack near the top of the page, with the
 * card-on-file button ABOVE the portal-invite button.
 *
 * Source-body assertions (mirrors the P43 / K49 / K71 patterns
 * used across this suite). Any regression that:
 *   * decouples the two components (splits them across containers),
 *   * flips their vertical order,
 *   * reintroduces a second ``PortalInviteQuickAction`` render on
 *     the Overview tab, OR
 *   * drops the wrapper testid
 * is caught by CI.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomerDetail.jsx"),
  "utf-8",
);


describe("CustomerDetail · top action stack order (Feb-2026)", () => {
  it("wraps the two actions in a labelled stack container", () => {
    expect(SRC).toMatch(
      /data-testid="customer-detail-top-action-stack"/,
    );
  });

  it("renders CardOnFileWarningBanner ABOVE PortalInviteQuickAction inside the stack", () => {
    // Match the entire stack block and confirm the two components
    // appear in the required order inside the same container.
    const stackMatch = SRC.match(
      /data-testid="customer-detail-top-action-stack"[\s\S]*?<\/div>\s*\)\}/,
    );
    expect(stackMatch).toBeTruthy();
    const block = stackMatch[0];
    const idxBanner = block.indexOf("<CardOnFileWarningBanner");
    const idxInvite = block.indexOf("<PortalInviteQuickAction");
    expect(idxBanner).toBeGreaterThan(-1);
    expect(idxInvite).toBeGreaterThan(-1);
    expect(idxBanner).toBeLessThan(idxInvite);
  });

  it("renders PortalInviteQuickAction exactly ONCE on the Overview surface (top stack only)", () => {
    // Two total occurrences are still allowed: one in the top stack
    // (Overview surface) + one inside the Portal Access tab body.
    // The former Overview-tab duplicate MUST be gone.
    const total = (SRC.match(/<PortalInviteQuickAction/g) || []).length;
    expect(total).toBe(2);
  });

  it("preserves the pre-existing PortalInviteQuickAction test-id (no logic change)", () => {
    // The component itself exposes ``testid="cd-portal-invite"`` — the
    // relocation must NOT rename it. This is the CI guard for the
    // "layout only, preserve test-ids" contract.
    expect(SRC).not.toMatch(/testid="portal-invite-top-stack"/);
    // The component source still owns the canonical test-id.
    const componentSrc = fs.readFileSync(
      path.resolve(process.cwd(), "src/pages/customers/CustomerDetail.jsx"),
      "utf-8",
    );
    expect(componentSrc).toMatch(/testid="cd-portal-invite"/);
  });

  it("preserves the CardOnFileWarningBanner send-link button test-id", () => {
    const bannerSrc = fs.readFileSync(
      path.resolve(
        process.cwd(),
        "src/components/customers/CardOnFileWarningBanner.jsx",
      ),
      "utf-8",
    );
    expect(bannerSrc).toMatch(/data-testid="card-on-file-send-link-btn"/);
  });

  it("keeps the same admin-visibility gate on the stack (canSeeCardControls)", () => {
    // The stack must remain wrapped in ``{canSeeCardControls && (...)}``
    // so techs never see either action. Regression guard.
    expect(SRC).toMatch(
      /\{canSeeCardControls && \(\s*<div\s+className="space-y-2 mb-4"\s+data-testid="customer-detail-top-action-stack"/,
    );
  });
});
