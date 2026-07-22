/**
 * Phase 4B · <PaymentForm> — Stripe PaymentElement (Card + ACH + wallets).
 *
 * Usage
 * -----
 *   <PaymentForm
 *     invoiceId={id}
 *     source="authenticated"          // or "portal"
 *     magicToken={token}              // required when source==="portal"
 *     onSuccess={() => refreshInvoice()}
 *     onClose={() => setOpen(false)}
 *   />
 *
 * Flow
 * ----
 * 1. GET /api/config/public              → publishable key + mode
 * 2. POST /api/payments/create-payment-intent
 *      { invoice_id, source, magic_token? }  → client_secret
 * 3. <Elements clientSecret={cs}> + <PaymentElement automatic_payment_methods />
 * 4. On confirm → Stripe SCA/3DS if needed → success/failure toast.
 *
 * The publishable key is fetched at runtime — never baked into the
 * webpack bundle. loadStripe is called once per mount and cached in
 * a promise for the modal lifetime.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { X, Loader2, ShieldCheck, AlertTriangle } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL;
const TOKEN_KEY = "token";

async function apiRaw(path, opts = {}, magicOverrideHeaders) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (!magicOverrideHeaders) {
    const t = localStorage.getItem(TOKEN_KEY) || "";
    if (t) headers["Authorization"] = `Bearer ${t}`;
    const slug = localStorage.getItem("tenant_slug") || "";
    if (slug) headers["X-Tenant-Slug"] = slug;
  }
  const res = await fetch(`${BASE}/api${path}`, { ...opts, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* leave as null */ }
  if (!res.ok) {
    const msg = data?.detail || `Request failed (${res.status})`;
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.status = res.status;
    throw err;
  }
  return data;
}

function InnerForm({ amountCents, currency, onSuccess, onError }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setSubmitting(true); setMessage("");
    const { error, paymentIntent } = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: window.location.href },
      redirect: "if_required",
    });
    setSubmitting(false);
    if (error) {
      const msg = error.message || "Payment failed.";
      setMessage(msg);
      onError && onError(msg);
      return;
    }
    if (paymentIntent && paymentIntent.status === "succeeded") {
      onSuccess && onSuccess(paymentIntent);
    } else if (paymentIntent && paymentIntent.status === "processing") {
      onSuccess && onSuccess(paymentIntent);
    } else {
      setMessage("Payment is pending. You'll receive a receipt when it's finalised.");
    }
  };

  const amountLabel = ((amountCents || 0) / 100).toFixed(2);
  const cur = (currency || "usd").toUpperCase();

  return (
    <form onSubmit={submit} data-testid="pay-form">
      <div style={{ padding: "8px 0 16px", fontSize: 14, color: "#475569" }}>
        Amount due: <b>${amountLabel} {cur}</b>
      </div>
      <PaymentElement
        options={{ layout: { type: "tabs", defaultCollapsed: false } }}
      />
      {message ? (
        <div
          role="alert"
          data-testid="pay-form-error"
          style={{
            marginTop: 12, padding: "10px 12px", borderRadius: 8,
            background: "#FEF3C7", color: "#92400E",
            display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13,
          }}
        >
          <AlertTriangle size={16} /> {message}
        </div>
      ) : null}
      <button
        type="submit"
        disabled={!stripe || submitting}
        data-testid="pay-form-submit-btn"
        style={{
          marginTop: 16, width: "100%",
          padding: "12px 16px", borderRadius: 10,
          background: submitting ? "#94A3B8" : "#0F172A",
          color: "white", fontWeight: 600, fontSize: 14,
          border: "none", cursor: submitting ? "wait" : "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          gap: 8,
        }}
      >
        {submitting ? (
          <><Loader2 size={16} className="animate-spin" /> Processing…</>
        ) : (
          <><ShieldCheck size={16} /> Pay ${amountLabel}</>
        )}
      </button>
      <div style={{ marginTop: 10, fontSize: 11, color: "#64748B", textAlign: "center" }}>
        Secured by Stripe. Card & ACH accepted.
      </div>
    </form>
  );
}

export default function PaymentForm({
  invoiceId, source = "authenticated", magicToken = "",
  onSuccess, onClose,
}) {
  const [phase, setPhase] = useState("loading");   // loading|ready|error
  const [error, setError] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [amountCents, setAmountCents] = useState(0);
  const [currency, setCurrency] = useState("usd");
  const [stripePromise, setStripePromise] = useState(null);
  const initedRef = useRef(false);

  useEffect(() => {
    if (initedRef.current) return;
    initedRef.current = true;
    (async () => {
      try {
        // 1. runtime pk
        const cfg = await apiRaw("/config/public", {}, source === "portal");
        const pk = cfg?.stripe_publishable_key;
        if (!pk) throw new Error("Payments unavailable — publishable key not configured.");
        setStripePromise(loadStripe(pk));

        // 2. create payment intent
        const body = { invoice_id: invoiceId, source };
        if (source === "portal") body.magic_token = magicToken;
        const overrideAuth = source === "portal" && magicToken;
        const pi = await apiRaw(
          "/payments/create-payment-intent",
          { method: "POST", body: JSON.stringify(body) },
          overrideAuth,
        );
        if (!pi?.client_secret) throw new Error("Could not create payment intent.");
        setClientSecret(pi.client_secret);
        setAmountCents(pi.amount_cents || 0);
        setCurrency(pi.currency || "usd");
        setPhase("ready");
      } catch (e) {
        setError(e?.message || "Failed to start payment.");
        setPhase("error");
      }
    })();
  }, [invoiceId, source, magicToken]);

  const elementsOptions = useMemo(() => ({
    clientSecret,
    appearance: { theme: "stripe", variables: { colorPrimary: "#0F172A" } },
  }), [clientSecret]);

  return (
    <div
      data-testid="payment-form-modal"
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(15, 23, 42, 0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose && onClose(); }}
    >
      <div
        style={{
          width: "100%", maxWidth: 480,
          background: "white", borderRadius: 14,
          boxShadow: "0 20px 40px rgba(0,0,0,0.25)",
          padding: 20,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
            Pay Invoice
          </div>
          <button
            type="button"
            data-testid="payment-form-close-btn"
            aria-label="Close"
            onClick={() => onClose && onClose()}
            style={{
              background: "transparent", border: "none",
              padding: 4, cursor: "pointer", color: "#475569",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {phase === "loading" ? (
          <div data-testid="pay-loading" style={{ padding: "40px 0", textAlign: "center", color: "#64748B" }}>
            <Loader2 className="animate-spin" size={24} />
            <div style={{ marginTop: 12, fontSize: 13 }}>Preparing secure checkout…</div>
          </div>
        ) : null}

        {phase === "error" ? (
          <div data-testid="pay-error" style={{
            padding: 16, borderRadius: 10,
            background: "#FEE2E2", color: "#991B1B",
            fontSize: 14, display: "flex", gap: 8, alignItems: "flex-start",
          }}>
            <AlertTriangle size={16} /> {error}
          </div>
        ) : null}

        {phase === "ready" && stripePromise && clientSecret ? (
          <Elements stripe={stripePromise} options={elementsOptions}>
            <InnerForm
              amountCents={amountCents}
              currency={currency}
              onSuccess={(pi) => { onSuccess && onSuccess(pi); }}
              onError={() => {}}
            />
          </Elements>
        ) : null}
      </div>
    </div>
  );
}
