/**
 * Feb 2026 · P0 Stripe ACH bank-account capture form.
 *
 * Locking specs for the new ``StripeAddBankForm`` component that
 * fixed the P0 where the "Connect Bank Account" flow never actually
 * mounted <Elements> — the previous branch merely ``console.info``-
 * logged the client_secret and showed a "widget will launch shortly"
 * toast. Nothing launched.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, waitFor, fireEvent,
} from "@testing-library/react";


// ─────────────────────── mocks ────────────────────────────────────
const originalFetch = global.fetch;
let fetchQueue = [];
function primeFetch(responses) {
  fetchQueue = [...responses];
  global.fetch = vi.fn(async () => {
    const next = fetchQueue.shift();
    if (!next) throw new Error("fetch called more times than primed");
    return {
      ok: next.ok !== false,
      status: next.status || 200,
      json: async () => next.body || {},
    };
  });
}


vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn(() => Promise.resolve({})),
}));


let confirmSetupMock;
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }) => <div data-testid="mock-elements">{children}</div>,
  PaymentElement: () => <div data-testid="mock-payment-element" />,
  useStripe: () => ({ confirmSetup: (...a) => confirmSetupMock(...a) }),
  useElements: () => ({}),
}));


vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));


import StripeAddBankForm from "@/components/payments/StripeAddBankForm";


const PROPS = {
  apiBase: "https://api.example.com/api",
  authToken: "test-token",
  publishableKey: "pk_test_XYZ",
};


describe("StripeAddBankForm · ACH capture", () => {
  beforeEach(() => {
    fetchQueue = [];
    confirmSetupMock = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("boots by fetching /ach/link-session and mounts <Elements>", async () => {
    primeFetch([
      { ok: true, body: { ok: true, client_secret: "seti_TEST_secret",
                            publishable_key: "pk_test_XYZ" } },
    ]);
    render(<StripeAddBankForm {...PROPS} onSuccess={vi.fn()} />);
    // Panel renders while boot is in flight.
    await waitFor(() =>
      expect(screen.getByTestId("stripe-add-bank-panel")).toBeInTheDocument());
    // Loaded — <Elements> is mounted with the returned client_secret.
    await waitFor(() =>
      expect(screen.getByTestId("mock-elements")).toBeInTheDocument());
    expect(screen.getByTestId("mock-payment-element")).toBeInTheDocument();
    expect(screen.getByTestId("stripe-add-bank-form")).toBeInTheDocument();
    // The fetch to link-session went out with the expected shape.
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/api/customer-portal/payment-methods/ach/link-session",
    );
    expect(opts.method).toBe("POST");
    expect(opts.headers.Authorization).toBe("Bearer test-token");
  });

  it("renders a boot error when /ach/link-session returns stripe_not_configured", async () => {
    primeFetch([
      { ok: true, body: { ok: false, reason: "stripe_not_configured" } },
    ]);
    render(<StripeAddBankForm {...PROPS} />);
    const err = await screen.findByTestId("stripe-add-bank-boot-error");
    expect(err.textContent || "").toMatch(/not configured/i);
    // <Elements> did NOT mount when boot failed.
    expect(screen.queryByTestId("mock-elements")).toBeNull();
  });

  it("clicking Submit → stripe.confirmSetup → attach → onSuccess", async () => {
    primeFetch([
      // 1) boot fetch to /ach/link-session
      { ok: true, body: { ok: true, client_secret: "seti_TEST_secret" } },
      // 2) attach fetch after confirmSetup returns a PM id
      { ok: true, body: {
        ok: true,
        payment_method: {
          last4: "6789", brand: "us_bank_account",
          is_default: false, type: "ach",
        },
      } },
    ]);
    confirmSetupMock.mockResolvedValue({
      setupIntent: {
        id: "seti_TEST_1",
        status: "succeeded",
        payment_method: "pm_TEST_bank_1",
      },
    });
    const onSuccess = vi.fn();
    render(<StripeAddBankForm {...PROPS} onSuccess={onSuccess} />);
    await waitFor(() =>
      expect(screen.getByTestId("stripe-add-bank-submit")).toBeInTheDocument());
    // Click submit — the form fires confirmSetup then attach.
    fireEvent.click(screen.getByTestId("stripe-add-bank-submit"));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    // confirmSetup was called with redirect: "if_required".
    expect(confirmSetupMock).toHaveBeenCalledTimes(1);
    expect(confirmSetupMock.mock.calls[0][0].redirect).toBe("if_required");
    // Attach fetch went out with the returned payment_method_id.
    const attachCall = global.fetch.mock.calls[1];
    expect(attachCall[0]).toBe(
      "https://api.example.com/api/customer-portal/payment-methods/ach/attach",
    );
    const body = JSON.parse(attachCall[1].body);
    expect(body).toEqual({ payment_method_id: "pm_TEST_bank_1" });
    // onSuccess got the persisted row.
    expect(onSuccess.mock.calls[0][0]).toEqual({
      last4: "6789", brand: "us_bank_account",
      is_default: false, type: "ach",
    });
  });

  it("Stripe confirmSetup error surfaces inline (attach not called)", async () => {
    primeFetch([
      { ok: true, body: { ok: true, client_secret: "seti_TEST_secret" } },
    ]);
    confirmSetupMock.mockResolvedValue({
      error: { message: "Your bank rejected the connection." },
    });
    const onSuccess = vi.fn();
    render(<StripeAddBankForm {...PROPS} onSuccess={onSuccess} />);
    await waitFor(() =>
      expect(screen.getByTestId("stripe-add-bank-submit")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("stripe-add-bank-submit"));
    const err = await screen.findByTestId("stripe-add-bank-error");
    expect(err.textContent || "").toMatch(/rejected/i);
    expect(onSuccess).not.toHaveBeenCalled();
    // Only the boot fetch happened; no attach call.
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
