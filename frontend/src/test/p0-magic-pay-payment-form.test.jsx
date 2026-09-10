/**
 * Feb-2026 P0 · Regression suite for the invoice-magic pay modal.
 *
 * Covers the two prod failure modes reported at
 * ``app.plofv.com/pay/invoice/e36e...``:
 *
 *   1. Modal renders ``Pay $0.00`` when the invoice payload uses the
 *      ``totals.total_due`` shape (magic-viewer). Fix: PaymentForm
 *      resolves the amount via a priority chain and accepts an
 *      explicit ``amount`` prop.
 *
 *   2. Modal freezes on "Preparing your secure payment link…"
 *      because the non-magic PM-count fetch 401s and blocks the
 *      flow. Fix: magic-link path skips the PM count fetch entirely
 *      and goes straight to ``start()`` — with a hard 20 s timeout
 *      so the modal cannot freeze silently even if the backend
 *      hangs.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

// api mocked BEFORE PaymentForm import so the module picks up the mock.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  TOKEN_KEY: "token",
}));

import { api } from "@/api";
import PaymentForm from "@/components/PaymentForm";


// Stub the redirect so we can observe it without navigating.
const originalLocation = window.location;
beforeEach(() => {
  Object.defineProperty(window, "location", {
    writable: true, configurable: true,
    value: { assign: vi.fn(), href: "http://test/pay/invoice/x?token=y" },
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  api.get.mockReset();
  api.post.mockReset();
  Object.defineProperty(window, "location", {
    writable: true, configurable: true, value: originalLocation,
  });
});


// ── 1. Amount interpolation ──────────────────────────────────────
describe("PaymentForm · amount interpolation", () => {
  it("uses explicit ``amount`` prop verbatim in the review CTA", async () => {
    // Force pmCount=0 path so the CTA renders instead of auto-redirecting.
    api.get.mockResolvedValueOnce({ methods: [] });
    render(
      <PaymentForm
        invoice={{ id: "inv-1", totals: { total_due: 205.0 } }}
        invoiceId="inv-1"
        amount={205.0}
        onClose={() => {}}
      />,
    );
    // The CTA + header both interpolate the amount.
    await waitFor(() => {
      const paybtn = screen.queryByTestId("payment-form-pay-cta");
      // Fall back to querying the visible amount text — the exact
      // testid may not exist, so we probe the DOM.
      const dom = document.body.textContent || "";
      expect(dom).toMatch(/\$205\.00/);
      expect(dom).not.toMatch(/\$0\.00/);
    });
  });

  it("falls back to ``invoice.totals.total_due`` when ``amount`` not passed",
    async () => {
    api.get.mockResolvedValueOnce({ methods: [] });
    render(
      <PaymentForm
        invoice={{ id: "inv-2", totals: { total_due: 42.82 } }}
        invoiceId="inv-2"
        onClose={() => {}}
      />,
    );
    await waitFor(() => {
      const dom = document.body.textContent || "";
      expect(dom).toMatch(/\$42\.82/);
    });
  });

  it("falls back to legacy ``invoice.total`` when neither is provided",
    async () => {
    api.get.mockResolvedValueOnce({ methods: [] });
    render(
      <PaymentForm
        invoice={{ id: "inv-3", total: 88, amount_paid: 12 }}
        invoiceId="inv-3"
        onClose={() => {}}
      />,
    );
    await waitFor(() => {
      const dom = document.body.textContent || "";
      expect(dom).toMatch(/\$76\.00/);
    });
  });
});


// ── 2. Magic-link path skips PM fetch, hits magic endpoint ────────
describe("PaymentForm · magic-link path", () => {
  it("skips /customer-portal/payment-methods and calls the magic endpoint",
    async () => {
    api.post.mockResolvedValueOnce({
      payment_url: "https://checkout.stripe.com/cs/abc",
      amount_cents: 20500,
    });
    render(
      <PaymentForm
        invoice={{ id: "inv-1", totals: { total_due: 205.0 } }}
        invoiceId="inv-1"
        magicToken="tok-abc"
        amount={205.0}
        onClose={() => {}}
      />,
    );
    // Magic path must NOT call the PM endpoint (auth-gated).
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledTimes(1);
    });
    expect(api.get).not.toHaveBeenCalled();
    const [path, body] = api.post.mock.calls[0];
    expect(path).toContain("/request-payment-link-magic");
    expect(path).toContain("token=tok-abc");
    expect(body).toEqual({});
    // Successful redirect.
    await waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith(
        "https://checkout.stripe.com/cs/abc",
      );
    });
  });

  it("surfaces a friendly error when the magic endpoint fails — no freeze",
    async () => {
    api.post.mockRejectedValueOnce({
      status: 503,
      data: { detail: { error: "payment_gateway_unavailable" } },
    });
    render(
      <PaymentForm
        invoice={{ id: "inv-1", totals: { total_due: 205.0 } }}
        invoiceId="inv-1"
        magicToken="tok-abc"
        amount={205.0}
        onClose={() => {}}
      />,
    );
    await waitFor(() => {
      // "Preparing" spinner must disappear — friendly error visible.
      const dom = document.body.textContent || "";
      expect(dom).not.toMatch(/Preparing your secure payment link/);
    });
    // The error copy references either a gateway problem or a retry.
    const dom = document.body.textContent || "";
    expect(dom.toLowerCase()).toMatch(/(unavailable|try again|error)/);
  });
});
