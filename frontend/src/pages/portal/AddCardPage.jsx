/**
 * Phase 12 · Feb 2026 — Public magic-link "Add card" page.
 *
 * Route: ``/portal/add-card?token=<jwt>``. Anonymous / public — the
 * JWT is the only credential. Backend endpoints hit:
 *
 *   GET  /api/customers/add-card/:token             → context
 *   POST /api/customers/add-card/:token/setup-intent → client_secret
 *
 * The token embeds ``customer_id``, ``tenant_id`` and a 30-day exp.
 * We NEVER reveal full PII from the token payload — the /add-card
 * context endpoint masks the customer name and only exposes tenant
 * display metadata.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  useElements,
  useStripe,
  PaymentElement,
} from "@stripe/react-stripe-js";
import { CreditCard, Lock, CheckCircle2, AlertTriangle } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL || "";

async function apiPublic(path, opts = {}) {
  const res = await fetch(`${BASE}/api${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
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


function useQueryToken() {
  const loc = useLocation();
  return useMemo(() => {
    const p = new URLSearchParams(loc.search);
    return p.get("token") || "";
  }, [loc.search]);
}


function SetupForm({ tenantName, supportPhone, customerNameMasked,
                     clientSecret, onDone }) {
  const stripe = useStripe();
  const elements = useElements();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setBusy(true);
    setErr("");
    try {
      const { error } = await stripe.confirmSetup({
        elements,
        confirmParams: {
          return_url: window.location.origin + "/portal/add-card/success",
        },
        redirect: "if_required",
      });
      if (error) {
        setErr(error.message || "Could not save the card.");
        return;
      }
      onDone && onDone();
    } catch (e2) {
      setErr(e2?.message || "Unexpected error saving card.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="add-card-setup-form">
      <PaymentElement options={{ layout: "tabs" }} />
      {err ? (
        <div
          data-testid="add-card-error"
          className="mt-3 text-xs px-3 py-2 rounded-lg"
          style={{ backgroundColor: "#FEF2F2", color: "#B91C1C" }}
        >
          <AlertTriangle size={12} className="inline mr-1" /> {err}
        </div>
      ) : null}
      <button
        type="submit"
        disabled={busy}
        data-testid="add-card-submit"
        className="mt-4 w-full py-3 rounded-xl text-white text-sm font-semibold flex items-center justify-center gap-2"
        style={{ backgroundColor: "#0F172A", opacity: busy ? 0.6 : 1 }}
      >
        <Lock size={13} />
        {busy ? "Saving securely…" : "Save card"}
      </button>
      <div className="mt-3 text-[11px] text-zinc-500 text-center">
        Secured by Stripe. {tenantName ? `${tenantName} never sees your card details.` : ""}
        {supportPhone ? ` Questions? Call ${supportPhone}.` : ""}
      </div>
    </form>
  );
}


export default function AddCardPage() {
  const token = useQueryToken();
  const [ctx, setCtx] = useState(null);
  const [stripePromise, setStripePromise] = useState(null);
  const [clientSecret, setClientSecret] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("Missing token. Please use the link from your email or text.");
      return;
    }
    (async () => {
      try {
        const context = await apiPublic(`/customers/add-card/${token}`);
        setCtx(context);
        if (!context.stripe_publishable_key) {
          throw new Error("Payments unavailable — publishable key not configured.");
        }
        setStripePromise(loadStripe(context.stripe_publishable_key));
        const setup = await apiPublic(
          `/customers/add-card/${token}/setup-intent`,
          { method: "POST", body: "{}" },
        );
        if (!setup?.client_secret) {
          throw new Error("Could not start the card save flow.");
        }
        setClientSecret(setup.client_secret);
      } catch (e) {
        setError(e?.message || "This link is invalid or expired.");
      }
    })();
  }, [token]);

  if (done) {
    return (
      <div className="min-h-screen bg-zinc-50 flex items-center justify-center p-4"
            data-testid="add-card-success">
        <div className="max-w-md w-full bg-white rounded-2xl p-8 text-center">
          <div className="w-14 h-14 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-4">
            <CheckCircle2 size={28} color="#059669" />
          </div>
          <div className="text-lg font-semibold text-zinc-900 mb-1">
            Thanks! Your card is saved securely.
          </div>
          <div className="text-sm text-zinc-500 mb-3">
            {ctx?.tenant_name ? `${ctx.tenant_name} will use it for future service.` : ""}
          </div>
          <div className="text-[11px] text-zinc-400">
            Reply STOP to opt out of texts.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-50 flex items-center justify-center p-4"
          data-testid="add-card-page">
      <div className="max-w-md w-full bg-white rounded-2xl p-6 shadow-sm">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-zinc-100 flex items-center justify-center">
            <CreditCard size={18} color="#0F172A" />
          </div>
          <div className="min-w-0">
            <div className="text-lg font-semibold text-zinc-900 truncate">
              {ctx?.tenant_name || "Add your card"}
            </div>
            <div className="text-xs text-zinc-500">
              {ctx?.customer_name_masked
                ? `For ${ctx.customer_name_masked}`
                : "Save a card securely with Stripe."}
            </div>
          </div>
        </div>

        {error ? (
          <div
            data-testid="add-card-init-error"
            className="text-sm px-3 py-3 rounded-lg"
            style={{ backgroundColor: "#FEF2F2", color: "#B91C1C" }}
          >
            <AlertTriangle size={14} className="inline mr-1" /> {error}
          </div>
        ) : !clientSecret || !stripePromise ? (
          <div className="text-sm text-zinc-500 py-10 text-center">
            Loading secure form…
          </div>
        ) : (
          <Elements key={clientSecret} stripe={stripePromise}
                     options={{ clientSecret, appearance: { theme: "stripe" } }}>
            <SetupForm
              tenantName={ctx?.tenant_name}
              supportPhone={ctx?.tenant_support_phone}
              customerNameMasked={ctx?.customer_name_masked}
              clientSecret={clientSecret}
              onDone={() => setDone(true)}
            />
          </Elements>
        )}
      </div>
    </div>
  );
}
