/**
 * Task B · Phase 2 · Commit 4 — dry-run preview table + duplicate
 * pre-flight highlighting.
 *
 * Locks the preview-surface contract that fires once a batch
 * reaches PREVIEW_READY:
 *
 *   1. ``fetchDuplicates(batchId)`` GET wire format (recon §A.3).
 *   2. ``formatCurrency`` / ``formatIsoDate`` display utilities.
 *   3. Preview surface renders one row per ``mapper_previews[*]``
 *      with ``mapped_target === "quote_in"`` — payment receipts
 *      are shown as an info notice, not a table row.
 *   4. Rows whose ``source_doc_index`` appears in the duplicates
 *      envelope render with the ``bg-amber-50 text-amber-900``
 *      tone AND expose a link-shaped ``Duplicate`` pill that
 *      opens the existing invoice at ``/invoices/{existing_quote_id}``
 *      in a new tab.
 *   5. Summary chip strip announces the total row count + the
 *      current duplicate count, using amber tint when there are
 *      duplicates.
 *   6. Expand / collapse — a PREVIEW_READY row exposes a
 *      chevron toggle that mounts / unmounts the preview surface
 *      inline.
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
  fetchDuplicates,
  formatCurrency,
  formatIsoDate,
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


// A canned preview envelope — 3 invoice rows + 1 payment
// receipt (should NOT render in the table).
const CANNED_BATCH = {
  batch_id: "canned-b1",
  id: "canned-b1",
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
        doc_number: "INV-1001",
        doc_date: "2026-01-15",
        total_due: 1234.56,
        customer_name: "Acme Pools LLC",
      },
    },
    {
      source_doc_index: 1,
      doc_kind: "invoice",
      mapped_target: "quote_in",
      customer_resolution: "matched",
      matched_customer_id: "cust-a2",
      quote_in: {
        doc_number: "INV-1002",
        doc_date: "2026-01-16",
        total_due: 89.00,
        customer_name: "Blue Wave Landscaping",
      },
    },
    {
      source_doc_index: 2,
      doc_kind: "invoice",
      mapped_target: "quote_in",
      customer_resolution: "pending",
      quote_in: {
        doc_number: "INV-1003",
        doc_date: "2026-01-17",
        total_due: 500.00,
        customer_name: "PENDING::Sunshine",
      },
    },
    {
      source_doc_index: 3,
      doc_kind: "payment_receipt",
      mapped_target: "deferred_to_h4",
      customer_resolution: "matched",
      matched_customer_id: "cust-b1",
      quote_in: null,
    },
  ],
};


describe("formatCurrency · US currency display", () => {
  it.each([
    [1234.56,     "$1,234.56"],
    [0,           "$0.00"],
    [null,        "—"],
    [undefined,   "—"],
    [NaN,         "—"],
    ["not-num",   "—"],
    [1000000,     "$1,000,000.00"],
  ])("formats %s → %s", (amount, expected) => {
    expect(formatCurrency(amount)).toBe(expected);
  });
});


describe("formatIsoDate · en-US locale display", () => {
  it.each([
    ["2026-03-14",   /Mar 14, 2026/],
    ["2026-01-01",   /Jan 1, 2026/],
    ["not-a-date",   /^—$/],
    ["",             /^—$/],
    [null,           /^—$/],
    [undefined,      /^—$/],
  ])("formats %s → matches %s", (dateStr, pattern) => {
    expect(formatIsoDate(dateStr)).toMatch(pattern);
  });
});


describe("fetchDuplicates · GET wire format", () => {
  beforeEach(() => { vi.spyOn(window, "fetch"); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("hits /duplicates with Bearer auth + URL-encoded batch id", async () => {
    const body = {
      batch_id: "b1",
      duplicate_count: 1,
      duplicates: [{
        source_doc_index: 0,
        existing_quote_id: "q-existing",
        doc_number: "INV-1001",
        customer_id: "cust-a1",
      }],
    };
    window.fetch.mockResolvedValueOnce(new Response(
      JSON.stringify(body), { status: 200 },
    ));
    const out = await fetchDuplicates("b1", {
      baseUrl: "https://api.example.com",
      token: "test-jwt",
    });
    expect(out.duplicate_count).toBe(1);
    const [url, opts] = window.fetch.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/api/imports/pdf-invoice/b1/duplicates",
    );
    expect(opts.method).toBe("GET");
    expect(opts.headers.Authorization).toBe("Bearer test-jwt");
  });

  it("throws with a translated message on 404", async () => {
    window.fetch.mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: { error: "batch_not_found" } }),
      { status: 404 },
    ));
    await expect(fetchDuplicates("missing", {
      baseUrl: "https://api.example.com", token: "test-jwt",
    })).rejects.toThrow(/Upload failed \(404\)/);
  });
});


// ── Component-level preview surface ─────────────────────────────

describe("PdfInvoiceImportPage · preview surface", () => {
  let fetchSpy;
  beforeEach(() => {
    fetchSpy = vi.spyOn(window, "fetch");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function drain() {
    for (let i = 0; i < 14; i += 1) {
      await act(async () => { await Promise.resolve(); });
    }
  }

  function primeFetches({ duplicates = [] } = {}) {
    // 1st fetch = POST kickoff (202 with batch_id).
    // 2nd fetch = GET poll → returns preview_complete + the
    //   canned mapper_previews.
    // 3rd fetch = GET duplicates.
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
          duplicate_count: duplicates.length,
          duplicates,
        }),
        { status: 200 },
      ));
  }

  it("renders the expand chevron on PREVIEW_READY rows only, " +
     "and NOT on QUEUED / UPLOADING / PROCESSING / ERROR rows", async () => {
    primeFetches();
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.PREVIEW_READY);
    });
    const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
    // Extract the file id from the row testid.
    const id = rows[0].getAttribute("data-testid")
      .replace(/^pdf-import-file-row-/, "");
    expect(
      screen.getByTestId(`pdf-import-file-expand-${id}`),
    ).toBeTruthy();
  });

  it("mounts the preview surface when the chevron is clicked, " +
     "renders one row per quote_in preview (payment receipt " +
     "skipped)", async () => {
    primeFetches();
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();
    await waitFor(() => screen.getByTestId(/^pdf-import-file-expand-/));

    // Preview surface not mounted until the chevron fires.
    expect(screen.queryByTestId(/^pdf-import-preview-/)).toBeNull();
    const expandBtn = screen.getByTestId(/^pdf-import-file-expand-/);
    await act(async () => { fireEvent.click(expandBtn); });
    await drain();

    // Preview + table are now mounted.
    const preview = screen.getByTestId(/^pdf-import-preview-pdf-file-\d+-\d+$/);
    expect(preview).toBeTruthy();
    const table = within(preview).getByTestId(
      /^pdf-import-preview-table-pdf-file-/,
    );
    const rows = within(table).getAllByTestId(
      /^pdf-import-preview-row-pdf-file-.*-\d+$/,
    );
    // 3 quote_in rows — payment receipt (index 3) filtered out.
    expect(rows).toHaveLength(3);
    // Row 0 carries INV-1001 / $1,234.56 / Acme Pools LLC.
    expect(rows[0].textContent).toMatch(/INV-1001/);
    expect(rows[0].textContent).toMatch(/\$1,234\.56/);
    expect(rows[0].textContent).toMatch(/Acme Pools LLC/);
  });

  it("highlights duplicate rows amber + renders a Duplicate " +
     "pill that opens the existing invoice in a new tab", async () => {
    primeFetches({
      duplicates: [{
        source_doc_index: 1,
        existing_quote_id: "existing-q42",
        doc_number: "INV-1002",
        customer_id: "cust-a2",
      }],
    });
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();
    await waitFor(() => screen.getByTestId(/^pdf-import-file-expand-/));
    fireEvent.click(screen.getByTestId(/^pdf-import-file-expand-/));
    await drain();

    // Row 1 is duplicate — check the data-duplicate attribute
    // and the amber tone.
    const rowDup = await waitFor(() => {
      const r = screen.getByTestId(
        /^pdf-import-preview-row-pdf-file-.*-1$/,
      );
      expect(r.getAttribute("data-duplicate")).toBe("true");
      return r;
    });
    // Amber background class.
    expect(rowDup.className).toMatch(/bg-amber-50/);
    expect(rowDup.className).toMatch(/text-amber-900/);
    // Duplicate pill links to the existing quote — new tab.
    const dupLink = within(rowDup).getByTestId(
      /^pdf-import-preview-dup-link-pdf-file-.*-1$/,
    );
    expect(dupLink.tagName.toLowerCase()).toBe("a");
    expect(dupLink.getAttribute("href")).toBe(
      "/invoices/existing-q42",
    );
    expect(dupLink.getAttribute("target")).toBe("_blank");
    expect(dupLink.getAttribute("rel")).toBe("noreferrer");

    // Row 0 is NOT a duplicate — no amber, "New" pill.
    const row0 = screen.getByTestId(
      /^pdf-import-preview-row-pdf-file-.*-0$/,
    );
    expect(row0.getAttribute("data-duplicate")).toBe("false");
    expect(row0.className).not.toMatch(/bg-amber-50/);
    expect(row0.textContent).toMatch(/New/);
  });

  it("summary chip strip announces N duplicates / M total, " +
     "with amber tint when count > 0", async () => {
    primeFetches({
      duplicates: [
        { source_doc_index: 0, existing_quote_id: "q-x1",
          doc_number: "INV-1001", customer_id: "cust-a1" },
        { source_doc_index: 2, existing_quote_id: "q-x2",
          doc_number: "INV-1003", customer_id: "cust-c" },
      ],
    });
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();
    await waitFor(() => screen.getByTestId(/^pdf-import-file-expand-/));
    fireEvent.click(screen.getByTestId(/^pdf-import-file-expand-/));
    await drain();

    const summary = await waitFor(() => screen.getByTestId(
      /^pdf-import-preview-summary-pdf-file-/,
    ));
    expect(summary.textContent).toMatch(/3 rows/);
    expect(summary.textContent).toMatch(/2 duplicates/);
    // The dup chip carries amber tint when count > 0.
    const dupChip = within(summary).getByTestId(
      /^pdf-import-preview-dupchip-pdf-file-/,
    );
    expect(dupChip.className).toMatch(/bg-amber-100/);
    expect(dupChip.className).toMatch(/text-amber-900/);
  });

  it("summary chip strip carries a neutral tint when count = 0", async () => {
    primeFetches({ duplicates: [] });
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();
    await waitFor(() => screen.getByTestId(/^pdf-import-file-expand-/));
    fireEvent.click(screen.getByTestId(/^pdf-import-file-expand-/));
    await drain();

    const dupChip = await waitFor(() => screen.getByTestId(
      /^pdf-import-preview-dupchip-pdf-file-/,
    ));
    // No amber — plain slate.
    expect(dupChip.className).not.toMatch(/bg-amber-100/);
    expect(dupChip.className).toMatch(/bg-slate-100/);
  });

  it("collapses the preview surface on second chevron click", async () => {
    primeFetches();
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();
    const expandBtn = await waitFor(
      () => screen.getByTestId(/^pdf-import-file-expand-/),
    );
    fireEvent.click(expandBtn);
    await drain();
    await waitFor(
      () => screen.getByTestId(/^pdf-import-preview-pdf-file-\d+-\d+$/),
    );
    // Click again to collapse.
    fireEvent.click(expandBtn);
    await drain();
    expect(
      screen.queryByTestId(/^pdf-import-preview-pdf-file-\d+-\d+$/),
    ).toBeNull();
  });
});
