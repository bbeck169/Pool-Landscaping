/**
 * Feb-2026 · Bulk Portal Invite from CustomersList — Phase 9b
 * baseline refresh.
 *
 * ─────────────────────────────────────────────────────────────────
 * Phase 9b REMOVED the top-cluster "Portal Invite" button
 * (``customers-toolbar-portal-invite-btn``) per user approval. The
 * two SURVIVING invite surfaces now carry the admin-gate +
 * disabled-binding + modal-routing contracts:
 *
 *   * ``customers-filter-bulk-portal-invite-btn`` — covered by
 *     ``customers-filter-bar-bulk-portal-invite.test.jsx``
 *   * ``bulk-portal-invite`` (selection toolbar) — covered by
 *     ``customers-bulk-portal-invite.test.jsx``
 *
 * This file now locks the two post-9b invariants that are UNIQUE
 * to the CustomersList shell and NOT covered by the per-surface
 * suites above:
 *
 *   1. Regression guard — the removed top-cluster test-id MUST NOT
 *      be re-introduced. If a future change re-adds the button,
 *      the surviving-surface suites would silently cover its
 *      role-gate / modal-routing / disabled-binding behavior, so
 *      only a dedicated absence-check catches the re-introduction.
 *   2. ``PortalOnboardingHealthTile`` receives
 *      ``externalRefetchToken={h1Result}`` so the tile refetches
 *      on every H1 modal close.
 *   3. ``closeH1ConfirmModal`` is the single close-path helper and
 *      is wired into Cancel / backdrop / success exits — the
 *      Phase 9b batch-tester bug shape ``setH1ConfirmOpen(false);
 *      load();`` MUST NOT re-appear inside ``doBulkPortalInvite``.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


const CUSTOMERS_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);
const TILE_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/components/customers/PortalOnboardingHealthTile.jsx"),
  "utf-8",
);


describe("CustomersList · Feb-2026 Phase 9b top-menu button removal", () => {
  it("REGRESSION GUARD — the removed top-cluster ``customers-toolbar-portal-invite-btn`` must stay out", () => {
    // Phase 9b rip. Re-adding this test-id without an explicit
    // follow-up would silently duplicate the surviving invite
    // surfaces. If this assertion fails, either rip the button
    // again or coordinate with the surviving-surface test suites
    // (``customers-bulk-portal-invite.test.jsx`` +
    // ``customers-filter-bar-bulk-portal-invite.test.jsx``) to
    // retire one of them before re-introducing a third surface.
    expect(CUSTOMERS_SRC).not.toMatch(
      /testid="customers-toolbar-portal-invite-btn"/,
    );
  });

  it("preserves the two SURVIVING invite surfaces (filter-row + selection toolbar)", () => {
    // The filter-row button (filter-driven flow — uses
    // ``openBulkPortalInviteFromFilter`` + ``BulkPortalInviteConfirm``
    // modal).
    expect(CUSTOMERS_SRC).toMatch(
      /data-testid="customers-filter-bulk-portal-invite-btn"/,
    );
    // The selection-toolbar button (selection-driven flow — opens
    // the inline H1 modal via ``setH1ConfirmOpen`` +
    // ``doBulkPortalInvite``). Uses the ``testid`` prop on the
    // ui-kit Button, which forwards to ``data-testid``.
    expect(CUSTOMERS_SRC).toMatch(/testid="bulk-portal-invite"/);
    // The H1 modal state must still exist — the ``bulk-portal-invite``
    // button in the selection toolbar depends on it.
    expect(CUSTOMERS_SRC).toMatch(/setH1ConfirmOpen/);
    expect(CUSTOMERS_SRC).toMatch(/doBulkPortalInvite/);
  });

  it("Portal Onboarding Health tile receives ``externalRefetchToken={h1Result}`` for post-bulk refetch", () => {
    // CustomersList wires h1Result through the tile prop.
    expect(CUSTOMERS_SRC).toMatch(
      /PortalOnboardingHealthTile[\s\S]{0,120}externalRefetchToken=\{h1Result\}/,
    );
    // And the tile useEffect includes ``externalRefetchToken`` in
    // its dep array so any change re-fires the fetch.
    expect(TILE_SRC).toMatch(
      /useEffect\([\s\S]*?\}, \[refetchTick, externalRefetchToken\]\)/,
    );
    // Tile accepts the prop.
    expect(TILE_SRC).toMatch(
      /function PortalOnboardingHealthTile\(\{\s*externalRefetchToken\s*\}\)/,
    );
  });

  it("customers list refetches on EVERY H1 modal close path (Cancel, backdrop, success)", () => {
    // Feb-2026 batch-tester fix — Cancel + backdrop-click close
    // paths must invalidate the customers list, not only the
    // success path. A unified ``closeH1ConfirmModal`` helper
    // handles all three exits and calls ``load()`` after
    // ``setH1ConfirmOpen(false)``.
    //
    // 1) Helper exists and its body calls both close + refetch.
    expect(CUSTOMERS_SRC).toMatch(
      /const closeH1ConfirmModal = useCallback\(\(\) => \{\s*setH1ConfirmOpen\(false\);\s*load\(\);\s*\}, \[load\]\);/,
    );
    // 2) Backdrop click routes through the helper (NOT direct
    //    setH1ConfirmOpen(false) — the raw setter would skip the
    //    refetch, which is the bug).
    expect(CUSTOMERS_SRC).toMatch(
      /if \(e\.target === e\.currentTarget\) closeH1ConfirmModal\(\);/,
    );
    // 3) Cancel button routes through the helper.
    expect(CUSTOMERS_SRC).toMatch(
      /onClick=\{closeH1ConfirmModal\}[\s\S]{0,300}data-testid="h1-modal-cancel"/,
    );
    // 4) Success path (inside doBulkPortalInvite) routes through
    //    the helper too — no more direct ``setH1ConfirmOpen(false);
    //    load();`` pair that could drift out of sync.
    const doBulkIdx = CUSTOMERS_SRC.indexOf("const doBulkPortalInvite");
    expect(doBulkIdx).toBeGreaterThan(0);
    // Slice from doBulkPortalInvite definition to the end of its
    // body (approximated by the next top-level ``const`` /
    // ``function`` boundary — 3000 chars is more than enough).
    const doBulkBody = CUSTOMERS_SRC.slice(doBulkIdx, doBulkIdx + 3000);
    expect(doBulkBody).toMatch(/closeH1ConfirmModal\(\);/);
    // Belt-and-braces — the doBulkPortalInvite body must NOT
    // contain the pre-fix inline ``setH1ConfirmOpen(false);\s*load();``
    // pair. That pair is the bug shape.
    expect(doBulkBody).not.toMatch(
      /setH1ConfirmOpen\(false\);\s*load\(\);/,
    );
  });
});
