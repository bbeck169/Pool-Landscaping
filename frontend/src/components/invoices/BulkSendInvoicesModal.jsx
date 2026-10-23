/**
 * TD-invoice-list-bulk-send · Feb-2026
 * ============================================================
 *
 * Opens from the Invoices-list bulk action bar. Two steps:
 *   1. Confirm — "Send invoice (email + SMS) to {N} selected
 *      customers?"
 *   2. Results — per-invoice status chip table + summary.
 *
 * Backend contract: ``POST /api/invoices/bulk-send`` returns
 * ``{summary, results, request_id}``.  See
 * ``backend/routers/invoices_bulk_send.py`` for the exact
 * shape + status vocabulary.  On close, the parent calls
 * ``loadRows()`` + ``clearSelection()``.
 *
 * Mirrors ``BulkApplyCreditModal`` visual + state shape 1:1
 * so the two bulk-action modals are maintenance-coherent.
 */
import React, { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api";
import { colors } from "@/theme";


const _STATUS_TONE = {
  sent_both:              { bg: "#059669", fg: "#FFFFFF",
                             label: "Sent (email + SMS)" },
  sent_email_only:        { bg: "#10B981", fg: "#FFFFFF",
                             label: "Email only" },
  sent_sms_only:          { bg: "#10B981", fg: "#FFFFFF",
                             label: "SMS only" },
  skipped_already_paid:   { bg: "#DBEAFE", fg: "#1E40AF",
                             label: "Already paid" },
  skipped_draft:          { bg: "#FEF3C7", fg: "#92400E",
                             label: "Draft — not sent" },
  skipped_no_contact:     { bg: "#FEE2E2", fg: "#991B1B",
                             label: "No email / phone" },
  skipped_recent_send:    { bg: "#F3F4F6", fg: "#4B5563",
                             label: "Just sent (<60s)" },
  skipped_not_found:      { bg: "#F3F4F6", fg: "#4B5563",
                             label: "Not found" },
  error:                  { bg: "#991B1B", fg: "#FFFFFF",
                             label: "Error" },
};


function StatusChip({ status }) {
  const tone = _STATUS_TONE[status] || {
    bg: colors.surfaceSecondary, fg: colors.muted,
    label: status || "—",
  };
  return (
    <span
      className="inline-flex items-center text-xs font-bold px-2 py-0.5 rounded-full"
      style={{ background: tone.bg, color: tone.fg }}
      data-testid={`bulk-send-status-${status || "unknown"}`}
    >
      {tone.label}
    </span>
  );
}


export default function BulkSendInvoicesModal({
  open, onClose, invoiceIds = [], onComplete,
}) {
  const [step, setStep] = useState("confirm"); // confirm | results
  const [busy, setBusy] = useState(false);
  const [resp, setResp] = useState(null);

  const _count = invoiceIds.length;

  const _close = useCallback(() => {
    setStep("confirm");
    setResp(null);
    setBusy(false);
    onClose?.();
  }, [onClose]);

  const _onConfirm = useCallback(async () => {
    if (!invoiceIds.length) {
      toast.error("No invoices selected.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/invoices/bulk-send", {
        invoice_ids: invoiceIds,
      });
      setResp(r);
      setStep("results");
      onComplete?.(r);
    } catch (e) {
      toast.error(e?.message || "Bulk send failed.");
    } finally {
      setBusy(false);
    }
  }, [invoiceIds, onComplete]);

  const _summaryBits = useMemo(() => {
    if (!resp?.summary) return [];
    const s = resp.summary;
    const bits = [];
    if (s.sent_both)             bits.push(`${s.sent_both} sent (both)`);
    if (s.sent_email_only)       bits.push(`${s.sent_email_only} email only`);
    if (s.sent_sms_only)         bits.push(`${s.sent_sms_only} SMS only`);
    if (s.skipped_already_paid)  bits.push(`${s.skipped_already_paid} paid-skipped`);
    if (s.skipped_draft)         bits.push(`${s.skipped_draft} draft-skipped`);
    if (s.skipped_no_contact)    bits.push(`${s.skipped_no_contact} no-contact`);
    if (s.skipped_recent_send)   bits.push(`${s.skipped_recent_send} recent-skipped`);
    if (s.skipped_not_found)     bits.push(`${s.skipped_not_found} not-found`);
    if (s.errored)               bits.push(`${s.errored} errors`);
    return bits;
  }, [resp]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) _close(); }}
      data-testid="bulk-send-modal"
    >
      <div
        className="w-full max-w-2xl rounded-2xl p-6 shadow-2xl"
        style={{ backgroundColor: colors.surface,
                 border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {step === "confirm" ? (
          <div data-testid="bulk-send-confirm-step">
            <h2 className="text-lg font-bold"
                 style={{ color: colors.onSurface }}>
              Send invoice to {_count} selected customer{_count === 1 ? "" : "s"}?
            </h2>
            <p className="text-sm mt-2"
               style={{ color: colors.muted }}>
              Fires email + SMS to each invoice's customer. Paid /
              draft invoices are skipped. Customers missing both
              email and phone are skipped. Any invoice sent within
              the last 60 seconds is skipped to prevent double-sends.
            </p>
            <div className="flex items-center justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={_close}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: colors.surfaceSecondary,
                         color: colors.onSurface }}
                data-testid="bulk-send-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={_onConfirm}
                disabled={busy || !_count}
                className="px-4 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-50"
                style={{ background: "#0284C7" }}
                data-testid="bulk-send-confirm-btn"
              >
                {busy
                  ? "Sending…"
                  : `Send to ${_count} customer${_count === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
        ) : (
          <div data-testid="bulk-send-results-step">
            <h2 className="text-lg font-bold"
                 style={{ color: colors.onSurface }}>
              Bulk send results
            </h2>
            {_summaryBits.length ? (
              <div
                className="mt-2 flex flex-wrap gap-1.5"
                data-testid="bulk-send-summary-chips"
              >
                {_summaryBits.map((b, i) => (
                  <span
                    key={i}
                    className="text-xs px-2 py-0.5 rounded-full"
                    style={{ background: colors.surfaceSecondary,
                             color: colors.onSurface }}
                  >
                    {b}
                  </span>
                ))}
              </div>
            ) : null}
            <div
              className="mt-4 max-h-96 overflow-y-auto"
              style={{ border: `1px solid ${colors.border}`,
                       borderRadius: 8 }}
              data-testid="bulk-send-results-table-wrap"
            >
              <table className="w-full text-sm">
                <thead style={{ background: colors.surfaceSecondary }}>
                  <tr>
                    <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>
                      Invoice
                    </th>
                    <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>
                      Status
                    </th>
                    <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>
                      Detail
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(resp?.results || []).map((r) => (
                    <tr
                      key={r.invoice_id}
                      style={{ borderTop: `1px solid ${colors.divider}` }}
                      data-testid={`bulk-send-row-${r.invoice_id}`}
                    >
                      <td className="px-3 py-2 font-mono text-xs"
                          style={{ color: colors.onSurface }}>
                        {r.invoice_id.slice(0, 12)}…
                      </td>
                      <td className="px-3 py-2">
                        <StatusChip status={r.status} />
                      </td>
                      <td className="px-3 py-2 text-xs"
                          style={{ color: colors.muted }}>
                        {r.error
                          ? r.error
                          : (r.email_to || r.sms_to || "—")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={_close}
                className="px-4 py-2 rounded-lg text-sm font-semibold text-white"
                style={{ background: "#0284C7" }}
                data-testid="bulk-send-done"
              >
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
