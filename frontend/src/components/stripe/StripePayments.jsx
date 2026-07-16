/**
 * Phase 53 · Stripe payment surface.
 *
 * Two flavors, both hitting the same invoice:
 *   1. <PayNowButton />       — redirects to Stripe Hosted Checkout.
 *   2. <PayInAppForm />       — inline Stripe Elements PaymentElement.
 *
 * Both invoke server-side amount lookup (no frontend-supplied amounts),
 * insert a ledger row in `stripe_payments`, and rely on webhooks +
 * status-polling for reconciliation.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { CreditCard, ExternalLink, Loader2, ShieldCheck, CircleAlert } from "lucide-react";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { api } from "@/api";
import { colors } from "@/theme";
import { getStripePromise } from "@/lib/stripe";

// ─── Hosted Checkout — one-click ────────────────────────────────────
export function PayNowButton({ invoice, onError, className }) {
  const [busy, setBusy] = useState(false);
  const [mocked, setMocked] = useState(false);

  const go = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.post("/stripe/checkout/session", {
        invoice_id: invoice.id,
        origin: window.location.origin,
      });
      if (r?.mocked) {
        setMocked(true);
        onError?.(`Stripe not configured (${r.reason || "unknown"})`);
        setBusy(false);
        return;
      }
      if (r?.url) window.location.href = r.url;
    } catch (e) {
      onError?.(e?.message || "Checkout failed");
      setBusy(false);
    }
  }, [invoice?.id, onError]);

  if (!invoice?.id) return null;
  return (
    <button
      type="button"
      onClick={go}
      disabled={busy}
      className={"inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold shadow-sm transition-opacity " + (className || "")}
      style={{ backgroundColor: colors.brand, color: "#fff", opacity: busy ? 0.6 : 1 }}
      data-testid="pay-now-button"
    >
      {busy ? <Loader2 size={14} className="animate-spin" /> : <CreditCard size={14} />}
      {mocked ? "Stripe unavailable" : busy ? "Redirecting…" : "Pay with Stripe"}
      {!busy && !mocked ? <ExternalLink size={12} /> : null}
    </button>
  );
}

// ─── Elements-based in-app card form ─────────────────────────────────
function ElementsInner({ invoice, onSuccess }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setSubmitting(true);
    setError("");
    const { error: err } = await stripe.confirmPayment({
      elements,
      confirmParams: {
        return_url: `${window.location.origin}/invoices/${invoice.id}?stripe=elements_success`,
      },
      redirect: "if_required",
    });
    if (err) {
      setError(err.message || "Payment failed");
      setSubmitting(false);
      return;
    }
    setSubmitting(false);
    onSuccess?.();
  };

  return (
    <form onSubmit={submit} className="space-y-3" data-testid="pay-in-app-form">
      <div className="rounded-lg border p-3" style={{ borderColor: colors.border, backgroundColor: colors.surface }}>
        <PaymentElement options={{ layout: "tabs" }} />
      </div>
      {error ? (
        <div className="text-xs font-semibold inline-flex items-center gap-1" style={{ color: "#DC2626" }} data-testid="pay-in-app-error">
          <CircleAlert size={12} /> {error}
        </div>
      ) : null}
      <div className="flex items-center justify-between">
        <div className="text-[11px] inline-flex items-center gap-1" style={{ color: colors.muted }}>
          <ShieldCheck size={12} /> Payment secured by Stripe
        </div>
        <button
          type="submit"
          disabled={submitting || !stripe}
          className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold shadow-sm"
          style={{ backgroundColor: colors.brand, color: "#fff", opacity: submitting ? 0.6 : 1 }}
          data-testid="pay-in-app-submit"
        >
          {submitting ? <Loader2 size={14} className="animate-spin" /> : <CreditCard size={14} />}
          {submitting ? "Charging…" : "Pay now"}
        </button>
      </div>
    </form>
  );
}

export function PayInAppForm({ invoice, onSuccess }) {
  const [clientSecret, setClientSecret] = useState("");
  const [amountCents, setAmountCents] = useState(0);
  const [unavailable, setUnavailable] = useState("");
  const stripePromise = useMemo(() => getStripePromise(), []);

  useEffect(() => {
    if (!invoice?.id) return;
    (async () => {
      try {
        const r = await api.post("/stripe/payment-intent", { invoice_id: invoice.id });
        if (r?.mocked) { setUnavailable(r.reason || "unavailable"); return; }
        if (r?.client_secret) {
          setClientSecret(r.client_secret);
          setAmountCents(Number(r.amount_cents || 0));
        }
      } catch (e) {
        setUnavailable(e?.message || "unavailable");
      }
    })();
  }, [invoice?.id]);

  if (unavailable) {
    return (
      <div className="rounded-lg p-3 text-xs" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }} data-testid="pay-in-app-unavailable">
        Stripe not configured ({unavailable}).
      </div>
    );
  }
  if (!clientSecret) {
    return (
      <div className="rounded-lg p-4 text-sm inline-flex items-center gap-2" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }} data-testid="pay-in-app-loading">
        <Loader2 size={14} className="animate-spin" /> Loading card form…
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="text-xs" style={{ color: colors.muted }}>
        Charging <span className="font-bold" style={{ color: colors.onSurface }}>${(amountCents / 100).toFixed(2)}</span>
      </div>
      <Elements stripe={stripePromise} options={{ clientSecret }}>
        <ElementsInner invoice={invoice} onSuccess={onSuccess} />
      </Elements>
    </div>
  );
}

// ─── Refund confirmation modal ───────────────────────────────────────
export function RefundButton({ payment, onRefunded, onError }) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  if (!payment?.id) return null;
  const total = Number(payment.amount_cents || 0);
  const already = Number(payment.refunded_cents || 0);
  const max = Math.max(total - already, 0);

  const submit = async () => {
    setBusy(true);
    try {
      const amtCents = amount ? Math.round(parseFloat(amount) * 100) : undefined;
      const r = await api.post("/stripe/refunds", {
        payment_id: payment.id,
        ...(amtCents ? { amount_cents: amtCents } : {}),
      });
      if (r?.mocked) onError?.(r.reason || "unavailable");
      else onRefunded?.(r);
      setOpen(false);
    } catch (e) {
      onError?.(e?.message || "Refund failed");
    }
    setBusy(false);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-semibold"
        style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        data-testid={`refund-btn-${payment.id}`}
        disabled={max <= 0}
      >
        Refund
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-testid="refund-modal">
          <div className="w-full max-w-sm rounded-2xl p-5" style={{ backgroundColor: "#fff" }}>
            <div className="text-lg font-bold mb-1" style={{ color: colors.onSurface }}>Refund payment</div>
            <div className="text-xs mb-4" style={{ color: colors.muted }}>
              Available to refund: <span className="font-bold">${(max / 100).toFixed(2)}</span>
            </div>
            <label className="block text-xs font-semibold mb-1" style={{ color: colors.onSurface }}>
              Amount (leave blank for full refund)
            </label>
            <input
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              max={(max / 100).toFixed(2)}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={(max / 100).toFixed(2)}
              className="w-full rounded-lg px-3 py-2 text-sm border"
              style={{ borderColor: colors.border }}
              data-testid="refund-amount"
            />
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="px-3 py-2 rounded-lg text-sm font-semibold"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="refund-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={busy}
                className="px-3 py-2 rounded-lg text-sm font-semibold"
                style={{ backgroundColor: "#DC2626", color: "#fff", opacity: busy ? 0.6 : 1 }}
                data-testid="refund-confirm"
              >
                {busy ? "Refunding…" : "Confirm refund"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

// ─── Post-checkout status listener (mounts on the invoice page) ─────
export function StripeCheckoutReturn({ onPaid }) {
  useEffect(() => {
    const url = new URL(window.location.href);
    const sessId = url.searchParams.get("session_id");
    const flag = url.searchParams.get("stripe");
    if (!sessId || flag !== "success") return;
    let cancelled = false;
    let attempts = 0;
    const poll = async () => {
      if (cancelled || attempts >= 5) return;
      attempts += 1;
      try {
        const r = await api.get(`/stripe/checkout/status/${sessId}`);
        if (r?.payment_status === "paid") { onPaid?.(r); return; }
      } catch { /* keep polling */ }
      setTimeout(poll, 2000);
    };
    poll();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}
