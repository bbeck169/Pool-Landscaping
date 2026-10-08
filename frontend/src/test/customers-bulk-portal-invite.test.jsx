/**
 * Phase H1 · Feb-2026 — CustomersList bulk portal invite.
 *
 * Source-body contract check (mirrors G4a + F5 pattern). Locks the
 * critical invariants:
 *
 *   - The "Send portal invite" button is admin-gated (rendered
 *     inside an ``isAdmin ? ... : null`` conditional).
 *   - The confirm modal surfaces the current filter state so ops
 *     don't accidentally chase the wrong cohort.
 *   - An already-activated warning fires when the selection
 *     contains any ``has_login === true`` rows.
 *   - The POST hits ``/admin/customers/portal-invite/bulk`` with
 *     ``customer_ids`` in the body.
 *   - The failure-details panel opens when the response contains a
 *     non-empty ``failures`` array.
 *   - Selection is cleared on a successful send.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);


describe("CustomersList · H1 bulk portal invite", () => {
  it("bulk toolbar surfaces the 'Send portal invite (N)' button", () => {
    expect(SRC).toMatch(
      /Send portal invite \({[\s\S]{0,40}selected\.size[\s\S]{0,40}\}\)/,
    );
    expect(SRC).toMatch(/testid="bulk-portal-invite"/);
  });

  it("the H1 button renders ONLY for admin+ role (isAdmin gate)", () => {
    // The block that renders the button MUST be inside an isAdmin
    // conditional so tech/customer roles never see it.
    //
    // Feb-2026 — ``c4af1ec80`` added a second ``bulk-portal-invite``-
    // bearing testid (the filter-bar flow at
    // ``customers-filter-bulk-portal-invite-btn``), which the
    // original ``SRC.indexOf("bulk-portal-invite")`` lookup now
    // hits first.  Anchor on the SELECTION button's exact testid
    // literal so this check stays scoped to the top-right toolbar
    // H1 flow (the filter-bar flow has its own vitest file).
    const idx = SRC.indexOf('testid="bulk-portal-invite"');
    expect(idx).toBeGreaterThan(0);
    const preamble = SRC.slice(Math.max(0, idx - 500), idx);
    expect(preamble).toMatch(/isAdmin\s*\?\s*\(/);
  });

  it("confirm modal surfaces the current filter state", () => {
    expect(SRC).toMatch(/data-testid="h1-modal-filter-state"/);
    expect(SRC).toMatch(/Currently filtered:\s*Portal =/);
    expect(SRC).toMatch(/Cohort =/);
    expect(SRC).toMatch(/customer\{selected\.size === 1 \? "" : "s"\} selected/);
  });

  it("modal surfaces the 'already activated' warning when applicable", () => {
    expect(SRC).toMatch(/data-testid="h1-modal-already-warning"/);
    expect(SRC).toMatch(
      /_h1AlreadyActivatedCount\(\)\s*>\s*0/,
    );
    expect(SRC).toMatch(
      /already[\s\S]{0,80}have portal access[\s\S]{0,80}skipped/,
    );
  });

  it("POST hits /admin/customers/portal-invite/bulk with customer_ids", () => {
    expect(SRC).toMatch(
      /api\.post\(\s*"\/admin\/customers\/portal-invite\/bulk"\s*,\s*\{\s*customer_ids/,
    );
  });

  it("clears selection on success and refetches the list", () => {
    // ``setSelected(new Set())`` inside the success branch, followed
    // by the customers-list refetch. Feb-2026 batch-tester fix —
    // the refetch is now routed through the unified
    // ``closeH1ConfirmModal`` helper (which calls ``load()``) so
    // Cancel/backdrop close paths also invalidate the list. Accept
    // either the direct ``load()`` (legacy) or the helper call.
    //
    // Feb-2026 — anchor on the SELECTION-flow function definition
    // (``const doBulkPortalInvite = async () =>``) so this check
    // isn't disturbed by the filter-bar flow's ``api.post`` call
    // that landed with ``c4af1ec80`` and now sits earlier in the
    // file.  The filter-bar flow owns its own vitest coverage.
    const idx = SRC.indexOf("const doBulkPortalInvite = async () =>");
    expect(idx).toBeGreaterThan(0);
    // 2000-char window — the ``closeH1ConfirmModal()`` call sits
    // ~1532 chars after the function definition (past
    // ``setSelected(new Set())`` and the explanatory block comment
    // that mentions the helper name without parens).  Bump above
    // 1500 so the regex catches the actual call, not the comment.
    const body = SRC.slice(idx, idx + 2000);
    expect(body).toMatch(/setSelected\(new Set\(\)\)/);
    expect(body).toMatch(/load\(\)|closeH1ConfirmModal\(\)/);
  });

  it("failure-details side-panel renders when non-empty failures come back", () => {
    expect(SRC).toMatch(/data-testid="h1-failure-details"/);
    expect(SRC).toMatch(/data-testid="h1-failure-close"/);
    expect(SRC).toMatch(
      /h1Result\s*&&\s*\(h1Result\.failures\s*\|\|\s*\[\]\)\.length\s*>\s*0/,
    );
  });

  it("modal cancel + confirm testids are present", () => {
    expect(SRC).toMatch(/data-testid="h1-modal-cancel"/);
    expect(SRC).toMatch(/data-testid="h1-modal-confirm"/);
  });

  it("H1 confirm button label reflects selection size", () => {
    // "Send N invite" (singular for 1, plural otherwise).
    expect(SRC).toMatch(
      /Send \$\{selected\.size\} invite\$\{selected\.size === 1 \? "" : "s"\}/,
    );
  });
});


describe("H1 · regression guards for surrounding features", () => {
  it("preserves the G4a portal-status filter and the F6c cohort tabs", () => {
    expect(SRC).toMatch(/data-testid="customers-filter-portal-status"/);
    expect(SRC).toMatch(/data-testid="customers-cohort-tabs"/);
  });

  it("does not remove the existing bulk toolbar 'N selected' badge", () => {
    expect(SRC).toMatch(
      /\{selected\.size\}\s*selected/,
    );
  });
});
