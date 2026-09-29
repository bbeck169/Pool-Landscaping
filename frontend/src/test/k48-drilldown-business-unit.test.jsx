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

  it("fetches tenant-scoped income_categories on BOTH income variants (INCOME-DRILLDOWN-EDIT widening)", () => {
    // ModalBody effect now gates on both income variants because the
    // ``income-by-service`` drill-down grew its own paired-ID
    // Category dropdown (INCOME-DRILLDOWN-EDIT · Feb-2026).
    expect(MODAL).toMatch(
      /if \(variant !== "income-by-category" && variant !== "income-by-service"\) \{\s*\n?\s*return undefined;/,
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

  it("swaps the income-by-service Category input for a paired-ID Select (INCOME-DRILLDOWN-EDIT)", () => {
    // Pre-INCOME-DRILLDOWN-EDIT the else-branch rendered a free-text
    // ``<Input {...bindText("category")} />``.  After the phase the
    // else-branch now renders a Select bound to commitLineCategoryPaired
    // so category changes carry BOTH ``income_category_id`` and
    // ``category`` on the PATCH payload.
    expect(MODAL).toMatch(/isRevenueVariant \?/);
    expect(MODAL).toMatch(/-cat-trigger`/);
    expect(MODAL).toMatch(/onValueChange={commitLineCategoryPaired}/);
    // Legacy free-text editor is intentionally retired from the
    // ``income-by-service`` variant.
    expect(MODAL).not.toMatch(
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

  it("saves via the existing K41 PATCH pipeline (BU + BU-id, no line_items)", () => {
    // INCOME-DRILLDOWN-EDIT · Feb-2026 — commitBusinessUnit now
    // sends the paired-ID contract: BOTH ``business_unit`` (name)
    // AND ``business_unit_id`` (canonical FK) land in the PATCH
    // body.  Backend ``InvoiceEditBody`` accepts both via ``$set``.
    // Money-neutral (no ``line_items`` in the payload), so the
    // paid-lock ``_validate_line_items`` numeric guard still
    // never fires for BU edits.
    expect(MODAL).toMatch(/business_unit: nextCat\.name,/);
    expect(MODAL).toMatch(/business_unit_id: nextCat\.id,/);
    expect(MODAL).toMatch(/api\.patch\(`\/quotes\/\$\{row\.invoice_id\}`, patchBody\)/);
    // Regression guard — the BU-only patch path must NEVER re-fetch
    // the invoice and spread line_items into the payload.
    const commitBody = MODAL.split("const commitBusinessUnit = async")[1]
      .split("\n  const commit")[0];
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

  it("K48 Round-4 · prefers row.business_unit over income_category_id / category on hydrate", () => {
    // Round-4 read-path fix — the backend now projects the invoice-
    // level ``business_unit`` field onto each drill-down row.  The
    // resolver MUST prefer this value over the legacy per-line-item
    // ``income_category_id`` / ``category`` fallbacks so a re-tagged
    // paid invoice hydrates the Select with the saved bucket on
    // modal reopen (fixes the "Select…" placeholder regression).
    const body = MODAL.split("const resolveInitialBuId = ()")[1]
      .split("};")[0];
    // 1. First branch reads row.business_unit + lowercases it.
    expect(body).toMatch(/const bu = \(row\?\.business_unit \|\| ""\)\.trim\(\)\.toLowerCase\(\);/);
    // 2. Name match against incomeCategories fires FIRST — before
    //    the id fallback — so a saved BU wins over a stale
    //    income_category_id on the same line item.
    const buIdx = body.indexOf("row?.business_unit");
    const directIdx = body.indexOf("row?.income_category_id");
    expect(buIdx).toBeGreaterThan(-1);
    expect(directIdx).toBeGreaterThan(-1);
    expect(buIdx).toBeLessThan(directIdx);
    // 3. Re-resolve effect re-runs when the async incomeCategories
    //    fetch lands (mount snapshot sees empty list; effect fills).
    expect(MODAL).toMatch(/useEffect\(\(\) => \{[\s\S]{0,600}resolveInitialBuId\(\)/);
  });
});


describe("K48 · Non-target variants left untouched (regression guard)", () => {
  it("keeps the ``category`` slot in EDITABLE_INCOME_FIELDS (commitField compatibility)", () => {
    // INCOME-DRILLDOWN-EDIT retired the free-text ``category``
    // editor on the income-by-service variant, but the commitField
    // closure still names ``category`` in EDITABLE_INCOME_FIELDS
    // so the legacy pathway (e.g. programmatic edits, future
    // dispatches) stays compilable without a rename.
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
