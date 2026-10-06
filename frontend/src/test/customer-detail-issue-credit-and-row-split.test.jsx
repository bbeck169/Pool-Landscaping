/**
 * CUSTOMER-PROFILE-ACTION-BAR · Feb-2026 — regression guards for
 * the row-split navy command strip + the Issue Credit shortcut on
 * ``CustomerDetail.jsx``.
 *
 * The feature atomic:
 *   1. Splits the single-row ``cd-command-strip`` into two rows.
 *      Row 1 (``cd-action-row``) keeps every action button.
 *      Row 2 holds ONLY the Overview dropdown
 *      (``cd-tabs-dropdown-shell``) wrapped in a new white
 *      container (``cd-tabs-dropdown-shell-light``) that stands
 *      out against the navy strip background.
 *   2. Adds an ``Issue Credit`` button to Row 1 (``cd-issue-
 *      credit-btn``) role-gated to admin / super_admin / manager
 *      / owner.  On click it opens the existing
 *      ``AdjustDialog`` modal from ``CustomerCreditsPage.jsx`` —
 *      no fork, no new positive-only variant.
 *
 * ``CustomerDetail.jsx`` is a 3.2-kloc React component with
 * extensive provider / router / auth / api dependencies that
 * would require a full test-harness mount to RTL-render.
 * Mirroring the LIGHTBOX-UNIFY / BULK-RESCHEDULE-FIX regression-
 * guard pattern, this test file inspects the SOURCE text of the
 * component to lock the structural contract (data-testids, role
 * gate expression, modal wiring).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/customers/CustomerDetail.jsx"),
  "utf8",
);

describe("CUSTOMER-PROFILE-ACTION-BAR · row-split structure", () => {
  it("cd-command-strip is a flex-col (two-row layout)", () => {
    // The pre-fix strip was ``flex flex-row items-center``.
    // After the fix it is ``flex flex-col gap-3`` so the two
    // rows stack vertically inside the shared navy container.
    expect(SRC).toMatch(
      /data-testid="cd-command-strip"[^>]*/,
    );
    const stripRegion = SRC.match(
      /className="rounded-2xl mb-4 px-3 py-3 flex flex-col gap-3"/,
    );
    expect(stripRegion,
      "cd-command-strip must be flex flex-col gap-3 (row-split layout)")
      .toBeTruthy();
  });

  it("cd-action-row is still a horizontal flex row", () => {
    // Row 1 preserves the original horizontal layout.
    expect(SRC).toMatch(
      /flex flex-row flex-nowrap items-center gap-2 overflow-x-auto[^"]*"\s*\n?\s*data-testid="cd-action-row"/,
    );
  });

  it("Overview dropdown lives inside the WHITE wrapper on row 2", () => {
    // The new ``cd-tabs-dropdown-shell-light`` wrapper exists
    // and carries ``bg-white`` so the trigger area stands out
    // against the navy strip background.
    expect(SRC).toMatch(
      /data-testid="cd-tabs-dropdown-shell-light"/,
    );
    const lightShell = SRC.match(
      /className="rounded-xl bg-white"[\s\S]{0,120}data-testid="cd-tabs-dropdown-shell-light"/,
    );
    expect(lightShell,
      "cd-tabs-dropdown-shell-light must carry bg-white classes")
      .toBeTruthy();
    // The ResponsiveTabs forceDropdown trigger (inner
    // ``cd-tabs-dropdown-shell``) sits INSIDE the light wrapper.
    expect(SRC).toMatch(
      /data-testid="cd-tabs-dropdown-shell-light"[\s\S]{0,300}data-testid="cd-tabs-dropdown-shell"/,
    );
  });

  it("Overview dropdown is OUTSIDE cd-action-row (true row-split)", () => {
    // Pre-fix: dropdown was a sibling INSIDE the single-row flex.
    // Post-fix: dropdown must appear AFTER cd-action-row closes.
    const actionRowOpen = SRC.indexOf('data-testid="cd-action-row"');
    const dropdownShellPos = SRC.indexOf(
      'data-testid="cd-tabs-dropdown-shell-light"',
    );
    expect(actionRowOpen).toBeGreaterThan(0);
    expect(dropdownShellPos).toBeGreaterThan(actionRowOpen);
  });
});


describe("CUSTOMER-PROFILE-ACTION-BAR · Issue Credit shortcut", () => {
  it("cd-issue-credit-btn testid is wired", () => {
    expect(SRC).toMatch(/testid="cd-issue-credit-btn"/);
  });

  it("Issue Credit button carries the correct label + icon", () => {
    expect(SRC).toMatch(
      /testid="cd-issue-credit-btn"[\s\S]{0,400}<DollarSign size=\{14\} \/> Issue Credit/,
    );
  });

  it("role gate matches the widened backend set (admin + super_admin + manager + owner)", () => {
    expect(SRC).toMatch(
      /const canIssueCredit = \["admin", "super_admin", "manager", "owner"\][\s\S]{0,80}\.includes\(\(meRole \|\| ""\)\.toLowerCase\(\)\);/,
    );
  });

  it("button renders only when canIssueCredit is true", () => {
    // The JSX guards the <Button> on ``canIssueCredit ? (<Button
    // ... testid="cd-issue-credit-btn"...>...</Button>) : null``.
    expect(SRC).toMatch(
      /\{canIssueCredit \? \(\s*<Button[\s\S]{0,600}testid="cd-issue-credit-btn"/,
    );
  });

  it("click handler opens the modal via openIssueCreditModal", () => {
    // The onClick must be wired to the dedicated handler that
    // fetches the current balance before opening (so the
    // modal's live-preview starts with a correct starting
    // value — see openIssueCreditModal's api.get).  The Button's
    // ``onClick`` appears before the ``testid`` prop in the JSX
    // (standard variant/className/onClick/testid prop order).
    expect(SRC).toMatch(
      /onClick=\{openIssueCreditModal\}\s*\n\s*testid="cd-issue-credit-btn"/,
    );
    // The handler itself exists and hits the credits GET route.
    expect(SRC).toMatch(/const openIssueCreditModal = async \(\) => \{/);
    expect(SRC).toMatch(
      /openIssueCreditModal[\s\S]{0,2000}api\.get\(`\/customers\/\$\{id\}\/credits`\)/,
    );
  });

  it("renders AdjustDialog from CustomerCreditsPage (no fork)", () => {
    // Import must pull AdjustDialog from the existing module.
    expect(SRC).toMatch(
      /import \{ CustomerCreditsPanel, AdjustDialog \} from "\.\/CustomerCreditsPage";/,
    );
    // JSX uses the imported component with the right props.
    expect(SRC).toMatch(
      /\{issueCreditOpen && canIssueCredit \? \(\s*<AdjustDialog/,
    );
    expect(SRC).toMatch(/customerId=\{id\}[\s\S]{0,120}currentBalanceCents=\{issueCreditBalanceCents\}/);
    // onSaved must refetch the customer summary via load().
    expect(SRC).toMatch(/onSaved=\{\(\) => \{\s*setIssueCreditOpen\(false\);\s*load\(\);/);
  });
});


describe("CUSTOMER-PROFILE-ACTION-BAR · existing action-bar buttons preserved", () => {
  // Row 1 keeps every pre-fix testid + role gate byte-for-byte.
  // These guards land a loud regression if a future refactor
  // accidentally drops one.
  it.each([
    ["cd-edit"],
    ["cd-delete"],
    ["cd-hard-delete-btn"],
    ["cd-merge-btn"],
    ["cd-click-to-call-wrapper"],
  ])("preserves testid %s", (tid) => {
    expect(SRC).toMatch(new RegExp(`testid="${tid}"|data-testid="${tid}"`));
  });

  it("hard-delete role gate stays admin / super_admin only", () => {
    expect(SRC).toMatch(
      /\["admin", "super_admin"\]\.includes\([\s\S]{0,500}testid="cd-hard-delete-btn"/,
    );
  });

  it("merge role gate stays admin / super_admin / owner", () => {
    expect(SRC).toMatch(
      /\["admin", "super_admin", "owner"\]\.includes\([\s\S]{0,500}testid="cd-merge-btn"/,
    );
  });
});
