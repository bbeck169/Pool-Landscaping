/**
 * Phase K48 · Feb-2026 — Business Unit editable on Revenue-by-Category
 * drill-down.
 *
 * Contract checks live at the source-body level (mirroring the K41
 * pattern already used in `k41-dashboard-drilldown-modal.test.jsx`)
 * so the suite runs without mounting the full modal graph.  These
 * assertions lock in the *shape* of the K48 change:
 *
 *   1. Business Unit dropdown is wired ONLY in the
 *      ``income-by-category`` variant (Path B — no schema change,
 *      the free-text CATEGORY editor is kept for
 *      ``income-by-service``).
 *   2. Save reuses the existing K41 PATCH /api/quotes/{iid} pipeline
 *      and writes BOTH ``income_category_id`` + denormalized
 *      ``category``.
 *   3. Audit companion fires with ``field="income_category_id"``
 *      (dashboard_drilldown_edit event on the backend).
 *   4. Locked invoices (paid / sent / partially_paid / refunded)
 *      render a read-only chip instead of the editor.
 *   5. Column header for the revenue-by-category variant reads
 *      "BUSINESS UNIT" (income-by-service keeps "CATEGORY").
 *   6. income_categories are fetched on mount for the revenue-by-
 *      category variant only.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const MODAL = read("src/components/dashboard/DashboardDrillDownModal.jsx");


describe("K48 · DashboardDrillDownModal — Business Unit editor", () => {
  it("imports the shadcn Select components", () => {
    expect(MODAL).toMatch(/from "@\/components\/ui\/select"/);
    expect(MODAL).toMatch(/SelectContent/);
    expect(MODAL).toMatch(/SelectItem/);
    expect(MODAL).toMatch(/SelectTrigger/);
    expect(MODAL).toMatch(/SelectValue/);
  });

  it("fetches tenant-scoped income_categories on the income-by-category variant only", () => {
    // ModalBody effect gated on variant === "income-by-category".
    expect(MODAL).toMatch(
      /if \(variant !== "income-by-category"\) return undefined;/,
    );
    expect(MODAL).toMatch(
      /api\.get\("\/income-categories\?include_archived=false"\)/,
    );
  });

  it("passes incomeCategories + currentBucket down to IncomeRow", () => {
    // IncomeRow accepts K48 props.
    expect(MODAL).toMatch(/incomeCategories = \[\],/);
    expect(MODAL).toMatch(/currentBucket = null,/);
    // Modal passes them only for the revenue variant.
    expect(MODAL).toMatch(/incomeCategories={incomeCategories}/);
    expect(MODAL).toMatch(
      /currentBucket=\{variant === "income-by-category" \? params\?\.category : null\}/,
    );
  });

  it("renders a BUSINESS UNIT column header for revenue-by-category only", () => {
    // Header line-up must include a variant-scoped BUSINESS UNIT label.
    expect(MODAL).toMatch(
      /variant === "income-by-category" \? "BUSINESS UNIT" : "CATEGORY"/,
    );
  });

  it("swaps to a Select dropdown on the revenue-by-category variant", () => {
    // The Business Unit trigger is data-testid'd for QA + testing agent.
    expect(MODAL).toMatch(/-bu-trigger`/);
    expect(MODAL).toMatch(/-bu-option-\$\{c\.id\}`/);
    // The dropdown value is bound to the local buCategoryId state and
    // change events call commitBusinessUnit.
    expect(MODAL).toMatch(/onValueChange={commitBusinessUnit}/);
  });

  it("keeps the free-text CATEGORY editor on the income-by-service variant", () => {
    // ``isRevenueVariant ? <Select…/> : <Input …category… />`` — the
    // else branch of the Business Unit cell must still bind the
    // ``category`` field via the same text input used pre-K48.
    expect(MODAL).toMatch(/isRevenueVariant \?/);
    expect(MODAL).toMatch(
      /<Input \{\.\.\.bindText\("category"\)\} style=\{\{ maxWidth: 140 \}\} \/>/,
    );
  });

  it("locks only terminal (void / cancelled) invoices; paid/sent stay editable", () => {
    // K48 (revised 2026-02-XX) — Business Unit re-classification is
    // money-neutral (subtotal / tax / total unchanged), so the
    // dropdown stays editable on paid/sent/partially_paid/refunded
    // rows.  We simply carry the backend's required confirmation
    // flags automatically on the PATCH.  Only void / cancelled
    // stay hard-locked (the backend rejects them even with
    // confirmations).
    expect(MODAL).toMatch(/K48_TERMINAL_STATUSES = new Set\(\["void", "cancelled"\]\)/);
    expect(MODAL).toMatch(/K48_CONFIRM_SENT_STATUSES/);
    expect(MODAL).toMatch(/K48_CONFIRM_PAID_STATUSES/);
    // Terminal-branch renders a LockedCell (K41 pattern) instead of
    // the Select.  Chip text carries the -bu-locked testid.
    expect(MODAL).toMatch(/-bu-locked`/);
    expect(MODAL).toMatch(/k48Status\.isTerminal \? \(/);
    // paid/sent rows carry the confirmation flags through to the PATCH.
    expect(MODAL).toMatch(/confirm_edit_sent = true/);
    expect(MODAL).toMatch(/confirm_edit_paid_invoice_number/);
  });

  it("saves via the existing K41 PATCH pipeline (BU-only payload, no line_items)", () => {
    // K48 verify-hotfix · Feb-2026 — commitBusinessUnit now sends a
    // MINIMAL BU-only payload.  Do NOT spread ``line_items`` into
    // the body — the shape validator upstream of the paid-lock
    // guard 409s on stringified numerics.  Backend accepts a top-
    // level ``business_unit`` field via ``$set`` (money-neutral).
    expect(MODAL).toMatch(
      /const patchBody = \{ business_unit: nextCat\.name \};/,
    );
    expect(MODAL).toMatch(/api\.patch\(`\/quotes\/\$\{row\.invoice_id\}`, patchBody\)/);
    // Regression guard — the BU-only patch path must NEVER re-fetch
    // the invoice and spread line_items into the payload.
    const commitBody = MODAL.split("const commitBusinessUnit = async")[1]
      .split("const bindText")[0];
    expect(commitBody).not.toMatch(/target\.income_category_id/);
    expect(commitBody).not.toMatch(/target\.category = /);
    expect(commitBody).not.toMatch(/line_items: items/);
  });

  it("emits the K41 audit companion with field=\"business_unit\"", () => {
    // K48 verify-hotfix · Feb-2026 — audit field name now matches
    // the invoice-level ``business_unit`` tag written on the wire
    // (was ``income_category_id`` in the pre-verify-hotfix ship
    // that patched line_items[].category).
    expect(MODAL).toMatch(
      /api\.post\("\/dashboard\/drilldown\/line-item-audit",[\s\S]{0,400}field: "business_unit"/,
    );
  });

  it("rolls back the Business Unit selection on PATCH failure", () => {
    // Optimistic update path: setBuCategoryId(nextId) BEFORE the api
    // call; on catch we setBuCategoryId(beforeId) to restore the
    // pre-edit value.
    expect(MODAL).toMatch(/setBuCategoryId\(nextId\);/);
    expect(MODAL).toMatch(/setBuCategoryId\(beforeId\);/);
  });

  it("keeps the row in place with a Moved-to indicator after save", () => {
    // K48 default per user brief — the row does NOT vanish when
    // reassigned to a different bucket; a "Moved to X" chip is
    // rendered below the Select until the modal is refreshed.
    expect(MODAL).toMatch(/setMovedTo\(nextCat\.name\);/);
    expect(MODAL).toMatch(/Moved to \{movedTo\}/);
    expect(MODAL).toMatch(/-bu-moved`/);
  });

  it("resolves the initial Business Unit id from income_category_id THEN name fallback", () => {
    // Path B — legacy rows only carry the denormalized name in
    // ``category``; the resolver falls back to a case-insensitive
    // match against the income_categories list so the dropdown
    // shows the correct value on first render.
    expect(MODAL).toMatch(/resolveInitialBuId/);
    expect(MODAL).toMatch(/row\?\.income_category_id/);
    expect(MODAL).toMatch(/incomeCategories\.find\(/);
  });
});


describe("K48 · Non-target variants left untouched (regression guard)", () => {
  it("preserves the K41 free-text ``category`` editor on income-by-service", () => {
    // Ensures we did NOT accidentally rip out the pre-K48 free-text
    // editor when adding the Business Unit dropdown.
    expect(MODAL).toMatch(/EDITABLE_INCOME_FIELDS = new Set\(\[[\s\S]*?"category"[\s\S]*?\]\)/);
  });

  it("preserves the data-integrity variant's bulk resolve bar + undo banner", () => {
    expect(MODAL).toMatch(/BulkResolveBar/);
    expect(MODAL).toMatch(/UndoBanner/);
  });

  it("preserves the K37 PortalErrorBoundary wrap on the modal body", () => {
    expect(MODAL).toMatch(/<PortalErrorBoundary/);
    expect(MODAL).toMatch(/label="dashboard-drilldown"/);
  });
});
