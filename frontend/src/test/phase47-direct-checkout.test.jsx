/**
 * Phase 47 · Feb 2026 — Direct Stripe Checkout Session flow tests.
 *
 * Formerly ``lumino-pay-flow.test.jsx``. User has directed every
 * payment surface to route through Stripe directly, so the flow
 * being exercised here is now:
 *
 *   1. Mount ``<PaymentForm />``.
 *   2. Component POSTs ``/invoices/{id}/request-payment-link``.
 *   3. Backend returns ``{payment_url: "https://checkout.stripe.com/…"}``.
 *   4. Component immediately redirects the browser to that URL — no
 *      polling, no retry-after stub, no Lumino/Zapier round-trip.
 *
 * Regression guards:
 *   • The old ``lumino_payment_url`` key is NOT read anywhere in
 *     ``PaymentForm.jsx``.
 *   • The 30-second poll (``pollForUrl`` / ``POLL_MAX_ATTEMPTS``) is
 *     gone.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import PaymentForm from "@/components/PaymentForm";

// Mock the API module — every ``api.post`` call is under test control.
vi.mock("@/api", () => ({ api: { post: vi.fn(), get: vi.fn() } }));
import { api } from "@/api";

const _stripeUrl = "https://checkout.stripe.com/c/pay/cs_test_phase47_abc";

describe("Phase 47 · PaymentForm direct Stripe Checkout redirect", () => {
  let assignSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    // Every assign call is captured so we can assert on the URL and
    // never actually navigate the JSDOM window.
    assignSpy = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign: assignSpy },
    });
    // Feb 2026 addendum — the component now fetches the customer's
    // saved-PM list before choosing between the fast-path auto
    // redirect and the review-UI-with-consent flow. Every legacy
    // spec below asserts the fast-path shape, so we default the
    // GET to "1 PM on file" (skips the checkbox). The dedicated
    // save-on-first-payment specs later in this file override this
    // with a 0-PMs mock to exercise the review UI.
    api.get.mockResolvedValue({
      methods: [{ id: "pm-existing", last4: "0001" }],
    });
  });

  it("POSTs /request-payment-link on mount and redirects to the Stripe URL", async () => {
    api.post.mockResolvedValueOnce({
      payment_url: _stripeUrl,
      checkout_session_id: "cs_test_phase47_abc",
      amount_cents: 12345,
      currency: "usd",
      mode: "test",
    });
    render(<PaymentForm invoice={{ id: "inv-1", total: 123.45 }} />);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/invoices/inv-1/request-payment-link",
        // Feb 2026 addendum — the body now carries the resolved
        // save flag. When the customer already has 1+ saved PMs
        // (mocked in beforeEach), the flag is FALSE regardless.
        expect.objectContaining({ save_for_future_billing: false }),
      );
    });
    await waitFor(() => {
      expect(assignSpy).toHaveBeenCalledWith(_stripeUrl);
    });
  });

  it("shows a friendly error on 502 payment_gateway_unavailable and offers retry", async () => {
    api.post.mockRejectedValueOnce({
      data: { detail: "payment_gateway_unavailable" },
      message: "payment_gateway_unavailable",
    });
    render(<PaymentForm invoice={{ id: "inv-2", total: 45.0 }} />);
    const err = await screen.findByTestId("payment-form-error");
    expect(err.textContent).toMatch(/couldn't reach the payment provider/i);
    // Retry button re-fires the POST.
    api.post.mockResolvedValueOnce({ payment_url: _stripeUrl });
    fireEvent.click(screen.getByTestId("payment-form-retry"));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith(_stripeUrl));
  });

  it("maps invoice_already_paid → 'already paid' friendly copy", async () => {
    api.post.mockRejectedValueOnce({
      data: { detail: "invoice_already_paid" },
      message: "invoice_already_paid",
    });
    render(<PaymentForm invoice={{ id: "inv-3", total: 99.0 }} />);
    const err = await screen.findByTestId("payment-form-error");
    expect(err.textContent).toMatch(/already paid/i);
    // Never redirected on an error path.
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("renders a preparing spinner between mount and redirect", async () => {
    // Delay the resolution so we can catch the preparing state.
    let resolve;
    api.post.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    render(<PaymentForm invoice={{ id: "inv-4", total: 10 }} />);
    expect(await screen.findByTestId("payment-form-preparing")).toBeInTheDocument();
    resolve({ payment_url: _stripeUrl });
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith(_stripeUrl));
  });
});


describe("Phase 47 · Feb 2026 addendum · save-on-first-payment", () => {
  let assignSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    assignSpy = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign: assignSpy },
    });
  });

  it("customer with ZERO PMs → renders the consent checkbox (default checked)", async () => {
    api.get.mockResolvedValue({ methods: [] });
    render(<PaymentForm invoice={{ id: "inv-new", total: 42 }} />);
    // Consent row + checkbox visible, no auto-redirect fired.
    const cb = await screen.findByTestId("payment-form-save-checkbox");
    expect(cb).toBeInTheDocument();
    expect(cb.checked).toBe(true);
    // Feb-2026 · Round 2 flake fix — production copy was shortened
    // from "Save this payment method for future automatic billing"
    // to "Save this card for future invoices". Update the matcher
    // to the current copy.
    expect(screen.getByTestId("payment-form-save-row").textContent)
      .toMatch(/Save this card for future invoices/i);
    expect(screen.getByTestId("payment-form-review").textContent)
      .toMatch(/remove saved payment methods anytime/i);
    // POST didn't fire yet, and the user was not redirected.
    expect(api.post).not.toHaveBeenCalled();
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("clicking Pay $X posts save_for_future_billing=true when the checkbox is left checked", async () => {
    api.get.mockResolvedValue({ methods: [] });
    api.post.mockResolvedValueOnce({ payment_url: _stripeUrl });
    render(<PaymentForm invoice={{ id: "inv-save", total: 55 }} />);
    await screen.findByTestId("payment-form-pay-btn");
    fireEvent.click(screen.getByTestId("payment-form-pay-btn"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/invoices/inv-save/request-payment-link",
        { save_for_future_billing: true },
      );
    });
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith(_stripeUrl));
  });

  it("unchecking the box posts save_for_future_billing=false", async () => {
    api.get.mockResolvedValue({ methods: [] });
    api.post.mockResolvedValueOnce({ payment_url: _stripeUrl });
    render(<PaymentForm invoice={{ id: "inv-optout", total: 99 }} />);
    const cb = await screen.findByTestId("payment-form-save-checkbox");
    fireEvent.click(cb);
    expect(cb.checked).toBe(false);
    fireEvent.click(screen.getByTestId("payment-form-pay-btn"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/invoices/inv-optout/request-payment-link",
        { save_for_future_billing: false },
      );
    });
  });

  it("customer with 1+ PMs → NO checkbox rendered, auto-redirect fast-path", async () => {
    api.get.mockResolvedValue({
      methods: [
        { id: "pm-1", last4: "4242" },
        { id: "pm-2", last4: "0002" },
      ],
    });
    api.post.mockResolvedValueOnce({ payment_url: _stripeUrl });
    render(<PaymentForm invoice={{ id: "inv-existing", total: 20 }} />);
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith(_stripeUrl));
    // Checkbox never rendered.
    expect(screen.queryByTestId("payment-form-save-checkbox")).toBeNull();
    expect(screen.queryByTestId("payment-form-review")).toBeNull();
    // Server-side save flag is false because the customer isn't new.
    expect(api.post).toHaveBeenCalledWith(
      "/invoices/inv-existing/request-payment-link",
      { save_for_future_billing: false },
    );
  });

  it("PM-count fetch failure → safe default (skip checkbox, auto-redirect with save=false)", async () => {
    api.get.mockRejectedValue(new Error("boom"));
    api.post.mockResolvedValueOnce({ payment_url: _stripeUrl });
    render(<PaymentForm invoice={{ id: "inv-boom", total: 30 }} />);
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith(_stripeUrl));
    // No checkbox on failure — err on the side of NOT saving.
    expect(screen.queryByTestId("payment-form-save-checkbox")).toBeNull();
    expect(api.post).toHaveBeenCalledWith(
      "/invoices/inv-boom/request-payment-link",
      { save_for_future_billing: false },
    );
  });
});

describe("Phase 47 · Regression guards against the LZ3 Lumino/Zapier flow", () => {
  it("PaymentForm source has no lumino_payment_url, no polling, no zapier", () => {
    // Read the component source and assert the pre-migration cruft
    // is gone. Prevents accidental re-introduction on a future rewrite.
    const fs = require("node:fs");
    const path = require("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../components/PaymentForm.jsx"),
      "utf8",
    );
    // Strip comments before scanning — the migration story LIVES in
    // the top-of-file docstring on purpose (so anyone reading knows
    // why we swapped away from Lumino/Zapier); we only want to catch
    // runtime code references.
    const codeOnly = src
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    expect(codeOnly).not.toMatch(/lumino_payment_url/);
    expect(codeOnly).not.toMatch(/POLL_MAX_ATTEMPTS/);
    expect(codeOnly).not.toMatch(/POLL_INTERVAL_MS/);
    expect(codeOnly).not.toMatch(/pollForUrl/);
    expect(codeOnly).not.toMatch(/retry-after/i);
    expect(codeOnly).not.toMatch(/zapier/i);
  });

  it("PaymentForm reads payment_url off the /request-payment-link response", () => {
    const fs = require("node:fs");
    const path = require("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../components/PaymentForm.jsx"),
      "utf8",
    );
    expect(src).toContain("payment_url");
    expect(src).toContain("/invoices/${invId}/request-payment-link");
  });
});
