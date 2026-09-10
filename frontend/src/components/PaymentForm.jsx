/**
 * Phase 47 · Feb-2026 — Direct Stripe Checkout Session redirect flow.
 *
 * Every payment surface routes through Stripe directly. This
 * component POSTs ``/api/invoices/{id}/request-payment-link`` and
 * redirects on the returned ``payment_url`` (a
 * ``https://checkout.stripe.com/…`` URL).
 *
 * Feb 2026 addendum · save-on-first-payment.
 *   * If the customer has ZERO saved payment methods (checked via
 *     ``GET /api/customer-portal/payment-methods`` — same endpoint the
 *     portal PM page uses), we surface a review UI first with a
 *     default-checked "Save this payment method for future automatic
 *     billing" checkbox. The customer can uncheck it before clicking
 *     "Pay $X".
 *   * If the customer has 1+ saved PMs, we auto-redirect exactly as
 *     before — no consent step is shown. This protects customers who
 *     already deliberately picked a default from being silently
 *     re-defaulted.
 *   * The checkbox state is threaded through as
 *     ``save_for_future_billing`` in the request body. The backend
 *     still gates on the server-side PM count (double-check) before
 *     applying ``setup_future_usage="off_session"`` to Stripe.
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

export default function PaymentForm({ invoice, invoiceId, source, magicToken, amount, onClose }) {
  const [errorMsg, setErrorMsg] = useState("");
  const [preparing, setPreparing] = useState(true);
  // Feb 2026 addendum — ``pmCount === null`` means we haven't fetched
  // yet. After the fetch resolves, ``pmCount === 0`` → review UI
  // with checkbox; ``pmCount >= 1`` → auto-redirect (legacy).
  const [pmCount, setPmCount] = useState(null);
  const [saveForFuture, setSaveForFuture] = useState(true);
  const startedRef = useRef(false);
  const autoRedirectedRef = useRef(false);

  // Feb-2026 P0 · resolve the correct amount. The pay-link modal
  // historically read ``invoice.total`` which is undefined on the
  // magic-link payload shape (the balance lives at
  // ``invoice.totals.total_due``). Priority chain:
  //   1. explicit ``amount`` prop passed by the caller
  //   2. ``invoice.totals.total_due`` (canonical viewer payload)
  //   3. legacy ``invoice.total - invoice.amount_paid`` shape
  //   4. 0 (never negative)
  const resolvedAmount = (() => {
    if (Number.isFinite(Number(amount))) return Number(amount);
    const td = invoice?.totals?.total_due;
    if (Number.isFinite(Number(td))) return Number(td);
    const legacy = Number(invoice?.total ?? 0) - Number(invoice?.amount_paid ?? 0);
    return Math.max(0, legacy);
  })();

  const invId = invoiceId || invoice?.id || invoice?.invoice_id;
  const isMagic = Boolean(magicToken);

  const start = React.useCallback(async (options) => {
    if (!invId) {
      setErrorMsg("Invoice id missing — please refresh and try again.");
      setPreparing(false);
      return;
    }
    setPreparing(true);
    setErrorMsg("");
    // Feb-2026 P0 · Hard 20 s timeout so the modal NEVER freezes on
    // "Preparing…". Underlying ``api.post`` already has a 30 s abort
    // but we surface a friendly message sooner so the customer gets
    // a retry button rather than staring at a spinner.
    let timer = null;
    const timeoutP = new Promise((_, reject) => {
      timer = setTimeout(
        () => reject(new Error("payment_gateway_timeout")),
        20000,
      );
    });
    try {
      const body = isMagic
        ? {}
        : { save_for_future_billing: !!(options && options.saveForFuture) };
      const path = isMagic
        ? `/invoices/${invId}/request-payment-link-magic?token=${encodeURIComponent(magicToken)}`
        : `/invoices/${invId}/request-payment-link`;
      const result = await Promise.race([
        api.post(path, body),
        timeoutP,
      ]);
      const url = result?.payment_url;
      if (url) {
        _redirect(url);
        return;
      }
      // Backend returned 200 but no url — treat as gateway problem.
      setErrorMsg(friendlyFor("payment_gateway_unavailable"));
    } catch (err) {
      if (err && err.message === "payment_gateway_timeout") {
        setErrorMsg(
          "Preparing your payment link is taking longer than expected. " +
          "Please try again or contact support.",
        );
      } else {
        const code = extractErrorCode(err);
        setErrorMsg(friendlyFor(code));
      }
    } finally {
      if (timer) clearTimeout(timer);
      setPreparing(false);
    }
  }, [invId, isMagic, magicToken]);

  // Fetch PM count before deciding whether to auto-redirect or show
  // the review UI. If the fetch fails, err ON THE SIDE of NOT saving
  // (skip the checkbox) so we never save behind a customer whose
  // account state we couldn't confirm.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      // Feb-2026 P0 · Magic-link path skips the PM count fetch and
      // the save-for-future flow entirely. A public magic-link
      // customer isn't portal-authed so the PM endpoint 401s, which
      // used to trigger the global session-clear-and-redirect
      // and freeze the pay modal. Straight to start().
      if (isMagic) {
        autoRedirectedRef.current = true;
        setPmCount(1);        // sentinel: skip review UI
        await start({ saveForFuture: false });
        return;
      }
      let count = 1;   // safe default = "1+" → skip checkbox
      try {
        const r = await api.get("/customer-portal/payment-methods");
        const arr = Array.isArray(r?.methods) ? r.methods : [];
        count = arr.length;
      } catch (_) {
        count = 1;   // fetch failed → assume ≥1 → skip checkbox path
      }
      setPmCount(count);
      if (count >= 1 && !autoRedirectedRef.current) {
        // Legacy fast path — no consent step needed.
        autoRedirectedRef.current = true;
        await start({ saveForFuture: false });
      } else {
        // 0 PMs on file — stop the preparing spinner and show the
        // review UI with the checkbox. The customer clicks
        // "Pay $X" to actually generate the Session.
        setPreparing(false);
      }
    })();
  }, [start, isMagic]);

  const retry = () => {
    // Re-fire the Session-create call with the last-known consent
    // state. We deliberately DON'T re-fetch the PM count on retry —
    // the customer's account state hasn't changed in the seconds
    // since first load, and re-fetching risks the count flipping
    // if we JUST attached a PM in a parallel tab.
    autoRedirectedRef.current = true;
    start({ saveForFuture: pmCount === 0 ? saveForFuture : false });
  };

  const payNow = () => {
    autoRedirectedRef.current = true;
    start({ saveForFuture });
  };

  const amountDue = resolvedAmount.toFixed(2);
  const showReview = pmCount === 0 && !preparing && !errorMsg;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
         data-testid="payment-form-modal">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold mb-2" data-testid="payment-form-title">
          Pay ${amountDue}
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
        ) : showReview ? (
          <div className="space-y-4" data-testid="payment-form-review">
            <p className="text-sm text-slate-600">
              You'll be redirected to Stripe's secure checkout to complete this payment.
            </p>
            <label
              className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 p-3"
              data-testid="payment-form-save-row"
            >
              <input
                type="checkbox"
                checked={saveForFuture}
                onChange={(e) => setSaveForFuture(e.target.checked)}
                className="mt-0.5 h-4 w-4"
                data-testid="payment-form-save-checkbox"
              />
              <span className="text-sm text-slate-800">
                <span className="font-medium">
                  Save this payment method for future automatic billing
                </span>
                <br />
                <span className="text-xs text-slate-500">
                  You can remove saved payment methods anytime from your account settings.
                </span>
              </span>
            </label>
            <div className="flex justify-end gap-2">
              {onClose ? (
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 rounded-md border border-slate-300 text-sm"
                  data-testid="payment-form-review-cancel"
                >
                  Cancel
                </button>
              ) : null}
              <button
                type="button"
                onClick={payNow}
                className="px-4 py-1.5 rounded-md bg-slate-900 text-white text-sm font-semibold"
                data-testid="payment-form-pay-btn"
              >
                Pay ${amountDue}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
