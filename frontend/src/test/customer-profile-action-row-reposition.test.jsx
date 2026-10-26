/**
 * Phase 20 · Feb-2026 — Customer Profile Action-Row Reposition.
 *
 * The prior session (``CUSTOMER-PROFILE-ACTION-BAR`` · Feb-2026
 * Phase 2) unified every affordance on CustomerDetail into a
 * single flex-row strip.  Phase 20 RELOCATES the action-bar
 * portion of that strip (Edit / Merge / Issue Credit / Mark
 * Correction / Call / Delete / Move to Trash + mobile kebab)
 * into its OWN dedicated full-width row that renders ABOVE the
 * Send / Create / Overview tabs row.
 *
 * Expected DOM / source order on CustomerDetail.jsx:
 *   [Portal Access tiles (CardOnFileWarningBanner + Portal Invite)]
 *   [``cd-command-strip``       -> ``cd-action-row``]  // actions
 *   [``cd-command-strip-tabs``  -> ``cd-tabs-row``]    // tabs
 *   [Header card comment marker]
 *
 * Preservation contract:
 *   • All 7 action-row testids kept byte-for-byte (cd-edit,
 *     cd-merge-btn, cd-issue-credit-btn, cd-account-correction-
 *     btn, cd-click-to-call-wrapper, cd-delete, cd-hard-delete-
 *     btn).
 *   • Mobile kebab (``cd-mobile-kebab-wrapper`` + 6 kebab items)
 *     stays in the ACTION row — unchanged behavior below ``md:``.
 *   • Role gates (canMerge / canIssueCredit /
 *     canToggleAccountCorrection / canHardDelete) unchanged.
 *   • No handler, modal, or confirmation flow rewritten — pure
 *     positional move.
 *   • ``cd-tabs-dropdown-shell`` compact shell (minWidth 220)
 *     preserved, now sitting in the tabs row.
 *
 * Source-inspection pattern — fast, deterministic, no React
 * render, no provider mount.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname,
  "../pages/customers/CustomerDetail.jsx");
const SRC = readFileSync(PAGE_PATH, "utf8");


describe("Phase 20 · action row renders ABOVE the tabs row", () => {
  it("cd-action-row precedes cd-tabs-row in source order", () => {
    const actionRowIdx = SRC.indexOf('data-testid="cd-action-row"');
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    expect(actionRowIdx).toBeGreaterThan(-1);
    expect(tabsRowIdx).toBeGreaterThan(-1);
    expect(actionRowIdx).toBeLessThan(tabsRowIdx);
  });

  it("cd-command-strip (actions) precedes cd-command-strip-tabs in source order", () => {
    const stripIdx = SRC.indexOf('data-testid="cd-command-strip"');
    const tabsStripIdx = SRC.indexOf('data-testid="cd-command-strip-tabs"');
    expect(stripIdx).toBeGreaterThan(-1);
    expect(tabsStripIdx).toBeGreaterThan(-1);
    expect(stripIdx).toBeLessThan(tabsStripIdx);
  });

  it("both strips sit BELOW Portal Access (Phase 28 moved Header card above Portal Access)", () => {
    // Phase 28 · Feb-2026 — the identity ("Header card") was
    // repositioned to render ABOVE the Phase-20 command strip +
    // Portal Access so the customer's identity is the first thing
    // visible after the breadcrumb.  The Phase-20 contract
    // ``strips sit BELOW Portal Access`` still holds; the former
    // tail of the chain (``AND ABOVE the Header card``) no longer
    // reflects the real DOM — the Header card now precedes the
    // whole chain in source order.
    const portalIdx = SRC.indexOf("<PortalInviteQuickAction");
    const stripIdx = SRC.indexOf('data-testid="cd-command-strip"');
    const tabsStripIdx = SRC.indexOf('data-testid="cd-command-strip-tabs"');
    const headerCardIdx = SRC.indexOf("{/* Header card */}");
    expect(portalIdx).toBeGreaterThan(-1);
    expect(headerCardIdx).toBeGreaterThan(-1);
    // Phase-28 source order: Header card → PortalInvite → actions
    // strip → tabs strip.
    expect(headerCardIdx).toBeLessThan(portalIdx);
    expect(stripIdx).toBeGreaterThan(portalIdx);
    expect(tabsStripIdx).toBeGreaterThan(stripIdx);
  });
});


describe("Phase 20 · action row is full-width and dedicated to actions", () => {
  it("cd-action-row does NOT host the tabs/overview dropdown shell", () => {
    // Scope: content between cd-action-row open and the end of
    // its enclosing <div> (i.e. before the next strip opens).
    const actionRowIdx = SRC.indexOf('data-testid="cd-action-row"');
    const tabsStripIdx = SRC.indexOf('data-testid="cd-command-strip-tabs"');
    expect(actionRowIdx).toBeGreaterThan(-1);
    expect(tabsStripIdx).toBeGreaterThan(actionRowIdx);
    const actionBlock = SRC.slice(actionRowIdx, tabsStripIdx);
    expect(actionBlock).not.toContain('data-testid="cd-tabs-dropdown-shell"');
    // Nor the Send/Create wrapper.
    expect(actionBlock).not.toContain("<CustomerActionDropdowns");
  });

  it("cd-tabs-row hosts the Overview dropdown ONLY; Send/Create/Portal moved to identity header (Ticket HH)", () => {
    // Phase 28 · Feb-2026 — ``{/* Header card */}`` was moved
    // ABOVE cd-tabs-row.  Use the next sibling sentinel —
    // ``{/* Feb-2026 · Tabs — the standalone`` — to bound the
    // tabs-row block.
    //
    // Ticket HH · Feb-2026 — ``<CustomerActionDropdowns>`` was
    // relocated from the tabs-row into the identity header
    // (``cd-identity-header-actions`` slot above the H1 name).
    // The tabs-row now carries ONLY the Overview tabs dropdown.
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    const nextSiblingIdx = SRC.indexOf(
      "{/* Feb-2026 · Tabs — the standalone", tabsRowIdx);
    expect(tabsRowIdx).toBeGreaterThan(-1);
    expect(nextSiblingIdx).toBeGreaterThan(tabsRowIdx);
    const tabsBlock = SRC.slice(tabsRowIdx, nextSiblingIdx);
    expect(tabsBlock).not.toContain("<CustomerActionDropdowns");
    expect(tabsBlock).toContain('data-testid="cd-tabs-dropdown-shell"');
    // Positive HH lock — the dropdowns live inside the identity
    // header slice now, between the pill row and the H1.
    const idHeaderIdx = SRC.indexOf('data-testid="cd-identity-header"');
    const h1Idx = SRC.indexOf(
      'data-testid="customer-detail-inline-h1"', idHeaderIdx);
    expect(idHeaderIdx).toBeGreaterThan(-1);
    expect(h1Idx).toBeGreaterThan(idHeaderIdx);
    const idSlice = SRC.slice(idHeaderIdx, h1Idx);
    expect(idSlice).toContain('data-testid="cd-identity-header-actions"');
    expect(idSlice).toContain("<CustomerActionDropdowns");
  });

  it("action row has NO flex-1 spacer — left-aligned buttons by natural flex order", () => {
    // The pre-Phase-20 single-row layout used
    // ``cd-action-row-spacer`` (flex-1) to push the right group
    // to the right side of the shared row.  Phase 20 retires
    // that spacer so the dedicated action row left-aligns.
    expect(SRC).not.toMatch(/data-testid="cd-action-row-spacer"/);
  });

  it("cd-action-row carries the same flex-row chrome as the tabs row", () => {
    const actionRowIdx = SRC.indexOf('data-testid="cd-action-row"');
    const actionSlice = SRC.slice(actionRowIdx - 200, actionRowIdx + 60);
    expect(actionSlice).toMatch(/flex[- ]row/);
    expect(actionSlice).toMatch(/flex-nowrap/);
    expect(actionSlice).toMatch(/overflow-x-auto/);
    // Same contract on the tabs row.
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    const tabsSlice = SRC.slice(tabsRowIdx - 200, tabsRowIdx + 60);
    expect(tabsSlice).toMatch(/flex[- ]row/);
    expect(tabsSlice).toMatch(/flex-nowrap/);
    expect(tabsSlice).toMatch(/overflow-x-auto/);
  });
});


describe("Phase 20 · buttons appear in expected source-order within the action row", () => {
  it("Edit → Merge → Issue Credit → Mark Correction → Call → Delete → Move to Trash", () => {
    const actionRowIdx = SRC.indexOf('data-testid="cd-action-row"');
    const tabsStripIdx = SRC.indexOf('data-testid="cd-command-strip-tabs"');
    const block = SRC.slice(actionRowIdx, tabsStripIdx);

    const editIdx       = block.indexOf('testid="cd-edit"');
    const mergeIdx      = block.indexOf('testid="cd-merge-btn"');
    const creditIdx     = block.indexOf('testid="cd-issue-credit-btn"');
    const correctionIdx = block.indexOf('testid="cd-account-correction-btn"');
    const callIdx       = block.indexOf('data-testid="cd-click-to-call-wrapper"');
    const deleteIdx     = block.indexOf('testid="cd-delete"');
    const trashIdx      = block.indexOf('testid="cd-hard-delete-btn"');

    for (const [name, idx] of [
      ["cd-edit", editIdx],
      ["cd-merge-btn", mergeIdx],
      ["cd-issue-credit-btn", creditIdx],
      ["cd-account-correction-btn", correctionIdx],
      ["cd-click-to-call-wrapper", callIdx],
      ["cd-delete", deleteIdx],
      ["cd-hard-delete-btn", trashIdx],
    ]) {
      expect(idx, `${name} missing from action-row block`).toBeGreaterThan(-1);
    }
    // Source order lock.
    expect(editIdx).toBeLessThan(mergeIdx);
    expect(mergeIdx).toBeLessThan(creditIdx);
    expect(creditIdx).toBeLessThan(correctionIdx);
    expect(correctionIdx).toBeLessThan(callIdx);
    expect(callIdx).toBeLessThan(deleteIdx);
    expect(deleteIdx).toBeLessThan(trashIdx);
  });
});


describe("Phase 20 · mobile kebab-collapse behavior preserved", () => {
  it("cd-mobile-kebab-wrapper is still md:hidden and sits in the action row", () => {
    const actionRowIdx = SRC.indexOf('data-testid="cd-action-row"');
    const tabsStripIdx = SRC.indexOf('data-testid="cd-command-strip-tabs"');
    const block = SRC.slice(actionRowIdx, tabsStripIdx);
    expect(block).toContain('data-testid="cd-mobile-kebab-wrapper"');
    // md:hidden on the kebab wrapper + hidden md:inline-flex on
    // the two right groups — same as pre-Phase-20.
    expect(SRC).toMatch(
      /className="md:hidden"\s*\n?\s*data-testid="cd-mobile-kebab-wrapper"/,
    );
    expect(SRC).toMatch(
      /className="hidden md:inline-flex[^"]*"\s*\n?\s*data-testid="cd-action-row-right-primary"/,
    );
    expect(SRC).toMatch(
      /className="hidden md:inline-flex[^"]*"\s*\n?\s*data-testid="cd-action-row-right-destructive"/,
    );
  });

  it("kebab items still mirror the inline right-group affordances", () => {
    for (const tid of [
      "cd-mobile-kebab-edit",
      "cd-mobile-kebab-merge",
      "cd-mobile-kebab-issue-credit",
      "cd-mobile-kebab-correction",
      "cd-mobile-kebab-delete",
      "cd-mobile-kebab-trash",
    ]) {
      expect(SRC).toContain(`data-testid="${tid}"`);
    }
    expect(SRC).toMatch(/testid="cd-mobile-kebab-trigger"/);
  });

  it("mobile kebab is NOT scattered into the tabs row", () => {
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    const headerCardIdx = SRC.indexOf("{/* Header card */}", tabsRowIdx);
    const tabsBlock = SRC.slice(tabsRowIdx, headerCardIdx);
    expect(tabsBlock).not.toContain('data-testid="cd-mobile-kebab-wrapper"');
    expect(tabsBlock).not.toContain('testid="cd-mobile-kebab-trigger"');
  });
});


describe("Phase 20 · wiring preservation (no handler rewritten)", () => {
  it("every pre-Phase-20 action handler expression is still present", () => {
    // These are the exact onClick / onSelect expressions
    // from the pre-Phase-20 single-row layout.  A positional
    // move must NOT rewrite them.
    const HANDLERS = [
      /onClick=\{\(\) => navigate\(`\/customers\/\$\{id\}\/edit`\)\}/,          // cd-edit
      /onClick=\{\(\) => setMergeOpen\(true\)\}/,                                // cd-merge
      /onClick=\{openIssueCreditModal\}/,                                        // cd-issue-credit
      /setAccountCorrectionNote\(""\);\s*\n\s*setAccountCorrectionOpen\(true\)/, // cd-account-correction
      /onClick=\{\(\) => setConfirmDelete\(true\)\}/,                            // cd-delete
      /onClick=\{\(\) => setHardDeleteOpen\(true\)\}/,                           // cd-hard-delete
    ];
    for (const re of HANDLERS) {
      expect(SRC).toMatch(re);
    }
  });

  it("role gate expressions unchanged (regression lock)", () => {
    // Admin-only hard delete, admin / super_admin / owner for
    // merge, widened manager + owner for Issue Credit and
    // Mark Correction (shared via canToggleAccountCorrection).
    expect(SRC).toMatch(
      /const canHardDelete = \["admin", "super_admin"\]\.includes\(roleLower\)/,
    );
    expect(SRC).toMatch(
      /const canMerge = \["admin", "super_admin", "owner"\]\.includes\(roleLower\)/,
    );
    expect(SRC).toMatch(
      /const canIssueCredit = \["admin", "super_admin", "manager", "owner"\][\s\S]{0,80}\.includes\(\(meRole \|\| ""\)\.toLowerCase\(\)\)/,
    );
    expect(SRC).toMatch(/const canToggleAccountCorrection = canIssueCredit/);
  });

  it("every pre-Phase-20 testid preserved byte-for-byte", () => {
    const TESTIDS = [
      "cd-command-strip",
      "cd-action-row",
      "cd-action-row-right-primary",
      "cd-action-row-right-destructive",
      "cd-edit",
      "cd-merge-btn",
      "cd-issue-credit-btn",
      "cd-account-correction-btn",
      "cd-click-to-call-wrapper",
      "cd-click-to-call-tel-fallback",
      "cd-delete",
      "cd-hard-delete-btn",
      "cd-mobile-kebab-wrapper",
      "cd-mobile-kebab-trigger",
      "cd-mobile-kebab-edit",
      "cd-mobile-kebab-merge",
      "cd-mobile-kebab-issue-credit",
      "cd-mobile-kebab-correction",
      "cd-mobile-kebab-delete",
      "cd-mobile-kebab-trash",
      "cd-tabs-dropdown-shell",
    ];
    for (const tid of TESTIDS) {
      expect(SRC).toMatch(
        new RegExp(`testid="${tid}"|data-testid="${tid}"`),
      );
    }
  });
});
