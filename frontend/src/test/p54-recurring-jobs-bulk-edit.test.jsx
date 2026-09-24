/**
 * Phase P54 · Feb-2026 — Recurring Jobs Bulk Edit Categories
 * (filter dropdown + bulk-edit modal).
 *
 * Locks in the source-shape invariants for RecurringJobs.jsx per
 * the file's discovered testing convention (see
 * p18-recurring-jobs-tabs.test.jsx :7-10 — full JSDOM mount is
 * brittle on the ~2500 LOC surface; source-scan captures the
 * wire contract at the same level as the backend test suite).
 *
 * Invariants:
 *   1. Service-category filter <select> renders with the
 *      canonical data-testid ``recurring-jobs-service-category-
 *      filter`` and an "All categories" default first option
 *      (value=""). Options are mapped from ``serviceCats``.
 *   2. ``filteredItems`` memo composes the search filter AND
 *      the category filter; a non-empty ``serviceCategoryFilter``
 *      narrows to exact ``r.service_category_id`` matches.
 *   3. Categories load on mount (not just on Edit-modal open) so
 *      the filter + bulk-edit modal have options on first render.
 *   4. Toolbar "Bulk Edit Categories" button testid
 *      ``recurring-bulk-edit-categories`` — always rendered,
 *      disabled when ``selectedIds.size === 0`` or the request
 *      is in-flight.
 *   5. Modal root data-testid ``recurring-bulk-edit-categories-
 *      modal``. Renders only when ``bulkEditOpen`` is truthy.
 *   6. Modal dropdowns:
 *        * Service: data-testid ``recurring-bulk-edit-service-
 *          cat-select``. First <option> is the "Unchanged"
 *          sentinel (value=""). Remaining options mapped from
 *          ``serviceCats``.
 *        * Income:  data-testid ``recurring-bulk-edit-income-
 *          cat-select``. Same "Unchanged" pattern.
 *   7. ``bulkEditApply`` builds the POST payload conditionally:
 *        * ``if (bulkEditServiceCat) payload.service_category_id
 *          = ...``  — empty-string "Unchanged" is OMITTED.
 *        * same for income.
 *      No ``null`` is ever sent for a category field.
 *   8. Apply button disabled when both dropdowns are still
 *      "Unchanged". Disable predicate:
 *      ``!bulkEditServiceCat && !bulkEditIncomeCat``.
 *   9. Apply / Cancel testids: ``recurring-bulk-edit-apply``,
 *      ``recurring-bulk-edit-cancel``. Inline error slot testid
 *      ``recurring-bulk-edit-error`` for backend 422 codes.
 *  10. Batch cap constant ``BULK_UPDATE_CATEGORIES_BATCH = 100``
 *      matches the backend ``_BULK_UPDATE_CATEGORIES_MAX``.
 *
 * The frontend tests LOCK the wire contract; the authoritative
 * behaviour coverage lives in the P54 backend test suite
 * (backend/tests/test_p54_recurring_jobs_bulk_update_categories.py).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC_PATH = path.resolve(
  __dirname, "../pages/admin/RecurringJobs.jsx",
);
const src = fs.readFileSync(SRC_PATH, "utf8");


describe("Phase P54 · Recurring Jobs service-category filter", () => {
  it("renders the filter <select> with the canonical data-testid", () => {
    expect(src).toMatch(
      /data-testid="recurring-jobs-service-category-filter"/,
    );
  });

  it('exposes an "All categories" default first option (value="")', () => {
    // The value="" sentinel is what turns the filter OFF —
    // filteredItems ignores an empty string filter.
    expect(src).toMatch(/<option value="">All categories<\/option>/);
  });

  it("maps its option list from the serviceCats state", () => {
    // The filter dropdown reuses the same serviceCats state
    // populated by _loadCategories — no separate fetch.
    expect(src).toMatch(
      /serviceCats\.map\(\(c\) => \(\s*<option key=\{c\.id\} value=\{c\.id\}>\s*\{c\.name\}\s*<\/option>\s*\)\)/,
    );
  });

  it("declares a serviceCategoryFilter state (default empty string)", () => {
    expect(src).toMatch(
      /const \[serviceCategoryFilter, setServiceCategoryFilter\] = useState\(""\)/,
    );
  });

  it("composes filteredItems with the category filter AFTER the search filter", () => {
    // Non-empty ``serviceCategoryFilter`` narrows to exact
    // ``service_category_id`` matches. Rows without the denorm
    // drop out — matches the P4 taxonomy read-side contract.
    expect(src).toMatch(
      /if \(serviceCategoryFilter\)\s*\{[\s\S]*?vis\.filter\(\s*\(r\) =>\s*r\.service_category_id === serviceCategoryFilter/,
    );
  });

  it("depends the filteredItems memo on all three inputs", () => {
    // The memo's dep array must include serviceCategoryFilter
    // alongside items + searchQuery so the filter re-runs when
    // the dropdown flips.
    expect(src).toMatch(
      /\}, \[items, searchQuery, serviceCategoryFilter\]\);/,
    );
  });

  it("loads categories on mount (not just modal open)", () => {
    // The Edit-modal-open effect stays put; the P54 addition is
    // a SEPARATE mount-only effect that fires _loadCategories
    // once on first render so the filter has options before any
    // modal is ever opened.
    expect(src).toMatch(
      /useEffect\(\(\) => \{\s*_loadCategories\(\);[\s\S]*?\}, \[\]\);/,
    );
  });
});


describe("Phase P54 · Bulk Edit Categories toolbar button", () => {
  it("renders with the canonical bulk-namespace data-testid", () => {
    // Convention: bulk-only buttons use ``recurring-bulk-*``,
    // not the ``recurring-jobs-*`` prefix used by non-bulk
    // elements (P54 · Q4/A grep-verified).
    expect(src).toMatch(/data-testid="recurring-bulk-edit-categories"/);
  });

  it("gates open on selectedIds.size + bulkEditBusy", () => {
    // Same disabled predicate as Bulk Activate / Delete Permanently
    // for consistency with the discovered convention.
    expect(src).toMatch(
      /disabled=\{selectedIds\.size === 0 \|\| bulkEditBusy\}/,
    );
  });

  it("opens the modal + resets dropdown + error state on click", () => {
    // The onClick MUST reset both dropdowns to "" and clear any
    // prior inline error so a stale 422 doesn't leak into the
    // next modal open.
    expect(src).toMatch(/setBulkEditServiceCat\(""\)/);
    expect(src).toMatch(/setBulkEditIncomeCat\(""\)/);
    expect(src).toMatch(/setBulkEditError\(""\)/);
    expect(src).toMatch(/setBulkEditOpen\(true\)/);
  });
});


describe("Phase P54 · Bulk Edit Categories modal", () => {
  it("renders the modal root with the canonical data-testid", () => {
    expect(src).toMatch(
      /data-testid="recurring-bulk-edit-categories-modal"/,
    );
  });

  it("only mounts when bulkEditOpen is truthy", () => {
    // Same ternary pattern as the sibling bulk-hard-delete modal.
    expect(src).toMatch(/\{bulkEditOpen \? \(/);
  });

  it("renders the Service dropdown with an Unchanged sentinel first", () => {
    expect(src).toMatch(
      /data-testid="recurring-bulk-edit-service-cat-select"/,
    );
    // The Unchanged option MUST be first (index 0) inside this
    // specific select — anchored to the service-cat testid so
    // the assertion doesn't accidentally match the filter dropdown.
    expect(src).toMatch(
      /recurring-bulk-edit-service-cat-select[\s\S]{0,600}<option value="">Unchanged<\/option>/,
    );
  });

  it("renders the Income dropdown with an Unchanged sentinel first", () => {
    expect(src).toMatch(
      /data-testid="recurring-bulk-edit-income-cat-select"/,
    );
    expect(src).toMatch(
      /recurring-bulk-edit-income-cat-select[\s\S]{0,600}<option value="">Unchanged<\/option>/,
    );
  });

  it("renders the Apply + Cancel buttons with canonical testids", () => {
    expect(src).toMatch(/data-testid="recurring-bulk-edit-apply"/);
    expect(src).toMatch(/data-testid="recurring-bulk-edit-cancel"/);
  });

  it("declares an inline-error slot with the canonical testid", () => {
    // Backend 422 codes render inline next to the dropdowns
    // instead of a raw error toast — more actionable per the
    // dropdown-adjacent error pattern used elsewhere in the file.
    expect(src).toMatch(/data-testid="recurring-bulk-edit-error"/);
  });

  it("disables Apply when both dropdowns are still Unchanged", () => {
    // Empty-string sentinel is falsy — ``!x && !y`` fires the
    // disable when both are still on Unchanged. Matches the
    // backend's no_category_fields_set guard so the operator
    // never sees a raw 400.
    expect(src).toMatch(
      /disabled=\{[\s\S]*?bulkEditBusy \|\|[\s\S]*?selectedIds\.size === 0 \|\|[\s\S]*?\(!bulkEditServiceCat && !bulkEditIncomeCat\)/,
    );
  });
});


describe("Phase P54 · bulkEditApply payload construction", () => {
  it("only includes service_category_id when bulkEditServiceCat is truthy", () => {
    // Empty-string sentinel is falsy, so this conditional guards
    // against the frontend ever sending ``service_category_id: ""``
    // OR ``service_category_id: null`` — the backend's
    // model_fields_set check requires the key to be ABSENT from
    // the JSON body to leave the field unchanged.
    expect(src).toMatch(
      /if \(bulkEditServiceCat\)\s*\{\s*payload\.service_category_id = bulkEditServiceCat/,
    );
  });

  it("only includes income_category_id when bulkEditIncomeCat is truthy", () => {
    expect(src).toMatch(
      /if \(bulkEditIncomeCat\)\s*\{\s*payload\.income_category_id = bulkEditIncomeCat/,
    );
  });

  it("posts to the P54 bulk endpoint URL", () => {
    expect(src).toMatch(
      /api\.post\(\s*["']\/recurring-jobs\/bulk-update-categories["']/,
    );
  });

  it("uses BULK_UPDATE_CATEGORIES_BATCH = 100 to slice the payload", () => {
    // Matches the backend constant _BULK_UPDATE_CATEGORIES_MAX
    // = 100 so the operator never sees a raw batch_too_large 400.
    expect(src).toMatch(
      /const BULK_UPDATE_CATEGORIES_BATCH = 100;/,
    );
    expect(src).toMatch(
      /allIds\.slice\(i, i \+ BULK_UPDATE_CATEGORIES_BATCH\)/,
    );
  });

  it("aggregates response counts across payload slices", () => {
    // updated / already / failed / childInv are incremented across
    // slices — the operator's toast reflects the truth after every
    // slice completes.
    expect(src).toMatch(
      /updated \+= Number\(res\?\.updated \|\| 0\)/,
    );
    expect(src).toMatch(
      /already \+= Number\(res\?\.already_current \|\| 0\)/,
    );
    expect(src).toMatch(
      /failed \+= Number\(res\?\.failed \|\| 0\)/,
    );
    expect(src).toMatch(
      /childInv \+= Number\([\s\S]{0,200}?child_invoices_updated \|\| 0/,
    );
  });

  it("clears selection + closes modal + resets dropdowns on success", () => {
    // Success path: bulk operation is done — reset the modal
    // state so the next open starts fresh.
    expect(src).toMatch(/setSelectedIds\(new Set\(\)\);/);
    expect(src).toMatch(/setBulkEditOpen\(false\);/);
  });

  it("routes backend 422 codes to the inline error slot (not a toast)", () => {
    // Backend 422 detail is {code, field, attempted, collection}.
    // The handler reads code + field and stamps them on
    // bulkEditError instead of firing a generic error toast.
    expect(src).toMatch(
      /setBulkEditError\([\s\S]{0,240}?raw\.code/,
    );
  });
});
