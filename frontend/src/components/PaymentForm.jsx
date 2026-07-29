/**
 * LZ3 · Feb-2026 — Lumino hosted-checkout redirect flow.
 *
 * Replaces the Stripe PaymentElement modal. When mounted:
 *   1. If the invoice already has ``lumino_payment_url`` → redirect
 *      immediately.
 *   2. Otherwise → POST /api/invoices/{id}/request-payment-link,
 *      then poll /api/quotes/{id} every 3s (up to 30s / 10 tries)
 *      waiting for the URL to appear. Redirect on success. Show a
 *      retry-friendly error on timeout.
 *
 * All Stripe/PaymentElement/client_secret code paths deleted per
 * LZ3 scope. Stripe integration will be fully removed in LZ4.
 */
import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 10;   // 30 s total

export default function PaymentForm({ invoice, invoiceId, source = "authenticated", onClose }) {
  const [status, setStatus] = useState("idle");   // idle | preparing | error
  const [errorMsg, setErrorMsg] = useState("");
  const cancelledRef = useRef(false);

  const inv = invoice || {};
  const invId = invoiceId || inv.id || "";

  useEffect(() => () => { cancelledRef.current = true; }, []);

  const redirectTo = (url) => {
    if (!url || cancelledRef.current) return;
    window.location.assign(url);
  };

  const pollForUrl = async () => {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      if (cancelledRef.current) return null;
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      try {
        const fresh = await api.get(`/quotes/${invId}`);
        if (fresh?.lumino_payment_url) return fresh.lumino_payment_url;
      } catch (_e) {
        /* keep polling */
      }
    }
    return null;
  };

  const startFlow = async () => {
    const existing = inv.lumino_payment_url;
    if (existing) {
      redirectTo(existing);
      return;
    }
    setStatus("preparing");
    setErrorMsg("");
    try {
      const result = await api.post(
        `/invoices/${invId}/request-payment-link`, {},
      );
      // If Zap responded synchronously with URL (rare), take shortcut
      if (result?.lumino_payment_url) {
        redirectTo(result.lumino_payment_url);
        return;
      }
      const url = await pollForUrl();
      if (url) {
        redirectTo(url);
      } else {
        setStatus("error");
        setErrorMsg(
          "Payment link generation is delayed. Please try again in a "
          + "moment or contact support."
        );
      }
    } catch (e) {
      setStatus("error");
      setErrorMsg(
        (e && e.message)
        || "We couldn't start the payment. Please try again."
      );
    }
  };

  // Auto-start when modal opens.
  useEffect(() => {
    if (invId && status === "idle") {
      startFlow();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invId]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.5)" }}
      onClick={onClose}
      data-testid="pay-modal-backdrop"
    >
      <div
        className="bg-white max-w-md w-full p-6 rounded-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="pay-modal"
      >
        <h3 className="text-lg font-semibold mb-3">Pay Invoice</h3>
        {status === "preparing" ? (
          <div data-testid="pay-preparing" className="text-sm text-gray-700">
            <div className="animate-pulse mb-2">⏳ Preparing your payment link…</div>
            <div className="text-xs text-gray-500">
              This usually takes just a few seconds.
            </div>
          </div>
        ) : null}
        {status === "error" ? (
          <div data-testid="pay-error" className="text-sm">
            <div className="text-red-600 mb-3">{errorMsg}</div>
            <div className="flex gap-2">
              <button
                onClick={() => { setStatus("idle"); startFlow(); }}
                data-testid="pay-retry-btn"
                className="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold">
                Retry
              </button>
              <button
                onClick={onClose}
                data-testid="pay-close-btn"
                className="px-3 py-2 rounded-lg border text-sm">
                Close
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
