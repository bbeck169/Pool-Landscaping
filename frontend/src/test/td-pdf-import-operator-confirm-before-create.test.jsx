/**
 * TD-pdf-import-operator-confirm-before-create · Feb-2026
 * ============================================================
 *
 * Vitest coverage for Part 1's FE confirmation gate in
 * ``PdfInvoiceUploadSidePanel``.
 *
 * Scope note: static-source assertions only.  The panel's full
 * state machine (``idle → uploading → polling → preview_ready →
 * committing``) is already covered by the Phase 33 + PDFI-PAID
 * test suites; those suites exercise the Commit button and
 * state transitions.  This file guards the specific delta:
 *   * ``pendingClassification`` state is wired to the poll
 *     response's ``pending_customer_classification`` field.
 *   * ``confirmWillAutoCreate`` state exists + is reset in
 *     ``_reset``.
 *   * ``_readyToCommit`` includes the ``!_unmatchedRequiresConfirm``
 *     guard so the button disables when ``will_auto_create > 0``
 *     and the checkbox is unticked.
 *   * ``commitBatch`` payload carries ``confirm_will_auto_create``.
 *   * The confirmation banner + checkbox + testids render inside
 *     the preview-ready step.
 *   * Error handler maps the new BE 400
 *     ``unmatched_customers_require_confirmation`` to a toast +
 *     return-to-preview flow (mirrors the manual_review handler).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";


const PANEL_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/components/invoices/PdfInvoiceUploadSidePanel.jsx"),
  "utf-8",
);


describe("PdfInvoiceUploadSidePanel · confirmation gate state", () => {
  it("declares pendingClassification + confirmWillAutoCreate state", () => {
    expect(PANEL_SRC).toMatch(
      /const\s+\[pendingClassification,\s*setPendingClassification\]\s*=\s*useState\(null\)/);
    expect(PANEL_SRC).toMatch(
      /const\s+\[confirmWillAutoCreate,\s*setConfirmWillAutoCreate\]\s*=\s*useState\(false\)/);
  });

  it("_reset clears both new state slots", () => {
    // Narrow to the _reset callback body.
    const idx = PANEL_SRC.indexOf("const _reset = useCallback");
    expect(idx).toBeGreaterThan(-1);
    const slice = PANEL_SRC.slice(idx, idx + 600);
    expect(slice).toMatch(/setPendingClassification\(null\)/);
    expect(slice).toMatch(/setConfirmWillAutoCreate\(false\)/);
  });

  it("poll handler captures pending_customer_classification into state", () => {
    expect(PANEL_SRC).toMatch(
      /setPendingClassification\(\s*row\.pending_customer_classification\s*\|\|\s*null,?\s*\)/);
  });
});


describe("PdfInvoiceUploadSidePanel · _readyToCommit gating", () => {
  it("derives _willAutoCreateCount from pendingClassification", () => {
    expect(PANEL_SRC).toMatch(/_willAutoCreateCount/);
    expect(PANEL_SRC).toMatch(
      /pendingClassification\?\.will_auto_create/);
  });

  it("derives _unmatchedRequiresConfirm", () => {
    expect(PANEL_SRC).toMatch(/_unmatchedRequiresConfirm/);
    expect(PANEL_SRC).toMatch(
      /_willAutoCreateCount\s*>\s*0\s*&&\s*!confirmWillAutoCreate/);
  });

  it("_readyToCommit includes the unmatched-requires-confirm guard", () => {
    // Narrow to the _readyToCommit expression.
    const idx = PANEL_SRC.indexOf("const _readyToCommit = (");
    expect(idx).toBeGreaterThan(-1);
    const close = PANEL_SRC.indexOf("  );", idx);
    const slice = PANEL_SRC.slice(idx, close + 4);
    expect(slice).toMatch(/!_unmatchedRequiresConfirm/);
  });
});


describe("PdfInvoiceUploadSidePanel · commit payload + error handling", () => {
  it("commitBatch call ships confirm_will_auto_create flag", () => {
    expect(PANEL_SRC).toMatch(
      /commitBatch\(\s*batchId,\s*\{[\s\S]{0,500}confirm_will_auto_create:\s*confirmWillAutoCreate/);
  });

  it("error handler maps unmatched_customers_require_confirmation", () => {
    expect(PANEL_SRC).toMatch(
      /errCode === "unmatched_customers_require_confirmation"/);
    // Returns operator to the preview-ready step for the retry.
    const idx = PANEL_SRC.indexOf(
      '"unmatched_customers_require_confirmation"');
    expect(idx).toBeGreaterThan(-1);
    const slice = PANEL_SRC.slice(idx, idx + 400);
    expect(slice).toMatch(/setStep\("preview_ready"\)/);
    expect(slice).toMatch(/toast\.error\(/);
  });
});


describe("PdfInvoiceUploadSidePanel · banner + checkbox rendering", () => {
  it("renders the warning banner only when _willAutoCreateCount > 0", () => {
    // Conditional render guard — guards against regression where
    // the banner is shown on a matched-only batch.
    expect(PANEL_SRC).toMatch(
      /\{_willAutoCreateCount\s*>\s*0\s*&&\s*\(/);
  });

  it("banner carries the required testids for operator automation", () => {
    expect(PANEL_SRC).toMatch(
      /data-testid="pdfi-upload-will-auto-create-banner"/);
    expect(PANEL_SRC).toMatch(
      /data-testid="pdfi-upload-will-auto-create-count"/);
    expect(PANEL_SRC).toMatch(
      /data-testid="pdfi-upload-confirm-auto-create-checkbox"/);
    expect(PANEL_SRC).toMatch(
      /data-testid="pdfi-upload-confirm-auto-create-label"/);
  });

  it("checkbox wires to setConfirmWillAutoCreate", () => {
    expect(PANEL_SRC).toMatch(
      /onChange=\{\(e\)\s*=>[\s\S]{0,200}setConfirmWillAutoCreate\(\s*e\.target\.checked[,\s)]/);
  });

  it("singular / plural copy present on the banner", () => {
    expect(PANEL_SRC).toMatch(
      /1 new customer will be auto-created/);
    expect(PANEL_SRC).toMatch(
      /\$\{_willAutoCreateCount\} new customers will be auto-created/);
  });

  it("checkbox copy includes an explicit 'I confirm' affordance", () => {
    expect(PANEL_SRC).toMatch(/I confirm/);
  });
});
