/**
 * Feb-2026 · Invoice edit modal β — paid metadata-only bypass.
 *
 * Pins the 4 vitest cases locked in the operator dispatch for
 * Commit B. The modal pulls in a dozen heavy adjacent modules
 * (date-fns, pricebook picker, Stripe helpers, Lumino refs,
 * EditLockConfirmDialog); the mocks below reduce every one to a
 * stable minimal shim so the test only exercises the β paid-
 * metadata-only wiring.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";


const { patchSpy } = vi.hoisted(() => ({ patchSpy: vi.fn() }));
vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: vi.fn(() => Promise.resolve({ items: [] })),
    post: vi.fn(),
    patch: (...a) => patchSpy(...a),
    delete: vi.fn(),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", tenant_id: "t-1" } }),
}));

vi.mock("@/theme", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    money: (n) => `$${Number(n || 0).toFixed(2)}`,
  };
});

vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

vi.mock(
  "@/components/documents/EditLockConfirmDialog",
  () => ({
    default: ({ open }) => (
      open
        ? <div data-testid="edit-lock-confirm-dialog">confirm</div>
        : null
    ),
  }),
);

vi.mock("@/components/invoices/LineCategoryPicker", () => ({
  default: ({ value, onChange, testid }) => (
    <input
      data-testid={testid || "line-cat-picker"}
      value={value || ""}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

vi.mock("@/components/invoices/LinePricebookPicker", () => ({
  default: ({ value, onSelect, testid }) => (
    <input
      data-testid={testid || "line-pricebook-picker"}
      value={value || ""}
      onChange={(e) => onSelect?.({
        name: e.target.value, default_price: null,
      })}
    />
  ),
}));


import InvoiceEditModal from "@/components/invoices/InvoiceEditModal";


function _mkInvoice(status = "draft", over = {}) {
  return {
    id: "inv-1", status, invoice_number: "INV-100",
    customer_id: "cust-1", tenant_id: "t-1",
    tax_rate: 0, discount_amount: 0, discount_type: "fixed",
    notes: "orig_notes", memo: "", private_notes: "",
    due_date: "", currency: "USD",
    line_items: [{
      id: "li-1", description: "orig_desc",
      quantity: 2, unit_price: 50, tax_rate: 0,
      category: "Pool",
      item_id: "pb-1", pricebook_item_id: "pb-1",
    }],
    ...over,
  };
}


beforeEach(() => {
  patchSpy.mockReset();
  patchSpy.mockResolvedValue({ changed: true });
});


describe("InvoiceEditModal β — paid metadata-only bypass", () => {
  it("1. paid: description editable; qty + price readonly", () => {
    render(
      <InvoiceEditModal
        invoice={_mkInvoice("paid")}
        signInfo={null}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    const qty = screen.getByTestId("invoice-edit-line-0-qty");
    const price = screen.getByTestId("invoice-edit-line-0-price");
    expect(qty.getAttribute("readOnly")).not.toBeNull();
    expect(qty.getAttribute("aria-readonly")).toBe("true");
    expect(price.getAttribute("readOnly")).not.toBeNull();
    expect(price.getAttribute("aria-readonly")).toBe("true");
    // Description-equivalent input (``invoice-edit-line-0-desc``)
    // stays interactive — no readOnly / aria-readonly attrs.
    const desc = screen.getByTestId("invoice-edit-line-0-desc");
    expect(desc.getAttribute("readOnly")).toBeNull();
    expect(desc.getAttribute("aria-readonly")).toBeNull();
  });

  it("2. paid metadata-only save → no confirm dialog", async () => {
    render(
      <InvoiceEditModal
        invoice={_mkInvoice("paid")}
        signInfo={null}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    // Edit description only.
    fireEvent.change(
      screen.getByTestId("invoice-edit-line-0-desc"),
      { target: { value: "metadata_edit" } },
    );
    fireEvent.click(screen.getByTestId("invoice-edit-save"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    // Confirm dialog never opened.
    expect(
      screen.queryByTestId("edit-lock-confirm-dialog"),
    ).toBeNull();
    // ``acknowledged_lock_bypass`` NOT attached — BE metadata-only
    // short-circuit takes care of it.
    const payload = patchSpy.mock.calls[0][1];
    expect(payload.acknowledged_lock_bypass).toBeUndefined();
    expect(payload.confirm_edit_paid_invoice_number).toBeUndefined();
  });

  it("3. paid financial-field save → confirm dialog appears", () => {
    render(
      <InvoiceEditModal
        invoice={_mkInvoice("paid")}
        signInfo={null}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    // Even though qty is readOnly in the UI, user can still
    // mutate the controlled value via onChange firing — simulate.
    const qty = screen.getByTestId("invoice-edit-line-0-qty");
    fireEvent.change(qty, { target: { value: "99" } });
    fireEvent.click(screen.getByTestId("invoice-edit-save"));
    // Confirm dialog DOES open because the diff includes a
    // financial field (regardless of the readOnly UI gate).
    expect(
      screen.getByTestId("edit-lock-confirm-dialog"),
    ).toBeTruthy();
  });

  it("4. unpaid: all inputs editable; no confirm dialog on save",
     async () => {
    render(
      <InvoiceEditModal
        invoice={_mkInvoice("draft")}
        signInfo={null}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    const qty = screen.getByTestId("invoice-edit-line-0-qty");
    const price = screen.getByTestId("invoice-edit-line-0-price");
    expect(qty.getAttribute("readOnly")).toBeNull();
    expect(price.getAttribute("readOnly")).toBeNull();

    fireEvent.change(qty, { target: { value: "7" } });
    fireEvent.click(screen.getByTestId("invoice-edit-save"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByTestId("edit-lock-confirm-dialog"),
    ).toBeNull();
  });
});
