/**
 * Phase K41 · Feb-2026 — Dashboard drill-down modal Vitest.
 *
 * Contract checks live at the source-body level (mirroring the K40
 * pattern already used across this repo) so the suite runs without
 * mounting the full modal graph.  This keeps the tests focused on
 * the invariants that matter — variant wiring, locked fields, K37
 * boundary presence, K41 audit hook — without spinning up recharts /
 * shadcn / api mocks per case.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const MODAL = read("src/components/dashboard/DashboardDrillDownModal.jsx");
const REV   = read("src/components/dashboard/RevenueByCategoryTile.jsx");
const SVC   = read("src/components/dashboard/IncomeByServiceCategoryTile.jsx");
const DI    = read("src/components/admin/DataIntegrityTile.jsx");


describe("K41 · DashboardDrillDownModal — component contract", () => {
  it("declares exactly three variants", () => {
    expect(MODAL).toMatch(/variant="data-integrity"/);
    expect(MODAL).toMatch(/variant="income-by-category"/);
    expect(MODAL).toMatch(/variant="income-by-service"/);
  });

  it("wraps the modal body in the K37 PortalErrorBoundary with the K41 label", () => {
    expect(MODAL).toMatch(/import\s+PortalErrorBoundary\s+from\s+"@\/components\/errors\/PortalErrorBoundary"/);
    expect(MODAL).toMatch(/<PortalErrorBoundary[\s\S]{0,120}label="dashboard-drilldown"/);
  });

  it("hits the three K41 GET endpoints with cursor + limit", () => {
    expect(MODAL).toMatch(/\/dashboard\/data-integrity\/rows\?class=/);
    expect(MODAL).toMatch(/\/dashboard\/income\/by-category\/rows\?category=/);
    expect(MODAL).toMatch(/\/dashboard\/income\/by-service\/rows\?service_category_id=/);
    expect(MODAL).toMatch(/limit=100/);
    expect(MODAL).toMatch(/cursor=/);
  });

  it("posts K41 line-item audit after every income-variant save", () => {
    expect(MODAL).toMatch(/api\.post\("\/dashboard\/drilldown\/line-item-audit"/);
    expect(MODAL).toMatch(/tile,[\s\S]{0,60}invoice_id:[\s\S]{0,120}field,[\s\S]{0,60}before,[\s\S]{0,60}after/);
  });

  it("posts K41 data-integrity resolve endpoint on assign/delete", () => {
    expect(MODAL).toMatch(/api\.post\("\/dashboard\/data-integrity\/resolve"/);
    expect(MODAL).toMatch(/action: act/);
    expect(MODAL).toMatch(/ref_class: refClass/);
  });

  it("marks the LOCKED fields (extended, invoice_total, status) read-only", () => {
    // LockedCell wrapper is applied to computed/status fields only.
    expect(MODAL).toMatch(/LockedCell[\s\S]{0,200}row\.extended/);
    expect(MODAL).toMatch(/LockedCell[\s\S]{0,200}row\.invoice_total/);
    expect(MODAL).toMatch(/LockedCell[\s\S]{0,220}row\.invoice_status/);
    // And qty/unit_price/description/category ARE inline-editable.
    expect(MODAL).toMatch(/EDITABLE_INCOME_FIELDS = new Set\(\[[\s\S]*?"description"[\s\S]*?"quantity"[\s\S]*?"unit_price"[\s\S]*?"category"[\s\S]*?\]\)/);
  });

  it("implements optimistic UI with rollback on save failure", () => {
    // Draft state is set OPTIMISTICALLY (via onChange) BEFORE the
    // patch call.  On catch, the draft rolls back to originalRef.
    expect(MODAL).toMatch(/setDraft\(\(d\) => \(\{ \.\.\.d, \[field\]: before \}\)\)/);
    expect(MODAL).toMatch(/originalRef\.current = \{ \.\.\.draft \}/);
  });

  it("supports cursor pagination via a Load more button", () => {
    expect(MODAL).toMatch(/data-testid="drilldown-load-more"/);
    expect(MODAL).toMatch(/setCursor\(nextCursor\)/);
  });

  it("closes on ESC via Dialog + explicit close button", () => {
    // shadcn Dialog handles ESC natively; we assert the close button
    // wiring so a keyboard-only user can dismiss even if focus is
    // trapped elsewhere.
    expect(MODAL).toMatch(/data-testid={`dashboard-drilldown-close-\$\{variant\}`}/);
    expect(MODAL).toMatch(/onOpenChange={\(v\) => \{ if \(!v\) onClose\?\.\(\); \}\}/);
  });
});


describe("K41 · Tile wiring — legend click opens the modal", () => {
  it("RevenueByCategoryTile — legend items are keyboard-focusable and open the modal", () => {
    expect(REV).toMatch(/import DashboardDrillDownModal/);
    expect(REV).toMatch(/tabIndex=\{0\}/);
    expect(REV).toMatch(/role="button"/);
    expect(REV).toMatch(/onClick=\{\(\) => setDrillCategory\(it\.displayLabel\)\}/);
    // Enter/space keyboard access
    expect(REV).toMatch(/if \(e\.key === "Enter" \|\| e\.key === " "\)/);
    // Cursor + hover affordance
    expect(REV).toMatch(/cursor-pointer/);
    expect(REV).toMatch(/hover:bg-slate-100/);
    // Modal is mounted with the right variant + params
    expect(REV).toMatch(/variant="income-by-category"/);
    expect(REV).toMatch(/category: drillCategory/);
  });

  it("IncomeByServiceCategoryTile — legend items open the modal", () => {
    expect(SVC).toMatch(/import DashboardDrillDownModal/);
    expect(SVC).toMatch(/onClick=\{\(\) => setDrillCategory\(it\.category\)\}/);
    expect(SVC).toMatch(/variant="income-by-service"/);
    expect(SVC).toMatch(/service_category_id: drillCategory/);
    expect(SVC).toMatch(/if \(e\.key === "Enter" \|\| e\.key === " "\)/);
  });

  it("DataIntegrityTile — dangling-ref stat cells open the modal on click", () => {
    expect(DI).toMatch(/import DashboardDrillDownModal/);
    expect(DI).toMatch(/setDrillClass\("orphaned_customer_refs"\)/);
    expect(DI).toMatch(/variant="data-integrity"/);
    // Keyboard access via role=button + tabIndex on the StatCell
    expect(DI).toMatch(/role={clickable \? "button" : undefined}/);
    expect(DI).toMatch(/tabIndex={clickable \? 0 : undefined}/);
  });
});


describe("K41 · Locked fields — never editable via the modal", () => {
  const LOCKED_KEYS = [
    "invoice_total",
    "invoice_tax",
    "invoice_status",
    "paid_at",
    "payment_method",
    "extended",
  ];

  it.each(LOCKED_KEYS)("field %s is NOT in EDITABLE_INCOME_FIELDS", (key) => {
    // Extract the editable-set literal and assert the key is absent.
    const match = MODAL.match(
      /EDITABLE_INCOME_FIELDS = new Set\(\[([\s\S]*?)\]\)/,
    );
    expect(match).toBeTruthy();
    const editableBody = match[1];
    expect(editableBody).not.toMatch(new RegExp(`"${key}"`));
  });
});


describe("K41 · Endpoints — modal targets the K41 URL surface", () => {
  it("no direct dependency on any other dashboard endpoint", () => {
    // Regression guard: the drill-down modal must not accidentally
    // hit the aggregate tile endpoints (that's the tile's job).
    expect(MODAL).not.toMatch(/\/admin\/dashboard\/revenue-by-category/);
    expect(MODAL).not.toMatch(/\/admin\/dashboard\/income-by-service-category/);
  });

  it("still uses the existing invoice PATCH pipeline for line-item edits", () => {
    // K41 phase brief §K6: do NOT invent new PATCH endpoints.
    expect(MODAL).toMatch(/api\.patch\(`\/quotes\/\$\{row\.invoice_id\}`/);
  });
});
