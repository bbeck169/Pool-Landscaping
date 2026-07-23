/**
 * Phase 10 · Feb 2026 — Reusable "Have a promo code?" input.
 *
 * Drop-in for both the authenticated invoice detail viewer AND the
 * public magic-link ``/pay/invoice/:id?token=...`` viewer.
 *
 * Props:
 *   invoiceId      — invoice id
 *   invoiceTotalCents
 *   magicToken     — optional; when set, passed as ?token=<...> on validate
 *   onChange({promo_code_id, code, apply_to, discount_cents, effective_total_cents})
 *
 * Server always re-validates on ``create-payment-intent`` — this UI is
 * strictly display + a hint to attach ``promo_code_id`` in the intent
 * body. The client-computed discount is never trusted for charging.
 */
import React, { useState } from "react";
import { X as XIcon, Tag, AlertCircle } from "lucide-react";

export default function PromoCodeInput({
  invoiceId, invoiceTotalCents, magicToken, onChange,
}) {
  const [expanded, setExpanded] = useState(false);
  const [code, setCode] = useState("");
  const [applied, setApplied] = useState(null); // {promo_code_id, code, apply_to, effective_cents}
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function apply() {
    if (!code.trim()) return;
    setBusy(true);
    setError("");
    try {
      const base = process.env.REACT_APP_BACKEND_URL;
      const qp = magicToken ? `?token=${encodeURIComponent(magicToken)}` : "";
      const res = await fetch(`${base}/api/promo-codes/validate${qp}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(magicToken ? {} :
              { "Authorization": `Bearer ${localStorage.getItem("token") || ""}` }),
        },
        body: JSON.stringify({ code: code.trim(), invoice_id: invoiceId,
                                invoice_total_cents: invoiceTotalCents }),
      });
      const j = await res.json();
      if (!res.ok || !j.valid) {
        setError(_humanReason(j.reason));
        setApplied(null);
        onChange?.(null);
        return;
      }
      const state = {
        promo_code_id: j.promo_code_id,
        code: j.code,
        apply_to: j.apply_to,
        discount_cents: j.amount_cents_effective || 0,
        effective_total_cents: j.apply_to === "next_invoice"
          ? Math.max(0, invoiceTotalCents - (j.amount_cents_effective || 0))
          : invoiceTotalCents,
      };
      setApplied(state);
      onChange?.(state);
    } catch (e) {
      setError("Could not reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function clear() {
    setApplied(null);
    setCode("");
    setError("");
    onChange?.(null);
  }

  return (
    <div className="rounded-lg border border-zinc-200 bg-white"
         data-testid="promo-code-input">
      <button onClick={() => setExpanded((v) => !v)}
              type="button"
              data-testid="promo-code-input-toggle"
              className="w-full flex items-center gap-2 px-4 py-3 text-left text-sm text-zinc-700 hover:bg-zinc-50">
        <Tag className="w-4 h-4 text-zinc-500" />
        <span>Have a promo code?</span>
        {applied && (
          <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-800"
                data-testid="promo-code-input-applied-pill">
            Applied: {applied.code}
            {applied.apply_to === "next_invoice"
              ? ` (−$${(applied.discount_cents/100).toFixed(2)})`
              : ` (+$${(applied.discount_cents/100).toFixed(2)} credit)`}
          </span>
        )}
      </button>
      {(expanded || applied) && (
        <div className="px-4 pb-3 space-y-2">
          {applied ? (
            <div className="flex items-center justify-between rounded-lg bg-green-50 border border-green-200 px-3 py-2 text-sm">
              <div>
                <div className="font-medium text-green-800">
                  {applied.apply_to === "next_invoice"
                    ? `Applied: ${applied.code} (−$${(applied.discount_cents/100).toFixed(2)})`
                    : `Applied: ${applied.code} (+$${(applied.discount_cents/100).toFixed(2)} credit — added after payment)`}
                </div>
                {applied.apply_to === "account_credit" && (
                  <div className="text-xs text-green-700 mt-0.5">
                    This code adds credit to your account — it won't reduce today's invoice total.
                  </div>
                )}
              </div>
              <button onClick={clear}
                      data-testid="promo-code-input-clear"
                      className="p-1 rounded hover:bg-green-100 text-green-700">
                <XIcon className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <input value={code}
                        onChange={(e) => { setCode(e.target.value.toUpperCase()); setError(""); }}
                        placeholder="Enter code"
                        data-testid="promo-code-input-code"
                        className="flex-1 px-3 py-2 rounded-lg border border-zinc-200 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-zinc-300" />
                <button onClick={apply}
                        disabled={!code.trim() || busy}
                        data-testid="promo-code-input-apply"
                        className="px-3 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50">
                  {busy ? "Checking…" : "Apply"}
                </button>
              </div>
              {error && (
                <div className="flex items-center gap-1 text-xs text-red-600"
                     data-testid="promo-code-input-error">
                  <AlertCircle className="w-3 h-3" />
                  {error}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}


function _humanReason(reason) {
  switch (reason) {
    case "not_found": return "That code isn't valid.";
    case "inactive":  return "That code has been disabled.";
    case "expired":   return "That code has expired.";
    case "max_uses_reached": return "That code has reached its usage limit.";
    case "already_applied_to_invoice": return "That code is already applied to this invoice.";
    default:          return "That code can't be applied.";
  }
}
