/**
 * Phase 47c · Feb-2026 — RESTORED public "Add card" magic-link page.
 *
 * Previously killed in Phase LZ4 (Feb-2026) when the card-on-file
 * capture surface was redirected through the Lumino/Zapier bridge.
 * User has since directed that ALL payment + add-card-on-file flows
 * MUST route through Stripe directly. This page owns the browser
 * half of that flow for the public magic-link (no auth) trigger.
 *
 * URL:  /portal/add-card?token=<JWT>
 *
 * Backend contract (see backend/routers/customers.py):
 *   GET  /api/customers/add-card/{token}                — context (masked name, tenant, pk)
 *   POST /api/customers/add-card/{token}/setup-intent    — client_secret + pk
 *   POST /api/customers/add-card/{token}/attach         — mirror PM into db.payment_methods
 *
 * Auth: NONE. The JWT token is the sole authority; verify happens
 * server-side on every call via ``decode_add_card_token``.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  useStripe,
  useElements,
  PaymentElement,
} from "@stripe/react-stripe-js";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import BrandLogo from "@/components/branding/BrandLogo";

const _API_BASE = `${process.env.REACT_APP_BACKEND_URL}/api`;

function useToken() {
  const { search } = useLocation();
  return useMemo(() => new URLSearchParams(search).get("token") || "", [search]);
}

function InnerForm({ token, onSuccess }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const submit = async (evt) => {
    evt?.preventDefault?.();
    if (!stripe || !elements) return;
    setErrorMsg("");
    setSubmitting(true);
    try {
      const { error, setupIntent } = await stripe.confirmSetup({
        elements,
        confirmParams: {
          return_url: `${window.location.origin}${window.location.pathname}?stripe=return`,
        },
        redirect: "if_required",
      });
      if (error) {
        setErrorMsg(error.message || "Card capture failed.");
        setSubmitting(false);
        return;
      }
      const paymentMethodId = setupIntent?.payment_method;
      if (!paymentMethodId) {
        setErrorMsg("Stripe did not return a payment method id.");
        setSubmitting(false);
        return;
      }
      const res = await fetch(
        `${_API_BASE}/customers/add-card/${encodeURIComponent(token)}/attach`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ payment_method_id: paymentMethodId, set_default: true }),
        },
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErrorMsg(json.detail || "Failed to save card on file.");
        setSubmitting(false);
        return;
      }
      toast.success(`Card ending in ${json.last4 || "••••"} saved.`);
      onSuccess?.(json);
    } catch (err) {
      setErrorMsg(String(err?.message || err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="phase47c-add-card-form" className="space-y-4">
      <PaymentElement options={{ layout: "tabs" }} />
      {errorMsg ? (
        <div
          data-testid="phase47c-add-card-error"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {errorMsg}
        </div>
      ) : null}
      <div className="flex justify-end pt-1">
        <Button
          type="submit"
          disabled={!stripe || submitting}
          data-testid="phase47c-add-card-submit"
        >
          {submitting ? "Saving…" : "Save card"}
        </Button>
      </div>
    </form>
  );
}

export default function AddCardPage() {
  const token = useToken();
  const [ctx, setCtx] = useState(null);         // { tenant_name, customer_name_masked, publishable_key, ... }
  const [clientSecret, setClientSecret] = useState("");
  const [bootError, setBootError] = useState("");
  const [saved, setSaved] = useState(false);

  const stripePromise = useMemo(() => {
    const pk = ctx?.stripe_publishable_key || ctx?.publishable_key || "";
    return pk ? loadStripe(pk) : null;
  }, [ctx?.stripe_publishable_key, ctx?.publishable_key]);

  useEffect(() => {
    if (!token) {
      setBootError("Missing token in URL. Please open the link from your text message.");
      return;
    }
    let cancelled = false;
    const boot = async () => {
      try {
        const ctxRes = await fetch(
          `${_API_BASE}/customers/add-card/${encodeURIComponent(token)}`,
        );
        const ctxJson = await ctxRes.json().catch(() => ({}));
        if (!ctxRes.ok) {
          // Feb-2026 · BUG 2 — backend now returns a structured
          // ``detail`` object for the stale-link case. Prefer the
          // human ``message`` over the code so the banner reads
          // like a helpful hint, not a stack trace.
          const d = ctxJson?.detail;
          const msg = (d && typeof d === "object" && d.message)
            ? d.message
            : (typeof d === "string" ? d : "This link is no longer valid.");
          throw new Error(msg);
        }
        if (cancelled) return;
        setCtx(ctxJson);

        const siRes = await fetch(
          `${_API_BASE}/customers/add-card/${encodeURIComponent(token)}/setup-intent`,
          { method: "POST" },
        );
        const siJson = await siRes.json().catch(() => ({}));
        if (!siRes.ok) {
          throw new Error(siJson.detail || "Card capture is unavailable right now.");
        }
        if (cancelled) return;
        setClientSecret(siJson.client_secret || "");
        if (siJson.publishable_key) {
          setCtx((c) => ({ ...(c || {}), stripe_publishable_key: siJson.publishable_key }));
        }
      } catch (err) {
        if (!cancelled) setBootError(String(err?.message || err));
      }
    };
    boot();
    return () => { cancelled = true; };
  }, [token]);

  return (
    <div className="min-h-screen bg-slate-50 py-12 px-4" data-testid="phase47c-add-card-page">
      {/*
       * Phase P34 · Feb-2026 — Branded header row above the card so
       * the public "Add card" surface matches the customer-facing
       * shell used on InvoiceView + EstimateView. Uses ``BrandLogo``
       * (variant="full") which multi-tenant resolves the logo url
       * server-side via ``useTenantBrand``. The link target is
       * ``/portal/login`` (not "/") so a public no-auth visitor
       * lands on the login page instead of the role-gated app root.
       */}
      <header
        className="w-full max-w-md mx-auto mb-6 flex items-center justify-center"
        data-testid="add-card-page-brand-header"
      >
        <BrandLogo
          variant="full"
          linkTo="/portal/login"
          testId="add-card-page-brand-logo"
        />
      </header>
      {/* Phase P43 · Feb-2026 — ``w-full`` so the card fills the
          new ``max-w-5xl`` portal container on desktop while still
          capping visually via ``max-w-md`` on narrow flows. */}
      <div
        className="w-full max-w-md mx-auto"
        data-testid="phase47c-add-card-form-container"
      >
        <Card>
          <CardHeader>
            <CardTitle data-testid="phase47c-add-card-title">
              {ctx?.tenant_name ? `Add a card for ${ctx.tenant_name}` : "Add a card"}
            </CardTitle>
            {ctx?.customer_name_masked ? (
              <div className="text-sm text-slate-600" data-testid="phase47c-add-card-greeting">
                Hi {ctx.customer_name_masked}, save a card so we can bill visits automatically.
              </div>
            ) : null}
          </CardHeader>
          <CardContent>
            {bootError ? (
              <div
                data-testid="phase47c-add-card-boot-error"
                className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
              >
                {bootError}
              </div>
            ) : saved ? (
              <div
                data-testid="phase47c-add-card-success"
                className="rounded-md border border-green-300 bg-green-50 px-3 py-3 text-sm text-green-800"
              >
                Your card is on file. You can close this window.
                {ctx?.tenant_support_phone ? (
                  <div className="mt-1 text-xs">
                    Questions? Call {ctx.tenant_support_phone}.
                  </div>
                ) : null}
              </div>
            ) : !ctx || !clientSecret || !stripePromise ? (
              <p
                className="text-sm text-slate-500"
                data-testid="phase47c-add-card-loading"
              >
                Preparing secure card entry…
              </p>
            ) : (
              <Elements
                stripe={stripePromise}
                options={{ clientSecret, appearance: { theme: "stripe" } }}
              >
                <InnerForm token={token} onSuccess={() => setSaved(true)} />
              </Elements>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
