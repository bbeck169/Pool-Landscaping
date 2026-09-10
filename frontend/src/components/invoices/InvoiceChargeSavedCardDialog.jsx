/**
 * Feb-2026 · Task 5 — Admin ``Charge on file`` confirm dialog.
 *
 * Shows the target card (default marked, or user-picked from a small
 * dropdown when multiple exist), the amount, and POSTs to
 * ``/api/invoices/{iid}/charge-saved-card``. Machine-readable error
 * codes from the backend (``authentication_required``,
 * ``card_declined``, ``payment_gateway_unavailable``) surface as
 * friendly toasts + inline copy.
 */
import React, { useMemo, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { CreditCard, X, Loader2 } from "lucide-react";


function fmt(n) {
  const v = Number(n || 0);
  return v.toFixed(2);
}


export default function InvoiceChargeSavedCardDialog({
  invoiceId, savedCards = [], amount = 0, onClose, onSuccess,
}) {
  const defaultPmId = useMemo(() => {
    const d = savedCards.find((c) => c.default) || savedCards[0];
    return d ? (d.provider_payment_method_id || d.id) : "";
  }, [savedCards]);
  const [pmId, setPmId] = useState(defaultPmId);
  const [busy, setBusy] = useState(false);
  const [errorText, setErrorText] = useState("");

  const selected = savedCards.find(
    (c) => (c.provider_payment_method_id || c.id) === pmId,
  ) || savedCards[0] || {};

  async function submit() {
    if (!pmId || busy) return;
    setBusy(true);
    setErrorText("");
    try {
      const resp = await api.post(
        `/invoices/${invoiceId}/charge-saved-card`,
        { payment_method_id: pmId },
      );
      if (resp && resp.status === "succeeded") {
        onSuccess && onSuccess(resp);
        return;
      }
      setErrorText("Charge did not complete. Try a fresh payment link.");
    } catch (e) {
      // FastAPI structured error → { detail: { error_code, message } }
      const detail = (e && e.detail) || (e && e.response && e.response.data && e.response.data.detail) || {};
      const code = detail.error_code || detail.code || "";
      const msg = detail.message || e?.message || "Charge failed.";
      setErrorText(msg);
      toast.error(msg);
      if (code === "authentication_required") {
        toast.info(
          "Send the customer a fresh payment link so they can complete 3DS.",
        );
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      data-testid="invoice-charge-saved-card-dialog"
    >
      <div
        className="bg-white rounded-lg shadow-lg w-[min(92vw,420px)] p-5"
        style={{ border: "1px solid #E5E7EB" }}
      >
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 text-base font-semibold">
            <CreditCard size={18} /> Charge on file
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
            aria-label="Close"
            data-testid="invoice-charge-saved-card-close"
          ><X size={18} /></button>
        </div>

        {savedCards.length === 0 ? (
          <div className="text-sm text-gray-500">
            No saved cards on file for this customer.
          </div>
        ) : (
          <>
            <div className="text-sm text-gray-700 mb-3">
              You're about to charge{" "}
              <b>${fmt(amount)}</b> to{" "}
              <b>
                {selected.brand}{" "}
                ···· {selected.last4}
              </b>
              {selected.exp_month && selected.exp_year ? (
                <span className="text-gray-500">
                  {" "}(exp {String(selected.exp_month).padStart(2, "0")}/
                  {String(selected.exp_year).slice(-2)})
                </span>
              ) : null}.
            </div>
            {savedCards.length > 1 ? (
              <label className="block text-xs text-gray-600 mb-1">
                Payment method
              </label>
            ) : null}
            {savedCards.length > 1 ? (
              <select
                className="w-full mb-3 px-3 py-2 border rounded"
                value={pmId}
                onChange={(e) => setPmId(e.target.value)}
                data-testid="invoice-charge-saved-card-picker"
              >
                {savedCards.map((c) => (
                  <option
                    key={c.provider_payment_method_id || c.id}
                    value={c.provider_payment_method_id || c.id}
                  >
                    {c.brand} ···· {c.last4}
                    {c.default ? "  (default)" : ""}
                  </option>
                ))}
              </select>
            ) : null}
            {errorText ? (
              <div
                className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2 mb-3"
                data-testid="invoice-charge-saved-card-error"
              >
                {errorText}
              </div>
            ) : null}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-2 text-sm rounded border border-gray-300"
                data-testid="invoice-charge-saved-card-cancel"
              >Cancel</button>
              <button
                type="button"
                onClick={submit}
                disabled={busy || !pmId}
                className="px-4 py-2 text-sm rounded bg-emerald-600 text-white disabled:opacity-60"
                data-testid="invoice-charge-saved-card-confirm"
              >
                {busy ? <Loader2 size={14} className="inline animate-spin mr-1" /> : null}
                Charge ${fmt(amount)}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
