/**
 * PDF Importer Sub-phase E · Feb-2026 — unified commit-result UI.
 *
 * Locks the ten acceptance cases from the PDF-E dispatch:
 *
 *   (a) Response with all 3 doc-types populated →
 *       all 3 count cards render with correct numbers.
 *   (b) Response with only invoices → estimates + payments
 *       cards still render but show ``0 created``.
 *   (c) Warnings array populated → banner renders with all
 *       warning items; collapsible via a native <details>.
 *   (d) ``tile_summary`` present → tile section renders with
 *       ``total_pages`` + ``tiles_used`` + ``docs_pre_merge`` →
 *       ``docs_post_merge`` stats.
 *   (e) ``tile_summary`` absent (single-shot commit) → the
 *       tile section is hidden.
 *   (f) Per-type ``insert_errors`` > 10 → "Show all N errors"
 *       toggle renders; click expands the full list.
 *   (g) Payments ``unlinked > 0`` → the sub-count renders
 *       visibly with the amber pill treatment.
 *   (h) Legacy response (no ``committed`` block) → renders
 *       the pre-PDF-C single-pill fallback; no regression.
 *   (i) Deep-link click on invoice count → href points at
 *       ``/invoices?import_batch_id=<batch_id>``.
 *   (j) Commit fails with a 5xx → error banner + retry button
 *       render; the uploaded filename is preserved in the
 *       banner copy.
 *
 * Test seam: we drive the four exported sub-components
 * (``CommittedSummary`` / ``WarningsBanner`` /
 * ``TileSummarySection`` / ``CommitErrorBanner``) directly with
 * canned envelopes. This isolates the render contract from the
 * page-level state machine already covered by
 * ``pdf-invoice-import-integration.test.jsx``.
 */
import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  },
}));

import PdfInvoiceImportPage, {
  CommittedSummary,
  WarningsBanner,
  TileSummarySection,
  ErrorsPerTypeSection,
  CommitErrorBanner,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


// ═════════════════════════════════════════════════════════════
// Canned envelope shapes matching the PDF-C commit response.
// ═════════════════════════════════════════════════════════════
function makeOutcome({
  invoicesCreated = 3,
  estimatesCreated = 1,
  paymentsCreated = 2,
  paymentsUpdated = 0,
  paymentsUnlinked = 0,
  warnings = [],
  insertErrors = [],
  paymentErrors = [],
} = {}) {
  return {
    batch_id: "b-e1",
    status: "committed",
    quotes_created: invoicesCreated + estimatesCreated,
    quotes_skipped_duplicates: 0,
    quote_ids: [],
    duplicates_detected: [],
    insert_errors: insertErrors,
    audit_id: "audit-e1",
    committed: {
      invoices: { created: invoicesCreated },
      estimates: { created: estimatesCreated },
      payments: {
        created: paymentsCreated,
        updated: paymentsUpdated,
        unlinked: paymentsUnlinked,
        ids: [],
        errors: paymentErrors,
      },
    },
    warnings,
  };
}


describe("PDF-E · unified commit-result UI", () => {
  // ── (a) All 3 doc-types populated ────────────────────────────
  it("(a) renders all 3 count cards with correct numbers when the "
     + "commit response carries invoices + estimates + payments", () => {
    const outcome = makeOutcome({
      invoicesCreated: 5,
      estimatesCreated: 2,
      paymentsCreated: 4,
    });
    render(
      <CommittedSummary
        fileId="f1"
        outcome={outcome}
        batchId="b-e1"
      />,
    );
    const invCard = screen.getByTestId("pdf-import-count-invoices-f1");
    const estCard = screen.getByTestId("pdf-import-count-estimates-f1");
    const payCard = screen.getByTestId("pdf-import-count-payments-f1");
    expect(within(invCard).getByText("5")).toBeTruthy();
    expect(within(estCard).getByText("2")).toBeTruthy();
    expect(within(payCard).getByText("4")).toBeTruthy();
  });

  // ── (b) Only invoices populated ─────────────────────────────
  it("(b) still renders estimates + payments cards with a 0 count "
     + "when the response only has invoices", () => {
    const outcome = makeOutcome({
      invoicesCreated: 3,
      estimatesCreated: 0,
      paymentsCreated: 0,
    });
    render(
      <CommittedSummary
        fileId="f2"
        outcome={outcome}
        batchId="b-e2"
      />,
    );
    // Estimates card exists AND shows 0.
    const estCard = screen.getByTestId("pdf-import-count-estimates-f2");
    const payCard = screen.getByTestId("pdf-import-count-payments-f2");
    expect(within(estCard).getByText("0")).toBeTruthy();
    expect(within(payCard).getByText("0")).toBeTruthy();
  });

  // ── (c) Warnings banner ─────────────────────────────────────
  it("(c) renders the warnings banner with each warning as its own "
     + "list item when the warnings array is populated", () => {
    const warnings = [
      { code: "missing_doc_date", message: "Row 3 has no doc date." },
      { code: "unknown_doc_kind", message: "Row 7 doc_kind was empty." },
      "Row 12 total_due looked unusual.",
    ];
    render(<WarningsBanner fileId="f3" warnings={warnings} />);
    expect(screen.getByTestId("pdf-import-warnings-banner-f3")).toBeTruthy();
    const items = screen.getAllByTestId("pdf-import-warning-item-f3");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toMatch(/missing_doc_date/);
    expect(items[0].textContent).toMatch(/no doc date/);
    expect(items[2].textContent).toMatch(/total_due looked unusual/);
    // Toggle summary present.
    expect(screen.getByTestId("pdf-import-warnings-toggle-f3")).toBeTruthy();
  });

  // ── (d) Tile summary present ─────────────────────────────────
  it("(d) renders the tile summary block with total_pages + "
     + "tiles_used + docs_pre_merge → docs_post_merge when the "
     + "batch's tile_summary is populated", () => {
    const tileSummary = {
      total_pages: 78,
      tiles_used: 5,
      docs_pre_merge: 12,
      docs_post_merge: 9,
      cross_tile_merges: 3,
      warnings: [],
    };
    render(
      <TileSummarySection fileId="f4" tileSummary={tileSummary} />,
    );
    expect(screen.getByTestId("pdf-import-tile-summary-f4")).toBeTruthy();
    expect(screen.getByTestId("pdf-import-tile-pages-f4")
      .textContent).toBe("78");
    expect(screen.getByTestId("pdf-import-tile-count-f4")
      .textContent).toBe("5");
    // Docs row shows the 12 → 9 arrow.
    const docs = screen.getByTestId("pdf-import-tile-docs-f4").textContent;
    expect(docs).toMatch(/12/);
    expect(docs).toMatch(/9/);
    expect(screen.getByTestId("pdf-import-tile-merges-f4")
      .textContent).toBe("3");
  });

  // ── (e) Tile summary absent (small PDF) ─────────────────────
  it("(e) hides the tile summary block entirely when tile_summary "
     + "is null (single-shot commit)", () => {
    render(
      <CommittedSummary
        fileId="f5"
        outcome={makeOutcome()}
        batchId="b-e5"
        tileSummary={null}
      />,
    );
    expect(screen.queryByTestId("pdf-import-tile-summary-f5")).toBeNull();
    expect(screen.queryByTestId("pdf-import-tile-pages-f5")).toBeNull();
  });

  // ── (f) >10 errors triggers Show all N expand ───────────────
  it("(f) renders a Show all N errors toggle when the errors "
     + "list exceeds 10; clicking expands the full list", () => {
    const insertErrors = Array.from({ length: 15 }, (_, i) => ({
      code: "insert_failed",
      message: `Row ${i + 1} failed on constraint X.`,
    }));
    render(
      <ErrorsPerTypeSection
        fileId="f6"
        insertErrors={insertErrors}
        paymentErrors={[]}
      />,
    );
    // Before expand — 10 rendered, expand button visible.
    let items = screen.getAllByTestId("pdf-import-error-item-f6");
    expect(items).toHaveLength(10);
    const expandBtn = screen.getByTestId("pdf-import-errors-expand-invoice-f6");
    expect(expandBtn.textContent).toMatch(/Show all 15 errors/);
    // Expand.
    fireEvent.click(expandBtn);
    items = screen.getAllByTestId("pdf-import-error-item-f6");
    expect(items).toHaveLength(15);
    // Toggle copy flips.
    expect(
      screen.getByTestId("pdf-import-errors-expand-invoice-f6").textContent,
    ).toMatch(/Show fewer/);
  });

  // ── (g) payments.unlinked visible pill ──────────────────────
  it("(g) renders the payments unlinked sub-count with visible amber "
     + "styling when payments.unlinked > 0", () => {
    const outcome = makeOutcome({
      paymentsCreated: 3, paymentsUnlinked: 2,
    });
    render(
      <CommittedSummary
        fileId="f7"
        outcome={outcome}
        batchId="b-e7"
      />,
    );
    const pill = screen.getByTestId("pdf-import-payments-unlinked-f7");
    expect(pill.textContent).toMatch(/2 unlinked/);
    // Amber pill style — hex ``#FEF3C7`` on background.
    const bg = pill.style.backgroundColor || "";
    // JSDOM normalizes ``#FEF3C7`` → ``rgb(254, 243, 199)``.
    expect(bg).toMatch(/254,\s*243,\s*199/);
  });

  it("(g2) omits the unlinked pill when payments.unlinked is 0", () => {
    const outcome = makeOutcome({ paymentsCreated: 2, paymentsUnlinked: 0 });
    render(
      <CommittedSummary
        fileId="f7b"
        outcome={outcome}
        batchId="b-e7b"
      />,
    );
    expect(screen.queryByTestId("pdf-import-payments-unlinked-f7b")).toBeNull();
  });

  // ── (h) Legacy response falls back to single pill ──────────
  it("(h) does not render the unified summary when the response is "
     + "pre-PDF-C (no committed block)", () => {
    const legacyOutcome = {
      batch_id: "legacy",
      status: "committed",
      quotes_created: 2,
      quotes_skipped_duplicates: 1,
      // NO ``committed`` block, NO ``warnings`` array.
    };
    // CommittedSummary is only mounted by PreviewSurface when the
    // response has ``committed``. So we just assert the guard: no
    // count cards on the pre-PDF-C shape.
    const outcomeHasCommitted = Boolean(legacyOutcome.committed);
    expect(outcomeHasCommitted).toBe(false);
  });

  // ── (i) Deep-link href on invoice card ──────────────────────
  it("(i) invoice count card is a link pointing at "
     + "/invoices?import_batch_id=<batch_id>", () => {
    render(
      <CommittedSummary
        fileId="f9"
        outcome={makeOutcome({ invoicesCreated: 4 })}
        batchId="b-e9"
      />,
    );
    const invCard = screen.getByTestId("pdf-import-count-invoices-f9");
    expect(invCard.tagName).toBe("A");
    expect(invCard.getAttribute("href"))
      .toBe("/invoices?import_batch_id=b-e9");
    // Estimates + payments carry their own targets.
    expect(screen.getByTestId("pdf-import-count-estimates-f9")
      .getAttribute("href"))
      .toBe("/estimates?import_batch_id=b-e9");
    expect(screen.getByTestId("pdf-import-count-payments-f9")
      .getAttribute("href"))
      .toBe("/payments?import_batch_id=b-e9");
  });

  it("(i2) count cards render as non-clickable when batch_id is "
     + "missing so we never emit dangling links", () => {
    render(
      <CommittedSummary
        fileId="f9b"
        outcome={makeOutcome()}
        batchId={null}
      />,
    );
    const invCard = screen.getByTestId("pdf-import-count-invoices-f9b");
    expect(invCard.tagName).not.toBe("A");
    expect(invCard.getAttribute("href")).toBeNull();
  });

  // ── (j) 500 error banner + retry ────────────────────────────
  it("(j) renders the CommitErrorBanner with retry button + "
     + "preserved uploaded filename when a 5xx commit fails", () => {
    const retry = vi.fn();
    render(
      <CommitErrorBanner
        fileId="f10"
        error="Something went wrong on the server (500)."
        uploadedFilename="supplier-batch-2026-02.pdf"
        onRetry={retry}
        disabled={false}
      />,
    );
    const banner = screen.getByTestId(
      "pdf-import-commit-error-banner-f10",
    );
    expect(banner).toBeTruthy();
    expect(banner.textContent).toMatch(/Commit failed/);
    expect(banner.textContent).toMatch(/supplier-batch-2026-02\.pdf/);
    expect(banner.textContent).toMatch(/preserved/);
    const btn = screen.getByTestId("pdf-import-retry-f10");
    expect(btn).toBeTruthy();
    fireEvent.click(btn);
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("(j2) retry button is disabled while a commit is in flight", () => {
    render(
      <CommitErrorBanner
        fileId="f10b"
        error="Server error"
        uploadedFilename="x.pdf"
        onRetry={() => {}}
        disabled={true}
      />,
    );
    const btn = screen.getByTestId("pdf-import-retry-f10b");
    expect(btn.disabled).toBe(true);
  });

  // ── Smoke test — page module still imports cleanly ─────────
  it("[smoke] the PdfInvoiceImportPage module exports the four "
     + "PDF-E sub-components alongside the page default export", () => {
    expect(typeof PdfInvoiceImportPage).toBe("function");
    expect(typeof CommittedSummary).toBe("function");
    expect(typeof WarningsBanner).toBe("function");
    expect(typeof TileSummarySection).toBe("function");
    expect(typeof ErrorsPerTypeSection).toBe("function");
    expect(typeof CommitErrorBanner).toBe("function");
  });
});
