/**
 * TD-customer-list-bulk-request-card-stripe-setupintent · Feb-2026.
 *
 * Public (no auth) card-capture page for the bulk admin flow.
 * The route path (/customer-portal/add-card/:token) is distinct from
 * Phase 47c's /portal/add-card?token=X so the two flows can coexist
 * while mobile parity + legacy paths migrate separately.
 *
 * Elements config: card-only (payment_method_types=["card"] on the
 * SetupIntent BE-side) + wallets:{link:"never",applePay:"never",
 * googlePay:"never"} on the Elements provider → no Link UI, no
 * Apple/Google Pay auto-prompt, no Bank tab.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements, useStripe, useElements, PaymentElement,
} from "@stripe/react-stripe-js";

const _API_BASE = `${process.env.REACT_APP_BACKEND_URL}/api`;


function InnerForm({ token, onSaved }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (evt) => {
    evt?.preventDefault?.();
    if (!stripe || !elements) return;
    setError(""); setSubmitting(true);
    try {
      const { error: sErr, setupIntent } = await stripe.confirmSetup({
        elements,
        confirmParams: { return_url: window.location.href },
        redirect: "if_required",
      });
      if (sErr) { setError(sErr.message || "Card capture failed."); return; }
      const pmId = setupIntent?.payment_method;
      if (!pmId) { setError("Stripe did not return a payment method id."); return; }
      const res = await fetch(
        `${_API_BASE}/card-capture/${encodeURIComponent(token)}/confirm`,
        { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ payment_method_id: pmId }) },
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(json?.detail?.message || json?.detail?.code
                 || "Failed to save card on file.");
        return;
      }
      onSaved?.(json);
    } catch (e) {
      setError(String(e?.message || e));
    } finally { setSubmitting(false); }
  };

  return (
    <form onSubmit={submit} className="space-y-4"
           data-testid="customer-card-capture-form">
      <PaymentElement options={{ layout: "tabs" }} />
      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800"
              data-testid="customer-card-capture-error">{error}</div>
      ) : null}
      <button type="submit" disabled={!stripe || submitting}
               className="w-full rounded bg-blue-600 text-white font-bold py-2 disabled:opacity-50"
               data-testid="customer-card-capture-submit">
        {submitting ? "Saving…" : "Save card"}
      </button>
    </form>
  );
}


export default function CustomerCardCapturePage() {
  const { token } = useParams();
  const [ctx, setCtx] = useState(null);
  const [clientSecret, setClientSecret] = useState("");
  const [bootError, setBootError] = useState("");
  const [saved, setSaved] = useState(false);

  const stripePromise = useMemo(
    () => (ctx?.publishable_key ? loadStripe(ctx.publishable_key) : null),
    [ctx?.publishable_key],
  );

  useEffect(() => {
    if (!token) {
      setBootError("Missing token. Open the link from the email or text message.");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `${_API_BASE}/card-capture/${encodeURIComponent(token)}`);
        const json = await r.json().catch(() => ({}));
        if (!r.ok) {
          const d = json?.detail;
          const code = (d && d.code) || "";
          const msg = (d && d.message) ||
            (code === "token_already_used" ? "This link has already been used." :
             code === "token_expired"      ? "This link has expired." :
             code === "token_not_found"    ? "This link is not valid." :
             code === "stripe_unavailable" ? "Card capture is temporarily unavailable." :
             "This link is not valid.");
          throw new Error(msg);
        }
        if (cancelled) return;
        setCtx(json);
        setClientSecret(json.setup_intent_client_secret || "");
        if (!json.publishable_key) {
          setBootError("Stripe not configured. Contact your provider.");
        }
      } catch (e) {
        if (!cancelled) setBootError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  return (
    <div className="min-h-screen bg-slate-50 py-12 px-4"
          data-testid="customer-card-capture-page">
      <div className="w-full max-w-md mx-auto rounded-lg bg-white shadow p-6 space-y-4">
        <h1 className="text-lg font-bold" data-testid="customer-card-capture-title">
          {ctx?.tenant_business_name ? `Add a card for ${ctx.tenant_business_name}` : "Add a card"}
        </h1>
        {ctx?.customer_first_name ? (
          <div className="text-sm text-slate-600"
                data-testid="customer-card-capture-greeting">
            Hi {ctx.customer_first_name}, save a card so we can bill
            visits automatically.
          </div>
        ) : null}

        {bootError ? (
          <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800"
                data-testid="customer-card-capture-boot-error">{bootError}</div>
        ) : saved ? (
          <div className="rounded border border-green-300 bg-green-50 p-3 text-sm text-green-800"
                data-testid="customer-card-capture-success">
            You're all set — your card is on file. You can close this window.
          </div>
        ) : !ctx || !clientSecret || !stripePromise ? (
          <p className="text-sm text-slate-500"
              data-testid="customer-card-capture-loading">
            Preparing secure card entry…
          </p>
        ) : (
          <Elements
            stripe={stripePromise}
            options={{
              clientSecret,
              appearance: { theme: "stripe" },
              // Link + wallets disabled — card-only capture per spec.
              wallets: { link: "never", applePay: "never", googlePay: "never" },
            }}
          >
            <InnerForm token={token} onSaved={() => setSaved(true)} />
          </Elements>
        )}
      </div>
    </div>
  );
}
