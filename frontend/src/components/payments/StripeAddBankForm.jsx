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
 * K43 · Feb-2026 — the backend ``create_setup_intent`` helper now
 * always passes ``payment_method_options.us_bank_account.verification_method
 * = "instant"`` + ``financial_connections.permissions = ["payment_method",
 * "balances"]`` when the SetupIntent covers ``us_bank_account``.  That
 * upgrades the PaymentElement below into a Financial-Connections-first
 * flow — the resulting PaymentMethod is returned in ``verified`` state
 * so K38 bulk-charge and autobilling can dispatch it immediately.
 * Stripe's own Element renders a subtle "Enter bank details manually"
 * fallback inside the FC modal when the customer's bank isn't reachable
 * via FC — those PMs land in ``pending_microdeposit`` state and are
 * cleared by the admin via the K43 verify-microdeposits action.
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


function InnerAchForm({ apiBase, authToken, onSuccess, onCancel,
                            attachPath, buildAttachBody, adaptAttachResponse }) {
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
      const res = await fetch(`${apiBase}${attachPath}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(buildAttachBody(paymentMethodId)),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErrorMsg(json.detail || "Failed to save bank account.");
        setSubmitting(false);
        return;
      }
      const pm = adaptAttachResponse(json);
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
  // Feb-2026 · Backlog Item 6 — see the sibling
  // StripeAddCardForm for the ``pubKeyLoading`` contract.
  pubKeyLoading = undefined,
  // B1 · Feb-2026 — Admin ACH parity dual-mode.  When ``customerId``
  // is provided the form drives the *admin* endpoints
  // (``/payments/stripe/setup-intent`` + ``/payments/stripe/attach``
  // with ``payment_method_types=["us_bank_account"]``); when omitted
  // it stays on the customer-portal endpoints unchanged.
  customerId,
}) {
  const isAdminMode = !!customerId;
  const linkSessionPath = isAdminMode
    ? "/payments/stripe/setup-intent"
    : "/customer-portal/payment-methods/ach/link-session";
  const attachPath = isAdminMode
    ? "/payments/stripe/attach"
    : "/customer-portal/payment-methods/ach/attach";
  const buildLinkSessionBody = React.useCallback(() => (isAdminMode
    ? { customer_id: customerId,
        payment_method_types: ["us_bank_account"] }
    : {}
  ), [isAdminMode, customerId]);
  const buildAttachBody = (paymentMethodId) => (isAdminMode
    ? { customer_id: customerId,
        payment_method_id: paymentMethodId,
        set_default: false }
    : { payment_method_id: paymentMethodId }
  );
  const adaptAttachResponse = (json) => (isAdminMode
    ? json                       // admin attach returns the mirror row directly
    : (json.payment_method || {}) // portal wraps under `.payment_method`
  );
  const [clientSecret, setClientSecret] = useState("");
  const [loadingSecret, setLoadingSecret] = useState(true);
  const [bootError, setBootError] = useState("");
  const [autoLoadingElapsed, setAutoLoadingElapsed] = useState(false);
  useEffect(() => {
    if (publishableKey) return;
    const t = setTimeout(() => setAutoLoadingElapsed(true), 6000);
    return () => clearTimeout(t);
  }, [publishableKey]);
  const _effectivePubKeyLoading = pubKeyLoading !== undefined
    ? pubKeyLoading
    : (!publishableKey && !autoLoadingElapsed);

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
        const res = await fetch(`${apiBase}${linkSessionPath}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify(buildLinkSessionBody()),
        });
        const json = await res.json().catch(() => ({}));
        // Admin endpoint doesn't wrap with an ``ok`` flag — it returns
        // the SetupIntent envelope directly with ``client_secret``.
        // Portal endpoint wraps with ``{ok, client_secret, ...}``.  We
        // accept both: !res.ok OR (portal shape without ``ok``).
        const portalWrapFailed =
          !isAdminMode && json?.ok === false;
        if (!res.ok || portalWrapFailed) {
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
  }, [apiBase, authToken, linkSessionPath, customerId, isAdminMode, buildLinkSessionBody]);

  if (!publishableKey) {
    if (_effectivePubKeyLoading) {
      return (
        <Card data-testid="stripe-add-bank-panel">
          <CardHeader>
            <CardTitle>{title}</CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className="text-sm text-slate-500 inline-flex items-center gap-2"
              data-testid="stripe-add-bank-loading-pubkey"
            >
              <span
                className="inline-block w-4 h-4 rounded-full border-2 border-slate-300 border-t-slate-600 animate-spin"
                aria-hidden
              />
              Loading payment form…
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
          <div
            className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700 flex items-start gap-2"
            data-testid="stripe-add-bank-not-configured"
            role="status"
          >
            <span aria-hidden className="mt-0.5">ⓘ</span>
            <div>
              <div className="font-semibold text-slate-800 mb-0.5">
                Payment methods are temporarily unavailable
              </div>
              <div className="text-slate-600">
                Please contact support to set up card or bank payments.
              </div>
            </div>
          </div>
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
              attachPath={attachPath}
              buildAttachBody={buildAttachBody}
              adaptAttachResponse={adaptAttachResponse}
            />
          </Elements>
        ) : null}
      </CardContent>
    </Card>
  );
}
