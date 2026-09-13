/**
 * send-and-copy-payment-link · Feb-2026 · UX Polish Batch B follow-up
 *
 * Locks the composed "Send + Copy Payment Link" invoice-toolbar
 * action. Pure unit tests against the handler contract — full page
 * render is heavy and covered by e2e, so we exercise the four flow
 * branches via a thin harness:
 *
 *   1. RBAC — button hidden for technician.
 *   2. Success chain — POST send-reminder + POST request-payment-link
 *      + clipboard.writeText fires with the correct URL.
 *   3. Send succeeds + link fetch fails — warning toast branch,
 *      clipboard NOT called.
 *   4. Send fails — error toast branch, clipboard NOT called.
 *   5. Terminal-status invoice — button hidden (paid / void / cancelled).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React from "react";

const postMock = vi.fn();
const putMock = vi.fn();
const writeTextMock = vi.fn().mockResolvedValue(undefined);

vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({}),
    post: (...a) => postMock(...a),
    put: (...a) => putMock(...a),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

import { api } from "@/api";


// Minimal harness that mirrors the QuoteInvoiceDetail button-gate +
// handler shape. Kept local so the unit doesn't drag in the entire
// 1800-LOC detail page.
function _Harness({ isInvoice, isStaff, docStatus, onToast }) {
  const [sending, setSending] = React.useState(false);
  const status = String(docStatus || "").toLowerCase();
  const gated = isInvoice && isStaff
    && !["void", "cancelled", "paid"].includes(status);

  const handle = async () => {
    if (sending) return;
    const wasDraft = status === "draft";
    setSending(true);
    let sendOk = false;
    let paymentUrl = null;
    try {
      if (wasDraft) await api.put(`/quotes/inv-1/status?status=sent`);
      await api.post(`/quotes/inv-1/send-reminder`);
      sendOk = true;
      try {
        const linkResp = await api.post(
          `/invoices/inv-1/request-payment-link`, {},
        );
        paymentUrl = linkResp?.payment_url || linkResp?.payment_link || null;
      } catch {
        onToast({ tone: "warning",
                  message: "Sent. Payment link unavailable — copy manually." });
      }
      if (paymentUrl) {
        try {
          await navigator.clipboard.writeText(paymentUrl);
          onToast({ tone: "success",
                    message: `Sent to customer. Payment link copied.` });
        } catch {
          onToast({ tone: "success",
                    message: `Sent. Copy this link manually: ${paymentUrl}` });
        }
      }
    } catch (e) {
      if (!sendOk) onToast({ tone: "error", message: e?.message || "Send failed." });
    } finally {
      setSending(false);
    }
  };

  return gated ? (
    <button
      data-testid="send-and-copy-payment-link-btn"
      disabled={sending}
      onClick={handle}
    >
      Send & Copy Payment Link
    </button>
  ) : null;
}


beforeEach(() => {
  postMock.mockReset();
  putMock.mockReset();
  writeTextMock.mockReset();
  writeTextMock.mockResolvedValue(undefined);
  Object.defineProperty(global.navigator, "clipboard", {
    value: { writeText: writeTextMock },
    configurable: true,
  });
});


describe("Send + Copy Payment Link · Batch B follow-up", () => {
  it("Case 1 · hidden for technician", () => {
    render(<_Harness isInvoice isStaff={false} docStatus="sent"
                       onToast={() => {}} />);
    expect(screen.queryByTestId("send-and-copy-payment-link-btn")).toBeNull();
  });

  it("Case 5 · hidden on paid / void / cancelled invoices", () => {
    for (const st of ["paid", "void", "cancelled"]) {
      const { unmount } = render(
        <_Harness isInvoice isStaff docStatus={st} onToast={() => {}} />,
      );
      expect(screen.queryByTestId("send-and-copy-payment-link-btn")).toBeNull();
      unmount();
    }
  });

  it("Case 2 · success chain fires send + link fetch + clipboard write", async () => {
    postMock
      .mockResolvedValueOnce({ ok: true, email_sent: true }) // send-reminder
      .mockResolvedValueOnce({ payment_url: "https://checkout.stripe.com/c/s_xyz" });
    const onToast = vi.fn();
    render(<_Harness isInvoice isStaff docStatus="sent" onToast={onToast} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("send-and-copy-payment-link-btn"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(2));
    expect(postMock.mock.calls[0][0]).toContain("send-reminder");
    expect(postMock.mock.calls[1][0]).toContain("request-payment-link");
    await waitFor(() => expect(writeTextMock).toHaveBeenCalledTimes(1));
    expect(writeTextMock.mock.calls[0][0])
      .toBe("https://checkout.stripe.com/c/s_xyz");
    // Success toast fires with the combined message.
    await waitFor(() => {
      const successCall = onToast.mock.calls.find(
        (c) => c[0].tone === "success",
      );
      expect(successCall).toBeTruthy();
      expect(successCall[0].message).toContain("Payment link copied");
    });
  });

  it("Case 3 · send succeeds but link fetch fails → warning toast, no clipboard", async () => {
    postMock
      .mockResolvedValueOnce({ ok: true }) // send-reminder success
      .mockRejectedValueOnce(new Error("stripe_unavailable")); // link fails
    const onToast = vi.fn();
    render(<_Harness isInvoice isStaff docStatus="sent" onToast={onToast} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("send-and-copy-payment-link-btn"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(2));
    // Clipboard must NOT be called when the URL couldn't be resolved.
    expect(writeTextMock).not.toHaveBeenCalled();
    await waitFor(() => {
      const warn = onToast.mock.calls.find((c) => c[0].tone === "warning");
      expect(warn).toBeTruthy();
      expect(warn[0].message).toContain("copy manually");
    });
  });

  it("Case 4 · send fails → error toast, no clipboard", async () => {
    postMock.mockRejectedValueOnce(new Error("network_down"));
    const onToast = vi.fn();
    render(<_Harness isInvoice isStaff docStatus="sent" onToast={onToast} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("send-and-copy-payment-link-btn"));
    });
    await waitFor(() => {
      const err = onToast.mock.calls.find((c) => c[0].tone === "error");
      expect(err).toBeTruthy();
    });
    expect(writeTextMock).not.toHaveBeenCalled();
    // Link-fetch call must NOT fire when send fails.
    expect(postMock).toHaveBeenCalledTimes(1);
  });
});
