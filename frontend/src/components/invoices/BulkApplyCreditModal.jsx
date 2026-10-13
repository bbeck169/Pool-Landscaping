/**
 * Feb-2026 · Bulk Apply Credit modal — Phase 1.
 *
 * Opens from the Invoices-list bulk action bar. Two steps:
 *   1. Confirm — "Apply credit to {N} selected invoice(s)?"
 *   2. Results — per-invoice table + summary chip row.
 *
 * Backend contract: ``POST /api/invoices/bulk-apply-credit``
 * returns ``{summary, results, request_id}``. See
 * ``backend/routers/invoices_bulk_apply_credit.py`` for the exact
 * shape and status-code semantics. On close, the parent calls
 * ``loadRows()`` + ``clearSelection()`` so updated balances show.
 */
import React, { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api";
import { colors } from "@/theme";


const _STATUS_TONE = {
  credited:                { bg: "#059669", fg: "#FFFFFF",
                              label: "Credited" },
  skipped_no_credit:       { bg: "#FEF3C7", fg: "#92400E",
                              label: "No credit" },
  skipped_already_paid:    { bg: "#DBEAFE", fg: "#1E40AF",
                              label: "Already paid" },
  skipped_blocked_status:  { bg: "#FEE2E2", fg: "#991B1B",
                              label: "Invalid status" },
  skipped_not_found:       { bg: "#F3F4F6", fg: "#4B5563",
                              label: "Not found" },
  error:                   { bg: "#991B1B", fg: "#FFFFFF",
                              label: "Error" },
};


function StatusChip({ status }) {
  const tone = _STATUS_TONE[status] || {
    bg: colors.surfaceSecondary,
    fg: colors.muted,
    label: status || "—",
  };
  return (
    <span
      className="inline-flex items-center text-xs font-bold px-2 py-0.5 rounded-full"
      style={{ background: tone.bg, color: tone.fg }}
      data-testid={`bulk-apply-credit-status-${status || "unknown"}`}
    >
      {tone.label}
    </span>
  );
}


function _fmt(dollars) {
  const n = Number(dollars || 0);
  return n.toLocaleString("en-US", {
    style: "currency", currency: "USD",
  });
}


export default function BulkApplyCreditModal({
  invoiceIds, onClose,
}) {
  const n = (invoiceIds || []).length;
  const [stage, setStage] = useState("confirm");  // 'confirm'|'results'
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const close = useCallback(
    (didApply) => {
      if (busy) return;
      onClose?.(didApply ? result?.request_id || true : null);
    },
    [busy, onClose, result],
  );

  const submit = useCallback(async () => {
    if (!n || busy) return;
    setBusy(true);
    try {
      const resp = await api.post(
        "/invoices/bulk-apply-credit",
        { invoice_ids: invoiceIds },
      );
      setResult(resp);
      setStage("results");
    } catch (e) {
      const msg =
        e?.data?.detail?.message
        || e?.data?.detail
        || e?.message
        || "Failed to apply credit. Please try again.";
      toast.error(
        typeof msg === "string" ? msg : "Failed to apply credit",
      );
    } finally {
      setBusy(false);
    }
  }, [n, busy, invoiceIds]);

  const summaryLine = useMemo(() => {
    if (!result?.summary) return null;
    const s = result.summary;
    const parts = [
      `${s.credited} invoice${s.credited === 1 ? "" : "s"} credited `
        + `for ${_fmt(s.total_amount_applied)}.`,
    ];
    if (s.skipped_no_credit > 0) {
      parts.push(`${s.skipped_no_credit} skipped (no credit).`);
    }
    if (s.skipped_already_paid > 0) {
      parts.push(
        `${s.skipped_already_paid} skipped (already paid).`,
      );
    }
    if (s.skipped_blocked_status > 0) {
      parts.push(
        `${s.skipped_blocked_status} skipped (invalid status).`,
      );
    }
    if (s.skipped_not_found > 0) {
      parts.push(`${s.skipped_not_found} skipped (not found).`);
    }
    if (s.errors > 0) {
      parts.push(`${s.errors} error${s.errors === 1 ? "" : "s"}.`);
    }
    return parts.join(" ");
  }, [result]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close(stage === "results");
      }}
      data-testid="bulk-apply-credit-modal"
    >
      <div
        className="w-full max-w-3xl rounded-2xl shadow-2xl overflow-hidden"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          maxHeight: "90vh",
        }}
      >
        {stage === "confirm" ? (
          <div className="p-6" data-testid="bulk-apply-credit-confirm-stage">
            <div
              className="text-base font-bold mb-2"
              style={{ color: colors.onSurface }}
            >
              Apply credit to {n} selected invoice
              {n === 1 ? "" : "s"}?
            </div>
            <div
              className="text-sm mb-5"
              style={{ color: colors.muted }}
            >
              For each selected invoice we'll apply up to the
              invoice's balance due from the customer's available
              credit. Any customer without a credit balance will be
              skipped — nothing is written for those.
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => close(false)}
                disabled={busy}
                className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                style={{
                  background: colors.surfaceSecondary,
                  color: colors.onSurface,
                }}
                data-testid="bulk-apply-credit-cancel-btn"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={busy || !n}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-50"
                style={{ backgroundColor: "#059669" }}
                data-testid="bulk-apply-credit-confirm-btn"
              >
                {busy ? "Applying…" : "Apply credit"}
              </button>
            </div>
          </div>
        ) : (
          <div
            className="flex flex-col"
            style={{ maxHeight: "90vh" }}
            data-testid="bulk-apply-credit-results-stage"
          >
            <div
              className="p-5 border-b"
              style={{ borderColor: colors.border }}
            >
              <div
                className="text-base font-bold mb-1"
                style={{ color: colors.onSurface }}
              >
                Credit application results
              </div>
              <div
                className="text-sm"
                style={{ color: colors.muted }}
                data-testid="bulk-apply-credit-summary"
              >
                {summaryLine}
              </div>
            </div>
            <div
              className="overflow-auto flex-1"
              style={{ maxHeight: "60vh" }}
            >
              <table
                className="w-full text-sm"
                data-testid="bulk-apply-credit-results-table"
              >
                <thead
                  style={{
                    background: colors.surfaceSecondary,
                    color: colors.muted,
                  }}
                >
                  <tr>
                    <th className="text-left px-4 py-2 text-xs font-semibold uppercase">
                      Invoice
                    </th>
                    <th className="text-left px-4 py-2 text-xs font-semibold uppercase">
                      Customer
                    </th>
                    <th className="text-left px-4 py-2 text-xs font-semibold uppercase">
                      Status
                    </th>
                    <th className="text-right px-4 py-2 text-xs font-semibold uppercase">
                      Applied
                    </th>
                    <th className="text-right px-4 py-2 text-xs font-semibold uppercase">
                      Balance remaining
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(result?.results || []).map((r, i) => (
                    <tr
                      key={r.invoice_id || i}
                      style={{
                        borderTop: i === 0
                          ? "none"
                          : `1px solid ${colors.border}`,
                        color: colors.onSurface,
                      }}
                      data-testid={`bulk-apply-credit-row-${
                        r.invoice_id || i
                      }`}
                    >
                      <td className="px-4 py-2 font-semibold">
                        {r.invoice_number || "—"}
                      </td>
                      <td className="px-4 py-2">
                        {r.customer_name || "—"}
                      </td>
                      <td className="px-4 py-2">
                        <StatusChip status={r.status} />
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {_fmt(r.amount_applied)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {_fmt(r.balance_remaining)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div
              className="p-4 flex justify-end border-t"
              style={{ borderColor: colors.border }}
            >
              <button
                type="button"
                onClick={() => close(true)}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white"
                style={{ backgroundColor: colors.brand || "#1D4ED8" }}
                data-testid="bulk-apply-credit-close-btn"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
