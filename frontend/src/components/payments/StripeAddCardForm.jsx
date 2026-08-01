/**
 * Phase 14a · Feb-2026 — Reusable Stripe Elements card capture form.
 *
 * Handles the SetupIntent → confirmSetup → attach flow for either:
 *   • Self-serve (customer role): backend infers customer_id from the JWT.
 *   • Admin-on-behalf: pass ``customerId`` prop; backend accepts admin role
 *     and captures the card for that customer.
 *
 * Props:
 *   apiBase        (string, required)  — REACT_APP_BACKEND_URL + '/api'.
 *   authToken      (string, required)  — Bearer token for authed calls.
 *   customerId     (string, optional)  — required for admin capture.
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

function _InnerForm({ apiBase, authToken, customerId, onSuccess, onCancel }) {
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
      // Mirror the PM into our DB via the attach endpoint.
      const body = { payment_method_id: paymentMethodId, set_default: true };
      if (customerId) body.customer_id = customerId;
      const res = await fetch(`${apiBase}/payments/stripe/attach`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(body),
      });
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
    <form onSubmit={submit} data-testid="stripe-add-card-form" className="space-y-4">
      <PaymentElement options={{ layout: "tabs" }} />
      {errorMsg ? (
        <div
          data-testid="stripe-add-card-error"
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
            data-testid="stripe-add-card-cancel"
          >
            Cancel
          </Button>
        ) : null}
        <Button
          type="submit"
          disabled={!stripe || submitting}
          data-testid="stripe-add-card-submit"
        >
          {submitting ? "Saving…" : "Save card"}
        </Button>
      </div>
    </form>
  );
}

export default function StripeAddCardForm({
  apiBase,
  authToken,
  customerId,
  publishableKey,
  onSuccess,
  onCancel,
  title = "Add a card",
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
        const body = customerId ? { customer_id: customerId } : {};
        const res = await fetch(`${apiBase}/payments/stripe/setup-intent`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify(body),
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(json.detail || "Failed to start card capture.");
        if (!cancelled) setClientSecret(json.client_secret);
      } catch (err) {
        if (!cancelled) setBootError(String(err?.message || err));
      } finally {
        if (!cancelled) setLoadingSecret(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [apiBase, authToken, customerId]);

  if (!publishableKey) {
    return (
      <Card data-testid="stripe-add-card-panel">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-red-700">
            Stripe publishable key not configured. Set{" "}
            <code>REACT_APP_STRIPE_PUBLISHABLE_KEY_TEST</code> or{" "}
            <code>REACT_APP_STRIPE_PUBLISHABLE_KEY_LIVE</code> in the frontend
            environment.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="stripe-add-card-panel">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {loadingSecret ? (
          <p className="text-sm text-slate-500">Preparing secure card entry…</p>
        ) : bootError ? (
          <p className="text-sm text-red-700">{bootError}</p>
        ) : clientSecret && stripePromise ? (
          <Elements
            stripe={stripePromise}
            options={{ clientSecret, appearance: { theme: "stripe" } }}
          >
            <_InnerForm
              apiBase={apiBase}
              authToken={authToken}
              customerId={customerId}
              onSuccess={onSuccess}
              onCancel={onCancel}
            />
          </Elements>
        ) : null}
      </CardContent>
    </Card>
  );
}
