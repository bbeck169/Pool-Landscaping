/**
 * Feb-2026 · Bug 1 parity test — ``<PortalInviteQuickAction>`` must
 * be mounted in BOTH the Overview tab and the Portal Access tab so
 * both surfaces render an identical Send Portal Invite CTA for the
 * same customer state.
 *
 * These are source-level structural assertions (matching the style
 * of ``customer-portal-invite-relocation.test.jsx``) — they lock the
 * dual-mount contract without needing a full render harness.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve(__dirname, "../pages/customers/CustomerDetail.jsx"),
  "utf8",
);

describe("Bug 1 — Send Portal Invite parity on both surfaces", () => {
  it("PortalInviteQuickAction is mounted at least twice", () => {
    // One inside the Overview tab (existing), one inside
    // PortalAccessPanel (Bug 1 fix). Additional mounts are fine.
    const matches = SRC.match(/<PortalInviteQuickAction\b/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("PortalAccessPanel mounts PortalInviteQuickAction", () => {
    const panelIdx = SRC.indexOf("function PortalAccessPanel");
    expect(panelIdx).toBeGreaterThan(-1);
    const panelBody = SRC.slice(panelIdx);
    // The dual-mount must be INSIDE the PortalAccessPanel body,
    // not somewhere below it in an unrelated component. The panel
    // is the LAST major component in the file, so if the mount is
    // present in the panel slice it can't be orphaned in a later
    // component. Locked with a generous cap to allow the panel to
    // grow without churning this test.
    const quickInPanelIdx = panelBody.indexOf("<PortalInviteQuickAction");
    expect(quickInPanelIdx).toBeGreaterThan(-1);
    expect(quickInPanelIdx).toBeLessThan(8000);
  });

  it("Overview mount is preserved (top action stack — Feb-2026 relocation)", () => {
    // Feb-2026 · Top-action-stack relocation moved the Overview
    // PortalInviteQuickAction from below CustomerContactsPanel to
    // the top action stack (above the header card). The Overview
    // surface still renders the button — it's just higher up on
    // the page now. Assert the button appears BEFORE the header /
    // contacts panel to lock the new invariant.
    const stackIdx = SRC.indexOf(
      'data-testid="customer-detail-top-action-stack"',
    );
    const contactsIdx = SRC.indexOf("<CustomerContactsPanel");
    const firstQuickIdx = SRC.indexOf("<PortalInviteQuickAction");
    expect(stackIdx).toBeGreaterThan(-1);
    expect(contactsIdx).toBeGreaterThan(-1);
    expect(firstQuickIdx).toBeGreaterThan(-1);
    // First mount lives INSIDE the top stack, BEFORE the contacts
    // panel — flipped from the pre-Feb-2026 order.
    expect(firstQuickIdx).toBeGreaterThan(stackIdx);
    expect(firstQuickIdx).toBeLessThan(contactsIdx);
  });

  it("Same handler + endpoint used by both mounts (no fork)", () => {
    // Both mounts render the SAME ``PortalInviteQuickAction``
    // component — so the endpoint / handler / toast copy are
    // shared by construction. Assert the component still POSTs to
    // the exact backend endpoint.
    const compIdx = SRC.indexOf("function PortalInviteQuickAction(");
    const compBody = SRC.slice(compIdx, SRC.indexOf("\n}\n", compIdx));
    expect(compBody).toMatch(
      /api\.post\(`\/customers\/\$\{customer\.id\}\/portal-invite`\)/,
    );
    // Same disabled-when-no-email gate applies to both mounts.
    expect(compBody).toMatch(/disabled=\{busy \|\| !hasEmail\}/);
  });

  it("Manual create button still exists in Portal Access panel", () => {
    // Regression guard — the Bug 1 fix must not have removed the
    // existing "Manual create…" affordance (separate flow: admin
    // sets password directly via the login modal).
    expect(SRC).toMatch(/testid="cd-portal-manual-create"/);
    expect(SRC).toMatch(/Manual create/);
  });
});
