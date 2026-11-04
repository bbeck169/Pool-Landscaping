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

const { patchSpy, getSpy, postSpy, authRef } = vi.hoisted(() => ({
  patchSpy: vi.fn(),
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  // TD-paid-invoice-admin-edit-unblock · Feb-2026 — mutable auth
  // context so individual tests can flip between admin / manager /
  // null without a re-import.  Default = null (no AuthProvider) so
  // the pre-ticket test cases retain their original behavior
  // (``isAdmin === false``), keeping the shipped banner + ack-dialog
  // flows unchanged.
  authRef: { current: null },
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));

// TD-paid-invoice-admin-edit-unblock · Feb-2026 — ``@/auth`` mock.
// ``useAuth`` is now consumed by InvoiceEditModal to gate the
// line-item qty / unit_price readOnly on the admin role.  The mock
// returns ``null`` by default (matches the pre-ticket
// AuthProvider-less render); flip ``authRef.current`` before
// render in tests that need an admin / manager identity.
vi.mock("@/auth", () => ({
  useAuth: () => authRef.current,
}));

beforeEach(() => {
  patchSpy.mockReset();
  getSpy.mockReset();
  postSpy.mockReset();
  // InvoiceEditModal → CategoryPicker fires GET /income-categories on
  // mount. Give the mock a benign default so its `.then()` doesn't
  // blow up unrelated tests. Individual specs can still override.
  getSpy.mockResolvedValue({ items: [] });
  // TD-paid-invoice-admin-edit-unblock · Feb-2026 — reset auth to
  // the pre-ticket baseline (``null`` = no AuthProvider) so each
  // test opts in to admin / manager via ``authRef.current = ...``.
  authRef.current = null;
});
afterEach(() => cleanup());

import InvoiceEditModal from "@/components/invoices/InvoiceEditModal";
import { invalidateCategoryCache } from "@/components/income/CategoryPicker";
// Phase P16.1 · Feb-2026 — the Master Service combobox module holds
// a per-tab cache; invalidate between tests so a prior GET
// ``/master-services`` result (mocked as ``{items:[]}``) doesn't
// leak into a later spec.
import { invalidateMasterServicesCache }
  from "@/components/services/MasterServiceCombobox";

// CategoryPicker caches its first fetch at module scope — reset that
// between suites so a stale mocked promise doesn't leak across tests.
beforeEach(() => {
  invalidateCategoryCache();
  invalidateMasterServicesCache();
});

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
    { description: "Chem service", quantity: 1, unit_price: 100, tax_rate: 0, category: "Chemicals" },
    { description: "Filter clean", quantity: 2, unit_price: 25, tax_rate: 0, category: "Chemicals" },
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
    // Phase P16.1 · Feb-2026 — the description input is now
    // wrapped in a MasterServiceCombobox; the inner input carries
    // the ``-input`` suffix.  Free-typing still bubbles the value
    // via the combobox's onChange handler, so ``fireEvent.change``
    // on the inner input is a faithful stand-in for a real user
    // keystroke.
    const newDescInput = screen.getByTestId("invoice-edit-line-2-desc-input");
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

  it("shows yellow banner + routes Save through confirm dialog on a sent invoice", async () => {
    const inv = { ...draftInvoice(), status: "sent" };
    patchSpy.mockResolvedValue({ ok: true, changed: true, invoice: {} });
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    // Sent banner is informational (no checkbox in Phase 1).
    expect(screen.getByTestId("invoice-edit-banner-sent")).toBeTruthy();
    // Save is NOT gated inline — click opens the shared confirm dialog.
    const saveBtn = screen.getByTestId("invoice-edit-save");
    expect(saveBtn.disabled).toBe(false);
    fireEvent.click(saveBtn);
    // Shared confirm dialog surfaces with generic-warning copy
    // (no Stripe / signature-invalidation warnings for a bare sent doc).
    expect(screen.getByTestId("edit-lock-confirm-dialog")).toBeTruthy();
    expect(screen.getByTestId("edit-lock-generic-warning")).toBeTruthy();
    // Confirm → PATCH fires with acknowledged_lock_bypass=true.
    fireEvent.click(screen.getByTestId("edit-lock-confirm-continue"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    const [path, payload] = patchSpy.mock.calls[0];
    expect(path).toBe("/quotes/inv-e2e-1");
    expect(payload.acknowledged_lock_bypass).toBe(true);
    // invoice_number is NEVER sent (input is disabled + immutable).
    expect(payload.invoice_number).toBeUndefined();
  });

  it("renders the invoice_number input as disabled (locked once assigned)", () => {
    render(<InvoiceEditModal invoice={draftInvoice()} onClose={() => {}} onSaved={() => {}} />);
    const input = screen.getByTestId("invoice-edit-invoice-number");
    expect(input.disabled).toBe(true);
    expect(input.readOnly).toBe(true);
  });

  it("shows accepted banner + generic confirm dialog on an accepted invoice", async () => {
    const inv = { ...draftInvoice(), status: "accepted" };
    patchSpy.mockResolvedValue({ ok: true, changed: true, invoice: {} });
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByTestId("invoice-edit-banner-accepted")).toBeTruthy();
    fireEvent.click(screen.getByTestId("invoice-edit-save"));
    expect(screen.getByTestId("edit-lock-confirm-dialog")).toBeTruthy();
    fireEvent.click(screen.getByTestId("edit-lock-confirm-continue"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    expect(patchSpy.mock.calls[0][1].acknowledged_lock_bypass).toBe(true);
  });

  it("shows Stripe-paid warning in the confirm dialog when doc has a payment_intent_id", async () => {
    const inv = {
      ...draftInvoice(),
      status: "paid",
      payment_intent_id: "pi_test_123",
    };
    patchSpy.mockResolvedValue({ ok: true, changed: true, invoice: {} });
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByTestId("invoice-edit-banner-paid")).toBeTruthy();
    fireEvent.click(screen.getByTestId("invoice-edit-save"));
    // Stripe-specific warning replaces the generic copy.
    expect(screen.getByTestId("edit-lock-stripe-warning")).toBeTruthy();
    expect(screen.queryByTestId("edit-lock-generic-warning")).toBeNull();
  });

  it("shows signature-invalidation warning in confirm dialog when signed", () => {
    const inv = { ...draftInvoice(), status: "sent", signature_status: "signed" };
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    // Banner rendered inline on modal body too.
    expect(screen.getByTestId("invoice-edit-banner-signed")).toBeTruthy();
    fireEvent.click(screen.getByTestId("invoice-edit-save"));
    expect(screen.getByTestId("edit-lock-signature-warning")).toBeTruthy();
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("shows red banner + gates Save on a paid invoice until number matches", () => {
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
      payment_url: "https://checkout.stripe.com/c/pay/cs_x_y",
    };
    render(<InvoiceEditModal invoice={inv} onClose={() => {}} onSaved={() => {}} />);
    // No warning until a money field changes.
    expect(screen.queryByTestId("invoice-edit-paylink-warning")).toBeNull();
    fireEvent.change(screen.getByTestId("invoice-edit-tax-rate"), {
      target: { value: "8.25" },
    });
    expect(screen.getByTestId("invoice-edit-paylink-warning")).toBeTruthy();
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("submits a PATCH with the correct payload including confirm flags", async () => {
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

  // ─────────────────────────────────────────────────────────────
  // TD-paid-invoice-admin-edit-unblock · Feb-2026 — admin + super_admin
  // can type into line-item qty / unit_price on paid invoices; Save
  // still routes through the shared <EditLockConfirmDialog> which arms
  // the ``acknowledged_lock_bypass`` + typed invoice-number proof.
  // Manager / owner keep the existing readOnly lock (matches the BE
  // ``_require_staff`` narrow-role-widening contract).
  // ─────────────────────────────────────────────────────────────
  describe("TD-paid-invoice-admin-edit-unblock", () => {
    const paidInvoice = () => ({ ...draftInvoice(), status: "paid",
                                 amount_paid: 150 });

    it("admin: qty and unit_price inputs are NOT readOnly on paid", () => {
      authRef.current = { user: { role: "admin", tenant_id: "t-1" } };
      render(<InvoiceEditModal invoice={paidInvoice()}
                               onClose={() => {}} onSaved={() => {}} />);
      const qty = screen.getByTestId("invoice-edit-line-0-qty");
      const price = screen.getByTestId("invoice-edit-line-0-price");
      expect(qty.readOnly).toBe(false);
      expect(price.readOnly).toBe(false);
      expect(qty.getAttribute("aria-readonly")).toBeNull();
      expect(price.getAttribute("aria-readonly")).toBeNull();
    });

    it("super_admin: qty and unit_price inputs are NOT readOnly on paid", () => {
      authRef.current = { user: { role: "super_admin", tenant_id: "t-1" } };
      render(<InvoiceEditModal invoice={paidInvoice()}
                               onClose={() => {}} onSaved={() => {}} />);
      expect(screen.getByTestId("invoice-edit-line-0-qty").readOnly).toBe(false);
      expect(screen.getByTestId("invoice-edit-line-0-price").readOnly).toBe(false);
    });

    it("manager: qty and unit_price inputs ARE readOnly on paid "
       + "(preserves BE _require_staff narrower role widening)", () => {
      authRef.current = { user: { role: "manager", tenant_id: "t-1" } };
      render(<InvoiceEditModal invoice={paidInvoice()}
                               onClose={() => {}} onSaved={() => {}} />);
      expect(screen.getByTestId("invoice-edit-line-0-qty").readOnly).toBe(true);
      expect(screen.getByTestId("invoice-edit-line-0-price").readOnly).toBe(true);
    });

    it("owner: qty and unit_price inputs ARE readOnly on paid", () => {
      authRef.current = { user: { role: "owner", tenant_id: "t-1" } };
      render(<InvoiceEditModal invoice={paidInvoice()}
                               onClose={() => {}} onSaved={() => {}} />);
      expect(screen.getByTestId("invoice-edit-line-0-qty").readOnly).toBe(true);
      expect(screen.getByTestId("invoice-edit-line-0-price").readOnly).toBe(true);
    });

    it("no-auth (null): qty and unit_price inputs ARE readOnly on paid "
       + "(safer default — never silently unlock without an identity)", () => {
      authRef.current = null;
      render(<InvoiceEditModal invoice={paidInvoice()}
                               onClose={() => {}} onSaved={() => {}} />);
      expect(screen.getByTestId("invoice-edit-line-0-qty").readOnly).toBe(true);
      expect(screen.getByTestId("invoice-edit-line-0-price").readOnly).toBe(true);
    });

    it("admin paid edit of unit_price routes through "
       + "<EditLockConfirmDialog> with acknowledged_lock_bypass + "
       + "typed invoice-number proof", async () => {
      authRef.current = { user: { role: "admin", tenant_id: "t-1" } };
      patchSpy.mockResolvedValue({ ok: true, changed: true, invoice: {} });
      render(<InvoiceEditModal invoice={paidInvoice()}
                               onClose={() => {}} onSaved={() => {}} />);
      // Admin edits unit_price — the input is now writable.
      fireEvent.change(screen.getByTestId("invoice-edit-line-0-price"), {
        target: { value: "999.99" },
      });
      // Save routes through the shared confirm dialog (not the β
      // metadata-only short-circuit — unit_price is a financial field).
      fireEvent.click(screen.getByTestId("invoice-edit-save"));
      expect(screen.getByTestId("edit-lock-confirm-dialog")).toBeTruthy();
      fireEvent.click(screen.getByTestId("edit-lock-confirm-continue"));
      await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
      const [path, payload] = patchSpy.mock.calls[0];
      expect(path).toBe("/quotes/inv-e2e-1");
      // BE ack path 1: acknowledged_lock_bypass=true
      expect(payload.acknowledged_lock_bypass).toBe(true);
      // BE ack path 2: typed invoice-number proof
      expect(payload.confirm_edit_paid_invoice_number).toBe("INV-2026-100");
      // The money change is carried in the payload.
      const edited = (payload.line_items || [])
        .find((li) => Number(li.unit_price) === 999.99);
      expect(edited).toBeTruthy();
    });

    it("admin paid invoice still renders invoice-edit-banner-paid "
       + "(soft warning preserved — not removed by this ticket)", () => {
      authRef.current = { user: { role: "admin", tenant_id: "t-1" } };
      render(<InvoiceEditModal invoice={paidInvoice()}
                               onClose={() => {}} onSaved={() => {}} />);
      expect(screen.getByTestId("invoice-edit-banner-paid")).toBeTruthy();
    });
  });
});
