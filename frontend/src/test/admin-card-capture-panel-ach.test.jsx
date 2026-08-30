/**
 * Phase B1 · Feb-2026 — Admin payment-methods panel dual-mode UX.
 *
 * Locks in:
 *   1. Both "+ Add card" and "+ Add bank (ACH)" buttons render.
 *   2. Opening the ACH form while the card form is open closes the
 *      card form first (accordion behaviour).
 *   3. Saved-methods list renders BOTH card and ACH rows with
 *      distinct chrome (brand chip vs bank name + verification chip).
 *   4. ACH row surfaces the verification-status chip with the
 *      micro-deposits tooltip copy.
 *   5. Failed-verification ACH row shows a "Re-verify" link.
 *   6. Removing an ACH opens a confirm modal; removing a card fires
 *      the historical ``window.confirm`` path.
 *   7. Empty state message: "No payment methods on file. Add card
 *      or ACH bank to enable one-off charges and auto-billing."
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

// Silence the toasts + shared config helper.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
vi.mock("@/lib/stripeConfig", () => ({
  getStripeConfig: () => Promise.resolve(
    { publishable_key: "pk_test_stub", mode: "test" }),
}));

// Stripe forms are heavy — replace with tiny stubs that only assert
// their mount contract (via data-testid).  We're testing the panel,
// not the SDK.
vi.mock("@/components/payments/StripeAddCardForm", () => ({
  default: (props) => (
    <div data-testid="stripe-add-card-form-stub">
      <span data-testid="add-card-customer-id">
        {props.customerId}
      </span>
      <button onClick={props.onCancel}
              data-testid="add-card-cancel-stub">c</button>
    </div>
  ),
}));
vi.mock("@/components/payments/StripeAddBankForm", () => ({
  default: (props) => (
    <div data-testid="stripe-add-bank-form-stub">
      <span data-testid="add-bank-customer-id">
        {props.customerId}
      </span>
      <button onClick={props.onCancel}
              data-testid="add-bank-cancel-stub">c</button>
    </div>
  ),
}));

import AdminCardCapturePanel
  from "@/components/customers/AdminCardCapturePanel";


function seedFetch(rows) {
  const fetchImpl = vi.fn().mockImplementation((url, opts) => {
    if (String(url).includes("/payments/stripe/payment-methods/")
        && (!opts || opts.method === undefined
              || opts.method === "GET")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ payment_methods: rows }),
      });
    }
    if (opts?.method === "DELETE") {
      return Promise.resolve({ ok: true,
                                  json: () => Promise.resolve({ ok: true }) });
    }
    return Promise.resolve({ ok: true,
                                json: () => Promise.resolve({}) });
  });
  global.fetch = fetchImpl;
  return fetchImpl;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.setItem("token", "t");
  window.confirm = vi.fn(() => true);
});


describe("B1 · admin payment-methods panel", () => {
  it("empty state carries the card+ACH prompt copy", async () => {
    seedFetch([]);
    render(<AdminCardCapturePanel customerId="cus-1" />);
    const msg = await screen.findByTestId("admin-no-cards-msg");
    expect(msg.textContent).toMatch(/no payment methods on file/i);
    expect(msg.textContent).toMatch(/ach bank/i);
    // Both Add buttons render regardless of list state.
    expect(screen.getByTestId("admin-toggle-add-card"))
      .toBeInTheDocument();
    expect(screen.getByTestId("admin-toggle-add-bank"))
      .toBeInTheDocument();
  });

  it("accordion — opening ACH closes card and vice-versa", async () => {
    seedFetch([]);
    render(<AdminCardCapturePanel customerId="cus-1" />);
    await screen.findByTestId("admin-no-cards-msg");
    // Open card first.
    fireEvent.click(screen.getByTestId("admin-toggle-add-card"));
    expect(await screen.findByTestId("stripe-add-card-form-stub"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("stripe-add-bank-form-stub"))
      .not.toBeInTheDocument();
    // Opening ACH must close the card form.
    fireEvent.click(screen.getByTestId("admin-toggle-add-bank"));
    await waitFor(() =>
      expect(screen.getByTestId("stripe-add-bank-form-stub"))
        .toBeInTheDocument());
    expect(screen.queryByTestId("stripe-add-card-form-stub"))
      .not.toBeInTheDocument();
    // Re-opening card closes ACH.
    fireEvent.click(screen.getByTestId("admin-toggle-add-card"));
    await waitFor(() =>
      expect(screen.getByTestId("stripe-add-card-form-stub"))
        .toBeInTheDocument());
    expect(screen.queryByTestId("stripe-add-bank-form-stub"))
      .not.toBeInTheDocument();
  });

  it("renders both a card and a bank row with distinct chrome",
      async () => {
    seedFetch([
      { provider_payment_method_id: "pm_card_1", type: "card",
         brand: "visa", last4: "4242",
         exp_month: 6, exp_year: 2029, is_default: true },
      { provider_payment_method_id: "pm_bank_1", type: "us_bank_account",
         bank_name: "Chase", last4: "0001",
         account_holder_type: "individual",
         verification_status: "pending" },
    ]);
    render(<AdminCardCapturePanel customerId="cus-1" />);
    expect(await screen.findByTestId("admin-card-row-pm_card_1"))
      .toBeInTheDocument();
    expect(screen.getByTestId("admin-bank-row-pm_bank_1"))
      .toBeInTheDocument();
    // ACH row surfaces verification chip.
    const chip = screen.getByTestId(
      "admin-ach-verification-chip-pending");
    expect(chip).toBeInTheDocument();
    expect(chip.getAttribute("title") || "")
      .toMatch(/micro-deposits/i);
    // Card row surfaces default badge + brand + last4.
    const cardRow = screen.getByTestId("admin-card-row-pm_card_1");
    expect(cardRow.textContent).toMatch(/visa/i);
    expect(cardRow.textContent).toContain("4242");
    expect(cardRow.textContent).toMatch(/default/i);
  });

  it("failed ACH row surfaces Re-verify link", async () => {
    seedFetch([
      { provider_payment_method_id: "pm_bank_bad",
         type: "us_bank_account", bank_name: "Chase",
         last4: "0002", verification_status: "failed" },
    ]);
    render(<AdminCardCapturePanel customerId="cus-1" />);
    expect(await screen.findByTestId("admin-bank-reverify-pm_bank_bad"))
      .toBeInTheDocument();
    expect(
      screen.getByTestId("admin-ach-verification-chip-failed"),
    ).toBeInTheDocument();
  });

  it("ACH remove opens the confirm modal — card remove does not",
      async () => {
    seedFetch([
      { provider_payment_method_id: "pm_card_1", type: "card",
         brand: "visa", last4: "4242",
         exp_month: 6, exp_year: 2029, is_default: true },
      { provider_payment_method_id: "pm_bank_1", type: "us_bank_account",
         bank_name: "Chase", last4: "0001",
         verification_status: "verified" },
    ]);
    render(<AdminCardCapturePanel customerId="cus-1" />);
    await screen.findByTestId("admin-bank-row-pm_bank_1");

    // Card remove → window.confirm path (no modal).
    fireEvent.click(screen.getByTestId("admin-remove-card-pm_card_1"));
    expect(window.confirm).toHaveBeenCalled();
    expect(screen.queryByTestId("admin-confirm-remove-bank"))
      .not.toBeInTheDocument();

    // Bank remove → modal opens.
    fireEvent.click(screen.getByTestId("admin-remove-bank-pm_bank_1"));
    await waitFor(() => expect(
      screen.getByTestId("admin-confirm-remove-bank")).toBeInTheDocument());
    // Modal has cancel + submit.
    expect(screen.getByTestId("admin-confirm-remove-bank-cancel"))
      .toBeInTheDocument();
    expect(screen.getByTestId("admin-confirm-remove-bank-submit"))
      .toBeInTheDocument();
  });

  it("clicking the ACH remove submit calls DELETE endpoint",
      async () => {
    const fetchImpl = seedFetch([
      { provider_payment_method_id: "pm_bank_1", type: "us_bank_account",
         bank_name: "Chase", last4: "0001",
         verification_status: "verified" },
    ]);
    render(<AdminCardCapturePanel customerId="cus-1" />);
    await screen.findByTestId("admin-bank-row-pm_bank_1");
    fireEvent.click(screen.getByTestId("admin-remove-bank-pm_bank_1"));
    const submit = await screen.findByTestId(
      "admin-confirm-remove-bank-submit");
    fireEvent.click(submit);
    await waitFor(() => {
      const deleteCall = fetchImpl.mock.calls.find(
        ([_u, opts]) => opts?.method === "DELETE");
      expect(deleteCall).toBeTruthy();
      expect(String(deleteCall[0])).toContain("pm_bank_1");
    });
  });
});
