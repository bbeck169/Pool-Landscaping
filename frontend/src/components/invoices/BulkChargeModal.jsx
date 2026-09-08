/**
 * Phase 14b · Feb-2026 — Two-step bulk-charge modal.
 * Phase K38 · Feb-2026 — Parameterized to support ACH (us_bank_account)
 * in addition to card. Same two-step dry-run/confirm flow.
 *
 * Flow:
 *   1. Mount → immediately calls the appropriate bulk endpoint with
 *      `dry_run=true` + a client-generated UUID `idempotency_key`.
 *      Renders the per-row eligibility table with badges.
 *   2. "Confirm" button (only enabled once step-1 resolves) → calls
 *      the same endpoint with `dry_run=false` + the *same* key.
 *      Renders results + amounts + charge IDs. Toast summary on close.
 *
 * Props:
 *   invoiceIds     (string[])  — selected invoice IDs (must be ≤ 100).
 *   paymentMethod  ("card"|"ach", default "card") — Phase K38 · Feb-2026.
 *                                Controls endpoint URL, copy, and result
 *                                terminology ("Charged" vs "Initiated").
 *   onClose        (fn(runId?))
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { X as XIcon, ChevronRight, Check, AlertTriangle, Landmark } from "lucide-react";

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

const _SKIP_LABELS_CARD = {
  already_paid: { label: "Already paid", tone: "bg-slate-100 text-slate-700" },
  no_card_on_file: { label: "No card on file", tone: "bg-amber-100 text-amber-800" },
  card_expired: { label: "Card expired", tone: "bg-red-100 text-red-800" },
  zero_balance: { label: "Zero balance", tone: "bg-slate-100 text-slate-700" },
  not_found: { label: "Not found", tone: "bg-red-100 text-red-800" },
};

const _SKIP_LABELS_ACH = {
  already_paid: { label: "Already paid", tone: "bg-slate-100 text-slate-700" },
  pending_ach: { label: "ACH in-flight", tone: "bg-amber-100 text-amber-800" },
  no_bank_on_file: { label: "No bank on file", tone: "bg-amber-100 text-amber-800" },
  bank_unverified: { label: "Bank not verified", tone: "bg-red-100 text-red-800" },
  zero_balance: { label: "Zero balance", tone: "bg-slate-100 text-slate-700" },
  not_found: { label: "Not found", tone: "bg-red-100 text-red-800" },
};

// K38 · Feb-2026 — verbatim ACH settlement warning copy.  Anchored as a
// test fixture — DO NOT paraphrase.
export const ACH_SETTLEMENT_WARNING =
  "ACH payments take 3\u20135 business days to settle. Charges may still fail after submission (NSF, closed account, or incorrect routing). Failed charges will revert the invoice to Unpaid.";

function _dollarsFromCents(c) {
  return `$${((c || 0) / 100).toFixed(2)}`;
}

export default function BulkChargeModal({ invoiceIds, paymentMethod = "card", onClose }) {
  const isAch = paymentMethod === "ach";
  const endpoint = isAch
    ? "/invoices/bulk-charge-ach-on-file"
    : "/invoices/bulk-charge-card-on-file";
  const skipLabels = isAch ? _SKIP_LABELS_ACH : _SKIP_LABELS_CARD;
  const [key] = useState(_uuid);
  const [step, setStep] = useState("loading"); // loading | review | confirming | done | error
  const [dryRun, setDryRun] = useState(null);
  const [real, setReal] = useState(null);
  const [errMsg, setErrMsg] = useState("");
  const token =
    typeof window !== "undefined" ? window.localStorage.getItem("token") : "";

  const post = useCallback(
    async (dry) => {
      const res = await fetch(`${API}${endpoint}`, {
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
      // Feb-2026 · Bug A — the backend can return non-JSON bodies (e.g.
      // Starlette's default `text/plain: "Internal Server Error"` on an
      // unhandled exception, a proxy 502 HTML page, or a truly empty
      // body).  Read the body defensively so the error surface shows a
      // helpful message instead of the string `"{}"`.
      const rawText = await res.text();
      let j = {};
      if (rawText) {
        try { j = JSON.parse(rawText); } catch { j = {}; }
      }
      if (!res.ok) {
        const status = `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}`;
        // Structured backend error (HTTPException) → detail is a string.
        // Pydantic 422 → detail is a list of {loc,msg,type}; stringify each.
        // FastAPI generic → look at .message too.
        let msg = "";
        if (typeof j.detail === "string") {
          msg = j.detail;
        } else if (Array.isArray(j.detail)) {
          msg = j.detail
            .map((e) => (typeof e === "string" ? e : e?.msg || JSON.stringify(e)))
            .join("; ");
        } else if (typeof j.message === "string") {
          msg = j.message;
        } else if (rawText && rawText.trim() && rawText.trim() !== "{}") {
          // Non-JSON body (plaintext / HTML).  Trim + clip so we don't
          // splash an entire HTML page into the error card.
          msg = rawText.trim().slice(0, 240);
        }
        const hint = res.status >= 500
          ? " — check backend logs"
          : res.status === 403
            ? " — check your admin role"
            : "";
        throw new Error(msg ? `${msg} (${status})` : `${status}${hint}`);
      }
      return j;
    },
    [invoiceIds, key, token, endpoint]
  );

  useEffect(() => {
    (async () => {
      try {
        const j = await post(true);
        setDryRun(j);
        setStep("review");
        const s = j.summary || {};
        if ((s.would_charge || 0) === 0 && (s.skipped || 0) > 0) {
          toast.warning(
            `${isAch ? "No bank accounts on file" : "No cards on file"} to charge — ${s.skipped} invoice${
              s.skipped === 1 ? "" : "s"
            } skipped`
          );
        }
      } catch (err) {
        const msg = String(err?.message || err);
        setErrMsg(msg);
        setStep("error");
        toast.error(`Bulk ${isAch ? "ACH " : ""}charge check failed: ${msg}`);
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
      if (isAch) {
        const initiated = s.initiated || 0;
        const msg = `${initiated} initiated · ${s.skipped || 0} skipped · ${s.failed || 0} failed`;
        if ((s.failed || 0) > 0) toast.error(msg);
        else if (initiated === 0) toast.warning(msg);
        else toast.success(msg);
      } else {
        const msg = `${s.charged || 0} charged · ${s.skipped || 0} skipped · ${s.failed || 0} failed`;
        if ((s.failed || 0) > 0) toast.error(msg);
        else if ((s.charged || 0) === 0) toast.warning(msg);
        else toast.success(msg);
      }
    } catch (err) {
      const msg = String(err?.message || err);
      setErrMsg(msg);
      setStep("error");
      toast.error(`Bulk ${isAch ? "ACH " : ""}charge failed: ${msg}`);
    }
  };

  const totalCents = useMemo(() => {
    if (!dryRun?.results) return 0;
    return dryRun.results
      .filter((r) => r.status === "would_charge")
      .reduce((acc, r) => acc + (r.amount_cents || 0), 0);
  }, [dryRun]);

  const testIdPrefix = isAch ? "bulk-charge-ach" : "bulk-charge";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && step !== "confirming") onClose?.();
      }}
      data-testid={`${testIdPrefix}-modal`}
    >
      <div
        className="w-full max-w-3xl rounded-2xl bg-white p-6 shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              {isAch ? "Bulk charge ACH on file" : "Bulk charge cards on file"}
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
            data-testid={`${testIdPrefix}-close`}
          >
            <XIcon size={18} />
          </button>
        </div>

        {isAch ? (
          <div
            className="mb-4 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
            data-testid="bulk-charge-ach-warning"
          >
            <Landmark size={14} className="mt-0.5 shrink-0" />
            <p>{ACH_SETTLEMENT_WARNING}</p>
          </div>
        ) : null}

        {step === "loading" ? (
          <p className="text-sm text-slate-600" data-testid={`${testIdPrefix}-loading`}>
            Checking eligibility…
          </p>
        ) : null}

        {step === "error" ? (
          <div
            className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
            data-testid={`${testIdPrefix}-error`}
          >
            <div className="flex items-center gap-2 font-semibold">
              <AlertTriangle size={14} /> Bulk {isAch ? "ACH " : ""}charge failed
            </div>
            <p className="mt-1" data-testid={`${testIdPrefix}-error-message`}>{errMsg}</p>
            {invoiceIds && invoiceIds.length > 0 ? (
              <p
                className="mt-1 text-[11px] text-red-700"
                data-testid={`${testIdPrefix}-error-invoices`}
              >
                Affected invoice{invoiceIds.length === 1 ? "" : "s"}:{" "}
                <code className="text-[10px]">
                  {invoiceIds.slice(0, 5).join(", ")}
                  {invoiceIds.length > 5 ? ` (+${invoiceIds.length - 5} more)` : ""}
                </code>
              </p>
            ) : null}
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
              data-testid={`${testIdPrefix}-summary`}
            >
              <div className="text-sm text-slate-700">
                <strong>{dryRun.summary?.would_charge || 0}</strong> eligible ·{" "}
                <strong>{dryRun.summary?.skipped || 0}</strong> skipped
              </div>
              <div className="text-sm font-semibold text-slate-900">
                {_dollarsFromCents(totalCents)} will {isAch ? "be submitted" : "be charged"}
              </div>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-md border border-slate-200">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-600">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-semibold">Invoice</th>
                    <th className="px-2 py-1.5 text-left font-semibold">Status</th>
                    {isAch ? (
                      <th className="px-2 py-1.5 text-left font-semibold">Bank</th>
                    ) : null}
                    <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {dryRun.results.map((r) => {
                    const skip = r.skip_reason
                      ? skipLabels[r.skip_reason] || {
                          label: r.skip_reason,
                          tone: "bg-slate-100 text-slate-700",
                        }
                      : null;
                    return (
                      <tr key={r.invoice_id} data-testid={`${testIdPrefix}-row-${r.invoice_id}`}>
                        <td className="px-2 py-1.5 font-mono text-[11px] text-slate-700">
                          {r.invoice_id}
                        </td>
                        <td className="px-2 py-1.5">
                          {r.status === "would_charge" ? (
                            <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800">
                              {isAch ? "Would submit" : "Would charge"}
                            </span>
                          ) : skip ? (
                            r.skip_reason === "bank_unverified" && r.customer_id ? (
                              // K43 · Feb-2026 — QoL: link the "BANK NOT
                              // VERIFIED" pill directly to the customer
                              // detail page so admins can click through
                              // and fire the K43 verify action without
                              // hunting for the customer.
                              <a
                                href={`/customers/${r.customer_id}`}
                                target="_blank"
                                rel="noreferrer"
                                className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase underline ${skip.tone}`}
                                data-testid={`${testIdPrefix}-row-${r.invoice_id}-verify-link`}
                                title="Open customer detail to verify bank"
                              >
                                {skip.label} ↗
                              </a>
                            ) : (
                              <span
                                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${skip.tone}`}
                              >
                                {skip.label}
                              </span>
                            )
                          ) : (
                            r.status
                          )}
                        </td>
                        {isAch ? (
                          <td className="px-2 py-1.5 text-slate-700">
                            {r.bank_last4 ? (
                              <span data-testid={`bulk-charge-ach-bank-${r.invoice_id}`}>
                                {r.bank_name ? `${r.bank_name} ` : ""}••••{r.bank_last4}
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                        ) : null}
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
                data-testid={`${testIdPrefix}-cancel`}
              >
                Cancel
              </Button>
              <Button
                onClick={confirm}
                disabled={
                  step === "confirming" || (dryRun.summary?.would_charge || 0) === 0
                }
                data-testid={`${testIdPrefix}-confirm`}
              >
                {step === "confirming" ? (
                  isAch ? "Submitting…" : "Charging…"
                ) : (
                  <>
                    {isAch ? "Submit ACH — " : "Confirm charge — "}
                    {_dollarsFromCents(totalCents)}{" "}
                    <ChevronRight size={14} />
                  </>
                )}
              </Button>
            </div>
          </>
        ) : null}

        {step === "done" && real ? (
          <div data-testid={`${testIdPrefix}-result`}>
            <div className="mb-3 flex items-center justify-between rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm">
              <div className="flex items-center gap-2 font-semibold text-emerald-800">
                <Check size={14} /> {isAch ? "ACH submissions sent" : "Bulk charge complete"}
              </div>
              <div className="text-emerald-800">
                <strong>{isAch ? (real.summary?.initiated || 0) : (real.summary?.charged || 0)}</strong>{" "}
                {isAch ? "initiated" : "charged"} ·{" "}
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
                    <th className="px-2 py-1.5 text-left font-semibold">
                      {isAch ? "Intent / error" : "Charge / error"}
                    </th>
                    <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {real.results.map((r) => (
                    <tr key={r.invoice_id} data-testid={`${testIdPrefix}-result-row-${r.invoice_id}`}>
                      <td className="px-2 py-1.5 font-mono text-[11px] text-slate-700">
                        {r.invoice_id}
                      </td>
                      <td className="px-2 py-1.5">
                        {r.status === "charged" ? (
                          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800">
                            Charged
                          </span>
                        ) : r.status === "initiated" ? (
                          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-800">
                            Initiated
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
                        {r.status === "charged" || r.status === "initiated" ? (
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
                data-testid={`${testIdPrefix}-run-link`}
              >
                View this run
              </a>
              <Button onClick={() => onClose?.(real.run_id)} data-testid={`${testIdPrefix}-done`}>
                Done
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
