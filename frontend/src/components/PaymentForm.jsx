/**
 * Phase 47 · Feb-2026 — Direct Stripe Checkout Session redirect flow.
 *
 * User has directed every payment surface to route through Stripe
 * directly (no Lumino / Zapier). This component replaces the LZ3
 * polling-for-Lumino flow with an immediate ``POST
 * /api/invoices/{id}/request-payment-link`` → redirect on the
 * returned ``payment_url`` (a ``https://checkout.stripe.com/…`` URL).
 *
 * Behaviour:
 *   1. On mount, POST the request-payment-link endpoint.
 *   2. Backend calls ``stripe.checkout.Session.create(mode="payment",
 *      metadata={crm_invoice_id, crm_tenant_id, crm_customer_id})``.
 *      Reconciliation happens webhook-side.
 *   3. If the response carries ``payment_url`` → redirect immediately.
 *   4. On failure → error state with a retry button + friendly copy
 *      mapped from the backend error code (409 already_paid, 400
 *      invoice_not_found, 502 payment_gateway_unavailable, …).
 *
 * There is NO polling anymore. The Session URL is returned in the
 * same response the browser initiates — waiting-30-seconds-for-Zapier
 * is gone.
 */
import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";

const FRIENDLY_ERRORS = {
  rate_limited:
    "You've tried to generate a payment link too many times in a short window. Please wait a minute and try again.",
  invoice_already_paid: "This invoice is already paid.",
  invoice_not_found: "Invoice not found.",
  not_your_invoice:
    "You don't have permission to pay this invoice. Please contact support.",
  payment_gateway_unavailable:
    "We couldn't reach the payment provider. Please try again in a moment.",
};
const GENERIC_ERROR =
  "Something went wrong preparing your payment link. Please try again or contact support.";

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
    // Some clients throw with a `.message` that IS the code (e.g.
    // FastAPI HTTPException(...) → JSON.detail bubbles up as message).
    if (typeof e.message === "string" && e.message.trim()) {
      return e.message.trim();
    }
    return null;
  } catch (_) {
    return null;
  }
}

// Split out so tests can stub window.location.assign.
export function _redirect(url) {
  if (typeof window !== "undefined" && url) {
    window.location.assign(url);
  }
}

export default function PaymentForm({ invoice, onClose }) {
  const [errorMsg, setErrorMsg] = useState("");
  const [preparing, setPreparing] = useState(true);
  const startedRef = useRef(false);

  const invId = invoice?.id;

  const start = React.useCallback(async () => {
    if (!invId) return;
    setPreparing(true);
    setErrorMsg("");
    try {
      const result = await api.post(
        `/invoices/${invId}/request-payment-link`, {},
      );
      const url = result?.payment_url;
      if (url) {
        _redirect(url);
        return;
      }
      // Backend returned 200 but no url — treat as gateway problem.
      setErrorMsg(friendlyFor("payment_gateway_unavailable"));
    } catch (err) {
      const code = extractErrorCode(err);
      setErrorMsg(friendlyFor(code));
    } finally {
      setPreparing(false);
    }
  }, [invId]);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    start();
  }, [start]);

  const retry = () => {
    startedRef.current = false;
    start();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
         data-testid="payment-form-modal">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold mb-2" data-testid="payment-form-title">
          Pay ${((invoice?.total ?? 0) - (invoice?.amount_paid ?? 0)).toFixed(2)}
        </h3>
        {preparing ? (
          <p className="text-sm text-slate-600" data-testid="payment-form-preparing">
            Preparing your secure payment link…
          </p>
        ) : errorMsg ? (
          <div className="space-y-3">
            <p className="text-sm text-red-700" data-testid="payment-form-error">
              {errorMsg}
            </p>
            <div className="flex justify-end gap-2">
              {onClose ? (
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 rounded-md border border-slate-300 text-sm"
                  data-testid="payment-form-close"
                >
                  Close
                </button>
              ) : null}
              <button
                type="button"
                onClick={retry}
                className="px-3 py-1.5 rounded-md bg-slate-900 text-white text-sm"
                data-testid="payment-form-retry"
              >
                Retry
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
