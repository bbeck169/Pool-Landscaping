/**
 * Task B · Phase 2 · Commit 6 — full-page integration test.
 *
 * Walks the entire PDF-invoice import lifecycle end-to-end with
 * mocked fetch:
 *
 *   upload → poll → preview → commit → rollback
 *
 * The four prior test files
 * (``pdf-invoice-import-scaffold`` / ``upload`` / ``polling`` /
 * ``preview``) lock the individual seams; this file locks the
 * seams' *composition* so a future refactor that shuffles
 * responsibilities between the pool pump + poll loop + preview
 * surface + commit/rollback handlers cannot silently break the
 * happy path or the commit-error revert path.
 *
 * Every fetch call is intercepted; no real network happens.
 */
import React from "react";
import {
  render, screen, fireEvent, act, waitFor, within,
} from "@testing-library/react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error:   vi.fn(),
    warning: vi.fn(),
    info:    vi.fn(),
    success: vi.fn(),
  },
}));

import PdfInvoiceImportPage, {
  FILE_STATUS,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


function makePdf(name, sizeBytes) {
  const blob = new Blob([new Uint8Array(1)], { type: "application/pdf" });
  const f = new File([blob], name, { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: sizeBytes });
  return f;
}

function fireFileSelect(input, files) {
  let list;
  try {
    const dt = new DataTransfer();
    for (const f of files) dt.items.add(f);
    list = dt.files;
  } catch {
    list = Object.assign(files, {
      item: (i) => files[i], length: files.length,
    });
  }
  fireEvent.change(input, { target: { files: list } });
}


// Canned batch shape reused across the integration cases.  Two
// invoice rows + one payment receipt (payment receipt filtered
// out of the preview table per Ruling from recon report §A.2).
const CANNED_BATCH = {
  batch_id: "int-b1",
  id: "int-b1",
  status: "preview_complete",
  progress_pct: 100,
  mapper_previews: [
    {
      source_doc_index: 0,
      doc_kind: "invoice",
      mapped_target: "quote_in",
      customer_resolution: "matched",
      matched_customer_id: "cust-a1",
      quote_in: {
        doc_number: "INV-2001",
        doc_date: "2026-02-15",
        total_due: 1500.00,
        customer_name: "Acme Pools LLC",
      },
    },
    {
      source_doc_index: 1,
      doc_kind: "invoice",
      mapped_target: "quote_in",
      customer_resolution: "matched",
      matched_customer_id: "cust-b1",
      quote_in: {
        doc_number: "INV-2002",
        doc_date: "2026-02-16",
        total_due: 250.00,
        customer_name: "Blue Wave Landscaping",
      },
    },
  ],
};


describe("PdfInvoiceImportPage · full lifecycle integration", () => {
  let fetchSpy;

  beforeEach(() => {
    fetchSpy = vi.spyOn(window, "fetch");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function drain() {
    for (let i = 0; i < 16; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      await act(async () => { await Promise.resolve(); });
    }
  }

  it("walks upload → poll → preview → commit → rollback with the "
     + "expected DOM state at every hop", async () => {
    // Wire the full fetch sequence:
    //   1. POST /pdf-invoice        → 202 batch_id
    //   2. GET  /pdf-invoice/{id}   → 200 preview_complete
    //   3. GET  /duplicates         → 200 dup on index 1
    //   4. POST /commit             → 200 committed
    //   5. POST /rollback           → 200 rolled_back
    fetchSpy
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: CANNED_BATCH.batch_id,
          status: "queued",
          poll_hint_seconds: 300,
        }),
        { status: 202 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify(CANNED_BATCH),
        { status: 200 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: CANNED_BATCH.batch_id,
          duplicate_count: 1,
          duplicates: [{
            source_doc_index: 1,
            existing_quote_id: "existing-q99",
            doc_number: "INV-2002",
            customer_id: "cust-b1",
          }],
        }),
        { status: 200 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: CANNED_BATCH.batch_id,
          status: "committed",
          quotes_created: 1,
          quotes_skipped_duplicates: 1,
          quote_ids: ["q-new-42"],
          audit_id: "audit-1",
        }),
        { status: 200 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: CANNED_BATCH.batch_id,
          status: "rolled_back",
          quotes_deleted: 1,
          collision_count: 0,
          audit_id: "audit-2",
        }),
        { status: 200 },
      ));

    render(<PdfInvoiceImportPage />);

    // ── Hop 1: upload ────────────────────────────────────────
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();

    // ── Hop 2: poll flips row to PREVIEW_READY ───────────────
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.PREVIEW_READY);
    });

    // ── Hop 3: expand chevron → duplicates fetched ───────────
    const expandBtn = screen.getByTestId(/^pdf-import-file-expand-/);
    await act(async () => { fireEvent.click(expandBtn); });
    await drain();

    // Preview surface mounted, 2 rows (both quote_in), 1 duplicate
    // pill on row index 1.
    const preview = await waitFor(() => screen.getByTestId(
      /^pdf-import-preview-pdf-file-\d+-\d+$/,
    ));
    const previewRows = within(preview).getAllByTestId(
      /^pdf-import-preview-row-pdf-file-.*-\d+$/,
    );
    expect(previewRows).toHaveLength(2);
    expect(previewRows[1].getAttribute("data-duplicate")).toBe("true");
    expect(within(preview).getByTestId(
      /^pdf-import-preview-dup-link-pdf-file-.*-1$/,
    )).toBeTruthy();

    // Commit CTA visible, rollback CTA absent.
    const commitBtn = within(preview).getByTestId(
      /^pdf-import-commit-btn-/,
    );
    expect(commitBtn).toBeTruthy();
    expect(within(preview).queryByTestId(
      /^pdf-import-rollback-btn-/,
    )).toBeNull();

    // ── Hop 4: click Commit → row flips to COMMITTED ─────────
    await act(async () => { fireEvent.click(commitBtn); });
    await drain();

    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.COMMITTED);
    });
    // Committed badge with 1 created / 1 skipped counts.
    const committedBadge = within(preview).getByTestId(
      /^pdf-import-preview-committed-badge-/,
    );
    expect(committedBadge.textContent).toMatch(/Committed/);
    expect(committedBadge.textContent).toMatch(/1 created/);
    expect(committedBadge.textContent).toMatch(/1 skipped/);
    // Radio group + Commit CTA hidden once terminal.
    expect(within(preview).queryByTestId(
      /^pdf-import-commit-btn-/,
    )).toBeNull();
    expect(within(preview).queryByTestId(
      /^pdf-import-preview-on-dup-/,
    )).toBeNull();

    // Rollback CTA now visible; carries a title (within 24h of a
    // just-set committed_at → the safe-window copy per Ruling
    // E.3).
    const rollbackBtn = within(preview).getByTestId(
      /^pdf-import-rollback-btn-/,
    );
    const title = rollbackBtn.getAttribute("title") || "";
    expect(title).toMatch(/Roll back/i);
    // Not the >24h warning copy because committed_at was just set.
    expect(title).not.toMatch(/24h of commit/);

    // ── Hop 5: click Rollback → row flips to ROLLED_BACK ─────
    await act(async () => { fireEvent.click(rollbackBtn); });
    await drain();

    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.ROLLED_BACK);
    });
    // Rolled-back badge visible; committed badge gone.
    expect(within(preview).getByTestId(
      /^pdf-import-preview-rolledback-badge-/,
    )).toBeTruthy();
    expect(within(preview).queryByTestId(
      /^pdf-import-preview-committed-badge-/,
    )).toBeNull();
    // Rollback CTA hidden once terminal.
    expect(within(preview).queryByTestId(
      /^pdf-import-rollback-btn-/,
    )).toBeNull();

    // ── Fetch call log — five hops, four verbs, correct URLs ──
    const calls = fetchSpy.mock.calls;
    expect(calls.length).toBe(5);
    // 1. POST /api/imports/pdf-invoice
    expect(calls[0][0]).toMatch(/\/api\/imports\/pdf-invoice$/);
    expect(calls[0][1].method).toBe("POST");
    // 2. GET  /api/imports/pdf-invoice/int-b1
    expect(calls[1][0]).toMatch(/\/api\/imports\/pdf-invoice\/int-b1$/);
    expect(calls[1][1].method).toBe("GET");
    // 3. GET  /api/imports/pdf-invoice/int-b1/duplicates
    expect(calls[2][0]).toMatch(
      /\/api\/imports\/pdf-invoice\/int-b1\/duplicates$/,
    );
    expect(calls[2][1].method).toBe("GET");
    // 4. POST /api/imports/pdf-invoice/int-b1/commit
    expect(calls[3][0]).toMatch(
      /\/api\/imports\/pdf-invoice\/int-b1\/commit$/,
    );
    expect(calls[3][1].method).toBe("POST");
    // Commit payload carries on_duplicate=skip (default per Ruling E.6).
    const commitBody = JSON.parse(calls[3][1].body);
    expect(commitBody.on_duplicate).toBe("skip");
    // 5. POST /api/imports/pdf-invoice/int-b1/rollback
    expect(calls[4][0]).toMatch(
      /\/api\/imports\/pdf-invoice\/int-b1\/rollback$/,
    );
    expect(calls[4][1].method).toBe("POST");
  });

  it("reverts to PREVIEW_READY + surfaces inline error copy when "
     + "the commit fails with a typed error", async () => {
    // POST kickoff → 202
    // GET poll     → preview_complete
    // GET dups     → 0 duplicates
    // POST commit  → 400 unresolved_customers
    fetchSpy
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: CANNED_BATCH.batch_id,
          status: "queued",
          poll_hint_seconds: 300,
        }),
        { status: 202 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify(CANNED_BATCH),
        { status: 200 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: CANNED_BATCH.batch_id,
          duplicate_count: 0,
          duplicates: [],
        }),
        { status: 200 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          detail: { error: "unresolved_customers" },
        }),
        { status: 400 },
      ));

    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();
    await waitFor(() => screen.getByTestId(/^pdf-import-file-expand-/));
    fireEvent.click(screen.getByTestId(/^pdf-import-file-expand-/));
    await drain();

    const preview = screen.getByTestId(
      /^pdf-import-preview-pdf-file-\d+-\d+$/,
    );
    const commitBtn = within(preview).getByTestId(
      /^pdf-import-commit-btn-/,
    );
    await act(async () => { fireEvent.click(commitBtn); });
    await drain();

    // Row reverts to PREVIEW_READY so the operator can adjust
    // + retry (spec revert path — see PdfInvoiceImportPage
    // ``handleCommitFailure``).
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.PREVIEW_READY);
    });
    // Inline error pill carries the translated typed-error copy.
    const errPill = within(preview).getByTestId(
      /^pdf-import-preview-commit-error-/,
    );
    expect(errPill.textContent).toMatch(/unresolved customer matches/i);
    // Commit CTA is visible again (not disabled/hidden by the error).
    expect(within(preview).getByTestId(
      /^pdf-import-commit-btn-/,
    )).toBeTruthy();
  });
});
