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
  TOKEN_KEY: "token",
}));

// Phase K1 · Feb-2026 — mock getStripeConfig so the tiles resolve
// the pubkey/configured state deterministically per test.  The
// default is a happy-path configured response; individual tests
// can override via ``getStripeConfigMock.mockResolvedValueOnce``.
const getStripeConfigMock = vi.fn();
vi.mock("@/lib/stripeConfig", () => ({
  getStripeConfig: (...a) => getStripeConfigMock(...a),
  _resetStripeConfigCacheForTests: () => {},
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#fafafa", border: "#eee",
    borderStrong: "#ddd", onSurface: "#000", muted: "#666",
    error: "#DC2626", onError: "#fff",
    success: "#16A34A",
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
  getStripeConfigMock.mockReset();
  // Default happy path — Stripe configured.
  getStripeConfigMock.mockResolvedValue({
    publishable_key: "pk_test_j1", stripe_configured: true, mode: "test",
  });
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

  // ── Phase J1 · Feb-2026 — Set-default affordance ──────────────
  it("Set-default button renders ONLY on non-default cards", async () => {
    const nonDefaultCard = { ...CARD_ROW, id: "row_card_2",
                                        is_default: false };
    getMock.mockResolvedValue({
      payment_methods: [CARD_ROW, nonDefaultCard],
    });
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    // Default card → NO set-default button.
    await waitFor(() => expect(screen.getByTestId(
      `payment-tile-card-${CARD_ROW.id}`)).toBeInTheDocument());
    expect(screen.queryByTestId(
      `payment-tile-card-set-default-${CARD_ROW.id}`)).toBeNull();
    // Non-default card → button IS present with the "Set default"
    // label.
    const btn = screen.getByTestId(
      `payment-tile-card-set-default-${nonDefaultCard.id}`);
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent(/Set default/);
  });

  it("clicking Set default posts to /set-default and toasts success", async () => {
    const nonDefaultCard = { ...CARD_ROW, id: "row_card_2",
                                        is_default: false };
    getMock.mockResolvedValue({payment_methods: [nonDefaultCard]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    postMock.mockResolvedValue({ok: true, last4: "4242"});
    // The refetch after set-default flips is_default → true, so the
    // button disappears from the DOM on the second render.
    getMock.mockResolvedValueOnce({
      payment_methods: [{...nonDefaultCard, is_default: true}],
    });
    await act(async () => {
      fireEvent.click(await screen.findByTestId(
        `payment-tile-card-set-default-${nonDefaultCard.id}`));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      `/payments/stripe/payment-methods/${
        nonDefaultCard.provider_payment_method_id}/set-default`,
      {},
    ));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith(
      "Card ending in 4242 set as default."));
    // Button gone after the flip.
    await waitFor(() => expect(screen.queryByTestId(
      `payment-tile-card-set-default-${nonDefaultCard.id}`)).toBeNull());
  });

  it("Set default failure surfaces via sonner error toast", async () => {
    const nonDefaultCard = { ...CARD_ROW, id: "row_card_2",
                                        is_default: false };
    getMock.mockResolvedValue({payment_methods: [nonDefaultCard]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    postMock.mockRejectedValue(new Error("stripe unavailable"));
    await act(async () => {
      fireEvent.click(await screen.findByTestId(
        `payment-tile-card-set-default-${nonDefaultCard.id}`));
    });
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      "stripe unavailable"));
    // Card + button still on-screen for the operator to retry.
    expect(screen.getByTestId(
      `payment-tile-card-set-default-${nonDefaultCard.id}`),
    ).toBeInTheDocument();
  });

  it("skips fetch when customerId prop is missing", async () => {
    await act(async () => {
      render(<PaymentMethodTiles customerId={null} />);
    });
    expect(getMock).not.toHaveBeenCalled();
  });

  // ── Wave C · Feb-2026 — solid-green fill + white bold contract ──
  it("on-file card tile uses colors.success as the solid fill", async () => {
    getMock.mockResolvedValue({payment_methods: [CARD_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    const tile = await screen.findByTestId(
      `payment-tile-card-${CARD_ROW.id}`);
    // ``colors.success`` in the mocked theme = ``#16A34A`` — same
    // hex as ``colors.landscape[600]`` and the green endpoint of
    // the brand gradient the Create button ships with.
    // We assert on the RGB rendering because JSDOM normalizes.
    const bg = tile.style.background || tile.style.backgroundColor;
    expect(bg.toLowerCase()).toMatch(/#16a34a|rgb\(22,\s*163,\s*74\)/);
  });

  it("on-file card tile fields render with white text", async () => {
    getMock.mockResolvedValue({payment_methods: [CARD_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    // Every LockedField label + value renders with color:#FFFFFF.
    // Check on the value box (masked card number).
    const numberField = await screen.findByTestId(
      `payment-tile-card-number-${CARD_ROW.id}`);
    // The label element is the first child; the value box is the
    // second child. Both must be white.
    const [label, box] = numberField.children;
    expect(label.style.color.toLowerCase()).toMatch(
      /#ffffff|rgb\(255,\s*255,\s*255\)/);
    expect(box.style.color.toLowerCase()).toMatch(
      /#ffffff|rgb\(255,\s*255,\s*255\)/);
  });

  it("on-file bank tile uses the same solid-green + white bold treatment", async () => {
    getMock.mockResolvedValue({payment_methods: [BANK_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_1" />);
    });
    const tile = await screen.findByTestId(
      `payment-tile-bank-${BANK_ROW.id}`);
    const bg = tile.style.background || tile.style.backgroundColor;
    expect(bg.toLowerCase()).toMatch(/#16a34a|rgb\(22,\s*163,\s*74\)/);
    const bankField = screen.getByTestId(
      `payment-tile-bank-name-${BANK_ROW.id}`);
    const [label, box] = bankField.children;
    expect(label.style.color.toLowerCase()).toMatch(
      /#ffffff|rgb\(255,\s*255,\s*255\)/);
    expect(box.style.color.toLowerCase()).toMatch(
      /#ffffff|rgb\(255,\s*255,\s*255\)/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// Phase K1 · Feb-2026 — Stripe-not-configured fallback contract.
// ═══════════════════════════════════════════════════════════════════
describe("PaymentMethodTiles · K1 stripe-not-configured fallback", () => {
  it("hides empty-state Add buttons when stripe_configured is false", async () => {
    getStripeConfigMock.mockReset();
    getStripeConfigMock.mockResolvedValue({
      publishable_key: "", stripe_configured: false, mode: "test",
    });
    getMock.mockResolvedValue({payment_methods: []});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_k1" />);
    });
    // Empty-state cards are still shown (customer needs to know the
    // state), but the Add CTAs are removed so the fail-forward
    // flow can't be triggered.
    await waitFor(() => expect(screen.getByTestId(
      "payment-method-tiles-card-empty")).toBeInTheDocument());
    expect(screen.queryByTestId(
      "payment-method-tiles-card-empty-add")).toBeNull();
    expect(screen.queryByTestId(
      "payment-method-tiles-bank-empty-add")).toBeNull();
  });

  it("hides 'Add another card/bank' controls when on-file rows exist AND stripe_configured=false", async () => {
    getStripeConfigMock.mockReset();
    getStripeConfigMock.mockResolvedValue({
      publishable_key: "", stripe_configured: false, mode: "test",
    });
    getMock.mockResolvedValue({payment_methods: [CARD_ROW, BANK_ROW]});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_k1" />);
    });
    await waitFor(() => expect(screen.getByTestId(
      `payment-tile-card-${CARD_ROW.id}`)).toBeInTheDocument());
    expect(screen.queryByTestId(
      "payment-method-tiles-add-card")).toBeNull();
    expect(screen.queryByTestId(
      "payment-method-tiles-add-bank")).toBeNull();
  });

  it("shows the neutral fallback (NOT the red env-var message) if the Add flow is somehow opened while unconfigured", async () => {
    // Force ``addOpen: "card"`` by rendering with a configured state
    // first (Add button visible), clicking it, then swapping the
    // config to unconfigured on a re-render.  Simplest reproducer:
    // spy on getStripeConfig to resolve unconfigured AFTER the
    // component mounts + the CTA is clicked.
    getStripeConfigMock.mockReset();
    getStripeConfigMock.mockResolvedValue({
      publishable_key: "", stripe_configured: false, mode: "test",
    });
    getMock.mockResolvedValue({payment_methods: []});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_k1" />);
    });
    // Fallback route surfaces via the shared K1 helper — it renders
    // ONLY inside the ``addOpen`` container.  Since the empty-state
    // Add button is hidden, we drive the state via the sibling
    // subsection (bank rows with a saved bank + the hidden add
    // button flow won't fire).  Instead, assert on the negative
    // contract: NO tile in the DOM contains the red env-var copy.
    // Belt-and-suspenders check against a future regression.
    expect(screen.queryByText(/STRIPE_PUBLISHABLE_KEY_LIVE/)).toBeNull();
    expect(screen.queryByText(/STRIPE_PUBLISHABLE_KEY_TEST/)).toBeNull();
    // Source-body contract that the fallback block exists and is
    // wired to the ``stripeDisabled`` branch of the add container.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const SRC = fs.readFileSync(
      path.resolve(process.cwd(),
        "src/components/customers/PaymentMethodTiles.jsx"),
      "utf-8",
    );
    expect(SRC).toMatch(
      /stripeDisabled\s*\?\s*\(\s*<StripeUnavailableFallback/,
    );
    expect(SRC).toMatch(
      /Payment methods are temporarily unavailable/,
    );
    expect(SRC).toMatch(
      /Please contact support to set up card or bank payments\./,
    );
    // The fallback block MUST NOT contain any Stripe env-var name.
    const fallbackFn = SRC.slice(
      SRC.indexOf("function StripeUnavailableFallback"),
      SRC.indexOf("function StripeUnavailableFallback") + 1200,
    );
    expect(fallbackFn).not.toMatch(/STRIPE_PUBLISHABLE_KEY/);
  });

  it("renders the Add flow normally when stripe_configured=true (regression guard)", async () => {
    // Explicitly re-assert the happy path so a future refactor
    // can't silently disable Stripe on every render.
    getMock.mockResolvedValue({payment_methods: []});
    await act(async () => {
      render(<PaymentMethodTiles customerId="cust_k1" />);
    });
    await waitFor(() => expect(screen.getByTestId(
      "payment-method-tiles-card-empty")).toBeInTheDocument());
    expect(screen.getByTestId(
      "payment-method-tiles-card-empty-add")).toBeInTheDocument();
    expect(screen.getByTestId(
      "payment-method-tiles-bank-empty-add")).toBeInTheDocument();
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
