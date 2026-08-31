/**
 * Phase B4 · Feb-2026 — Subscriptions panel for the customer detail
 * page. Lists per-customer subscriptions with create / edit / cancel
 * modals. Owner + admin + super_admin can mutate; techs + customers
 * see the read-only list (the backend gate 403s any write attempt).
 */
import React, { useCallback, useEffect, useState } from "react";
import { Plus, Pencil, XCircle, RefreshCw } from "lucide-react";
import { api } from "../../api";
import { Button, Chip, Modal, Skeleton, EmptyState, Toast }
  from "../../components/ui-kit";


const STATUS_TONE = {
  active: "success",
  trialing: "info",
  past_due: "warning",
  unpaid: "warning",
  canceled: "neutral",
  incomplete: "warning",
  incomplete_expired: "neutral",
  paused: "neutral",
};


function _money(cents, currency = "usd") {
  if (cents == null) return "";
  const n = Number(cents) / 100;
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: (currency || "usd").toUpperCase(),
    minimumFractionDigits: 0, maximumFractionDigits: 2,
  }).format(n);
}


function _priceLabel(price) {
  if (!price) return "";
  const money = _money(price.unit_amount, price.currency);
  const interval = price.recurring?.interval || "";
  const suffix = interval ? `/${interval}` : "";
  const nick = price.nickname || price.product_name || price.id;
  return `${nick} · ${money}${suffix}`;
}


function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined,
      { year: "numeric", month: "short", day: "numeric" });
  } catch { return "—"; }
}


export default function SubscriptionsPanel({ customerId, canWrite = true }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editRow, setEditRow] = useState(null);
  const [cancelRow, setCancelRow] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get(`/subscriptions?customer_id=${customerId}`);
      setRows(res?.rows || []);
      setTotal(res?.total || 0);
    } catch (e) {
      setToast({ tone: "error", message: e?.message || "Load failed" });
    } finally { setLoading(false); }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4" data-testid="subscriptions-panel">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold" data-testid="subscriptions-title">
            Subscriptions
          </h2>
          <p className="text-sm text-muted-foreground">
            {total} subscription{total === 1 ? "" : "s"} on file.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={load}
                    testid="subscriptions-refresh">
            <RefreshCw size={14} /> Refresh
          </Button>
          {canWrite ? (
            <Button variant="primary" onClick={() => setCreateOpen(true)}
                      testid="subscriptions-create-btn">
              <Plus size={14} /> Create subscription
            </Button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="space-y-2"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
      ) : rows.length === 0 ? (
        <div data-testid="subscriptions-empty">
          <EmptyState
            title="No subscriptions yet"
            hint="Create the first subscription to charge this customer on a recurring basis."
          />
        </div>
      ) : (
        <div className="overflow-x-auto" data-testid="subscriptions-list">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-2 pr-4">Plan</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Qty</th>
                <th className="py-2 pr-4">Current period end</th>
                <th className="py-2 pr-4">Auto-cancel?</th>
                {canWrite ? <th className="py-2 pr-4 text-right">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.stripe_subscription_id}
                     className="border-t"
                     data-testid={`subscriptions-row-${r.stripe_subscription_id}`}>
                  <td className="py-2 pr-4">
                    {/* Feb-2026 follow-up · price enrichment — prefer
                        the pre-computed humanised label; fall back to
                        the raw price_id + a subtle resolver hint for
                        rows the backfill hasn't caught yet. */}
                    {r.formatted_plan_label ? (
                      <span data-testid={`subscriptions-row-${r.stripe_subscription_id}-plan`}>
                        {r.formatted_plan_label}
                      </span>
                    ) : (
                      <span className="font-mono text-xs"
                            data-testid={`subscriptions-row-${r.stripe_subscription_id}-plan-fallback`}>
                        {r.price_id} <em className="text-muted-foreground not-italic">· resolving…</em>
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <Chip label={r.status || "unknown"}
                          tone={STATUS_TONE[r.status] || "neutral"} />
                  </td>
                  <td className="py-2 pr-4">{r.quantity ?? 1}</td>
                  <td className="py-2 pr-4">{_fmtDate(r.current_period_end)}</td>
                  <td className="py-2 pr-4">
                    {r.cancel_at_period_end ? (
                      <span className="text-amber-600 font-semibold"
                             data-testid={`subscriptions-row-${r.stripe_subscription_id}-autocancel`}>
                        Yes
                      </span>
                    ) : "No"}
                  </td>
                  {canWrite ? (
                    <td className="py-2 pr-4 text-right space-x-2">
                      <Button variant="ghost"
                                onClick={() => setEditRow(r)}
                                testid={`subscriptions-row-${r.stripe_subscription_id}-edit`}>
                        <Pencil size={12} /> Edit
                      </Button>
                      <Button variant="ghost"
                                onClick={() => setCancelRow(r)}
                                testid={`subscriptions-row-${r.stripe_subscription_id}-cancel`}>
                        <XCircle size={12} /> Cancel
                      </Button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen ? (
        <SubscriptionCreateModal
          customerId={customerId}
          onClose={() => setCreateOpen(false)}
          onDone={async (msg) => {
            setCreateOpen(false);
            setToast({ tone: "success", message: msg });
            await load();
          }}
        />
      ) : null}

      {editRow ? (
        <SubscriptionEditModal
          row={editRow}
          onClose={() => setEditRow(null)}
          onDone={async (msg) => {
            setEditRow(null);
            setToast({ tone: "success", message: msg });
            await load();
          }}
        />
      ) : null}

      {cancelRow ? (
        <SubscriptionCancelModal
          row={cancelRow}
          onClose={() => setCancelRow(null)}
          onDone={async (msg) => {
            setCancelRow(null);
            setToast({ tone: "success", message: msg });
            await load();
          }}
        />
      ) : null}

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════
// SubscriptionCreateModal — used by SubscriptionsPanel.
// ══════════════════════════════════════════════════════════════════
export function SubscriptionCreateModal({ customerId, onClose, onDone }) {
  const [prices, setPrices] = useState([]);
  const [pms, setPms] = useState([]);
  const [priceId, setPriceId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [pmId, setPmId] = useState("");
  const [trialDays, setTrialDays] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [priceRes, pmRes] = await Promise.all([
          api.get("/subscriptions/prices"),
          api.get(`/payment-methods/${customerId}`).catch(() => null),
        ]);
        setPrices(priceRes?.rows || []);
        setPms(pmRes?.payment_methods || pmRes?.rows || pmRes || []);
        if ((priceRes?.rows || [])[0]) setPriceId(priceRes.rows[0].id);
      } catch (e) { setErr(e?.message || "Failed to load form data"); }
    })();
  }, [customerId]);

  const canSubmit = priceId && !busy;

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await api.post("/subscriptions", {
        customer_id: customerId,
        price_id: priceId,
        quantity: Number(quantity) || 1,
        payment_method_id: pmId || null,
        trial_days: Number(trialDays) || 0,
      });
      onDone?.("Subscription created");
    } catch (e) {
      setErr(e?.message || "Create failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Create subscription"
      testid="subscriptions-create-modal"
      footer={
        <div className="flex items-center gap-2 justify-end">
          <Button variant="ghost" onClick={onClose}
                    testid="subscriptions-create-cancel">Cancel</Button>
          <Button variant="primary" disabled={!canSubmit} onClick={submit}
                    testid="subscriptions-create-submit">
            {busy ? "Creating…" : "Create subscription"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <label className="block text-sm">
          <div className="mb-1 font-semibold">Plan</div>
          {prices.length === 0 ? (
            <div
              className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground"
              data-testid="subscriptions-create-empty-plans"
            >
              No recurring plans configured in Stripe. Add a recurring price in
              your Stripe Dashboard to enable subscriptions.
            </div>
          ) : (
            <select
              value={priceId}
              onChange={(e) => setPriceId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              data-testid="subscriptions-create-price"
            >
              <option value="">Select a plan…</option>
              {prices.map((p) => (
                <option key={p.id} value={p.id}>{_priceLabel(p)}</option>
              ))}
            </select>
          )}
        </label>
        <label className="block text-sm">
          <div className="mb-1 font-semibold">Quantity</div>
          <input
            type="number" min={1}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border text-sm"
            data-testid="subscriptions-create-quantity"
          />
        </label>
        <label className="block text-sm">
          <div className="mb-1 font-semibold">Payment method</div>
          <select
            value={pmId}
            onChange={(e) => setPmId(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border text-sm"
            data-testid="subscriptions-create-pm"
          >
            <option value="">Use customer default</option>
            {pms.map((pm) => (
              <option key={pm.provider_payment_method_id || pm.id}
                       value={pm.provider_payment_method_id || pm.id}>
                {pm.card ? `Card •••• ${pm.card.last4}` : pm.us_bank_account
                  ? `ACH ${pm.us_bank_account.bank_name || ""} •••• ${pm.us_bank_account.last4}`
                  : (pm.provider_payment_method_id || pm.id)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <div className="mb-1 font-semibold">Trial days (optional)</div>
          <input
            type="number" min={0} max={365}
            value={trialDays}
            onChange={(e) => setTrialDays(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border text-sm"
            data-testid="subscriptions-create-trial"
          />
        </label>
        {err ? (
          <div className="text-sm text-red-600"
                data-testid="subscriptions-create-error">{err}</div>
        ) : null}
      </div>
    </Modal>
  );
}


// ══════════════════════════════════════════════════════════════════
// SubscriptionEditModal — quantity / cancel-at-period-end toggle.
// ══════════════════════════════════════════════════════════════════
export function SubscriptionEditModal({ row, onClose, onDone }) {
  const [quantity, setQuantity] = useState(row?.quantity ?? 1);
  const [cancelAtEnd, setCancelAtEnd] = useState(!!row?.cancel_at_period_end);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await api.patch(`/subscriptions/${row.stripe_subscription_id}`, {
        quantity: Number(quantity) || 1,
        cancel_at_period_end: !!cancelAtEnd,
      });
      onDone?.("Subscription updated");
    } catch (e) {
      setErr(e?.message || "Update failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit subscription"
      testid="subscriptions-edit-modal"
      footer={
        <div className="flex items-center gap-2 justify-end">
          <Button variant="ghost" onClick={onClose}
                    testid="subscriptions-edit-cancel">Cancel</Button>
          <Button variant="primary" disabled={busy} onClick={submit}
                    testid="subscriptions-edit-submit">
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <label className="block text-sm">
          <div className="mb-1 font-semibold">Quantity</div>
          <input
            type="number" min={1}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border text-sm"
            data-testid="subscriptions-edit-quantity"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={cancelAtEnd}
            onChange={(e) => setCancelAtEnd(e.target.checked)}
            data-testid="subscriptions-edit-cancel-at-end"
          />
          <span>Cancel at end of current billing period</span>
        </label>
        {err ? (
          <div className="text-sm text-red-600"
                data-testid="subscriptions-edit-error">{err}</div>
        ) : null}
      </div>
    </Modal>
  );
}


// ══════════════════════════════════════════════════════════════════
// SubscriptionCancelModal — radio choice, single-click confirm.
// ══════════════════════════════════════════════════════════════════
export function SubscriptionCancelModal({ row, onClose, onDone }) {
  const [mode, setMode] = useState("at_period_end");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await api.delete(`/subscriptions/${row.stripe_subscription_id}?mode=${mode}`);
      onDone?.(mode === "immediate"
        ? "Subscription canceled immediately"
        : "Subscription set to cancel at period end");
    } catch (e) {
      setErr(e?.message || "Cancel failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Cancel subscription"
      testid="subscriptions-cancel-modal"
      footer={
        <div className="flex items-center gap-2 justify-end">
          <Button variant="ghost" onClick={onClose}
                    testid="subscriptions-cancel-close">Keep subscription</Button>
          <Button variant="danger" disabled={busy} onClick={submit}
                    testid="subscriptions-cancel-submit">
            {busy ? "Canceling…" : mode === "immediate"
              ? "Cancel immediately" : "Cancel at period end"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <p className="text-sm">Choose when this subscription should stop billing.</p>
        <div className="space-y-2">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio" name="cancel-mode" value="at_period_end"
              checked={mode === "at_period_end"}
              onChange={() => setMode("at_period_end")}
              className="mt-1"
              data-testid="subscriptions-cancel-mode-period-end"
            />
            <div>
              <div className="font-semibold">Cancel at end of billing period (recommended)</div>
              <div className="text-muted-foreground">
                The customer keeps access until the current period ends;
                no refund. Reversible until the period ends.
              </div>
            </div>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio" name="cancel-mode" value="immediate"
              checked={mode === "immediate"}
              onChange={() => setMode("immediate")}
              className="mt-1"
              data-testid="subscriptions-cancel-mode-immediate"
            />
            <div>
              <div className="font-semibold">Cancel immediately</div>
              <div className="text-muted-foreground">
                Ends billing right now. No prorated refund is issued —
                use the Stripe dashboard if a refund is required.
              </div>
            </div>
          </label>
        </div>
        {err ? (
          <div className="text-sm text-red-600"
                data-testid="subscriptions-cancel-error">{err}</div>
        ) : null}
      </div>
    </Modal>
  );
}
