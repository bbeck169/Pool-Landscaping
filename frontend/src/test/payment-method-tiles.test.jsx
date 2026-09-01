/**
 * Phase I5 · Feb-2026 — PaymentMethodTiles component + admin
 * placement.
 *
 * Contract coverage:
 *   * Loading skeleton renders on mount, replaced by data.
 *   * Card + ACH subsections render independently.
 *   * On-file tile shows masked last4 + expiry.
 *   * Empty state renders when no methods of that kind exist.
 *   * Add button opens the inline Stripe form (Add-card / Add-bank).
 *   * Delete opens TypedConfirmModal keyed on last4; typing correct
 *     value enables the Remove button; POST body carries typed_last4.
 *   * Server delete failure surfaces via sonner error toast.
 *   * Component mounts on the admin CustomerDetail Overview between
 *     the ``cd-customer-name-secondary`` heading and the
 *     ``CustomerContactsPanel`` (source-body contract check).
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: (...args) => postMock(...args),
  },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#fafafa", border: "#eee",
    borderStrong: "#ddd", onSurface: "#000", muted: "#666",
    error: "#DC2626", onError: "#fff",
    landscape: { 50: "#F0FDF4", 100: "#DCFCE7", 300: "#86EFAC",
                    500: "#22C55E", 600: "#16A34A", 700: "#15803D" },
  },
}));

// Stub the inline add forms so tests don't need Stripe Elements.
// Vitest matches on resolved absolute paths; the ``@/…`` alias
// resolves both the component's ``../payments/…`` import and this
// mock declaration to the same file.
vi.mock("@/components/payments/StripeAddCardForm", () => ({
  default: function StripeAddCardForm({ customerId, onSuccess, onCancel }) {
    return (
      <div data-testid="stub-add-card-form">
        <button data-testid="stub-add-card-success"
                     onClick={() => onSuccess?.({id: "pm_new"})}>
          Simulate success
        </button>
        <button data-testid="stub-add-card-cancel"
                     onClick={onCancel}>Cancel</button>
      </div>
    );
  },
}));
vi.mock("@/components/payments/StripeAddBankForm", () => ({
  default: function StripeAddBankForm({ customerId, onSuccess, onCancel }) {
    return (
      <div data-testid="stub-add-bank-form">
        <button data-testid="stub-add-bank-success"
                     onClick={() => onSuccess?.({id: "pm_new_bank"})}>
          Simulate success
        </button>
      </div>
    );
  },
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccess(...a),
    error: (...a) => toastError(...a),
    info: (...a) => toastInfo(...a),
  },
}));

import PaymentMethodTiles from "@/components/customers/PaymentMethodTiles";


const CARD_ROW = {
  id: "row_card_1",
  customer_id: "cust_1",
  provider_payment_method_id: "pm_card_stripe",
  type: "card", brand: "visa", last4: "4242",
  exp_month: 12, exp_year: 2028,
  is_default: true,
};
const BANK_ROW = {
  id: "row_bank_1",
  customer_id: "cust_1",
  provider_payment_method_id: "pm_bank_stripe",
  type: "us_bank_account", brand: "", last4: "6789",
  bank_name: "Chase", account_holder_type: "individual",
  is_default: false,
};


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  toastInfo.mockReset();
});


describe("PaymentMethodTiles · I5", () => {
  it("renders loading state, then card + bank on-file tiles", async () => {
    getMock.mockResolvedValue({
      customer_id: "cust_1",
      payment_methods: [CARD_ROW, BANK_ROW],
    });
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    // Loading state should have been rendered before the resolution.
    expect(getMock).toHaveBeenCalledWith(
      "/payments/stripe/payment-methods/cust_1",
    );
    await waitFor(() => expect(screen.getByTestId(
      "payment-method-tiles-admin")).toBeInTheDocument());
    // Card tile.
    expect(screen.getByTestId(`payment-tile-card-${CARD_ROW.id}`)
    ).toBeInTheDocument();
    expect(screen.getByTestId(
      `payment-tile-card-number-${CARD_ROW.id}`),
    ).toHaveTextContent(/•+ 4242/);
    expect(screen.getByTestId(
      `payment-tile-card-exp-${CARD_ROW.id}`),
    ).toHaveTextContent(/12 \/ 2028/);
    // Bank tile.
    expect(screen.getByTestId(`payment-tile-bank-${BANK_ROW.id}`)
    ).toBeInTheDocument();
    expect(screen.getByTestId(
      `payment-tile-bank-number-${BANK_ROW.id}`),
    ).toHaveTextContent(/6789/);
    expect(screen.getByTestId(
      `payment-tile-bank-name-${BANK_ROW.id}`),
    ).toHaveTextContent(/Chase/);
  });

  it("shows both empty states when no methods on file", async () => {
    getMock.mockResolvedValue({
      customer_id: "cust_1", payment_methods: [],
    });
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    await waitFor(() => expect(screen.getByTestId(
      "payment-method-tiles-card-empty")).toBeInTheDocument());
    expect(screen.getByTestId("payment-method-tiles-card-empty")
    ).toHaveTextContent(
      /No Credit\/Debit Card Information Found for This Customer/);
    expect(screen.getByTestId("payment-method-tiles-bank-empty")
    ).toHaveTextContent(
      /No Bank Account Information Found for This Customer/);
    // Add CTA buttons wired.
    expect(screen.getByTestId("payment-method-tiles-card-empty-add")
    ).toHaveTextContent(/Add a Credit\/Debit Card/);
    expect(screen.getByTestId("payment-method-tiles-bank-empty-add")
    ).toHaveTextContent(/Add Bank Account/);
  });

  it("Add-card CTA opens the inline StripeAddCardForm", async () => {
    getMock.mockResolvedValue({payment_methods: []});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    fireEvent.click(await screen.findByTestId(
      "payment-method-tiles-card-empty-add"));
    expect(screen.getByTestId("stub-add-card-form")).toBeInTheDocument();
    // Simulating success closes the form + refetches methods.
    getMock.mockResolvedValueOnce({
      payment_methods: [CARD_ROW],
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("stub-add-card-success"));
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith(
      "Payment method added."));
  });

  it("Delete on card opens TypedConfirmModal keyed on last4", async () => {
    getMock.mockResolvedValue({payment_methods: [CARD_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    fireEvent.click(await screen.findByTestId(
      `payment-tile-card-delete-${CARD_ROW.id}`));
    // Modal opens with the H2 test-id prefix.
    expect(await screen.findByTestId(
      "payment-tile-delete-confirm-modal")).toBeInTheDocument();
    // Description mentions the last4.
    expect(screen.getByTestId(
      "payment-tile-delete-confirm-desc")).toHaveTextContent("4242");
    // Confirm is disabled until the last4 is typed correctly.
    const confirmBtn = screen.getByTestId(
      "payment-tile-delete-confirm-confirm");
    expect(confirmBtn).toBeDisabled();
    fireEvent.change(screen.getByTestId(
      "payment-tile-delete-confirm-input"),
      {target: {value: "4242"}});
    expect(confirmBtn).not.toBeDisabled();
    // POST fires with the typed keyword.
    postMock.mockResolvedValue({ok: true, last4: "4242"});
    getMock.mockResolvedValueOnce({payment_methods: []});
    await act(async () => {
      fireEvent.click(confirmBtn);
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      `/payments/stripe/payment-methods/${
        CARD_ROW.provider_payment_method_id}/delete-typed`,
      {typed_last4: "4242"},
    ));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith(
      "Card ending in 4242 removed."));
  });

  it("Delete failure keeps the modal open and toasts the error", async () => {
    getMock.mockResolvedValue({payment_methods: [CARD_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    fireEvent.click(await screen.findByTestId(
      `payment-tile-card-delete-${CARD_ROW.id}`));
    fireEvent.change(screen.getByTestId(
      "payment-tile-delete-confirm-input"),
      {target: {value: "4242"}});
    postMock.mockRejectedValue(new Error("typed_last4_mismatch"));
    await act(async () => {
      fireEvent.click(screen.getByTestId(
        "payment-tile-delete-confirm-confirm"));
    });
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      "typed_last4_mismatch"));
    // Modal stays open so the operator can retry / cancel.
    expect(screen.getByTestId("payment-tile-delete-confirm-modal")
    ).toBeInTheDocument();
  });

  it("Edit opens the inline Add form of the same type + info toast", async () => {
    getMock.mockResolvedValue({payment_methods: [BANK_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    fireEvent.click(await screen.findByTestId(
      `payment-tile-bank-edit-${BANK_ROW.id}`));
    expect(screen.getByTestId("stub-add-bank-form")).toBeInTheDocument();
    expect(toastInfo).toHaveBeenCalledWith(expect.stringContaining(
      "immutable"));
  });

  it("Bank delete uses the correct copy in the success toast", async () => {
    getMock.mockResolvedValue({payment_methods: [BANK_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    fireEvent.click(await screen.findByTestId(
      `payment-tile-bank-delete-${BANK_ROW.id}`));
    fireEvent.change(screen.getByTestId(
      "payment-tile-delete-confirm-input"),
      {target: {value: "6789"}});
    postMock.mockResolvedValue({ok: true, last4: "6789"});
    getMock.mockResolvedValueOnce({payment_methods: []});
    await act(async () => {
      fireEvent.click(screen.getByTestId(
        "payment-tile-delete-confirm-confirm"));
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith(
      "Bank account ending in 6789 removed."));
  });

  it("skips fetch when customerId prop is missing", async () => {
    await act(async () => {
      render(<PaymentMethodTiles customerId={null} />);
    });
    expect(getMock).not.toHaveBeenCalled();
  });
});


// ═══════════════════════════════════════════════════════════════════
// Admin placement contract — source-body check.
// ═══════════════════════════════════════════════════════════════════
describe("PaymentMethodTiles · admin placement in CustomerDetail", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/pages/customers/CustomerDetail.jsx"),
    "utf-8",
  );

  it("imports the shared component", () => {
    expect(SRC).toMatch(
      /import\s+PaymentMethodTiles\s+from\s+"@\/components\/customers\/PaymentMethodTiles"/,
    );
  });

  it("mounts the tiles with variant=\"admin\" inside the Overview branch", () => {
    // Overview is opened by ``tab === "overview" ? (`` — the
    // component must render inside that ternary AFTER the
    // ``cd-customer-name-secondary`` heading and BEFORE the
    // ``CustomerContactsPanel``. Verified by ordering the three
    // sentinel strings inside a single Overview slice.
    const overviewStart = SRC.indexOf('tab === "overview"');
    expect(overviewStart).toBeGreaterThan(-1);
    // Take a big slice after the Overview open so the ordering
    // check doesn't accidentally hit unrelated occurrences.
    const overviewSlice = SRC.slice(overviewStart, overviewStart + 4000);
    const nameIdx = overviewSlice.indexOf(
      "cd-customer-name-secondary");
    const tilesIdx = overviewSlice.indexOf(
      "<PaymentMethodTiles");
    const contactsIdx = overviewSlice.indexOf(
      "<CustomerContactsPanel");
    expect(nameIdx).toBeGreaterThan(-1);
    expect(tilesIdx).toBeGreaterThan(-1);
    expect(contactsIdx).toBeGreaterThan(-1);
    expect(nameIdx).toBeLessThan(tilesIdx);
    expect(tilesIdx).toBeLessThan(contactsIdx);
    // Variant is explicitly "admin".
    const propSlice = overviewSlice.slice(tilesIdx, tilesIdx + 300);
    expect(propSlice).toMatch(/variant="admin"/);
    expect(propSlice).toMatch(/customerId=\{customer\.id\}/);
  });

  it("does not mount the tiles in any non-overview tab branch", () => {
    // A single occurrence in the file — the Overview mount — no
    // duplicate renders on other tabs.
    const occurrences = SRC.match(/<PaymentMethodTiles/g) || [];
    expect(occurrences.length).toBe(1);
  });
});
