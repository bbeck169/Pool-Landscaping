/**
 * InvoiceEditModal · Feb-2026 — Vitest coverage.
 *
 * Covers:
 *   1. Draft: all editable fields render.
 *   2. Line-item add/remove + live totals reflect changes.
 *   3. Sent-status: yellow banner + confirmation checkbox gates Save.
 *   4. Paid-status: red banner + invoice-number input gates Save.
 *   5. Lumino warning shows on money change when URL was present.
 *   6. Submit posts the correct PATCH payload including confirm flags.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { patchSpy, getSpy, postSpy } = vi.hoisted(() => ({
  patchSpy: vi.fn(),
  getSpy: vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));

beforeEach(() => {
  patchSpy.mockReset();
  getSpy.mockReset();
  postSpy.mockReset();
});
afterEach(() => cleanup());

import InvoiceEditModal from "@/components/invoices/InvoiceEditModal";

const draftInvoice = () => ({
  id: "inv-e2e-1",
  invoice_number: "INV-2026-100",
  status: "draft",
  customer_id: "cust-1",
  currency: "USD",
  tax_rate: 7.5,
  discount_amount: 0,
  discount_type: "fixed",
  line_items: [
    { description: "Chem service", quantity: 1, unit_price: 100, tax_rate: 0 },
    { description: "Filter clean", quantity: 2, unit_price: 25, tax_rate: 0 },
  ],
  notes: "",
  memo: "",
  terms: "Net 14",
});

describe("InvoiceEditModal", () => {
  it("renders all editable fields for a draft invoice", () => {
    render(<InvoiceEditModal invoice={draftInvoice()} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByTestId("invoice-edit-modal")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-customer-id")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-invoice-number")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-line-items")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-discount-amount")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-discount-type")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-currency")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-tax-rate")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-due-date")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-notes")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-memo")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-private-notes")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-terms")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-save")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-totals")).toBeTruthy();
  });

  it("supports add / remove of line items and updates live totals", () => {
    render(<InvoiceEditModal invoice={draftInvoice()} onClose={() => {}} onSaved={() => {}} />);
    // Initial subtotal: 100 + 50 = 150
    expect(screen.getByTestId("invoice-edit-subtotal-value").textContent).toMatch(/150/);
    // Add a row.
    fireEvent.click(screen.getByTestId("invoice-edit-add-line"));
    // New empty row's description populates.
    const newDescInput = screen.getByTestId("invoice-edit-line-2-desc");
    fireEvent.change(newDescInput, { target: { value: "Salt" } });
    const newQtyInput = screen.getByTestId("invoice-edit-line-2-qty");
    fireEvent.change(newQtyInput, { target: { value: "5" } });
    const newPriceInput = screen.getByTestId("invoice-edit-line-2-price");
    fireEvent.change(newPriceInput, { target: { value: "10" } });
    // Now subtotal should be 150 + 50 = 200.
    expect(screen.getByTestId("invoice-edit-subtotal-value").textContent).toMatch(/200/);
    // Remove the first row (100).
    fireEvent.click(screen.getByTestId("invoice-edit-line-0-remove"));
    // Subtotal now 50 + 50 = 100.
    expect(screen.getByTestId("invoice-edit-subtotal-value").textContent).toMatch(/100/);
  });

  it("shows yellow banner + gates Save on a sent invoice", () => {
    const inv = { ...draftInvoice(), status: "sent" };
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByTestId("invoice-edit-banner-sent")).toBeTruthy();
    const saveBtn = screen.getByTestId("invoice-edit-save");
    expect(saveBtn.disabled).toBe(true);
    fireEvent.click(screen.getByTestId("invoice-edit-confirm-sent"));
    expect(screen.getByTestId("invoice-edit-save").disabled).toBe(false);
  });

  it("shows red banner + gates Save on a paid invoice until number matches", () => {
    const inv = { ...draftInvoice(), status: "paid" };
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByTestId("invoice-edit-banner-paid")).toBeTruthy();
    expect(screen.getByTestId("invoice-edit-save").disabled).toBe(true);
    // Wrong number → still disabled.
    fireEvent.change(screen.getByTestId("invoice-edit-paid-number-input"), {
      target: { value: "WRONG-NUMBER" },
    });
    expect(screen.getByTestId("invoice-edit-save").disabled).toBe(true);
    // Correct number → enabled.
    fireEvent.change(screen.getByTestId("invoice-edit-paid-number-input"), {
      target: { value: "INV-2026-100" },
    });
    expect(screen.getByTestId("invoice-edit-save").disabled).toBe(false);
  });

  it("shows Lumino warning when a money field changes and URL was present", () => {
    const inv = {
      ...draftInvoice(),
      lumino_payment_url: "https://pay.lumino.io/x/y",
    };
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    // No warning until a money field changes.
    expect(screen.queryByTestId("invoice-edit-lumino-warning")).toBeNull();
    fireEvent.change(screen.getByTestId("invoice-edit-tax-rate"), {
      target: { value: "8.25" },
    });
    expect(screen.getByTestId("invoice-edit-lumino-warning")).toBeTruthy();
  });

  it("submits a PATCH with the correct payload including confirm flags", async () => {
    patchSpy.mockResolvedValue({ ok: true, changed: true, invoice: {} });
    const inv = { ...draftInvoice(), status: "paid" };
    const onSaved = vi.fn();
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={onSaved} />);
    // Unlock the paid gate.
    fireEvent.change(screen.getByTestId("invoice-edit-paid-number-input"), {
      target: { value: "INV-2026-100" },
    });
    // Tweak a field.
    fireEvent.change(screen.getByTestId("invoice-edit-notes"), {
      target: { value: "New notes for audit" },
    });
    fireEvent.click(screen.getByTestId("invoice-edit-save"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    const [path, payload] = patchSpy.mock.calls[0];
    expect(path).toBe("/quotes/inv-e2e-1");
    expect(payload.notes).toBe("New notes for audit");
    expect(payload.confirm_edit_paid_invoice_number).toBe("INV-2026-100");
    expect(payload.confirm_edit_sent).toBeUndefined();
    expect(onSaved).toHaveBeenCalled();
  });
});
