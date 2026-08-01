/**
 * Phase 14b · Feb-2026 — Two-step bulk-charge modal.
 *
 * Flow:
 *   1. Mount → immediately calls `/api/invoices/bulk-charge-card-on-file` with
 *      `dry_run=true` + a client-generated UUID `idempotency_key`. Renders the
 *      per-row eligibility table with badges.
 *   2. "Confirm charge — $Y" button (only enabled once step-1 resolves) →
 *      calls the same endpoint with `dry_run=false` + the *same* key. Renders
 *      results + amounts + charge IDs. Toast summary on close.
 *
 * Props:
 *   invoiceIds  (string[])  — selected invoice IDs (must be ≤ 100).
 *   onClose     (fn(runId?))
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { X as XIcon, ChevronRight, Check, AlertTriangle } from "lucide-react";

import { Button } from "../ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function _uuid() {
  // RFC-4122 v4 without a lib.
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (
      Number(c) ^
      (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(c) / 4)))
    ).toString(16)
  );
}

const _SKIP_LABELS = {
  already_paid: { label: "Already paid", tone: "bg-slate-100 text-slate-700" },
  no_card_on_file: { label: "No card on file", tone: "bg-amber-100 text-amber-800" },
  card_expired: { label: "Card expired", tone: "bg-red-100 text-red-800" },
  zero_balance: { label: "Zero balance", tone: "bg-slate-100 text-slate-700" },
  not_found: { label: "Not found", tone: "bg-red-100 text-red-800" },
};

function _dollarsFromCents(c) {
  return `$${((c || 0) / 100).toFixed(2)}`;
}

export default function BulkChargeModal({ invoiceIds, onClose }) {
  const [key] = useState(_uuid);
  const [step, setStep] = useState("loading"); // loading | review | confirming | done | error
  const [dryRun, setDryRun] = useState(null);
  const [real, setReal] = useState(null);
  const [errMsg, setErrMsg] = useState("");
  const token =
    typeof window !== "undefined" ? window.localStorage.getItem("token") : "";

  const post = useCallback(
    async (dry) => {
      const res = await fetch(`${API}/invoices/bulk-charge-card-on-file`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          invoice_ids: invoiceIds,
          dry_run: dry,
          idempotency_key: key,
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail || j);
        throw new Error(detail || `HTTP ${res.status}`);
      }
      return j;
    },
    [invoiceIds, key, token]
  );

  useEffect(() => {
    (async () => {
      try {
        const j = await post(true);
        setDryRun(j);
        setStep("review");
      } catch (err) {
        setErrMsg(String(err?.message || err));
        setStep("error");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirm = async () => {
    setStep("confirming");
    try {
      const j = await post(false);
      setReal(j);
      setStep("done");
      const s = j.summary || {};
      const msg = `${s.charged || 0} charged · ${s.skipped || 0} skipped · ${s.failed || 0} failed`;
      if ((s.failed || 0) > 0) toast.error(msg);
      else toast.success(msg);
    } catch (err) {
      setErrMsg(String(err?.message || err));
      setStep("error");
    }
  };

  const totalCents = useMemo(() => {
    if (!dryRun?.results) return 0;
    return dryRun.results
      .filter((r) => r.status === "would_charge")
      .reduce((acc, r) => acc + (r.amount_cents || 0), 0);
  }, [dryRun]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && step !== "confirming") onClose?.();
      }}
      data-testid="bulk-charge-modal"
    >
      <div
        className="w-full max-w-3xl rounded-2xl bg-white p-6 shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              Bulk charge cards on file
            </h2>
            <p className="text-xs text-slate-500">
              {invoiceIds.length} invoice{invoiceIds.length === 1 ? "" : "s"} selected · idempotency key {" "}
              <code className="text-[10px]">{key.slice(0, 8)}…</code>
            </p>
          </div>
          <button
            type="button"
            onClick={() => onClose?.(real?.run_id)}
            className="p-1 text-slate-500"
            aria-label="Close"
            data-testid="bulk-charge-close"
          >
            <XIcon size={18} />
          </button>
        </div>

        {step === "loading" ? (
          <p className="text-sm text-slate-600" data-testid="bulk-charge-loading">
            Checking eligibility…
          </p>
        ) : null}

        {step === "error" ? (
          <div
            className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
            data-testid="bulk-charge-error"
          >
            <div className="flex items-center gap-2 font-semibold">
              <AlertTriangle size={14} /> Bulk charge failed
            </div>
            <p className="mt-1">{errMsg}</p>
            <div className="mt-3 flex justify-end">
              <Button variant="ghost" onClick={() => onClose?.()}>
                Close
              </Button>
            </div>
          </div>
        ) : null}

        {(step === "review" || step === "confirming") && dryRun ? (
          <>
            <div
              className="mb-3 flex items-baseline justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
              data-testid="bulk-charge-summary"
            >
              <div className="text-sm text-slate-700">
                <strong>{dryRun.summary?.would_charge || 0}</strong> eligible ·{" "}
                <strong>{dryRun.summary?.skipped || 0}</strong> skipped
              </div>
              <div className="text-sm font-semibold text-slate-900">
                {_dollarsFromCents(totalCents)} will be charged
              </div>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-md border border-slate-200">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-600">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-semibold">Invoice</th>
                    <th className="px-2 py-1.5 text-left font-semibold">Status</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {dryRun.results.map((r) => {
                    const skip = r.skip_reason
                      ? _SKIP_LABELS[r.skip_reason] || {
                          label: r.skip_reason,
                          tone: "bg-slate-100 text-slate-700",
                        }
                      : null;
                    return (
                      <tr key={r.invoice_id} data-testid={`bulk-charge-row-${r.invoice_id}`}>
                        <td className="px-2 py-1.5 font-mono text-[11px] text-slate-700">
                          {r.invoice_id}
                        </td>
                        <td className="px-2 py-1.5">
                          {r.status === "would_charge" ? (
                            <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800">
                              Would charge
                            </span>
                          ) : skip ? (
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${skip.tone}`}
                            >
                              {skip.label}
                            </span>
                          ) : (
                            r.status
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-right text-slate-700">
                          {r.amount_cents ? _dollarsFromCents(r.amount_cents) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => onClose?.()}
                disabled={step === "confirming"}
                data-testid="bulk-charge-cancel"
              >
                Cancel
              </Button>
              <Button
                onClick={confirm}
                disabled={
                  step === "confirming" || (dryRun.summary?.would_charge || 0) === 0
                }
                data-testid="bulk-charge-confirm"
              >
                {step === "confirming" ? (
                  "Charging…"
                ) : (
                  <>
                    Confirm charge — {_dollarsFromCents(totalCents)}{" "}
                    <ChevronRight size={14} />
                  </>
                )}
              </Button>
            </div>
          </>
        ) : null}

        {step === "done" && real ? (
          <div data-testid="bulk-charge-result">
            <div className="mb-3 flex items-center justify-between rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm">
              <div className="flex items-center gap-2 font-semibold text-emerald-800">
                <Check size={14} /> Bulk charge complete
              </div>
              <div className="text-emerald-800">
                <strong>{real.summary?.charged || 0}</strong> charged ·{" "}
                <strong>{real.summary?.skipped || 0}</strong> skipped ·{" "}
                <strong>{real.summary?.failed || 0}</strong> failed
              </div>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-md border border-slate-200">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-600">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-semibold">Invoice</th>
                    <th className="px-2 py-1.5 text-left font-semibold">Outcome</th>
                    <th className="px-2 py-1.5 text-left font-semibold">Charge / error</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {real.results.map((r) => (
                    <tr key={r.invoice_id} data-testid={`bulk-charge-result-row-${r.invoice_id}`}>
                      <td className="px-2 py-1.5 font-mono text-[11px] text-slate-700">
                        {r.invoice_id}
                      </td>
                      <td className="px-2 py-1.5">
                        {r.status === "charged" ? (
                          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800">
                            Charged
                          </span>
                        ) : r.status === "failed" ? (
                          <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-800">
                            Failed
                          </span>
                        ) : (
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-700">
                            {r.skip_reason || r.status}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-slate-700">
                        {r.status === "charged" ? (
                          <code className="text-[10px]">{r.charge_id}</code>
                        ) : r.status === "failed" ? (
                          <span className="text-red-800">
                            {r.error_code}
                            {r.error_message ? `: ${r.error_message.slice(0, 60)}` : ""}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-right text-slate-700">
                        {r.amount_charged_cents
                          ? _dollarsFromCents(r.amount_charged_cents)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex justify-between">
              <a
                href={`/admin/finance/bulk-charge-runs/${real.run_id}`}
                className="text-xs font-semibold text-blue-700 underline"
                data-testid="bulk-charge-run-link"
              >
                View this run
              </a>
              <Button onClick={() => onClose?.(real.run_id)} data-testid="bulk-charge-done">
                Done
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
