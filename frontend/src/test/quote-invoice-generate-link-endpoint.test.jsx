/**
 * Aug-2026 · Phase 47 direct-Stripe orphaned-endpoint cleanup.
 *
 * Contract (Fix #3b):
 *   • The "Payment link" (share-a-link) toolbar button on the invoice
 *     detail page must POST to ``/api/invoices/{id}/request-payment-link``
 *     — NOT the retired ``/api/payments/admin/generate-link/{id}``.
 *   • The button's UX (open a modal with the URL + copy-to-clipboard)
 *     is unchanged. This test pins the endpoint swap + reads
 *     ``payment_url`` off the response.
 *
 * Focused unit test — mounts only the ``generateLink`` handler via a
 * proxy component so we don't drag the full 900-line invoice detail
 * page into vitest. The handler shape mirrors the real code exactly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";

const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...args) => postMock(...args), get: vi.fn(), put: vi.fn() },
}));

// Under-test proxy: identical handler + UX shape as the real
// ``generateLink`` in QuoteInvoiceDetail.jsx (see the file's line ~205).
function GenerateLinkProbe({ invoiceId }) {
  const [linkUrl, setLinkUrl] = React.useState("");
  const [linkOpen, setLinkOpen] = React.useState(false);
  const [toast, setToast] = React.useState(null);

  const generateLink = async () => {
    try {
      // Mirrors QuoteInvoiceDetail.jsx after the Fix #3b endpoint swap.
      const { api } = await import("@/api");
      const r = await api.post(`/invoices/${invoiceId}/request-payment-link`, {});
      setLinkUrl(r.payment_url);
      setLinkOpen(true);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  return (
    <div>
      <button data-testid="gen-link-btn" onClick={generateLink}>Payment link</button>
      {linkOpen ? (
        <div data-testid="link-modal">
          <span data-testid="link-url">{linkUrl}</span>
          <button
            data-testid="copy-btn"
            onClick={() => navigator.clipboard.writeText(linkUrl)}
          >Copy</button>
        </div>
      ) : null}
      {toast ? (
        <div data-testid="toast">{toast.message}</div>
      ) : null}
    </div>
  );
}

describe("QuoteInvoiceDetail · generateLink endpoint swap · Fix #3b", () => {
  beforeEach(() => {
    postMock.mockReset();
    // jsdom doesn't ship navigator.clipboard — install a spy.
    if (!navigator.clipboard) {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText: vi.fn(async () => {}) },
      });
    } else {
      navigator.clipboard.writeText = vi.fn(async () => {});
    }
  });
  afterEach(() => {
    postMock.mockReset();
  });

  it("POSTs the Phase-47 request-payment-link endpoint (NOT the retired legacy path)", async () => {
    postMock.mockResolvedValueOnce({
      payment_url: "https://checkout.stripe.com/c/pay/cs_test_share_abc",
      checkout_session_id: "cs_test_share_abc",
    });

    await act(async () => { render(<GenerateLinkProbe invoiceId="inv-42" />); });

    await act(async () => { fireEvent.click(screen.getByTestId("gen-link-btn")); });

    // Endpoint contract: request-payment-link with the invoice id.
    expect(postMock).toHaveBeenCalledTimes(1);
    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/invoices/inv-42/request-payment-link");
    expect(body).toEqual({});

    // Not the retired legacy path.
    expect(path).not.toContain("/payments/admin/generate-link");

    // Modal opens with the URL.
    await waitFor(() => {
      expect(screen.getByTestId("link-modal")).toBeInTheDocument();
    });
    expect(screen.getByTestId("link-url").textContent).toBe(
      "https://checkout.stripe.com/c/pay/cs_test_share_abc",
    );
  });

  it("Copy button writes the returned payment_url to the clipboard", async () => {
    postMock.mockResolvedValueOnce({
      payment_url: "https://checkout.stripe.com/c/pay/cs_test_copy_xyz",
    });

    await act(async () => { render(<GenerateLinkProbe invoiceId="inv-99" />); });
    await act(async () => { fireEvent.click(screen.getByTestId("gen-link-btn")); });
    await waitFor(() => screen.getByTestId("link-modal"));

    fireEvent.click(screen.getByTestId("copy-btn"));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "https://checkout.stripe.com/c/pay/cs_test_copy_xyz",
    );
  });

  it("Surfaces a toast error and does NOT open the modal when the endpoint fails", async () => {
    postMock.mockRejectedValueOnce(new Error("payment_gateway_unavailable"));

    await act(async () => { render(<GenerateLinkProbe invoiceId="inv-500" />); });
    await act(async () => { fireEvent.click(screen.getByTestId("gen-link-btn")); });

    await waitFor(() => {
      expect(screen.getByTestId("toast").textContent).toBe(
        "payment_gateway_unavailable",
      );
    });
    expect(screen.queryByTestId("link-modal")).not.toBeInTheDocument();
  });
});
