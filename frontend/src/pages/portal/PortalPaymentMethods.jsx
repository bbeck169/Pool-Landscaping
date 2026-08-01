/**
 * Phase 14a · Feb-2026 — Customer-facing "Payment methods" portal page.
 *
 * Lets a signed-in customer add a card via Stripe Elements + view / remove
 * the cards they've saved. Uses the same reusable form as the admin panel;
 * the backend infers ``customer_id`` from the JWT so no customerId prop
 * needs to be passed.
 */
import React, { useCallback, useEffect, useState } from "react";

import StripeAddCardForm from "../../components/payments/StripeAddCardForm";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { toast } from "sonner";
// Phase 20 · Feb-2026 · Sub-item C — publishable key comes from the
// backend at request time (memoized per session) instead of the
// build-time REACT_APP_STRIPE_PUBLISHABLE_KEY env var.
import { getStripeConfig } from "@/lib/stripeConfig";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function PortalPaymentMethods() {
  const [me, setMe] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [pubKey, setPubKey] = useState("");
  const token =
    typeof window !== "undefined" ? window.localStorage.getItem("token") : "";

  useEffect(() => {
    getStripeConfig().then((c) => setPubKey(c.publishable_key || ""));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const meRes = await fetch(`${API}/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const meJson = await meRes.json().catch(() => ({}));
      if (!meRes.ok || !meJson?.customer_id) {
        setMe(meJson || null);
        setRows([]);
        return;
      }
      setMe(meJson);
      const res = await fetch(
        `${API}/payments/stripe/payment-methods/${meJson.customer_id}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const json = await res.json().catch(() => ({}));
      if (res.ok) setRows(json.payment_methods || []);
      else setRows([]);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async (pmId) => {
    if (!window.confirm("Remove this card?")) return;
    const res = await fetch(`${API}/payments/stripe/payment-methods/${pmId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast.error(json.detail || "Failed to remove card.");
      return;
    }
    toast.success("Card removed.");
    await load();
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-2xl p-6" data-testid="portal-payment-methods-page">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  if (!me?.customer_id) {
    return (
      <div className="mx-auto max-w-2xl p-6" data-testid="portal-payment-methods-page">
        <Card>
          <CardHeader>
            <CardTitle>Payment methods</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-red-700">
              Your account isn't linked to a customer record. Please contact
              support.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div
      className="mx-auto max-w-2xl space-y-4 p-6"
      data-testid="portal-payment-methods-page"
    >
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Payment methods</CardTitle>
          <Button
            size="sm"
            variant={showForm ? "ghost" : "default"}
            onClick={() => setShowForm((v) => !v)}
            data-testid="portal-toggle-add-card"
          >
            {showForm ? "Close" : "Add card"}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {rows.length === 0 ? (
            <p className="text-sm text-slate-500" data-testid="portal-no-cards-msg">
              You haven't added a card yet.
            </p>
          ) : (
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200">
              {rows.map((r) => (
                <li
                  key={r.provider_payment_method_id}
                  className="flex items-center justify-between p-3"
                  data-testid={`portal-card-row-${r.provider_payment_method_id}`}
                >
                  <div className="text-sm">
                    <div className="font-medium capitalize">
                      {r.brand || "Card"} •••• {r.last4 || "----"}
                      {r.is_default ? (
                        <span
                          className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800"
                          data-testid="portal-card-default-badge"
                        >
                          Default
                        </span>
                      ) : null}
                    </div>
                    <div className="text-xs text-slate-500">
                      exp {String(r.exp_month || "").padStart(2, "0")}/
                      {r.exp_year || "----"}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-600 hover:bg-red-50"
                    onClick={() => remove(r.provider_payment_method_id)}
                    data-testid={`portal-remove-card-${r.provider_payment_method_id}`}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}

          {showForm ? (
            <StripeAddCardForm
              apiBase={API}
              authToken={token}
              publishableKey={pubKey}
              title="Add a new card"
              onSuccess={async () => {
                setShowForm(false);
                await load();
              }}
              onCancel={() => setShowForm(false)}
            />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
