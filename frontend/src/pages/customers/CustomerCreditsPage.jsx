/**
 * Phase 10 · Feb 2026 — Customer credits tab (standalone route).
 *
 * Route: /customers/:id/credits — linked from the CustomerDetail
 * page's tab strip. Balance card + paginated ledger + admin-only
 * "Adjust balance" dialog.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Plus, ArrowLeft, Save } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const SOURCE_LABEL = {
  referral_credit: "Referral", referral_reward: "Referral",
  redeemed: "Redeemed", manual: "Manual", revert: "Revert",
};

function fmtDollars(cents) { return `$${((cents || 0) / 100).toFixed(2)}`; }
function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return String(iso).slice(0, 19); }
}


export default function CustomerCreditsPage() {
  const { id } = useParams();
  return (
    <div className="min-h-screen bg-zinc-50" data-testid="customer-credits-page">
      <div className="bg-white border-b border-zinc-200">
        <div className="max-w-5xl mx-auto px-6 py-6 flex items-center gap-3">
          <Link to={`/customers/${id}`}
                className="p-2 rounded-lg hover:bg-zinc-100 text-zinc-600">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold text-zinc-900">Credits</h1>
            <p className="text-sm text-zinc-500 mt-0.5">
              Referral + manual credit ledger.
            </p>
          </div>
        </div>
      </div>
      <div className="max-w-5xl mx-auto px-6 py-6">
        <CustomerCreditsPanel customerId={id} />
      </div>
    </div>
  );
}


/**
 * Feb 2026 · Phase 10c — Reusable Credits panel.
 *
 * Rendered as the /customers/:id/credits standalone route AND embedded
 * inside the CustomerDetail "Credits" tab. Owns its own data-fetch +
 * adjust-dialog wiring so callers only pass ``customerId``.
 */
export function CustomerCreditsPanel({ customerId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [adjusting, setAdjusting] = useState(false);
  const [reversing, setReversing] = useState(null);        // ledger entry pending reverse-confirm
  const [role, setRole] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [me, credits] = await Promise.all([
        api.get("/auth/me"),
        api.get(`/customers/${customerId}/credits`),
      ]);
      setRole(me?.role || "");
      setData(credits);
    } catch (e) {
      toast.error(e.message || "Failed to load credits");
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  // Backend adjust endpoint requires role in ("admin", "super_admin") —
  // manager sees the tab (via CustomerDetail.TABS gating) but will get
  // 403 on submit. Hide the button for anyone below admin to keep UX
  // aligned with backend RBAC.
  const canAdjust = role === "admin" || role === "super_admin";

  if (loading || !data) {
    return (
      <div className="py-10 text-center text-sm text-zinc-500"
            data-testid="customer-credits-panel-loading">
        Loading credits…
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="customer-credits-panel">
      <div className="flex items-center justify-between">
        <div className="rounded-2xl bg-white border border-zinc-200 p-5 flex-1 mr-3">
          <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
            Balance
          </div>
          <div className="text-4xl font-semibold text-zinc-900"
                data-testid="customer-credits-balance">
            {data.balance_formatted}
          </div>
        </div>
        {canAdjust && (
          <button onClick={() => setAdjusting(true)}
                  data-testid="customer-credits-issue-btn"
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800">
            <Plus className="w-4 h-4" />
            Issue credit
          </button>
        )}
      </div>

      <div className="rounded-2xl bg-white border border-zinc-200 overflow-hidden">
        <div className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-200 bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
          <div className="col-span-3">Date</div>
          <div className="col-span-2">Source</div>
          <div className="col-span-2 text-right">Delta</div>
          <div className="col-span-4">Note</div>
          <div className="col-span-1 text-right">Actions</div>
        </div>
        {(data.ledger || []).length === 0 && (
          <div className="py-10 text-center text-sm text-zinc-400"
                data-testid="customer-credits-ledger-empty">
            No ledger activity yet.
          </div>
        )}
        {(data.ledger || []).map((l) => {
          const delta = l.delta_cents != null
            ? (l.delta_cents / 100)
            : (parseFloat(l.delta) || 0);
          const positive = delta >= 0;
          const isReversal = l.kind === "reversal" || l.source === "revert";
          // A row is "already reversed" if the ledger contains
          // another entry whose ``reverted_from_entry_id`` points at
          // it. Cheap client-side scan since ledger is capped at 50.
          const alreadyReverted = (data.ledger || []).some(
            (x) => x.reverted_from_entry_id === l.id
          );
          const reversable = !isReversal && !alreadyReverted && canAdjust;
          return (
            <div key={l.id || l.created_at}
                  data-testid={`customer-credits-history-row-${l.id || l.created_at}`}
                  className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-100 items-center">
              <div className="col-span-3 text-sm text-zinc-500">
                {fmtDate(l.created_at)}
              </div>
              <div className="col-span-2">
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-zinc-100 text-zinc-700">
                  {SOURCE_LABEL[l.source] || l.source}
                </span>
              </div>
              <div className={`col-span-2 text-right text-sm font-semibold ${
                positive ? "text-green-700" : "text-red-600"}`}>
                {positive ? "+" : "−"}${Math.abs(delta).toFixed(2)}
              </div>
              <div className="col-span-4 text-sm text-zinc-600 truncate">
                {l.note || l.reason || "—"}
                {l.actor_email && (
                  <span className="text-xs text-zinc-400 ml-1">
                    by {l.actor_email}
                  </span>
                )}
              </div>
              <div className="col-span-1 text-right">
                {reversable && (
                  <button
                    onClick={() => setReversing(l)}
                    data-testid={`customer-credits-reverse-${l.id}`}
                    className="text-xs px-2 py-1 rounded border border-zinc-200 text-zinc-600 hover:bg-zinc-50">
                    Reverse
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {adjusting && canAdjust && (
        <AdjustDialog
          currentBalanceCents={data.balance_cents}
          customerId={customerId}
          onClose={() => setAdjusting(false)}
          onSaved={() => { setAdjusting(false); load(); }}/>
      )}
      {reversing && canAdjust && (
        <ReverseConfirmDialog
          entry={reversing}
          customerId={customerId}
          onClose={() => setReversing(null)}
          onSaved={() => { setReversing(null); load(); }}/>
      )}
    </div>
  );
}


export function AdjustDialog({ currentBalanceCents, customerId, onClose, onSaved }) {
  const [dollars, setDollars] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const delta = parseFloat(dollars || "0") || 0;
  const deltaCents = Math.round(delta * 100);
  const nextBalance = ((currentBalanceCents || 0) + deltaCents) / 100;
  const reasonOk = reason.trim().length >= 5;
  const canSubmit = deltaCents !== 0 && reasonOk && !saving;

  async function submit() {
    setSaving(true);
    try {
      await api.post(`/customers/${customerId}/credits/adjust`, {
        delta_cents: deltaCents,
        reason: reason.trim(),
      });
      toast.success("Balance adjusted");
      onSaved();
    } catch (e) {
      const msg = e.message || "";
      if (/INSUFFICIENT_BALANCE|Cannot decrement/i.test(msg)) {
        toast.error("Insufficient balance — this adjustment would go negative.");
      } else {
        toast.error(msg || "Adjust failed");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => (!o && onClose())}>
      <DialogContent className="max-w-md"
                     data-testid="customer-credits-issue-modal">
        <DialogHeader><DialogTitle>Adjust balance</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <label className="block">
            <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
              Amount (dollars — positive OR negative)
            </div>
            <input type="number" step="0.01"
                    value={dollars}
                    onChange={(e) => setDollars(e.target.value)}
                    data-testid="customer-credits-issue-amount"
                    placeholder="e.g. 10 or -5"
                    className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
          </label>
          <label className="block">
            <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
              Reason{" "}
              {!reasonOk && reason.length > 0 && (
                <span className="text-red-500 normal-case">— min 5 chars</span>
              )}
            </div>
            <textarea rows={3}
                       value={reason}
                       onChange={(e) => setReason(e.target.value)}
                       data-testid="customer-credits-issue-note"
                       placeholder="Why is this adjustment being made?"
                       className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
          </label>
          <div className="rounded-lg bg-zinc-50 border border-zinc-200 px-3 py-2 text-sm">
            <span className="text-zinc-500">This will change the balance from </span>
            <span className="font-medium text-zinc-900">
              {fmtDollars(currentBalanceCents)}
            </span>
            <span className="text-zinc-500"> to </span>
            <span className={`font-semibold ${nextBalance < 0 ? "text-red-600" : "text-zinc-900"}`}>
              ${nextBalance.toFixed(2)}
            </span>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 rounded-lg text-sm text-zinc-700 hover:bg-zinc-100">Cancel</button>
          <button onClick={submit}
                  disabled={!canSubmit}
                  data-testid="customer-credits-issue-submit"
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50">
            <Save className="w-4 h-4" />
            {saving ? "Saving…" : "Adjust"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


/**
 * Task RR/SS Phase 2 followup · Feb 2026 — Reverse-credit confirmation
 * dialog. Calls the new
 * ``POST /customers/{cid}/credits/{entry_id}/reverse`` endpoint. Never
 * deletes the original — a compensating ledger row is inserted and the
 * original stays visible in the history for audit-trail integrity.
 */
export function ReverseConfirmDialog({ entry, customerId, onClose, onSaved }) {
  const [saving, setSaving] = useState(false);
  const [reason, setReason] = useState("");
  const dollars = ((entry?.delta_cents || 0) / 100);
  const abs = Math.abs(dollars).toFixed(2);
  const positive = dollars >= 0;
  const reasonOk = reason.trim().length >= 5;

  async function submit() {
    if (!reasonOk) return;
    setSaving(true);
    try {
      await api.post(
        `/customers/${customerId}/credits/${entry.id}/reverse`,
        { reason: reason.trim() },
      );
      toast.success("Credit reversed.");
      onSaved?.();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === "object"
        ? detail?.message
        : (detail || e?.message);
      toast.error(msg || "Reverse failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={true} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent className="max-w-md"
                     data-testid="customer-credits-reverse-confirm-modal">
        <DialogHeader>
          <DialogTitle>Reverse this credit?</DialogTitle>
        </DialogHeader>
        <div className="text-sm text-zinc-600">
          Reverse this{" "}
          <strong>{positive ? "+" : "−"}${abs}</strong>{" "}
          credit? This creates an offsetting entry — the original
          entry stays in the ledger for auditability.
        </div>
        {entry?.note && (
          <div className="rounded-lg bg-zinc-50 p-3 text-xs text-zinc-500">
            <strong>Original note:</strong> {entry.note}
          </div>
        )}
        <label className="block">
          <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1 mt-3">
            Reason{" "}
            {!reasonOk && reason.length > 0 && (
              <span className="text-red-500 normal-case">— min 5 chars</span>
            )}
          </div>
          <textarea rows={2}
                     value={reason}
                     onChange={(e) => setReason(e.target.value)}
                     data-testid="customer-credits-reverse-reason"
                     placeholder="Why is this being reversed? (audit trail — required)"
                     className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
        </label>
        <div className="flex items-center justify-end gap-2 mt-2">
          <button onClick={onClose}
                   disabled={saving}
                   className="px-4 py-2 rounded-lg text-sm text-zinc-600">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={saving || !reasonOk}
            data-testid="customer-credits-reverse-confirm-btn"
            className="px-4 py-2 rounded-lg text-sm text-white bg-red-600 hover:bg-red-700 disabled:opacity-50">
            {saving ? "Reversing…" : "Reverse credit"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

