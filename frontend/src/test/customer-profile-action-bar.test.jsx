/**
 * CUSTOMER-PROFILE-ACTION-BAR · Phase 20 · Feb-2026 — ACTION ROW
 * RELOCATED to its own dedicated full-width row ABOVE the tabs
 * row.
 *
 * Prior session: Feb-2026 Phase 2 unified every affordance
 * (Send / Create / Overview / Edit / Merge / Issue Credit / Mark
 * Correction / Call / Delete / Move to Trash + mobile kebab)
 * into a SINGLE flex-row. Phase 20 splits that single row back
 * into two rows but preserves the single-row's unification goals
 * (shared NAVY_* className constants, kebab mirroring, role
 * gate reuse) byte-for-byte.
 *
 * Layout contract (post-Phase-20):
 *   • ROW 1 — ``cd-command-strip`` wraps a ``cd-action-row``
 *     flex-row with LEFT-ALIGNED buttons: Edit / Merge / Credit /
 *     Correction / Call / Delete / Trash + mobile kebab. No
 *     flex-1 spacer — the row is dedicated to actions only.
 *   • ROW 2 — ``cd-command-strip-tabs`` wraps a ``cd-tabs-row``
 *     flex-row holding Send / Create (CustomerActionDropdowns)
 *     + Overview (ResponsiveTabs forceDropdown via
 *     ``cd-tabs-dropdown-shell``). Hosts ONLY tab-navigation
 *     affordances.
 *   • Both strips share the navy chrome (rounded-2xl mb-4 px-3
 *     py-3 + colors.nav.bg) for visual coherence.
 *   • Below ``md:`` the Edit / Merge / Credit / Correction /
 *     Delete / Trash set still collapses into ``cd-mobile-kebab-
 *     trigger``; only Call + kebab stay visible on narrow
 *     viewports in Row 1. The tabs row (Row 2) is unaffected by
 *     the kebab collapse.
 *   • Shared className constants (``BTN_BASE``, ``NAVY_OUTLINE``,
 *     ``NAVY_DANGER``, ``NAVY_WARN``) remain the single source
 *     of truth for navy-adapted button styles.
 *   • Role filtering on the kebab items mirrors the inline
 *     buttons' role gates — zero behavioural drift between the
 *     two surfaces.
 *
 * Source-inspection pattern (same as
 * ``customer-detail-navy-command-strip.test.jsx`` and
 * ``customer-detail-action-row.test.jsx``) — no React render,
 * no provider mount, no window.  Fast, deterministic,
 * environment-free.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname,
  "../pages/customers/CustomerDetail.jsx");
const ACTIONS_PATH = resolve(__dirname,
  "../components/customers/CustomerActionDropdowns.jsx");
const pageSrc = readFileSync(PAGE_PATH, "utf8");
const actionsSrc = readFileSync(ACTIONS_PATH, "utf8");


describe("Customer profile action bar · single-row layout", () => {
  it("cd-command-strip is a container (no flex-col row-split)", () => {
    // Container only carries padding + rounded-2xl.  The inner
    // ``cd-action-row`` owns the flex layout now.
    const idx = pageSrc.indexOf('data-testid="cd-command-strip"');
    expect(idx).toBeGreaterThan(-1);
    const openIdx = pageSrc.lastIndexOf("<div", idx);
    const slice = pageSrc.slice(openIdx, idx + 60);
    expect(slice).toMatch(/className="rounded-2xl mb-4 px-3 py-3"/);
    expect(slice).not.toMatch(/flex-col/);
  });

  it("cd-action-row is a single flex-row with nowrap + overflow", () => {
    const rowIdx = pageSrc.indexOf('data-testid="cd-action-row"');
    expect(rowIdx).toBeGreaterThan(-1);
    const slice = pageSrc.slice(rowIdx - 200, rowIdx + 60);
    expect(slice).toMatch(/flex[- ]row/);
    expect(slice).toMatch(/flex-nowrap/);
    expect(slice).toMatch(/overflow-x-auto/);
  });

  it("Overview dropdown lives in the TABS row below cd-action-row (Phase 20)", () => {
    // Phase 20 · Feb-2026 — Overview was relocated OUT of
    // ``cd-action-row`` into its own ``cd-tabs-row`` sibling
    // beneath the action row.  Both rows share the navy chrome
    // but each strip hosts a distinct affordance set.  The tabs
    // row carries ``cd-tabs-dropdown-shell``; the action row no
    // longer does.
    const actionRowIdx = pageSrc.indexOf('data-testid="cd-action-row"');
    expect(actionRowIdx).toBeGreaterThan(-1);
    const tabsRowIdx = pageSrc.indexOf('data-testid="cd-tabs-row"');
    expect(tabsRowIdx).toBeGreaterThan(actionRowIdx);
    // ``cd-tabs-dropdown-shell`` sits on the tabs row — AFTER
    // the action row in DOM / source order.
    const shellIdx = pageSrc.indexOf('data-testid="cd-tabs-dropdown-shell"');
    expect(shellIdx).toBeGreaterThan(actionRowIdx);
    expect(shellIdx).toBeGreaterThan(tabsRowIdx);
    // The retired Row-2 white shell is still gone.
    expect(pageSrc).not.toContain("cd-tabs-dropdown-shell-light");
  });

  it("action row has NO flex-1 spacer — buttons left-align in the dedicated row (Phase 20)", () => {
    // Phase 20 · Feb-2026 — ``cd-action-row-spacer`` is retired.
    // The pre-Phase-20 single-row layout used a ``flex-1``
    // spacer to push the right-group buttons to the right of
    // the shared row.  In the new split layout the action row
    // is DEDICATED, so buttons simply left-align via normal
    // flex-row order — the spacer is removed.
    expect(pageSrc).not.toMatch(/data-testid="cd-action-row-spacer"/);
  });

  it("Phase 20 — a second navy strip (cd-command-strip-tabs) renders below the action strip", () => {
    // The two strips share the navy chrome contract — same
    // rounded-2xl mb-4 px-3 py-3 wrapper + colors.nav.bg
    // background.  The second strip hosts the tabs row and must
    // appear AFTER the first strip in source order.
    const stripIdx = pageSrc.indexOf('data-testid="cd-command-strip"');
    const tabsStripIdx = pageSrc.indexOf('data-testid="cd-command-strip-tabs"');
    expect(stripIdx).toBeGreaterThan(-1);
    expect(tabsStripIdx).toBeGreaterThan(stripIdx);
    // Second strip also carries the navy chrome contract.
    const openIdx = pageSrc.lastIndexOf("<div", tabsStripIdx);
    const slice = pageSrc.slice(openIdx, tabsStripIdx + 60);
    expect(slice).toMatch(/className="rounded-2xl mb-4 px-3 py-3"/);
    expect(slice).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
  });
});


describe("Customer profile action bar · navy className constants", () => {
  it("declares BTN_BASE + NAVY_OUTLINE + NAVY_DANGER + NAVY_WARN", () => {
    // The four shared className constants are the single source
    // of truth for navy-adapted button styles.  Any future tweak
    // to the strip's hover / focus / border treatment touches
    // ONE place.
    expect(pageSrc).toMatch(/const\s+BTN_BASE\s*=/);
    expect(pageSrc).toMatch(/const\s+NAVY_OUTLINE\s*=/);
    expect(pageSrc).toMatch(/const\s+NAVY_DANGER\s*=/);
    expect(pageSrc).toMatch(/const\s+NAVY_WARN\s*=/);
  });

  it("BTN_BASE carries px-2.5 py-1 text-xs + whitespace-nowrap", () => {
    expect(pageSrc).toMatch(
      /const\s+BTN_BASE\s*=\s*[\s\S]{0,80}px-2\.5 py-1 text-xs whitespace-nowrap/,
    );
  });

  it("all 7 inline right-group buttons apply BTN_BASE + a NAVY_* variant", () => {
    // Edit / Merge / Credit / Correction / Delete / Trash /
    // Kebab trigger — each one uses the templated className
    // ``${BTN_BASE} ${NAVY_*}``.  Count ≥ 7 means every button
    // in the right group picked up the constants.
    const matches = pageSrc.match(/\$\{BTN_BASE\} \$\{NAVY_/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(7);
  });
});


describe("Customer profile action bar · role-gated button set", () => {
  // Source-inspection cannot evaluate role flags at runtime, but
  // it CAN verify every button's role gate expression is still
  // wired.  Combined with the mobile-kebab mirror below, this
  // locks the role matrix to:
  //
  //   admin / super_admin  → 10 affordances
  //                           (Send+Create via dropdowns [2],
  //                            Overview, Edit, Merge, Credit,
  //                            Correction, Call, Delete, Trash)
  //   manager              → 8  (no Merge, no Trash)
  //   owner                → 9  (no Trash)
  //   tech                 → 6  (Send/Create/Overview/Edit/
  //                                Delete/Call — unconditional)
  it("Edit button is unconditional (visible to every role)", () => {
    // No role-gate wrapper around cd-edit — matches tech-visible
    // minimum.
    const editIdx = pageSrc.indexOf('testid="cd-edit"');
    expect(editIdx).toBeGreaterThan(-1);
    const before = pageSrc.slice(Math.max(0, editIdx - 500), editIdx);
    // No ``canXxx ?`` or ``[...].includes(...) ?`` directly
    // preceding the <Button>.  The last conditional ternary before
    // Edit is actually the overarching IIFE / spacer render — so
    // we assert the IMMEDIATE wrapper is the right-primary div.
    expect(before).toMatch(/data-testid="cd-action-row-right-primary"/);
  });

  it("Delete button is unconditional (visible to every role)", () => {
    const deleteIdx = pageSrc.indexOf('testid="cd-delete"');
    expect(deleteIdx).toBeGreaterThan(-1);
    const before = pageSrc.slice(Math.max(0, deleteIdx - 300), deleteIdx);
    // The right-destructive wrapper is the immediate parent.
    expect(before).toMatch(/data-testid="cd-action-row-right-destructive"/);
  });

  it("Merge is gated to admin / super_admin / owner", () => {
    expect(pageSrc).toMatch(
      /const canMerge = \["admin", "super_admin", "owner"\]\.includes\(roleLower\)/,
    );
  });

  it("Move to Trash is gated to admin / super_admin only", () => {
    expect(pageSrc).toMatch(
      /const canHardDelete = \["admin", "super_admin"\]\.includes\(roleLower\)/,
    );
  });

  it("Issue Credit + Mark Correction share the admin+manager+owner gate", () => {
    // Both buttons read ``canIssueCredit`` /
    // ``canToggleAccountCorrection`` which are defined once in
    // the component body and reused across the inline button
    // and the kebab item.
    expect(pageSrc).toMatch(
      /const canIssueCredit = \["admin", "super_admin", "manager", "owner"\][\s\S]{0,80}\.includes/,
    );
    expect(pageSrc).toMatch(
      /const canToggleAccountCorrection = canIssueCredit/,
    );
  });
});


describe("Customer profile action bar · mobile kebab collapse", () => {
  it("kebab wrapper is md:hidden; right groups are hidden md:inline-flex", () => {
    // Mobile kebab visibility:
    //   • <md: kebab visible, right groups hidden
    //   • ≥md: kebab hidden, right groups visible
    expect(pageSrc).toMatch(
      /className="md:hidden"\s*\n?\s*data-testid="cd-mobile-kebab-wrapper"/,
    );
    expect(pageSrc).toMatch(
      /className="hidden md:inline-flex[^"]*"\s*\n?\s*data-testid="cd-action-row-right-primary"/,
    );
    expect(pageSrc).toMatch(
      /className="hidden md:inline-flex[^"]*"\s*\n?\s*data-testid="cd-action-row-right-destructive"/,
    );
  });

  it("kebab mirrors the inline right-group items", () => {
    // Six potential items mirror the inline buttons.  Each one
    // is role-gated identically to its inline sibling.
    for (const tid of [
      "cd-mobile-kebab-edit",
      "cd-mobile-kebab-merge",
      "cd-mobile-kebab-issue-credit",
      "cd-mobile-kebab-correction",
      "cd-mobile-kebab-delete",
      "cd-mobile-kebab-trash",
    ]) {
      expect(pageSrc).toContain(`data-testid="${tid}"`);
    }
  });

  it("kebab trigger carries the expected testid + aria-label", () => {
    expect(pageSrc).toMatch(/testid="cd-mobile-kebab-trigger"/);
    expect(pageSrc).toMatch(/aria-label="More actions"/);
  });

  it("Call button + its tel: fallback stay OUTSIDE the kebab (always visible)", () => {
    const wrapperIdx = pageSrc.indexOf('data-testid="cd-click-to-call-wrapper"');
    const kebabIdx = pageSrc.indexOf('data-testid="cd-mobile-kebab-wrapper"');
    expect(wrapperIdx).toBeGreaterThan(-1);
    expect(kebabIdx).toBeGreaterThan(-1);
    // Call comes BEFORE the kebab in source order so mobile sees
    // ``[Send][Create][Overview] … [Call][⋯]``.
    expect(wrapperIdx).toBeLessThan(kebabIdx);
    // The tel: icon fallback sits inside the Call wrapper.
    const callBlock = pageSrc.slice(wrapperIdx, kebabIdx);
    expect(callBlock).toContain("cd-click-to-call-tel-fallback");
  });

  it("Call button label is just \"Call\" (no customer-name interpolation)", () => {
    // Phase-2 ruling Q3 — the ClickToCallButton's own default
    // label ``"Call"`` is used; the previous dynamic
    // ``Call ${customer.name}`` interpolation is retired so the
    // button width stays constant.
    expect(pageSrc).toMatch(/label="Call"/);
    expect(pageSrc).not.toMatch(/label=\{`Call \$\{customer\.name/);
  });
});


describe("Customer profile action bar · dropdown wrapper on navy mode", () => {
  it("CustomerActionDropdowns switches to flex-nowrap when navy=true", () => {
    // Prevents the Send/Create pair from wrapping away from the
    // rest of the strip while retaining flex-wrap for any future
    // non-navy consumer.
    expect(actionsSrc).toMatch(
      /const wrapperClass = navy\s*\?\s*"flex flex-row flex-nowrap gap-2"\s*:\s*"flex flex-wrap gap-2"/,
    );
    expect(actionsSrc).toMatch(
      /<div className=\{wrapperClass\}\s+data-testid="customer-action-dropdowns">/,
    );
  });
});


describe("Customer profile action bar · existing testid preservation", () => {
  // The feature's primary user complaint was inconsistent sizing
  // and multi-row wrapping — NOT missing buttons.  Every pre-fix
  // testid survives the refactor byte-for-byte so downstream
  // suites keep resolving.
  it.each([
    ["cd-command-strip"],
    ["cd-action-row"],
    ["cd-tabs-dropdown-shell"],
    ["cd-edit"],
    ["cd-delete"],
    ["cd-hard-delete-btn"],
    ["cd-merge-btn"],
    ["cd-issue-credit-btn"],
    ["cd-account-correction-btn"],
    ["cd-click-to-call-wrapper"],
    ["cd-click-to-call-tel-fallback"],
  ])("preserves testid %s", (tid) => {
    expect(pageSrc).toMatch(
      new RegExp(`testid="${tid}"|data-testid="${tid}"`),
    );
  });
});
