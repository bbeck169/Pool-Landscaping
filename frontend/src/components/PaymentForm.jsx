/**
 * LZ3 · Feb-2026 — Lumino hosted-checkout redirect flow.
 *
 * Replaces the Stripe PaymentElement modal. On mount:
 *   1. If ``invoice.lumino_payment_url`` present → redirect immediately.
 *   2. Otherwise → refetch the invoice once (in case the URL has
 *      landed since props were snapshotted), then POST
 *      /api/invoices/{id}/request-payment-link and poll
 *      /api/quotes/{id} every 3s (up to 30s / 10 tries).
 *   3. On success → redirect. On timeout → error state with retry.
 *   4. Known error codes → user-friendly copy. Raw code stays in
 *      the console for debugging.
 */
import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 10;   // 30 s total

const FRIENDLY_ERRORS = {
  rate_limited:
    "You've tried to generate a payment link too many times in a short window. Please wait a minute and try again.",
  not_configured:
    "Payment link generation isn't configured. Please contact support.",
  already_paid: "This invoice is already paid.",
  zapier_unreachable:
    "We couldn't reach our payment provider. Please try again in a moment.",
  invoice_not_found: "Invoice not found.",
  not_your_invoice:
    "You don't have permission to pay this invoice. Please contact support.",
};
const GENERIC_ERROR =
  "Something went wrong preparing your payment link. Please try again or contact support.";
const TIMEOUT_ERROR =
  "Payment link generation is delayed. Please try again in a moment or contact support.";

function friendlyFor(code) {
  if (!code) return GENERIC_ERROR;
  return FRIENDLY_ERRORS[code] || GENERIC_ERROR;
}

function extractErrorCode(e) {
  // Try known FastAPI shapes: {detail: {error: "code"}} or {detail: "code"}
  // or fetch-thrown errors carrying .data.error.
  try {
    if (!e) return null;
    if (e.data) {
      if (typeof e.data.error === "string") return e.data.error;
      if (e.data.detail && typeof e.data.detail === "string") return e.data.detail;
      if (e.data.detail && typeof e.data.detail.error === "string") {
        return e.data.detail.error;
      }
    }
    if (typeof e.message === "string" && /rate_limited|not_configured/.test(e.message)) {
      return e.message;
    }
    if (e.status === 429) return "rate_limited";
    if (e.status === 404) return "invoice_not_found";
  } catch (_x) { /* noop */ }
  return null;
}

export default function PaymentForm({ invoice, invoiceId, source = "authenticated", onClose }) {
  const [status, setStatus] = useState("idle");   // idle | preparing | error
  const [errorMsg, setErrorMsg] = useState("");
  const cancelledRef = useRef(false);

  const inv = invoice || {};
  const invId = invoiceId || inv.id || "";

  useEffect(() => () => { cancelledRef.current = true; }, []);

  const redirectTo = (url) => {
    if (!url || cancelledRef.current) return;
    // eslint-disable-next-line no-console
    console.log("[LZ3 PaymentForm] redirecting →", url);
    window.location.assign(url);
  };

  const pollForUrl = async () => {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      if (cancelledRef.current) return null;
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      try {
        const fresh = await api.get(`/quotes/${invId}`);
        // eslint-disable-next-line no-console
        console.log("[LZ3 PaymentForm] poll attempt", attempt + 1,
                     "→ has_url:", !!fresh?.lumino_payment_url);
        if (fresh?.lumino_payment_url) return fresh.lumino_payment_url;
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn("[LZ3 PaymentForm] poll fetch failed", e);
      }
    }
    return null;
  };

  const setFriendlyError = (rawCodeOrErr) => {
    const code = typeof rawCodeOrErr === "string"
      ? rawCodeOrErr : extractErrorCode(rawCodeOrErr);
    // eslint-disable-next-line no-console
    console.error("[LZ3 PaymentForm] error code:", code, rawCodeOrErr);
    setStatus("error");
    setErrorMsg(code ? friendlyFor(code) : GENERIC_ERROR);
  };

  const startFlow = async () => {
    // 1. Fast path — URL already on the passed-in invoice.
    const existing = inv.lumino_payment_url;
    if (existing) {
      redirectTo(existing);
      return;
    }
    setStatus("preparing");
    setErrorMsg("");
    // 2. Server-side re-check — the invoice snapshot the caller
    //    passed may be stale. If the URL is already there on the
    //    server, we can redirect without going through the whole
    //    request-and-poll dance.
    try {
      const fresh0 = await api.get(`/quotes/${invId}`);
      if (fresh0?.lumino_payment_url) {
        redirectTo(fresh0.lumino_payment_url);
        return;
      }
    } catch (_x) { /* proceed to POST */ }
    // 3. Ask the backend to trigger the Zap.
    try {
      const result = await api.post(
        `/invoices/${invId}/request-payment-link`, {},
      );
      if (result?.lumino_payment_url) {
        redirectTo(result.lumino_payment_url);
        return;
      }
    } catch (e) {
      setFriendlyError(e);
      return;
    }
    // 4. Poll for the URL to appear (Zap runs async).
    const url = await pollForUrl();
    if (url) {
      redirectTo(url);
    } else {
      // eslint-disable-next-line no-console
      console.warn("[LZ3 PaymentForm] poll exhausted without URL");
      setStatus("error");
      setErrorMsg(TIMEOUT_ERROR);
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
            <div className="text-red-600 mb-3" data-testid="pay-error-message">
              {errorMsg}
            </div>
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
