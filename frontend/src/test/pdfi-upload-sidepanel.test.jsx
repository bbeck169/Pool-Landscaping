/**
 * PDFI-IV · Feb-2026 — Sidepanel upload flow contract tests.
 *
 * Locks the user-facing surface shipped alongside the backend
 * PDFI-II / PDFI-III work:
 *
 *   (a) "Upload PDF" button is wired on InvoicesList with the
 *       correct testid (source-inspected; mounting the full
 *       page tree hangs vitest's collection phase per
 *       vitest.config.js note).
 *   (b) Dropzone rejects non-PDF files via a sonner error toast.
 *   (c) Pick + click Upload → kickoffUpload called with the file
 *       in form data.
 *   (d) Poll loop advances to ``preview_ready`` on
 *       ``status: "preview_complete"``.
 *   (e) All 5 color-coded tiles render in preview_ready state
 *       with the expected ``data-testid`` wiring.
 *   (f) Inline edit on CustomerTile name → ``patchPreview`` fires
 *       with the expected diff shape ``{doc_idx:0, patch:{customer_name:…}}``.
 *   (g) ``matched_customer_id`` absent → "Pick customer"
 *       affordance renders.
 *   (h) Line item without ``pricebook_item_id`` → "Pick from
 *       catalog" button renders on that row.
 *   (i) Click "Create Invoice" → ``commitBatch`` fires AND
 *       ``onImportComplete`` is invoked with the created id.
 *   (j) Cancel after upload → ``rollbackBatch`` fires.
 */
import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// Mock the API client module — all five fns stubbed as vi.fn().
vi.mock("@/api/pdfImports", () => ({
  kickoffUpload: vi.fn(),
  pollBatch: vi.fn(),
  patchPreview: vi.fn(),
  commitBatch: vi.fn(),
  rollbackBatch: vi.fn(),
}));

// Mock sonner so toast calls don't need a Toaster mounted.
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

import PdfInvoiceUploadSidePanel from
  "@/components/invoices/PdfInvoiceUploadSidePanel";
import {
  kickoffUpload, pollBatch, patchPreview, commitBatch, rollbackBatch,
} from "@/api/pdfImports";
import { toast } from "sonner";


function _samplePreviewRow(overrides = {}) {
  return {
    status: "preview_complete",
    mapper_previews: [{
      source_doc_index: 0,
      doc_kind: "invoice",
      mapped_target: "quote_in",
      customer_resolution: "unresolved",
      matched_customer_id: null,
      quote_in: {
        customer_name: "Diane Lloyd",
        customer_address: "123 Lake View Drive",
        doc_number: "10774",
        doc_date: "2026-08-28",
        grand_total: 140.0,
        subtotal: 140.0,
        amount_paid: 140.0,
        total_due: 0.0,
        line_items: [{
          item_name: "Full Weekly Pool Service",
          description: "weekly chem + clean",
          quantity: 1,
          unit_price: 140.0,
          line_total: 140.0,
          // No pricebook_item_id — triggers the "Pick from catalog"
          // fallback render.
        }],
      },
      ...overrides,
    }],
  };
}


beforeEach(() => {
  kickoffUpload.mockReset();
  pollBatch.mockReset();
  patchPreview.mockReset();
  commitBatch.mockReset();
  rollbackBatch.mockReset();
  toast.error.mockReset();
  toast.success.mockReset();
  toast.info.mockReset();
});

afterEach(() => {
  // Scrub any Radix portals leaked between tests (sidepanel uses
  // shadcn Sheet which portals to document.body).
  document.body.innerHTML = "";
});


// ══════════════════════════════════════════════════════════════════
// (a) InvoicesList source-inspect — button wiring
// ══════════════════════════════════════════════════════════════════

describe("PDFI-IV · InvoicesList button wiring", () => {
  const _SRC = readFileSync(
    resolve(__dirname, "../pages/invoices/InvoicesList.jsx"),
    "utf8",
  );

  it("(a) Upload PDF button is mounted with the correct testid", () => {
    expect(_SRC).toContain('testid="inv-list-upload-pdf-btn"');
    expect(_SRC).toContain("Upload PDF");
    expect(_SRC).toContain("PdfInvoiceUploadSidePanel");
    expect(_SRC).toContain("setPdfPanelOpen(true)");
  });
});


// ══════════════════════════════════════════════════════════════════
// (b-j) Sidepanel behaviour tests
// ══════════════════════════════════════════════════════════════════

describe("PDFI-IV · PdfInvoiceUploadSidePanel", () => {
  function _render(propsOverride = {}) {
    const props = {
      open: true,
      onClose: vi.fn(),
      onImportComplete: vi.fn(),
      ...propsOverride,
    };
    const utils = render(<PdfInvoiceUploadSidePanel {...props} />);
    return { ...utils, props };
  }

  function _fakePdfFile() {
    return new File(["%PDF-1.4 sample"], "sample.pdf", {
      type: "application/pdf",
    });
  }

  it("(b) rejects a non-PDF file with an error toast", async () => {
    _render();
    const input = await screen.findByTestId("pdfi-upload-file-input");
    const bogus = new File(["abc"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [bogus] } });
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.error.mock.calls[0][0]).toMatch(/PDF/i);
    expect(kickoffUpload).not.toHaveBeenCalled();
  });

  it("(c) upload fires kickoffUpload with the file", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-c" });
    pollBatch.mockResolvedValue({ status: "processing" });
    _render();
    const input = await screen.findByTestId("pdfi-upload-file-input");
    fireEvent.change(input, { target: { files: [_fakePdfFile()] } });
    const startBtn = await screen.findByTestId("pdfi-upload-start-btn");
    fireEvent.click(startBtn);
    await waitFor(() => expect(kickoffUpload).toHaveBeenCalledTimes(1));
    const [passedFile] = kickoffUpload.mock.calls[0];
    expect(passedFile.name).toBe("sample.pdf");
  });

  it("(d) polling advances to preview_ready on preview_complete", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-d" });
    pollBatch.mockResolvedValue(_samplePreviewRow());
    _render();
    const input = await screen.findByTestId("pdfi-upload-file-input");
    fireEvent.change(input, { target: { files: [_fakePdfFile()] } });
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    await screen.findByTestId("pdfi-preview-ready", {}, { timeout: 5000 });
    expect(screen.getByTestId("pdfi-tile-customer")).toBeTruthy();
  });

  it("(e) all 5 tiles render in preview_ready with their color-coded testids", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-e" });
    pollBatch.mockResolvedValue(_samplePreviewRow());
    _render();
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    await screen.findByTestId("pdfi-preview-ready", {}, { timeout: 5000 });

    const custTile = screen.getByTestId("pdfi-tile-customer");
    expect(custTile.className).toMatch(/bg-green-100/);
    const dateTile = screen.getByTestId("pdfi-tile-date");
    expect(dateTile.className).toMatch(/bg-purple-100/);
    const lineTile = screen.getByTestId("pdfi-tile-lineitems");
    expect(lineTile.className).toMatch(/bg-yellow-100/);
    const descTile = screen.getByTestId("pdfi-tile-descriptions");
    expect(descTile.className).toMatch(/bg-emerald-800/);
    const totalTile = screen.getByTestId("pdfi-tile-total");
    expect(totalTile.className).toMatch(/bg-orange-100/);
  });

  it("(f) editing customer name fires patchPreview with the right diff", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-f" });
    pollBatch.mockResolvedValue(_samplePreviewRow());
    patchPreview.mockResolvedValue({ ok: true });
    _render();
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    const nameInput = await screen.findByTestId(
      "pdfi-tile-customer-name-input", {}, { timeout: 5000 },
    );
    fireEvent.change(nameInput, { target: { value: "Diane A. Lloyd" } });
    await waitFor(() => expect(patchPreview).toHaveBeenCalled());
    const [bid, body] = patchPreview.mock.calls[0];
    expect(bid).toBe("bat-f");
    expect(body.doc_idx).toBe(0);
    expect(body.patch).toEqual({ customer_name: "Diane A. Lloyd" });
  });

  it("(g) no-match customer shows the Pick customer affordance", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-g" });
    pollBatch.mockResolvedValue(_samplePreviewRow());
    _render();
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    const btn = await screen.findByTestId(
      "pdfi-tile-customer-pick-btn", {}, { timeout: 5000 },
    );
    expect(btn).toBeTruthy();
    expect(
      screen.getByTestId("pdfi-tile-customer-no-match-badge"),
    ).toBeTruthy();
  });

  it("(h) line item without pricebook id shows Pick from catalog", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-h" });
    pollBatch.mockResolvedValue(_samplePreviewRow());
    _render();
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    const pickBtn = await screen.findByTestId(
      "pdfi-tile-lineitems-row-0-pick-btn", {}, { timeout: 5000 },
    );
    expect(pickBtn).toBeTruthy();
  });

  it("(i) commit fires and onImportComplete gets the created id", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-i" });
    pollBatch.mockResolvedValue(_samplePreviewRow());
    commitBatch.mockResolvedValue({
      status: "committed",
      quote_ids: ["q-77"],
    });
    const { props } = _render();
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    const commitBtn = await screen.findByTestId(
      "pdfi-upload-commit-btn", {}, { timeout: 5000 },
    );
    fireEvent.click(commitBtn);
    await waitFor(() => expect(commitBatch).toHaveBeenCalled());
    await waitFor(() => expect(props.onImportComplete).toHaveBeenCalledWith("q-77"));
  });

  it("(j) cancel after upload fires rollbackBatch", async () => {
    kickoffUpload.mockResolvedValue({ batch_id: "bat-j" });
    pollBatch.mockResolvedValue(_samplePreviewRow());
    rollbackBatch.mockResolvedValue({ ok: true });
    _render();
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    const cancelBtn = await screen.findByTestId(
      "pdfi-upload-cancel-btn", {}, { timeout: 5000 },
    );
    fireEvent.click(cancelBtn);
    await waitFor(() => expect(rollbackBatch).toHaveBeenCalled());
    expect(rollbackBatch.mock.calls[0][0]).toBe("bat-j");
  });
});
