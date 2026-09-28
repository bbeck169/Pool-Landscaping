/**
 * PDF-MIRROR · Feb-2026 — Preview panel mirror contract.
 *
 * Source-inspection locks matching the K6 / CHEM-LOCK pattern.
 * The runtime page is a 2000+ line component with route +
 * upload + polling wiring; validating the mirror surface at
 * source level is cheaper and just as strict.
 *
 * Coverage:
 *   1. Preview total row renders ``formatIsoDate(q.doc_date)``
 *      (verbatim from the extractor) — NOT ``formatIsoDate(new
 *      Date())`` or a today-fallback.
 *   2. Multi-line description renders with ``whitespace-pre-wrap``
 *      so embedded ``\n`` renders as line breaks.
 *   3. ``total_source`` badge (Verbatim / Reconstructed /
 *      Needs Review) sits under the amount cell with the
 *      canonical data-testid.
 *   4. ``Needs Review`` banner + commit-button gate: banner
 *      renders when ≥1 preview has grand_total AND line-item
 *      sum both $0.00; commit button is disabled until the
 *      admin checks the ack box.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/imports/PdfInvoiceImportPage.jsx"),
  "utf8",
);


describe("PdfInvoiceImportPage · PDF-MIRROR preview contract", () => {
  it("renders the extractor's ``q.doc_date`` verbatim in the preview row", () => {
    // Priority: source PDF's doc_date > commit-time fallback.
    // The row reads ``formatIsoDate(q.doc_date)`` — no ``||`` /
    // ``??`` fallback to ``new Date()`` or today.
    expect(SRC).toMatch(
      /\{\s*formatIsoDate\(\s*q\.doc_date\s*\)\s*\}/,
    );
    // No silent today-fallback anywhere near the doc_date cell.
    // (Prohibited: ``formatIsoDate(q.doc_date || new Date())``.)
    expect(SRC).not.toMatch(
      /formatIsoDate\(\s*q\.doc_date\s*\|\|\s*new\s+Date/,
    );
  });

  it("renders multi-line line-item descriptions via whitespace-pre-wrap", () => {
    // The description <td> carries ``whitespace-pre-wrap`` so
    // embedded ``\n`` renders as visible line breaks — matches
    // the extractor's mandate to join multi-line descriptions
    // with ``\n``.
    expect(SRC).toMatch(
      /whitespace-pre-wrap[\s\S]{0,200}data-testid=\{`pdf-import-line-item-\$\{fileId\}-\$\{sourceIdx\}-\$\{idx\}-description`\}/,
    );
  });

  it("renders the total_source badge under the total cell", () => {
    // Badge lives inside the total column with a canonical
    // data-testid that includes ``-total-source-badge``.
    expect(SRC).toMatch(
      /data-testid=\{`pdf-import-preview-row-\$\{fileId\}-\$\{preview\.source_doc_index\}-total-source-badge`\}/,
    );
    // Three possible values: Verbatim, Reconstructed, Needs Review.
    expect(SRC).toMatch(/Verbatim/);
    expect(SRC).toMatch(/Reconstructed/);
    expect(SRC).toMatch(/Needs Review/);
  });

  it("renders the Needs Review banner when any preview is zero-total-unrecoverable", () => {
    expect(SRC).toMatch(
      /data-testid=\{`pdf-import-needs-review-banner-\$\{fileId\}`\}/,
    );
    // Banner is gated ``needsReviewCount > 0 ? … : null``.
    expect(SRC).toMatch(/needsReviewCount\s*>\s*0\s*\?/);
    // Copy locked so a rename doesn't slip past review.
    expect(SRC).toMatch(/need review/);
  });

  it("disables the commit button until the admin acks the needs-review warning", () => {
    // Commit button carries ``disabled={isCommitting || (needsReviewCount > 0 && !needsReviewAcked)}``.
    // Whitespace-tolerant across newlines (the JSX prop wraps).
    expect(SRC).toMatch(
      /disabled=\{\s*isCommitting[\s\S]*?needsReviewCount\s*>\s*0[\s\S]*?!needsReviewAcked\s*\)\s*\}/,
    );
    // Ack checkbox has the canonical testid.
    expect(SRC).toMatch(
      /data-testid=\{`pdf-import-needs-review-ack-\$\{fileId\}`\}/,
    );
  });

  it("derives needsReviewCount from grand_total + line-item sum ($0.00 both)", () => {
    // The client-side heuristic mirrors the backend's
    // ``_apply_totals`` decision so the badge / gate render
    // pre-commit.
    expect(SRC).toMatch(
      /const\s+_isNeedsReview\s*=\s*\(p\)\s*=>/,
    );
    // Reads line_total || qty × unit_price for each line.
    expect(SRC).toMatch(/const\s+lt\s*=\s*li\?\.line_total/);
    // ``sum === 0`` is the terminal reject condition.
    expect(SRC).toMatch(/return\s+sum\s*===\s*0/);
  });
});
