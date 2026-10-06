/**
 * Atomic A2 · Feb-2026 — Revenue drill-down modal · remove
 * ``requires_confirmation`` friction on CATEGORY dropdown for
 * privileged roles.
 *
 * Contract checks live at the source-body level (mirroring the K41 /
 * K48 pattern used across this repo — see
 * ``DashboardDrillDownModal.categoryServiceUnit.test.jsx``).  The four
 * assertion groups below map 1:1 to the behavioural criteria from the
 * Atomic A2 brief:
 *
 *   a. Admin edits category on draft invoice      → PATCH body carries
 *      BOTH ``confirm_edit_sent`` AND
 *      ``acknowledged_lock_bypass`` on the privileged branch of
 *      commitLineCategoryPaired (no gate dialog).
 *   b. Admin edits category on sent / accepted    → same body, NOT
 *      gated on ``k48Status`` — so 409 friction never fires on the
 *      backend for privileged users.
 *   c. Admin edits a NON-category field (amount / qty / description)
 *      on sent → confirm flags are NOT auto-included (regression lock
 *      on ``commitField``).
 *   d. Non-privileged role (``tech``) edits category → flags NOT
 *      auto-included (role gate wraps BOTH commit paths).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const MODAL = read("src/components/dashboard/DashboardDrillDownModal.jsx");

/* Slice the IncomeRow function body once so per-test regex scans stay
 * focused on the right lexical scope. */
const INCOME_ROW = MODAL.split("function IncomeRow(")[1].split(
  "\nfunction ",
)[0];

/* IncomeRow prefix BEFORE commitField — where the role-aware helper
 * lives.  Used for the privileged-role allow-list assertions. */
const ROLE_SCOPE = INCOME_ROW.split("const commitField = async")[0];

/* Per-commit function body slices.  We bound each slice at the
 * closing ``\n  };\n`` (the 2-space-indented ``};`` that terminates
 * the arrow function body) so the JSX return statement at the end of
 * IncomeRow — which references ``k48Status.isTerminal`` — never leaks
 * into the commit-function regex scope. */
const COMMIT_FIELD = INCOME_ROW.split(
  "const commitField = async (field)",
)[1].split("\n  };\n")[0];
const COMMIT_LINE_CAT = INCOME_ROW.split(
  "const commitLineCategoryPaired = async",
)[1].split("\n  };\n")[0];
/* REV-CONFIRM-FIX · Feb-2026 — add slices for the two commit paths
 * extended in this ship: ``commitBusinessUnit`` (invoice-level BU
 * dropdown on the income-by-category variant) and
 * ``commitServiceUnit`` (line-level Service Unit dropdown on both
 * income variants).  Each slice is bounded at the arrow-function
 * closer so the per-test regex scans stay in the right lexical
 * scope. */
const COMMIT_BU = INCOME_ROW.split(
  "const commitBusinessUnit = async",
)[1].split("\n  };\n")[0];
const COMMIT_SVC = INCOME_ROW.split(
  "const commitServiceUnit = async",
)[1].split("\n  };\n")[0];


describe("Atomic A2 · privileged role detection", () => {
  it("imports useAuth and derives canBypassCategoryConfirm against admin/super_admin/manager/owner (case-insensitive)", () => {
    // Import wired at module scope so the hook resolves inside IncomeRow.
    expect(MODAL).toMatch(/import \{ useAuth \} from "@\/auth";/);
    // Hook call lives at IncomeRow scope (BEFORE commitField /
    // commitLineCategoryPaired).
    expect(ROLE_SCOPE).toMatch(/const \{ role \} = useAuth\(\) \|\| \{\};/);
    expect(ROLE_SCOPE).toMatch(/const canBypassCategoryConfirm =/);
    // Exactly the four privileged role strings — nothing more, nothing less.
    expect(ROLE_SCOPE).toMatch(/"admin"/);
    expect(ROLE_SCOPE).toMatch(/"super_admin"/);
    expect(ROLE_SCOPE).toMatch(/"manager"/);
    expect(ROLE_SCOPE).toMatch(/"owner"/);
    // Case-insensitive comparison via ``String(role || "").toLowerCase()``.
    expect(ROLE_SCOPE).toMatch(/String\(role \|\| ""\)\.toLowerCase\(\)/);
    // Negative: no non-privileged role string leaks into the allow-list.
    expect(ROLE_SCOPE).not.toMatch(/"tech"/);
    expect(ROLE_SCOPE).not.toMatch(/"technician"/);
    expect(ROLE_SCOPE).not.toMatch(/"viewer"/);
  });
});


describe("Atomic A2 · commitLineCategoryPaired · auto-pass confirm flags on CATEGORY (criteria a + b)", () => {
  it("a + b. privileged branch carries BOTH confirm_edit_sent AND acknowledged_lock_bypass, ungated by invoice status", () => {
    // Privileged branch wraps the PATCH call under the role check.
    expect(COMMIT_LINE_CAT).toMatch(/if \(canBypassCategoryConfirm\) \{/);
    // Both flags land on the SAME body that writes the paired
    // income_category_id + category keys.  Consecutive-line match
    // locks the exact object literal shape.
    expect(COMMIT_LINE_CAT).toMatch(
      /line_items: items,\s*\n\s*confirm_edit_sent: true,\s*\n\s*acknowledged_lock_bypass: true,/,
    );
    // Criterion (b): the privileged branch is NOT gated on
    // ``k48Status.needsSentConfirm`` / ``needsPaidConfirm`` — the whole
    // point of A2 is admin never sees the 409 friction on sent /
    // accepted / paid invoices.  commitLineCategoryPaired body should
    // not reference the K48 status helper at all.
    expect(COMMIT_LINE_CAT).not.toMatch(/k48Status\./);
    // Non-privileged fallback preserves the pre-A2 call shape so
    // tech-level users still hit the backend status gate.  This
    // also locks in the shared contract with
    // ``DashboardDrillDownModal.categoryServiceUnit.test.jsx`` test
    // #3 (paired-ID PATCH body regex).
    expect(COMMIT_LINE_CAT).toMatch(
      /api\.patch\(`\/quotes\/\$\{row\.invoice_id\}`,\s*\{ line_items: items \}\)/,
    );
    expect(COMMIT_LINE_CAT).toMatch(/\} else \{/);
  });
});


describe("Atomic A2 · commitField category branch · regression lock (criterion c)", () => {
  it("c. confirm flags inject ONLY when field === 'category' AND role is privileged", () => {
    // Explicit field-name guard so description / quantity / unit_price
    // never carry the auto-flags.
    expect(COMMIT_FIELD).toMatch(
      /if \(field === "category" && canBypassCategoryConfirm\) \{/,
    );
    expect(COMMIT_FIELD).toMatch(/patchBody\.confirm_edit_sent = true;/);
    expect(COMMIT_FIELD).toMatch(/patchBody\.acknowledged_lock_bypass = true;/);
  });

  it("c. non-category commitField branches never set the auto-flag keys", () => {
    // Both auto-flag assignments must appear AFTER the category guard —
    // if a future edit duplicates a flag write outside the guard, this
    // test fails loudly.
    const guardIdx = COMMIT_FIELD.indexOf(
      'if (field === "category" && canBypassCategoryConfirm)',
    );
    const sentIdx = COMMIT_FIELD.indexOf("patchBody.confirm_edit_sent");
    const bypassIdx = COMMIT_FIELD.indexOf("patchBody.acknowledged_lock_bypass");
    expect(guardIdx).toBeGreaterThan(-1);
    expect(sentIdx).toBeGreaterThan(guardIdx);
    expect(bypassIdx).toBeGreaterThan(guardIdx);
    // Exactly ONE occurrence of each flag inside the commitField body —
    // defends against drift that could duplicate the flag outside the
    // category guard (would re-introduce the regression).
    const sentCount = (COMMIT_FIELD.match(/patchBody\.confirm_edit_sent/g) || []).length;
    const bypassCount = (COMMIT_FIELD.match(/patchBody\.acknowledged_lock_bypass/g) || []).length;
    expect(sentCount).toBe(1);
    expect(bypassCount).toBe(1);
  });
});


describe("Atomic A2 · non-privileged roles do NOT auto-pass flags (criterion d)", () => {
  it("d. the auto-flag injection is strictly gated on canBypassCategoryConfirm in BOTH commit paths", () => {
    // commitLineCategoryPaired privileged branch is wrapped by the
    // role check — else branch has the lean ``{ line_items: items }``
    // payload (asserted above as part of criteria a + b).
    expect(COMMIT_LINE_CAT).toMatch(/if \(canBypassCategoryConfirm\) \{/);
    expect(COMMIT_LINE_CAT).toMatch(/\} else \{/);
    // commitField category branch is also wrapped by canBypassCategoryConfirm.
    expect(COMMIT_FIELD).toMatch(/canBypassCategoryConfirm/);
    // Declaration (1) + commitField guard (1) + commitLineCategoryPaired
    // branch (1) + commitBusinessUnit branch (1) + commitServiceUnit
    // branch (1) = 5 occurrences minimum post REV-CONFIRM-FIX, locking
    // the spelling in ALL FOUR commit paths so typo drift can't
    // silently open the bypass.
    const occurrences = (
      INCOME_ROW.match(/canBypassCategoryConfirm/g) || []
    ).length;
    expect(occurrences).toBeGreaterThanOrEqual(5);
  });
});


/* ═══════════════════════════════════════════════════════════════
 * REV-CONFIRM-FIX · Feb-2026 — extend the Atomic A2 bypass to the
 * remaining two Revenue-by-Category drill-down save paths:
 *   • commitBusinessUnit — invoice-level BU dropdown (``category``
 *     in user-facing language).  Pre-fix only sent
 *     ``confirm_edit_sent`` when ``k48Status.needsSentConfirm``,
 *     and NEVER sent ``acknowledged_lock_bypass`` → ``accepted``
 *     invoices 409'd even for admins.
 *   • commitServiceUnit — line-level Service Unit dropdown.
 *     Pre-fix shape had NO confirm flags at all → every edit on a
 *     non-draft invoice 409'd regardless of role.
 * Both paths now mirror ``commitLineCategoryPaired``: privileged →
 * auto-pass both flags; non-privileged → pre-fix shape (backend
 * 409 surfaced via toast).
 * ═══════════════════════════════════════════════════════════════ */

describe("REV-CONFIRM-FIX · commitBusinessUnit · auto-pass confirm flags for privileged roles", () => {
  it("privileged branch injects BOTH confirm_edit_sent AND acknowledged_lock_bypass unconditionally", () => {
    // Role gate wraps the two flag writes.
    expect(COMMIT_BU).toMatch(/if \(canBypassCategoryConfirm\) \{/);
    // Both flags land on patchBody inside the privileged branch —
    // consecutive-line match locks the exact write order.
    expect(COMMIT_BU).toMatch(
      /patchBody\.confirm_edit_sent = true;\s*\n\s*patchBody\.acknowledged_lock_bypass = true;/,
    );
    // Non-privileged fallback preserves the pre-fix conditional
    // behaviour so lower roles still hit the K48 status gate.
    expect(COMMIT_BU).toMatch(/\} else \{/);
    expect(COMMIT_BU).toMatch(/if \(k48Status\.needsSentConfirm\)/);
    expect(COMMIT_BU).toMatch(/if \(k48Status\.needsPaidConfirm\)/);
  });

  it("the privileged branch is NOT gated on k48Status (admin never sees 409 friction)", () => {
    // Slice the privileged branch body out of COMMIT_BU and assert
    // k48Status is absent.  Branch spans from the ``if
    // (canBypassCategoryConfirm) {`` opener up to the ``} else {``.
    const bypassOpen = COMMIT_BU.indexOf(
      "if (canBypassCategoryConfirm) {",
    );
    expect(bypassOpen).toBeGreaterThan(-1);
    const elseIdx = COMMIT_BU.indexOf("} else {", bypassOpen);
    expect(elseIdx).toBeGreaterThan(bypassOpen);
    const privilegedBranch = COMMIT_BU.slice(bypassOpen, elseIdx);
    expect(privilegedBranch).not.toMatch(/k48Status\./);
  });
});

describe("REV-CONFIRM-FIX · commitServiceUnit · auto-pass confirm flags for privileged roles", () => {
  it("privileged branch sends the paired-ID line_items PATCH WITH both confirm flags", () => {
    expect(COMMIT_SVC).toMatch(/if \(canBypassCategoryConfirm\) \{/);
    // Full body shape — line_items, confirm_edit_sent,
    // acknowledged_lock_bypass on the SAME call.
    expect(COMMIT_SVC).toMatch(
      /line_items: items,\s*\n\s*confirm_edit_sent: true,\s*\n\s*acknowledged_lock_bypass: true,/,
    );
  });

  it("non-privileged fallback preserves the pre-fix lean payload shape", () => {
    // The ``\} else \{`` branch sends only line_items — no confirm
    // flags — so technician edits on non-draft invoices still 409
    // and surface the backend message via toast (regression lock).
    expect(COMMIT_SVC).toMatch(/\} else \{/);
    expect(COMMIT_SVC).toMatch(
      /api\.patch\(`\/quotes\/\$\{row\.invoice_id\}`,\s*\{ line_items: items \}\)/,
    );
  });

  it("privileged branch is NOT gated on k48Status (admin bypasses on sent/accepted/paid)", () => {
    const bypassOpen = COMMIT_SVC.indexOf(
      "if (canBypassCategoryConfirm) {",
    );
    expect(bypassOpen).toBeGreaterThan(-1);
    const elseIdx = COMMIT_SVC.indexOf("} else {", bypassOpen);
    expect(elseIdx).toBeGreaterThan(bypassOpen);
    const privilegedBranch = COMMIT_SVC.slice(bypassOpen, elseIdx);
    expect(privilegedBranch).not.toMatch(/k48Status\./);
  });
});
