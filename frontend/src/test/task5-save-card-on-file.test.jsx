/**
 * Feb-2026 · Task 5 — Save card on file / Vitest coverage.
 *
 *   1. `InvoiceChargeSavedCardDialog` renders card + last4, and POSTs
 *      to `/invoices/:id/charge-saved-card` with the selected pm_id.
 *   2. Structured `authentication_required` 402 surfaces friendly
 *      error copy inline.
 *   3. `PortalPaymentMethods` lists cards, remove button opens
 *      confirm dialog, confirm calls DELETE.
 *   4. Empty state renders when the customer has no cards.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { getSpy, postSpy, patchSpy, delSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), postSpy: vi.fn(),
  patchSpy: vi.fn(), delSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:  (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del:  (...a) => delSpy(...a),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));


import InvoiceChargeSavedCardDialog from "@/components/invoices/InvoiceChargeSavedCardDialog";
import PortalPaymentMethods from "@/pages/portal/PortalPaymentMethods";


const CARDS = [
  {
    provider_payment_method_id: "pm_visa",
    id: "pm_visa",
    brand: "visa", last4: "4242", exp_month: 12, exp_year: 2030,
    default: true, type: "card",
  },
  {
    provider_payment_method_id: "pm_amex",
    id: "pm_amex",
    brand: "amex", last4: "0005", exp_month: 6, exp_year: 2029,
    default: false, type: "card",
  },
];


describe("InvoiceChargeSavedCardDialog (Task 5)", () => {
  beforeEach(() => {
    getSpy.mockReset(); postSpy.mockReset();
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("renders default card and POSTs charge-saved-card on confirm", async () => {
    postSpy.mockResolvedValue({
      status: "succeeded", payment_intent_id: "pi_1", amount_cents: 20000,
      brand: "visa", last4: "4242",
    });
    const onSuccess = vi.fn();
    render(
      <InvoiceChargeSavedCardDialog
        invoiceId="inv-1"
        savedCards={CARDS}
        amount={200}
        onClose={() => {}}
        onSuccess={onSuccess}
      />,
    );
    expect(await screen.findByTestId("invoice-charge-saved-card-dialog"))
      .toBeInTheDocument();
    // Default card (visa/4242) shown by default — appears in
    // summary + picker option so use `getAllByText`.
    expect(screen.getAllByText(/···· 4242/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("invoice-charge-saved-card-confirm"));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith(
        "/invoices/inv-1/charge-saved-card",
        { payment_method_id: "pm_visa" },
      ),
    );
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("surfaces authentication_required as inline error", async () => {
    // Simulate the FastAPI structured 402.
    postSpy.mockRejectedValue({
      detail: {
        error_code: "authentication_required",
        message: "Card requires additional authentication — please send the customer a fresh payment link.",
      },
    });
    render(
      <InvoiceChargeSavedCardDialog
        invoiceId="inv-2"
        savedCards={CARDS}
        amount={100}
        onClose={() => {}}
        onSuccess={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("invoice-charge-saved-card-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("invoice-charge-saved-card-error"))
        .toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("invoice-charge-saved-card-error").textContent,
    ).toMatch(/additional authentication/i);
  });

  it("shows picker when multiple cards + posts selected pm_id", async () => {
    postSpy.mockResolvedValue({
      status: "succeeded", payment_intent_id: "pi_2", amount_cents: 5000,
    });
    render(
      <InvoiceChargeSavedCardDialog
        invoiceId="inv-3"
        savedCards={CARDS}
        amount={50}
        onClose={() => {}}
        onSuccess={() => {}}
      />,
    );
    const picker = await screen.findByTestId("invoice-charge-saved-card-picker");
    expect(picker).toBeInTheDocument();
    fireEvent.change(picker, { target: { value: "pm_amex" } });
    fireEvent.click(screen.getByTestId("invoice-charge-saved-card-confirm"));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith(
        "/invoices/inv-3/charge-saved-card",
        { payment_method_id: "pm_amex" },
      ),
    );
  });
});


describe("PortalPaymentMethods (Task 5)", () => {
  beforeEach(() => {
    getSpy.mockReset(); patchSpy.mockReset(); delSpy.mockReset();
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("lists saved cards + shows default chip on default card", async () => {
    getSpy.mockResolvedValue({ methods: CARDS });
    render(
      <MemoryRouter>
        <PortalPaymentMethods />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("portal-payment-methods-page"))
      .toBeInTheDocument();
    await screen.findByTestId("portal-pm-list");
    expect(screen.getByTestId("portal-pm-row-pm_visa")).toBeInTheDocument();
    expect(screen.getByTestId("portal-pm-row-pm_amex")).toBeInTheDocument();
    expect(screen.getByTestId("portal-pm-default-chip-pm_visa"))
      .toBeInTheDocument();
  });

  it("renders empty state when no cards", async () => {
    getSpy.mockResolvedValue({ methods: [] });
    render(
      <MemoryRouter>
        <PortalPaymentMethods />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("portal-pm-empty-state"))
      .toBeInTheDocument();
  });

  it("remove flow — opens confirm and calls DELETE", async () => {
    getSpy.mockResolvedValue({ methods: CARDS });
    delSpy.mockResolvedValue({ removed: true, remaining: 1 });
    render(
      <MemoryRouter>
        <PortalPaymentMethods />
      </MemoryRouter>,
    );
    await screen.findByTestId("customer-pm-remove-pm_amex");
    fireEvent.click(screen.getByTestId("customer-pm-remove-pm_amex"));
    await screen.findByTestId("portal-pm-remove-confirm-dialog");
    fireEvent.click(screen.getByTestId("portal-pm-remove-confirm"));
    await waitFor(() =>
      expect(delSpy).toHaveBeenCalledWith(
        "/customer-portal/payment-methods/pm_amex",
      ),
    );
  });

  it("set-default calls PATCH endpoint with is_default true", async () => {
    getSpy.mockResolvedValue({ methods: CARDS });
    patchSpy.mockResolvedValue({ default_payment_method_id: "pm_amex" });
    render(
      <MemoryRouter>
        <PortalPaymentMethods />
      </MemoryRouter>,
    );
    await screen.findByTestId("customer-pm-set-default-pm_amex");
    fireEvent.click(screen.getByTestId("customer-pm-set-default-pm_amex"));
    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith(
        "/customer-portal/payment-methods/pm_amex/set-default",
        { is_default: true },
      ),
    );
  });
});
