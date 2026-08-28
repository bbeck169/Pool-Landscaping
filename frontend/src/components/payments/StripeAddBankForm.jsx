/**
 * Feb 2026 · P0 fix — Stripe Elements ACH bank-account capture form.
 *
 * Mirrors ``StripeAddCardForm`` but drives the ACH ("us_bank_account")
 * SetupIntent flow. The previous implementation only ``console.info``-
 * logged the ``client_secret`` after fetching it and never mounted
 * ``<Elements>``, so every customer who clicked "Connect Bank Account"
 * saw a toast saying "widget will launch shortly" — and nothing
 * happened. This component fixes that end-to-end.
 *
 * Backend contract:
 *   * ``POST /customer-portal/payment-methods/ach/link-session``
 *     → ``{ok, client_secret, publishable_key, mode}``. Backend now
 *       passes ``payment_method_types=["us_bank_account"]`` to Stripe.
 *   * ``POST /customer-portal/payment-methods/ach/attach``
 *     → ``{ok, payment_method: {last4, brand, is_default, type}}``.
 *
 * Stripe surface:
 *   * ``stripe.confirmSetup`` with the ``us_bank_account`` SetupIntent
 *     drives the built-in Financial Connections OR routing/account
 *     entry UX. The choice is negotiated by Stripe based on the
 *     merchant's dashboard config; no frontend switch needed.
 *
 * Props:
 *   apiBase        (string, required)  — REACT_APP_BACKEND_URL + '/api'.
 *   authToken      (string, required)  — Bearer token for authed calls.
 *   publishableKey (string, required)  — Stripe pk_test_ or pk_live_ key.
 *   onSuccess      (fn(paymentMethodRow))
 *   onCancel       (fn())
 */
import React, { useEffect, useMemo, useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  useStripe,
  useElements,
  PaymentElement,
} from "@stripe/react-stripe-js";

import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { toast } from "sonner";


function InnerAchForm({ apiBase, authToken, onSuccess, onCancel }) {
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
        setErrorMsg(error.message || "Bank connection failed.");
        setSubmitting(false);
        return;
      }
      const paymentMethodId = setupIntent?.payment_method;
      if (!paymentMethodId) {
        setErrorMsg("Stripe did not return a payment method id.");
        setSubmitting(false);
        return;
      }
      // Persist into ``db.payment_methods`` via the shared attach path.
      const res = await fetch(
        `${apiBase}/customer-portal/payment-methods/ach/attach`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify({ payment_method_id: paymentMethodId }),
        },
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErrorMsg(json.detail || "Failed to save bank account.");
        setSubmitting(false);
        return;
      }
      const pm = json.payment_method || {};
      toast.success(
        `Bank account ending in ${pm.last4 || "••••"} saved.`,
      );
      onSuccess?.(pm);
    } catch (err) {
      setErrorMsg(String(err?.message || err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      data-testid="stripe-add-bank-form"
      className="space-y-4"
    >
      <PaymentElement options={{ layout: "tabs" }} />
      {errorMsg ? (
        <div
          data-testid="stripe-add-bank-error"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {errorMsg}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2 justify-end pt-1">
        {onCancel ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onCancel}
            disabled={submitting}
            data-testid="stripe-add-bank-cancel"
          >
            Cancel
          </Button>
        ) : null}
        <Button
          type="submit"
          disabled={submitting || !stripe || !elements}
          data-testid="stripe-add-bank-submit"
        >
          {submitting ? "Connecting…" : "Connect bank"}
        </Button>
      </div>
    </form>
  );
}


export default function StripeAddBankForm({
  apiBase,
  authToken,
  publishableKey,
  title = "Connect bank account",
  onSuccess,
  onCancel,
}) {
  const [clientSecret, setClientSecret] = useState("");
  const [loadingSecret, setLoadingSecret] = useState(true);
  const [bootError, setBootError] = useState("");

  const stripePromise = useMemo(() => {
    if (!publishableKey) return null;
    return loadStripe(publishableKey);
  }, [publishableKey]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoadingSecret(true);
      setBootError("");
      try {
        const res = await fetch(
          `${apiBase}/customer-portal/payment-methods/ach/link-session`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${authToken}`,
            },
            body: JSON.stringify({}),
          },
        );
        const json = await res.json().catch(() => ({}));
        if (!res.ok || !json?.ok) {
          throw new Error(
            json.detail
            || (json?.reason === "stripe_not_configured"
                ? "Bank verification is temporarily unavailable — payment processing is not configured on this account yet."
                : "Failed to start bank connection."),
          );
        }
        if (!cancelled) setClientSecret(json.client_secret);
      } catch (err) {
        if (!cancelled) setBootError(String(err?.message || err));
      } finally {
        if (!cancelled) setLoadingSecret(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [apiBase, authToken]);

  if (!publishableKey) {
    return (
      <Card data-testid="stripe-add-bank-panel">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-red-700">
            Stripe publishable key not configured on the server.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="stripe-add-bank-panel">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {loadingSecret ? (
          <p className="text-sm text-slate-500">Preparing secure bank connection…</p>
        ) : bootError ? (
          <p
            className="text-sm text-red-700"
            data-testid="stripe-add-bank-boot-error"
          >
            {bootError}
          </p>
        ) : clientSecret && stripePromise ? (
          <Elements
            stripe={stripePromise}
            options={{ clientSecret, appearance: { theme: "stripe" } }}
          >
            <InnerAchForm
              apiBase={apiBase}
              authToken={authToken}
              onSuccess={onSuccess}
              onCancel={onCancel}
            />
          </Elements>
        ) : null}
      </CardContent>
    </Card>
  );
}
