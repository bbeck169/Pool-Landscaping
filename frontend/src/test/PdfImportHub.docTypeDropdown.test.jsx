/**
 * PDF-HUB · Feb-2026 — Document Type dropdown vitest suite.
 *
 * Locks the wire contract for the ``hint_doc_kind`` upload flow:
 *
 *   1. Dropdown renders with exactly 4 options.
 *   2. Default selection is "Auto-Detect" (empty value).
 *   3. Selecting Invoice → the resulting POST body includes
 *      ``hint_doc_kind=invoice``.
 *   4. Auto-Detect → the field is OMITTED from the POST body
 *      (server-side normaliser treats missing = auto-detect).
 *
 * The ``postPdfInvoice`` helper is exported by the page module —
 * we drive it directly with a spied ``fetch`` so we don't have to
 * mount the whole upload flow through drag-and-drop.
 */
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import PdfInvoiceImportPage, {
  postPdfInvoice,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


describe("PDF-HUB · Document Type dropdown · render", () => {
  it("renders the label, select, and all 4 options", () => {
    render(<PdfInvoiceImportPage />);
    // Label + hint copy.
    expect(screen.getByText(/Document Type/)).toBeTruthy();
    expect(screen.getByTestId("pdf-hub-doc-type-hint").textContent).toMatch(
      /Auto-detect uses AI classification/,
    );

    // Select + options.
    const select = screen.getByTestId("pdf-hub-doc-type-select");
    expect(select).toBeTruthy();
    expect(select.tagName).toBe("SELECT");

    // Exactly 4 options in order.
    expect(screen.getByTestId("pdf-hub-doc-type-option-auto")).toBeTruthy();
    expect(screen.getByTestId("pdf-hub-doc-type-option-invoice")).toBeTruthy();
    expect(screen.getByTestId("pdf-hub-doc-type-option-estimate")).toBeTruthy();
    expect(screen.getByTestId("pdf-hub-doc-type-option-payment")).toBeTruthy();

    const opts = select.querySelectorAll("option");
    expect(opts.length).toBe(4);
    expect(opts[0].value).toBe("");
    expect(opts[0].textContent).toMatch(/Auto-Detect/);
    expect(opts[1].value).toBe("invoice");
    expect(opts[1].textContent).toMatch(/Invoice/);
    expect(opts[2].value).toBe("estimate");
    expect(opts[2].textContent).toMatch(/Estimate/);
    expect(opts[3].value).toBe("payment");
    expect(opts[3].textContent).toMatch(/Payment History/);
  });

  it("defaults to Auto-Detect (empty value)", () => {
    render(<PdfInvoiceImportPage />);
    const select = screen.getByTestId("pdf-hub-doc-type-select");
    expect(select.value).toBe("");
  });

  it("updates the value on change", () => {
    render(<PdfInvoiceImportPage />);
    const select = screen.getByTestId("pdf-hub-doc-type-select");
    fireEvent.change(select, { target: { value: "invoice" } });
    expect(select.value).toBe("invoice");
    fireEvent.change(select, { target: { value: "payment" } });
    expect(select.value).toBe("payment");
    fireEvent.change(select, { target: { value: "" } });
    expect(select.value).toBe("");
  });
});


describe("PDF-HUB · postPdfInvoice · hint_doc_kind forwarding", () => {
  let originalFetch;
  let fetchSpy;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({
        batch_id: "test-batch-id",
        status: "queued",
        poll_hint_seconds: 3,
        poll_url: "/api/imports/pdf-invoice/test-batch-id",
        async: true,
      }),
    });
    globalThis.fetch = fetchSpy;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("appends hint_doc_kind=invoice when hintDocKind is 'invoice'", async () => {
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])],
                            "hub.pdf", { type: "application/pdf" });
    await postPdfInvoice(file, {
      baseUrl: "http://test.example",
      token: "test-tok",
      hintDocKind: "invoice",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const call = fetchSpy.mock.calls[0];
    expect(call[0]).toBe("http://test.example/api/imports/pdf-invoice");
    const body = call[1].body;
    // ``FormData.get`` returns the field value when present, ``null``
    // when absent.
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("hint_doc_kind")).toBe("invoice");
    expect(body.get("file")).toBeTruthy();
  });

  it("appends hint_doc_kind=payment when hintDocKind is 'payment'", async () => {
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])],
                            "hub.pdf", { type: "application/pdf" });
    await postPdfInvoice(file, {
      baseUrl: "http://test.example",
      token: "test-tok",
      hintDocKind: "payment",
    });
    const body = fetchSpy.mock.calls[0][1].body;
    expect(body.get("hint_doc_kind")).toBe("payment");
  });

  it("appends hint_doc_kind=estimate when hintDocKind is 'estimate'", async () => {
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])],
                            "hub.pdf", { type: "application/pdf" });
    await postPdfInvoice(file, {
      baseUrl: "http://test.example",
      token: "test-tok",
      hintDocKind: "estimate",
    });
    const body = fetchSpy.mock.calls[0][1].body;
    expect(body.get("hint_doc_kind")).toBe("estimate");
  });

  it("OMITS hint_doc_kind entirely when hintDocKind is '' (Auto-Detect)", async () => {
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])],
                            "hub.pdf", { type: "application/pdf" });
    await postPdfInvoice(file, {
      baseUrl: "http://test.example",
      token: "test-tok",
      hintDocKind: "",
    });
    const body = fetchSpy.mock.calls[0][1].body;
    // Field must NOT be present — Auto-Detect means "no hint" on the
    // wire, so the server's normaliser branches straight to None.
    expect(body.get("hint_doc_kind")).toBeNull();
  });

  it("OMITS hint_doc_kind entirely when hintDocKind is undefined", async () => {
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])],
                            "hub.pdf", { type: "application/pdf" });
    // No hintDocKind key at all — backward-compat with pre-PDF-HUB
    // callers.
    await postPdfInvoice(file, {
      baseUrl: "http://test.example",
      token: "test-tok",
    });
    const body = fetchSpy.mock.calls[0][1].body;
    expect(body.get("hint_doc_kind")).toBeNull();
  });
});
