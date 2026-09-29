/**
 * INCOME-DRILLDOWN-EDIT · Feb-2026 — Category + Service Unit Selects.
 *
 * Contract checks live at the source-body level (mirroring the K41 /
 * K48 pattern already used in ``src/test/*.test.jsx``) so the suite
 * runs without mounting the full modal graph.  These assertions lock
 * in the paired-ID commit contract on the ``DashboardDrillDownModal``
 * IncomeRow:
 *
 *   1. Category (income-by-service variant) renders as a Select
 *      driven by ``incomeCategories``.
 *   2. Service Unit renders as a Select driven by ``serviceCategories``
 *      in BOTH income variants.
 *   3. Changing Category calls the auto-save with paired
 *      ``{income_category_id, category}`` in the PATCH body.
 *   4. Changing Service Unit calls the auto-save with paired
 *      ``{service_category_id, service_category}`` in the PATCH body.
 *   5. Optimistic UI — the local Select id state is updated BEFORE
 *      the network call.
 *   6. Error rollback — on catch, the local id state is set back to
 *      the pre-edit value.
 *   7. Options load ONCE on modal open — each fetch effect is guarded
 *      by ``variant`` + a ``cancelled`` cleanup flag, and the fetches
 *      never appear inside a per-row IncomeRow scope.
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


describe("INCOME-DRILLDOWN-EDIT · Category Select on income-by-service", () => {
  it("1. renders a Select bound to incomeCategories with option testids", () => {
    // The else-branch of ``isRevenueVariant ?`` now renders a Select
    // (was a text ``<Input {...bindText("category")} />`` pre-phase).
    expect(INCOME_ROW).toMatch(/isRevenueVariant \?/);
    expect(INCOME_ROW).toMatch(/-cat-trigger`/);
    expect(INCOME_ROW).toMatch(/-cat-option-\$\{c\.id\}`/);
    expect(INCOME_ROW).toMatch(/onValueChange=\{commitLineCategoryPaired\}/);
    // Options are sourced from the tenant-scoped incomeCategories prop.
    expect(INCOME_ROW).toMatch(
      /\{incomeCategories\.map\(\(c\) => \([\s\S]{0,240}SelectItem/,
    );
  });

  it("3. changing Category sends paired {income_category_id, category} on the PATCH line item", () => {
    // commitLineCategoryPaired writes BOTH keys onto the target line
    // item before firing the PATCH.  Canonical FK first, denormalized
    // name second.
    expect(INCOME_ROW).toMatch(/const commitLineCategoryPaired = async \(nextId\) =>/);
    const commitBody = INCOME_ROW.split(
      "const commitLineCategoryPaired = async",
    )[1].split("\n  const ")[0];
    expect(commitBody).toMatch(/income_category_id: nextCat\.id,/);
    expect(commitBody).toMatch(/category: nextCat\.name,/);
    expect(commitBody).toMatch(
      /api\.patch\(`\/quotes\/\$\{row\.invoice_id\}`,\s*\{ line_items: items \}\)/,
    );
  });
});


describe("INCOME-DRILLDOWN-EDIT · Service Unit Select in both variants", () => {
  it("2. renders a Select bound to serviceCategories with option testids", () => {
    // Cell testid is scoped to the row so multiple rows are addressable.
    expect(INCOME_ROW).toMatch(/-svc-cell`/);
    expect(INCOME_ROW).toMatch(/-svc-trigger`/);
    expect(INCOME_ROW).toMatch(/-svc-option-\$\{c\.id\}`/);
    expect(INCOME_ROW).toMatch(/onValueChange=\{commitServiceUnit\}/);
    // Options are sourced from the tenant-scoped serviceCategories prop.
    expect(INCOME_ROW).toMatch(
      /\{serviceCategories\.map\(\(c\) => \([\s\S]{0,240}SelectItem/,
    );
    // Legacy read-only text cell (``row.service_category || "—"``) is
    // retired — the Service Unit column is now editable in both
    // income variants.
    expect(INCOME_ROW).not.toMatch(
      /\{row\.service_category \|\| "—"\}/,
    );
  });

  it("4. changing Service Unit sends paired {service_category_id, service_category} on the PATCH line item", () => {
    expect(INCOME_ROW).toMatch(/const commitServiceUnit = async \(nextId\) =>/);
    const commitBody = INCOME_ROW.split(
      "const commitServiceUnit = async",
    )[1].split("\n  const ")[0];
    expect(commitBody).toMatch(/service_category_id: nextCat\.id,/);
    expect(commitBody).toMatch(/service_category: nextCat\.name,/);
    expect(commitBody).toMatch(
      /api\.patch\(`\/quotes\/\$\{row\.invoice_id\}`,\s*\{ line_items: items \}\)/,
    );
  });
});


describe("INCOME-DRILLDOWN-EDIT · optimistic UI + rollback", () => {
  it("5. optimistic — commitServiceUnit sets svcCategoryId BEFORE the network call", () => {
    const commitBody = INCOME_ROW.split(
      "const commitServiceUnit = async",
    )[1].split("\n  const ")[0];
    const svcSetIdx = commitBody.indexOf("setSvcCategoryId(nextId);");
    const apiPatchIdx = commitBody.indexOf("api.patch(");
    expect(svcSetIdx).toBeGreaterThan(-1);
    expect(apiPatchIdx).toBeGreaterThan(-1);
    expect(svcSetIdx).toBeLessThan(apiPatchIdx);
  });

  it("5. optimistic — commitLineCategoryPaired sets lineCatId BEFORE the network call", () => {
    const commitBody = INCOME_ROW.split(
      "const commitLineCategoryPaired = async",
    )[1].split("\n  const ")[0];
    const setIdx = commitBody.indexOf("setLineCatId(nextId);");
    const apiPatchIdx = commitBody.indexOf("api.patch(");
    expect(setIdx).toBeGreaterThan(-1);
    expect(apiPatchIdx).toBeGreaterThan(-1);
    expect(setIdx).toBeLessThan(apiPatchIdx);
  });

  it("6. rollback — commitServiceUnit catch branch restores svcCategoryId to the pre-edit value", () => {
    const commitBody = INCOME_ROW.split(
      "const commitServiceUnit = async",
    )[1].split("\n  const ")[0];
    expect(commitBody).toMatch(/} catch \(e\) \{\s*\n\s*setSvcCategoryId\(before\);/);
  });

  it("6. rollback — commitLineCategoryPaired catch branch restores lineCatId to the pre-edit value", () => {
    const commitBody = INCOME_ROW.split(
      "const commitLineCategoryPaired = async",
    )[1].split("\n  const ")[0];
    expect(commitBody).toMatch(/} catch \(e\) \{\s*\n\s*setLineCatId\(before\);/);
  });
});


describe("INCOME-DRILLDOWN-EDIT · options load once on modal open", () => {
  it("7. income_categories fetch is a ModalBody effect (not a per-row IncomeRow effect)", () => {
    // The fetch effect lives in ModalBody (outside the IncomeRow
    // function).  If the effect leaked into IncomeRow it would fire
    // once PER row on mount and blow the "load once" contract.
    expect(INCOME_ROW).not.toMatch(
      /api\.get\("\/income-categories\?include_archived=false"\)/,
    );
    // The ModalBody-level effect is present and gated so it only
    // fires for the two income variants.
    expect(MODAL).toMatch(
      /api\.get\("\/income-categories\?include_archived=false"\)/,
    );
    expect(MODAL).toMatch(
      /if \(variant !== "income-by-category" && variant !== "income-by-service"\) \{\s*\n?\s*return undefined;/,
    );
  });

  it("7. service_categories fetch is a ModalBody effect (not a per-row IncomeRow effect)", () => {
    expect(INCOME_ROW).not.toMatch(
      /api\.get\("\/service-categories\?include_archived=false"\)/,
    );
    expect(MODAL).toMatch(
      /api\.get\("\/service-categories\?include_archived=false"\)/,
    );
  });

  it("7. both fetch effects short-circuit and set the cancelled flag on unmount (load-once contract)", () => {
    // Two fetch effects, each with a ``let cancelled = false;`` + a
    // cleanup ``return () => { cancelled = true; };``.
    const cancelledSetups = MODAL.match(/let cancelled = false;/g) || [];
    expect(cancelledSetups.length).toBeGreaterThanOrEqual(2);
    const cleanups = MODAL.match(
      /return \(\) => \{ cancelled = true; \};/g,
    ) || [];
    expect(cleanups.length).toBeGreaterThanOrEqual(2);
  });
});


describe("INCOME-DRILLDOWN-EDIT · Business Unit paired-ID contract", () => {
  it("commitBusinessUnit sends BOTH business_unit_id AND business_unit on the PATCH", () => {
    // Extends the K48 verify-hotfix BU-only contract with the
    // paired-ID FK.  Backend ``InvoiceEditBody`` accepts both fields.
    const commitBody = INCOME_ROW.split(
      "const commitBusinessUnit = async",
    )[1].split("\n  const ")[0];
    expect(commitBody).toMatch(/business_unit: nextCat\.name,/);
    expect(commitBody).toMatch(/business_unit_id: nextCat\.id,/);
    // Money-neutral BU-only body — must not spread line_items.
    expect(commitBody).not.toMatch(/line_items: items/);
  });
});


describe("INCOME-DRILLDOWN-EDIT · row-level hydration resolvers", () => {
  it("resolveInitialSvcId prefers row.service_category_id then falls back to name match", () => {
    expect(INCOME_ROW).toMatch(/const resolveInitialSvcId = \(\) => \{/);
    const body = INCOME_ROW.split("const resolveInitialSvcId = ()")[1]
      .split("};")[0];
    expect(body).toMatch(/row\?\.service_category_id/);
    expect(body).toMatch(/serviceCategories\.find\(/);
    // Direct FK check fires FIRST — before the name fallback.
    // ``indexOf("row?.service_category_id")`` locks onto the FK line;
    // ``indexOf("row?.service_category ||")`` locks onto the name line
    // (which uses ``|| ""`` to coalesce a null denorm to a lowercase-
    // safe empty string).
    const directIdx = body.indexOf("row?.service_category_id");
    const nameIdx = body.indexOf("row?.service_category ||");
    expect(directIdx).toBeGreaterThan(-1);
    expect(nameIdx).toBeGreaterThan(directIdx);
  });

  it("resolveInitialLineCatId prefers row.income_category_id then falls back to name match", () => {
    expect(INCOME_ROW).toMatch(/const resolveInitialLineCatId = \(\) => \{/);
    const body = INCOME_ROW.split("const resolveInitialLineCatId = ()")[1]
      .split("};")[0];
    expect(body).toMatch(/row\?\.income_category_id/);
    expect(body).toMatch(/incomeCategories\.find\(/);
    const directIdx = body.indexOf("row?.income_category_id");
    const nameIdx = body.indexOf("row?.category");
    expect(directIdx).toBeGreaterThan(-1);
    expect(nameIdx).toBeGreaterThan(directIdx);
  });
});
