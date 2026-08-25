/**
 * Feb-2026 · Stripe reconcile-endpoint hardening — Vitest.
 *
 * Locks in the new synchronous reconcile call in
 * ``frontend/src/pages/portal/PortalPages.jsx::PortalPaymentComplete``.
 * Previously the screen only polled ``GET /payments/status/{sid}``
 * and relied on webhook delivery to flip the invoice. Now:
 *
 *   1. On mount, POST /payments/stripe/session/{sid}/reconcile.
 *   2. If ``reconciled: true`` → show "Payment confirmed" immediately.
 *   3. If ``reconciled: false`` (unpaid — Stripe still processing) →
 *      fall through to the polling fallback.
 *   4. If the reconcile call itself errors (502, network) → show a
 *      retry-with-error-id state so the customer isn't stranded.
 *
 * Uses the same ``@/api`` + ``sonner`` mock plumbing the other portal
 * tests use.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: apiPostMock,
    patch: vi.fn(), put: vi.fn(), del: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

// The portal page pulls in auth context.
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-c", role: "customer", email: "c@x.co",
             name: "C", customer_id: "cust-1" },
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));


async function renderPaymentComplete(sessionId = "cs_test_reconcile_ok") {
  const { PortalPaymentComplete } = await import(
    "@/pages/portal/PortalPages"
  );
  return render(
    <MemoryRouter initialEntries={[`/portal/payment-complete?session_id=${sessionId}`]}>
      <PortalPaymentComplete />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  vi.clearAllMocks();
  // Default: /quotes/{id} used to fetch invoice details post-reconcile.
  apiGetMock.mockResolvedValue({
    id: "inv-1", title: "Pool Repair", total: 250.00,
  });
});


// ══════════════════════════════════════════════════════════════════════
// 1 · Reconcile returns paid → "Payment confirmed" state.
// ══════════════════════════════════════════════════════════════════════
describe("PortalPaymentComplete · reconcile success", () => {
  it("shows 'Payment confirmed' when reconcile returns reconciled=true", async () => {
    apiPostMock.mockResolvedValueOnce({
      reconciled: true,
      already_paid: false,
      invoice_id: "inv-1",
      amount_paid: 250.00,
      payment_status: "paid",
    });

    await renderPaymentComplete();

    // Assert the reconcile POST fired to the correct URL.
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith(
        "/payments/stripe/session/cs_test_reconcile_ok/reconcile",
        {},
      ),
    );
    // Paid state DOM.
    await screen.findByTestId("pc-paid");
    expect(screen.getByText(/Payment confirmed/i)).toBeTruthy();
    // The polling fallback GET must NOT fire when reconcile already
    // succeeded — that would be a redundant round-trip.
    expect(apiGetMock).not.toHaveBeenCalledWith(
      expect.stringMatching(/^\/payments\/status\//),
    );
  });
});


// ══════════════════════════════════════════════════════════════════════
// 2 · Reconcile returns unpaid → polling fallback fires.
// ══════════════════════════════════════════════════════════════════════
describe("PortalPaymentComplete · reconcile unpaid → polling", () => {
  it("falls through to /payments/status polling when reconciled=false", async () => {
    apiPostMock.mockResolvedValueOnce({
      reconciled: false,
      reason: "unpaid",
      payment_status: "unpaid",
    });

    // First polling GET — still unpaid; second — paid.
    apiGetMock
      .mockResolvedValueOnce({ status: "unpaid" })
      .mockResolvedValueOnce({ status: "paid", invoice_id: "inv-1" })
      // Third + fourth calls: the invoice-details fetch after paid.
      .mockResolvedValue({ id: "inv-1", title: "Pool Repair",
                            total: 250.00 });

    await renderPaymentComplete();

    // Reconcile was called.
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledTimes(1),
    );
    // And the polling GET fires (may take a couple of ticks — the
    // component sleeps 5s between polls in production; here we
    // just assert eventual invocation).
    await waitFor(
      () => expect(apiGetMock).toHaveBeenCalledWith(
        "/payments/status/cs_test_reconcile_ok",
      ),
      { timeout: 15_000 },
    );
  }, 20_000);
});


// ══════════════════════════════════════════════════════════════════════
// 3 · Reconcile HTTP error → error state with retry button.
// ══════════════════════════════════════════════════════════════════════
describe("PortalPaymentComplete · reconcile error", () => {
  it("shows error state + retry button when the reconcile call throws", async () => {
    apiPostMock.mockRejectedValueOnce(
      Object.assign(new Error("Bad Gateway"),
                     { detail: "stripe.session.retrieve failed" }),
    );

    await renderPaymentComplete();

    // Error state rendered.
    const err = await screen.findByTestId("pc-error");
    expect(err).toBeTruthy();
    expect(screen.getByText(/Something went wrong/i)).toBeTruthy();
    // Ref line with the last 12 chars of the session id.
    const ref = screen.getByTestId("pc-error-id");
    expect(ref.textContent).toMatch(/reconcile_ok/);
    // Retry button re-fires the reconcile POST.
    const retry = screen.getByTestId("pc-retry");
    apiPostMock.mockResolvedValueOnce({
      reconciled: true, already_paid: false,
      invoice_id: "inv-1", amount_paid: 250.00,
      payment_status: "paid",
    });
    fireEvent.click(retry);
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledTimes(2),
    );
    // Retry path resolves to the paid state.
    await screen.findByTestId("pc-paid");
  });
});


// ══════════════════════════════════════════════════════════════════════
// 4 · Missing session_id in URL → no_session guard (no POST fires).
// ══════════════════════════════════════════════════════════════════════
describe("PortalPaymentComplete · no session_id", () => {
  it("does not fire the reconcile call when the URL has no session_id", async () => {
    const { PortalPaymentComplete } = await import(
      "@/pages/portal/PortalPages"
    );
    render(
      <MemoryRouter initialEntries={["/portal/payment-complete"]}>
        <PortalPaymentComplete />
      </MemoryRouter>,
    );
    // No reconcile POST fired.
    expect(apiPostMock).not.toHaveBeenCalled();
  });
});
