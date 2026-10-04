/**
 * PDFI-IV + V · Feb-2026 — Sidepanel contract tests.
 *
 * (a)-(j) locked by PDFI-IV, (k)-(p) added by PDFI-V. Each test
 * is self-contained; the shared harness builds a known preview
 * shape and advances through upload + poll → preview_ready.
 */
import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { parse as babelParse } from "@babel/parser";

vi.mock("@/api/pdfImports", () => ({
  kickoffUpload: vi.fn(),
  pollBatch: vi.fn(),
  patchPreview: vi.fn(),
  commitBatch: vi.fn(),
  rollbackBatch: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => Promise.resolve([
      { id: "cust-1", name: "Diane Lloyd", address: "123 Lake View" },
      { id: "cust-2", name: "Other Customer", address: "456 Elsewhere" },
    ])),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    del: vi.fn(),
  },
  api_base: () => "http://localhost/api",
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("@/api/customers", () => ({
  createCustomer: vi.fn(),
}));

vi.mock("@/components/customers/CustomerCombobox", () => ({
  CustomerCombobox: ({ customers, onChange, testid }) => (
    <div data-testid={testid || "customer-combobox-mock"}>
      <button
        type="button"
        data-testid={`${testid || "customer-combobox-mock"}-pick-first`}
        onClick={() => onChange(customers?.[0]?.id || "cust-mock-1")}
      >
        Mock pick first customer
      </button>
    </div>
  ),
}));

vi.mock("@/components/pricebook/PricebookItemPicker", () => ({
  __esModule: true,
  default: ({ onSelect, inputTestid }) => (
    <div data-testid={inputTestid ? `${inputTestid}-wrapper` : "pricebook-picker-mock"}>
      <button
        type="button"
        data-testid={inputTestid ? `${inputTestid}-pick` : "pricebook-picker-mock-pick"}
        onClick={() => onSelect({
          id: "pb-mock-1",
          name: "Mock Service",
          unit_price: 99.5,
        })}
      >
        Mock pick first pricebook item
      </button>
    </div>
  ),
}));

import PdfInvoiceUploadSidePanel from
  "@/components/invoices/PdfInvoiceUploadSidePanel";
import {
  kickoffUpload, pollBatch, patchPreview, commitBatch, rollbackBatch,
} from "@/api/pdfImports";
import { createCustomer } from "@/api/customers";
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
        }],
      },
      ...overrides,
    }],
  };
}

function _multiDocRow() {
  const makeDoc = (idx, name, total) => ({
    source_doc_index: idx,
    doc_kind: "invoice",
    mapped_target: "quote_in",
    customer_resolution: "matched",
    matched_customer_id: `cust-doc-${idx}`,
    quote_in: {
      customer_name: name,
      customer_address: `addr ${idx}`,
      doc_number: `100${idx}`,
      doc_date: "2026-08-28",
      grand_total: total,
      line_items: [{
        item_name: `Service ${idx}`,
        description: "",
        quantity: 1,
        unit_price: total,
        line_total: total,
        pricebook_item_id: `pb-${idx}`,
      }],
    },
  });
  return {
    status: "preview_complete",
    mapper_previews: [
      makeDoc(0, "First Customer",  140.0),
      makeDoc(1, "Second Customer", 220.5),
      makeDoc(2, "Third Customer",  310.0),
    ],
  };
}


beforeEach(() => {
  kickoffUpload.mockReset();
  pollBatch.mockReset();
  patchPreview.mockReset();
  commitBatch.mockReset();
  rollbackBatch.mockReset();
  createCustomer.mockReset();
  toast.error.mockReset();
  toast.success.mockReset();
  toast.info.mockReset();
});

afterEach(() => {
  document.body.innerHTML = "";
});


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

function _fakePdfFile(name = "sample.pdf") {
  return new File(["%PDF-1.4 sample"], name, { type: "application/pdf" });
}

async function _advanceToPreviewReady(previewRow = _samplePreviewRow()) {
  kickoffUpload.mockResolvedValue({ batch_id: "bat-x" });
  pollBatch.mockResolvedValue(previewRow);
  const input = await screen.findByTestId("pdfi-upload-file-input");
  fireEvent.change(input, { target: { files: [_fakePdfFile()] } });
  fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
  await screen.findByTestId("pdfi-preview-ready", {}, { timeout: 5000 });
}


describe("PDFI-IV · PdfInvoiceUploadSidePanel baseline", () => {
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
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    await waitFor(() => expect(kickoffUpload).toHaveBeenCalledTimes(1));
    expect(kickoffUpload.mock.calls[0][0].name).toBe("sample.pdf");
  });

  it("(d) polling advances to preview_ready on preview_complete", async () => {
    _render();
    await _advanceToPreviewReady();
    expect(screen.getByTestId("pdfi-tile-customer")).toBeTruthy();
  });

  it("(e) all 5 tiles render in preview_ready with their color classes", async () => {
    _render();
    await _advanceToPreviewReady();
    expect(screen.getByTestId("pdfi-tile-customer").className).toMatch(/bg-green-100/);
    expect(screen.getByTestId("pdfi-tile-date").className).toMatch(/bg-purple-100/);
    expect(screen.getByTestId("pdfi-tile-lineitems").className).toMatch(/bg-yellow-100/);
    expect(screen.getByTestId("pdfi-tile-descriptions").className).toMatch(/bg-emerald-800/);
    expect(screen.getByTestId("pdfi-tile-total").className).toMatch(/bg-orange-100/);
  });

  it("(f) editing customer name fires patchPreview with the right diff", async () => {
    patchPreview.mockResolvedValue({ ok: true });
    _render();
    await _advanceToPreviewReady();
    const nameInput = screen.getByTestId("pdfi-tile-customer-name-input");
    fireEvent.change(nameInput, { target: { value: "Diane A. Lloyd" } });
    await waitFor(() => expect(patchPreview).toHaveBeenCalled());
    const [bid, body] = patchPreview.mock.calls[0];
    expect(bid).toBe("bat-x");
    expect(body.doc_idx).toBe(0);
    expect(body.patch).toEqual({ customer_name: "Diane A. Lloyd" });
  });

  it("(g) no-match customer shows the Pick customer affordance", async () => {
    _render();
    await _advanceToPreviewReady();
    expect(screen.getByTestId("pdfi-tile-customer-pick-btn")).toBeTruthy();
    expect(screen.getByTestId("pdfi-tile-customer-no-match-badge")).toBeTruthy();
  });

  it("(h) line without pricebook id shows Pick from catalog", async () => {
    _render();
    await _advanceToPreviewReady();
    expect(screen.getByTestId("pdfi-tile-lineitems-row-0-pick-btn")).toBeTruthy();
  });

  it("(i) commit fires and onImportComplete gets the created id", async () => {
    commitBatch.mockResolvedValue({ status: "committed", quote_ids: ["q-77"] });
    const { props } = _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-upload-commit-btn"));
    await waitFor(() => expect(commitBatch).toHaveBeenCalled());
    await waitFor(() => expect(props.onImportComplete).toHaveBeenCalledWith("q-77"));
  });

  it("(j) cancel after upload fires rollbackBatch", async () => {
    rollbackBatch.mockResolvedValue({ ok: true });
    _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-upload-cancel-btn"));
    await waitFor(() => expect(rollbackBatch).toHaveBeenCalled());
    expect(rollbackBatch.mock.calls[0][0]).toBe("bat-x");
  });
});


describe("PDFI-V · wired pickers + edge states", () => {
  it("(k) Pick customer click mounts the CustomerCombobox", async () => {
    _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-tile-customer-pick-btn"));
    const combo = await screen.findByTestId("pdfi-tile-customer-combobox");
    expect(combo).toBeTruthy();
  });

  it("(l) combobox pick fires patchPreview with matched_customer_id + name + address", async () => {
    patchPreview.mockResolvedValue({ ok: true });
    _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-tile-customer-pick-btn"));
    const pickBtn = await screen.findByTestId("pdfi-tile-customer-combobox-pick-first");
    fireEvent.click(pickBtn);
    await waitFor(() => expect(patchPreview).toHaveBeenCalled());
    const [, body] = patchPreview.mock.calls[0];
    expect(body.doc_idx).toBe(0);
    expect(body.patch.matched_customer_id).toBe("cust-1");
    expect(body.patch.customer_name).toBe("Diane Lloyd");
    expect(body.patch.customer_address).toBe("123 Lake View");
  });

  it("(m) Pick from catalog mounts PricebookItemPicker on that row", async () => {
    _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-tile-lineitems-row-0-pick-btn"));
    const picker = await screen.findByTestId(
      "pdfi-tile-lineitems-row-0-picker-input-wrapper",
    );
    expect(picker).toBeTruthy();
  });

  it("(n) picker pick fires patchPreview with the line_items partial at the right index", async () => {
    patchPreview.mockResolvedValue({ ok: true });
    _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-tile-lineitems-row-0-pick-btn"));
    const pickBtn = await screen.findByTestId(
      "pdfi-tile-lineitems-row-0-picker-input-pick",
    );
    fireEvent.click(pickBtn);
    await waitFor(() => expect(patchPreview).toHaveBeenCalled());
    const [, body] = patchPreview.mock.calls[0];
    expect(body.doc_idx).toBe(0);
    expect(body.patch.line_items).toEqual({
      0: {
        pricebook_item_id: "pb-mock-1",
        item_name: "Mock Service",
        unit_price: 99.5,
      },
    });
  });

  it("(o) multi-doc batch renders selector + switching changes the preview", async () => {
    _render();
    await _advanceToPreviewReady(_multiDocRow());
    const selector = await screen.findByTestId("pdfi-preview-doc-selector-input");
    expect(screen.getByTestId("pdfi-tile-customer-name-input").value).toBe("First Customer");
    fireEvent.change(selector, { target: { value: "2" } });
    await waitFor(() => {
      expect(screen.getByTestId("pdfi-tile-customer-name-input").value).toBe("Third Customer");
    });
    expect(screen.getByTestId("pdfi-preview-doc-selector-bulk-link")).toBeTruthy();
  });

  it("(p) poll timeout renders the retry + bulk-hub affordances", async () => {
    // Parametrize the component with a short real-timer deadline:
    // 10ms poll interval, 50ms timeout. pollBatch returns the
    // sentinel ``processing`` indefinitely → Date.now() crosses
    // the deadline on the second tick and the component switches
    // to the ``timeout`` step.
    kickoffUpload.mockResolvedValue({ batch_id: "bat-p" });
    pollBatch.mockResolvedValue({ status: "processing" });
    _render({ pollIntervalMs: 10, pollTimeoutMs: 50 });
    fireEvent.change(
      await screen.findByTestId("pdfi-upload-file-input"),
      { target: { files: [_fakePdfFile()] } },
    );
    fireEvent.click(await screen.findByTestId("pdfi-upload-start-btn"));
    const retry = await screen.findByTestId(
      "pdfi-upload-timeout-retry-btn", {}, { timeout: 3000 },
    );
    expect(retry).toBeTruthy();
    expect(screen.getByTestId("pdfi-upload-timeout-bulk-btn")).toBeTruthy();
  });
});


describe("PDFI-VB · new-customer modal on CustomerTile", () => {
  it("(q) Click 'New' opens the create modal pre-filled with the parsed customer name", async () => {
    _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-tile-customer-create-btn"));
    const modal = await screen.findByTestId("pdfi-tile-customer-create-modal");
    expect(modal).toBeTruthy();
    const nameInput = screen.getByTestId("pdfi-tile-customer-create-name-input");
    expect(nameInput.value).toBe("Diane Lloyd");
    const addressInput = screen.getByTestId("pdfi-tile-customer-create-address-input");
    expect(addressInput.value).toBe("123 Lake View Drive");
  });

  it("(r) Save fires createCustomer with payload AND patchPreview with the new customer id, then modal closes", async () => {
    createCustomer.mockResolvedValue({
      id: "cust-new-99",
      name: "Diane Lloyd",
      billing_address: "123 Lake View Drive",
    });
    patchPreview.mockResolvedValue({ ok: true });
    _render();
    await _advanceToPreviewReady();
    fireEvent.click(screen.getByTestId("pdfi-tile-customer-create-btn"));
    await screen.findByTestId("pdfi-tile-customer-create-modal");
    fireEvent.change(screen.getByTestId("pdfi-tile-customer-create-email-input"), {
      target: { value: "diane@example.com" },
    });
    fireEvent.change(screen.getByTestId("pdfi-tile-customer-create-phone-input"), {
      target: { value: "480-555-0199" },
    });
    fireEvent.click(screen.getByTestId("pdfi-tile-customer-create-save-btn"));
    await waitFor(() => expect(createCustomer).toHaveBeenCalledTimes(1));
    const [payload] = createCustomer.mock.calls[0];
    expect(payload.name).toBe("Diane Lloyd");
    expect(payload.email).toBe("diane@example.com");
    expect(payload.phone).toBe("480-555-0199");
    expect(payload.billing_address).toBe("123 Lake View Drive");

    await waitFor(() => expect(patchPreview).toHaveBeenCalled());
    const linkCall = patchPreview.mock.calls.find(
      (call) => call[1]?.patch?.matched_customer_id === "cust-new-99",
    );
    expect(linkCall).toBeTruthy();
    expect(linkCall[1].patch.customer_name).toBe("Diane Lloyd");
    expect(linkCall[1].patch.customer_address).toBe("123 Lake View Drive");

    await waitFor(() => {
      expect(screen.queryByTestId("pdfi-tile-customer-create-modal")).toBeFalsy();
    });
  });
});


describe("PDFI-PAID-C · paid-status UI", () => {
  function _paidPreviewRow({ is_paid = true, paid_at = "2026-08-28",
                              amount_paid = 140.0 } = {}) {
    return {
      status: "preview_complete",
      mapper_previews: [{
        source_doc_index: 0,
        doc_kind: "invoice",
        mapped_target: "quote_in",
        customer_resolution: "matched",
        matched_customer_id: "cust-1",
        quote_in: {
          customer_name: "Diane Lloyd",
          customer_address: "123 Lake View Drive",
          doc_number: "10774",
          doc_date: "2026-08-28",
          grand_total: 140.0,
          subtotal: 140.0,
          amount_paid,
          total_due: is_paid ? 0.0 : 140.0,
          is_paid,
          paid_at,
          line_items: [{
            item_name: "Full Weekly Pool Service",
            description: "weekly chem + clean",
            quantity: 1,
            unit_price: 140.0,
            line_total: 140.0,
            pricebook_item_id: "pb-1",
          }],
        },
      }],
    };
  }

  it("(s) TotalTile renders PAID chip when preview carries is_paid=true", async () => {
    _render();
    await _advanceToPreviewReady(_paidPreviewRow());
    const chip = screen.getByTestId("pdfi-tile-total-paid-chip");
    expect(chip).toBeTruthy();
    expect(chip.textContent.toUpperCase()).toMatch(/PAID/);
    expect(screen.getByTestId("pdfi-tile-total-paid-row")).toBeTruthy();
    expect(screen.getByTestId("pdfi-tile-total-paid-at-input")).toBeTruthy();
    expect(screen.getByTestId("pdfi-tile-total-amount-paid-input")).toBeTruthy();
  });

  it("(t) is_paid=true + paid_at=null shows date-required warning + disables commit", async () => {
    _render();
    await _advanceToPreviewReady(_paidPreviewRow({ paid_at: null }));
    expect(screen.getByTestId("pdfi-tile-total-paid-at-warning")).toBeTruthy();
    const commitBtn = screen.getByTestId("pdfi-upload-commit-btn");
    expect(commitBtn.disabled).toBe(true);
    const dateInput = screen.getByTestId("pdfi-tile-total-paid-at-input");
    expect(dateInput.className).toMatch(/border-red/);
  });

  it("(u) editing paid_at fires patchPreview with the paid_at diff", async () => {
    patchPreview.mockResolvedValue({ ok: true });
    _render();
    await _advanceToPreviewReady(_paidPreviewRow({ paid_at: null }));
    const dateInput = screen.getByTestId("pdfi-tile-total-paid-at-input");
    fireEvent.change(dateInput, { target: { value: "2026-08-28" } });
    await waitFor(() => expect(patchPreview).toHaveBeenCalled());
    const [bid, body] = patchPreview.mock.calls[0];
    expect(bid).toBe("bat-x");
    expect(body.doc_idx).toBe(0);
    expect(body.patch).toEqual({ paid_at: "2026-08-28" });
  });

  it("(v) commit button re-enables after paid_at is set", async () => {
    patchPreview.mockResolvedValue({ ok: true });
    _render();
    await _advanceToPreviewReady(_paidPreviewRow({ paid_at: null }));
    expect(screen.getByTestId("pdfi-upload-commit-btn").disabled).toBe(true);
    const dateInput = screen.getByTestId("pdfi-tile-total-paid-at-input");
    fireEvent.change(dateInput, { target: { value: "2026-08-28" } });
    await waitFor(() => {
      expect(
        screen.getByTestId("pdfi-upload-commit-btn").disabled,
      ).toBe(false);
    });
    expect(
      screen.queryByTestId("pdfi-tile-total-paid-at-warning"),
    ).toBeFalsy();
  });

  it("(w) 422 paid_without_date on commit triggers toast + re-focuses date input", async () => {
    const err422 = Object.assign(
      new Error("Payment date required to commit."),
      {
        status: 422,
        data: {
          detail: {
            error: "paid_without_date",
            batch_id: "bat-x",
            doc_indices: [0],
            message: "Payment date required.",
          },
        },
      },
    );
    commitBatch.mockRejectedValueOnce(err422);
    _render();
    await _advanceToPreviewReady(_paidPreviewRow({ paid_at: "2026-08-28" }));
    fireEvent.click(screen.getByTestId("pdfi-upload-commit-btn"));
    await waitFor(() => expect(commitBatch).toHaveBeenCalled());
    await waitFor(() => {
      const hit = toast.error.mock.calls.find(
        (c) => /payment date/i.test(String(c[0])),
      );
      expect(hit).toBeTruthy();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getByTestId("pdfi-tile-total-paid-at-input"),
      );
    });
  });
});


describe("HOTFIX-PDFI-IV · parse-lock regression", () => {
  it("[regression] InvoicesList.jsx parses cleanly as a JSX module (no top-level JSX siblings outside the return's root)", () => {
    const src = readFileSync(
      resolve(__dirname, "../pages/invoices/InvoicesList.jsx"),
      "utf8",
    );
    expect(() =>
      babelParse(src, {
        sourceType: "module",
        plugins: ["jsx"],
      }),
    ).not.toThrow();
  });
});
