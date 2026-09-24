/**
 * Phase P56 · Feb-2026 — Pricebook Bulk Edit Categories modal
 * on OpsHub PriceBook tab.
 *
 * Locks in the source-shape invariants for OpsHub.jsx's P56
 * additions per the file's discovered testing convention
 * (source-scan via fs.readFileSync + regex — same pattern as
 * p18-recurring-jobs-tabs.test.jsx + p54-recurring-jobs-bulk-
 * edit.test.jsx).
 *
 * Invariants:
 *   1. Toolbar "Bulk Edit Categories" button testid
 *      ``bulk-edit-categories-button`` — sits inside the existing
 *      ``selectedCount > 0`` toolbar conditional, so it's only
 *      rendered when the bulk-actions bar itself is visible.
 *   2. Modal root ``bulk-edit-categories-modal`` — mounted only
 *      when ``bulkEditOpen`` is truthy.
 *   3. Service dropdown ``bulk-edit-service-cat-select`` — first
 *      <option> is the "Unchanged" sentinel (value="").
 *   4. Income dropdown ``bulk-edit-income-cat-select`` — same
 *      "Unchanged" first-option pattern.
 *   5. Apply / Cancel testids: ``bulk-edit-apply``,
 *      ``bulk-edit-cancel``.
 *   6. Inline error slot ``bulk-edit-error`` — routes backend
 *      422 codes without a raw toast.
 *   7. ``doBulkEditCategories`` builds POST payload conditionally:
 *        * if (bulkEditServiceCat) payload.service_category_id
 *          = bulkEditServiceCat  — "Unchanged" (empty string) is
 *          OMITTED.
 *        * same for income.
 *      No ``null`` is ever sent.
 *   8. Apply disabled when both dropdowns are "Unchanged".
 *   9. Batch cap ``_BULK_UPDATE_CATEGORIES_BATCH = 100`` matches
 *      the backend constant ``_PRICEBOOK_BULK_UPDATE_CATEGORIES_
 *      MAX``.
 *  10. Slicing loop: ``allIds.slice(i, i +
 *      _BULK_UPDATE_CATEGORIES_BATCH)`` so payloads > 100 don't
 *      trigger a raw 400.
 *
 * The frontend tests LOCK the wire contract; the authoritative
 * behaviour coverage lives in the P56 backend test suite
 * (backend/tests/test_p56_pricebook_bulk_update_categories.py).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC_PATH = path.resolve(__dirname, "../pages/ops/OpsHub.jsx");
const src = fs.readFileSync(SRC_PATH, "utf8");


describe("Phase P56 · Pricebook Bulk Edit Categories toolbar button", () => {
  it("renders with the canonical bulk-namespace data-testid", () => {
    // Convention: OpsHub PriceBook uses ``bulk-*`` (no page
    // qualifier) for bulk-only elements — Q4/A grep-verified.
    expect(src).toMatch(/data-testid="bulk-edit-categories-button"/);
  });

  it("gates open on bulkEditBusy for double-submit protection", () => {
    // Toolbar-level disable predicate. selectedCount gate is
    // enforced by the enclosing ``{selectedCount > 0 ? ...}``
    // conditional in the bar itself (already covered by the
    // sibling bulk-delete pattern).
    expect(src).toMatch(/disabled=\{bulkEditBusy\}/);
  });

  it("resets dropdowns + error state on click, then opens modal", () => {
    expect(src).toMatch(/setBulkEditServiceCat\(""\)/);
    expect(src).toMatch(/setBulkEditIncomeCat\(""\)/);
    expect(src).toMatch(/setBulkEditError\(""\)/);
    expect(src).toMatch(/setBulkEditOpen\(true\)/);
  });
});


describe("Phase P56 · Pricebook Bulk Edit Categories modal", () => {
  it("renders the modal root with the canonical data-testid", () => {
    expect(src).toMatch(/data-testid="bulk-edit-categories-modal"/);
  });

  it("only mounts when bulkEditOpen is truthy", () => {
    expect(src).toMatch(/\{bulkEditOpen \? \(/);
  });

  it("renders the Service dropdown with an Unchanged sentinel first", () => {
    expect(src).toMatch(/data-testid="bulk-edit-service-cat-select"/);
    // Anchored inside the specific select so the assertion doesn't
    // collide with any other <option value=""> in the file.
    expect(src).toMatch(
      /bulk-edit-service-cat-select[\s\S]{0,600}<option value="">Unchanged<\/option>/,
    );
  });

  it("renders the Income dropdown with an Unchanged sentinel first", () => {
    expect(src).toMatch(/data-testid="bulk-edit-income-cat-select"/);
    expect(src).toMatch(
      /bulk-edit-income-cat-select[\s\S]{0,600}<option value="">Unchanged<\/option>/,
    );
  });

  it("renders the Apply + Cancel buttons with canonical testids", () => {
    expect(src).toMatch(/data-testid="bulk-edit-apply"/);
    expect(src).toMatch(/data-testid="bulk-edit-cancel"/);
  });

  it("declares an inline-error slot with the canonical testid", () => {
    expect(src).toMatch(/data-testid="bulk-edit-error"/);
  });

  it("disables Apply when both dropdowns are still Unchanged", () => {
    // Same predicate as the P54 modal — empty-string sentinel
    // is falsy, so ``!x && !y`` fires the disable when both are
    // still on Unchanged. Also covers the ``selectedCount === 0``
    // + ``bulkEditBusy`` guards.
    expect(src).toMatch(
      /disabled=\{[\s\S]*?bulkEditBusy \|\|[\s\S]*?selectedCount === 0 \|\|[\s\S]*?\(!bulkEditServiceCat && !bulkEditIncomeCat\)/,
    );
  });
});


describe("Phase P56 · doBulkEditCategories payload construction", () => {
  it("only includes service_category_id when bulkEditServiceCat is truthy", () => {
    expect(src).toMatch(
      /if \(bulkEditServiceCat\)\s*\{\s*payload\.service_category_id = bulkEditServiceCat/,
    );
  });

  it("only includes income_category_id when bulkEditIncomeCat is truthy", () => {
    expect(src).toMatch(
      /if \(bulkEditIncomeCat\)\s*\{\s*payload\.income_category_id = bulkEditIncomeCat/,
    );
  });

  it("posts to the P56 bulk endpoint URL", () => {
    expect(src).toMatch(
      /api\.post\(\s*["']\/pricebook\/bulk-update-categories["']/,
    );
  });

  it("uses _BULK_UPDATE_CATEGORIES_BATCH = 100 to slice the payload", () => {
    // Matches the backend constant
    // _PRICEBOOK_BULK_UPDATE_CATEGORIES_MAX = 100.
    expect(src).toMatch(
      /const _BULK_UPDATE_CATEGORIES_BATCH = 100;/,
    );
    expect(src).toMatch(
      /allIds\.slice\(i, i \+ _BULK_UPDATE_CATEGORIES_BATCH\)/,
    );
  });

  it("aggregates response counts across payload slices", () => {
    expect(src).toMatch(/updated \+= Number\(res\?\.updated \|\| 0\)/);
    expect(src).toMatch(/already \+= Number\(res\?\.already_current \|\| 0\)/);
    expect(src).toMatch(/failed \+= Number\(res\?\.failed \|\| 0\)/);
    expect(src).toMatch(
      /childInv \+= Number\([\s\S]{0,200}?child_invoices_updated \|\| 0/,
    );
  });

  it("clears selection + closes modal + resets dropdowns on success", () => {
    expect(src).toMatch(/clearSelection\(\);/);
    expect(src).toMatch(/setBulkEditOpen\(false\);/);
    expect(src).toMatch(/refresh\(\);/);
  });

  it("routes backend 422 codes to the inline error slot (not a toast)", () => {
    expect(src).toMatch(/setBulkEditError\([\s\S]{0,240}?raw\.code/);
  });

  it("uses OpsHub's setToast (not sonner toast.*) for the aggregate result", () => {
    // OpsHub's toast surface is the setToast({tone, message})
    // shape, not the sonner toast.success/warning helpers used
    // in RecurringJobs. Grep-verified in the P56 halt-report.
    expect(src).toMatch(
      /setToast\(\{\s*tone:\s*failed > 0 \? "warning" : "success"/,
    );
  });
});
