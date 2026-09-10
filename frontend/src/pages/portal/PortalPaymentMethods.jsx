/**
 * Feb-2026 · Task 5 — Portal Payment Methods page.
 *
 * Route: ``/portal/profile/payment-methods``
 *
 * Lists the customer's saved cards (from `db.payment_methods` mirror
 * via `/api/customer-portal/payment-methods`) with brand + last4 +
 * expiry, plus actions to Set as default and Remove.
 *
 * Empty state guides new customers to save a card during their next
 * invoice pay.
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CreditCard, Trash2, Star, Loader2 } from "lucide-react";
import { api } from "@/api";


export default function PortalPaymentMethods() {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState("");
  const [confirmRemoveId, setConfirmRemoveId] = useState("");

  const load = useCallback(() => {
    api.get("/customer-portal/payment-methods")
      .then((r) => {
        const cards = ((r && r.methods) || [])
          .filter((m) => m.type === "card");
        setRows(cards);
      })
      .catch(() => setRows([]));
  }, []);

  useEffect(() => { load(); }, [load]);

  const setDefault = async (pmId) => {
    setBusy(`default:${pmId}`);
    try {
      await api.patch(
        `/customer-portal/payment-methods/${encodeURIComponent(pmId)}/set-default`,
        { is_default: true },
      );
      toast.success("Default payment method updated.");
      load();
    } catch (e) {
      toast.error(e?.message || "Failed to set default.");
    } finally {
      setBusy("");
    }
  };

  const doRemove = async (pmId) => {
    setBusy(`remove:${pmId}`);
    try {
      await api.del(
        `/customer-portal/payment-methods/${encodeURIComponent(pmId)}`,
      );
      toast.success("Card removed.");
      setConfirmRemoveId("");
      load();
    } catch (e) {
      toast.error(e?.message || "Failed to remove card.");
    } finally {
      setBusy("");
    }
  };

  return (
    <div
      className="max-w-3xl mx-auto px-4 py-6"
      data-testid="portal-payment-methods-page"
    >
      <div className="flex items-center gap-3 mb-5">
        <CreditCard size={22} />
        <h1 className="text-xl font-semibold">Payment methods</h1>
      </div>

      {rows === null ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : rows.length === 0 ? (
        <div
          className="text-sm bg-gray-50 border rounded p-4"
          data-testid="portal-pm-empty-state"
        >
          No cards on file. Cards are saved automatically when you pay
          an invoice (if you leave the box checked).
        </div>
      ) : (
        <ul className="space-y-3" data-testid="portal-pm-list">
          {rows.map((c) => {
            const key = c.provider_payment_method_id || c.id;
            return (
              <li
                key={key}
                className="flex items-center justify-between rounded border p-3 bg-white"
                data-testid={`portal-pm-row-${key}`}
              >
                <div className="flex items-center gap-3">
                  <CreditCard size={18} className="text-gray-500" />
                  <div>
                    <div className="text-sm font-medium">
                      {c.brand} ···· {c.last4}
                      {c.default ? (
                        <span
                          className="ml-2 text-xs bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded"
                          data-testid={`portal-pm-default-chip-${key}`}
                        >Default</span>
                      ) : null}
                    </div>
                    {c.exp_month && c.exp_year ? (
                      <div className="text-xs text-gray-500">
                        Expires {String(c.exp_month).padStart(2, "0")}/
                        {String(c.exp_year).slice(-2)}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!c.default ? (
                    <button
                      type="button"
                      disabled={busy === `default:${key}`}
                      onClick={() => setDefault(key)}
                      className="text-xs px-2 py-1 rounded border hover:bg-gray-50 disabled:opacity-60"
                      data-testid={`customer-pm-set-default-${key}`}
                    >
                      <Star size={12} className="inline mr-1" />
                      Set as default
                    </button>
                  ) : null}
                  <button
                    type="button"
                    disabled={busy === `remove:${key}`}
                    onClick={() => setConfirmRemoveId(key)}
                    className="text-xs px-2 py-1 rounded border border-red-200 text-red-700 hover:bg-red-50 disabled:opacity-60"
                    data-testid={`customer-pm-remove-${key}`}
                  >
                    <Trash2 size={12} className="inline mr-1" />
                    Remove
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {confirmRemoveId ? (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          data-testid="portal-pm-remove-confirm-dialog"
        >
          <div className="bg-white rounded-lg shadow-lg w-[min(92vw,400px)] p-5 border">
            <div className="font-semibold mb-2">Remove this card?</div>
            <div className="text-sm text-gray-600 mb-4">
              This will detach the card from your account. You can
              always save a new one during your next invoice payment.
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmRemoveId("")}
                className="px-3 py-2 text-sm rounded border"
                data-testid="portal-pm-remove-cancel"
              >Cancel</button>
              <button
                type="button"
                disabled={busy.startsWith("remove:")}
                onClick={() => doRemove(confirmRemoveId)}
                className="px-3 py-2 text-sm rounded bg-red-600 text-white"
                data-testid="portal-pm-remove-confirm"
              >
                {busy.startsWith("remove:") ? (
                  <Loader2 size={12} className="inline animate-spin mr-1" />
                ) : null}
                Remove card
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
