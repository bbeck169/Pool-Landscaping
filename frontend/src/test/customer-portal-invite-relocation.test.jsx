/**
 * Feb-2026 · Send Portal Invite button relocation — source-inspection
 * tests.
 *
 * Same pattern as ``customer-detail-action-row.test.jsx``: we don't
 * mount the whole page (heavy — dozens of dependencies), we inspect
 * the JSX source directly so the layout contract stays locked
 * without needing to spin the full render tree.
 *
 * Contract locked:
 *   1. ``cd-portal-invite`` testid EXISTS somewhere in the page.
 *   2. That testid lives INSIDE the new ``PortalInviteQuickAction``
 *      quick-action component (mounted in the Overview tab, right
 *      after the Contact panel — NOT the old Portal Access tab).
 *   3. The Portal Access tab source NO LONGER emits the button
 *      (regression guard — no duplicate placement).
 *   4. Disabled-state affordance: the button is disabled when
 *      ``customer.email`` is empty (via the ``!hasEmail`` prop),
 *      with the exact tooltip the spec requires.
 *   5. Handler reuses the exact backend endpoint the old placement
 *      called: ``/customers/{id}/portal-invite`` — byte-identical
 *      behaviour.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");
const src = readFileSync(PAGE_PATH, "utf8");


describe("Send Portal Invite · relocation to main Contact card", () => {
  it("1. cd-portal-invite testid still exists on the page", () => {
    expect(src).toMatch(/testid="cd-portal-invite"/);
  });

  it("2. testid lives inside the new PortalInviteQuickAction component", () => {
    // The quick-action component is defined at file top; assert it
    // exists AND owns the cd-portal-invite testid.
    expect(src).toMatch(/function PortalInviteQuickAction\(/);
    const compIdx = src.indexOf("function PortalInviteQuickAction(");
    const compEnd = src.indexOf("\n}\n", compIdx);
    expect(compEnd).toBeGreaterThan(compIdx);
    const compBody = src.slice(compIdx, compEnd);
    expect(compBody).toMatch(/testid="cd-portal-invite"/);
    // The component is also mounted from the Overview tab.
    expect(src).toMatch(/<PortalInviteQuickAction\b/);
  });

  it("3. Portal Access panel source no longer emits the button", () => {
    // Locate the PortalAccessPanel function; assert nothing inside
    // renders the "Send portal invite" button anymore.  The old
    // implementation used exact copy "Send portal invite" and
    // ``doAction("portal-invite", ...)`` inline.
    const panelIdx = src.indexOf("function PortalAccessPanel");
    expect(panelIdx).toBeGreaterThan(-1);
    // Slice everything after the panel's definition; the moved
    // block appears BEFORE this function so a later match is safe.
    const panelBody = src.slice(panelIdx);
    // The old inline "Send portal invite" call MUST be gone from
    // this panel (moved to the quick-action component).
    expect(panelBody).not.toMatch(
      /doAction\("portal-invite", "Portal invite"\)/,
    );
    expect(panelBody).not.toMatch(/Send portal invite/);
  });

  it("4. Button is disabled when customer has no email + tooltip present", () => {
    const compIdx = src.indexOf("function PortalInviteQuickAction(");
    const compBody = src.slice(compIdx, src.indexOf("\n}\n", compIdx));
    // Disabled expression combines the busy flag with the hasEmail
    // presence check — matches the spec's disabled-state affordance.
    expect(compBody).toMatch(/disabled=\{busy \|\| !hasEmail\}/);
    // Tooltip copy locked to the spec's exact wording.
    expect(compBody).toMatch(
      /title=\{!hasEmail\s*\?\s*"Add customer email to send portal invite"/,
    );
  });

  it("5. Handler POSTs to the exact same backend endpoint the old button used", () => {
    const compIdx = src.indexOf("function PortalInviteQuickAction(");
    const compBody = src.slice(compIdx, src.indexOf("\n}\n", compIdx));
    expect(compBody).toMatch(
      /api\.post\(`\/customers\/\$\{customer\.id\}\/portal-invite`\)/,
    );
  });

  it("6. Quick-action is mounted inside the Overview tab, after CustomerContactsPanel", () => {
    // The Overview branch mounts CustomerContactsPanel then the
    // new quick-action.  Assert lexical order to lock placement.
    const contactsIdx = src.indexOf("<CustomerContactsPanel");
    const quickIdx    = src.indexOf("<PortalInviteQuickAction");
    expect(contactsIdx).toBeGreaterThan(-1);
    expect(quickIdx).toBeGreaterThan(contactsIdx);
  });
});
