// CHEM-LOCK · Feb-2026 — Admin-only "Unlock for Edit" button + modal.
//
// Renders in the JobDetail action strip when the current user is
// admin/super_admin/manager/owner AND the job is currently locked
// (``service_report_submitted_at`` set AND ``unlocked_at`` not
// stamped). Clicking opens a modal with:
//   • Required reason textarea (min 8 chars — submit disabled
//     until valid).
//   • Optional paid-invoice acknowledgement checkbox (rendered
//     ONLY after the first POST attempt when the backend returns
//     ``warnings: ["invoice_paid"]``, per brief §Edge cases §3).
//   • Cancel + Confirm buttons.
//
// On success, calls the parent ``onUnlocked`` callback so JobDetail
// can refetch the job + edit history sidebar.

import React, { useState, useMemo } from "react";
import { Unlock, AlertTriangle } from "lucide-react";
import { api } from "@/api";

const ADMIN_ROLES = new Set(["admin", "super_admin", "manager", "owner"]);

export default function JobUnlockButton({ job, user, onUnlocked }) {
  const role = (user?.role || "").toLowerCase();
  const isAdmin = ADMIN_ROLES.has(role);

  // Locked = SR was submitted AND admin hasn't unlocked yet.
  // ``service_report_submitted_at`` is the flag stamped on the JOB
  // doc by the submit path (see routers/service_reports.py:942).
  const isLocked = useMemo(
    () =>
      !!job?.service_report_submitted_at
      && !job?.unlocked_at,
    [job?.service_report_submitted_at, job?.unlocked_at],
  );

  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [ackInvoice, setAckInvoice] = useState(false);
  const [warnings, setWarnings] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (!isAdmin || !isLocked) return null;

  const reasonValid = reason.trim().length >= 8;
  const invoicePaid = warnings.includes("invoice_paid");
  const canSubmit = reasonValid && (!invoicePaid || ackInvoice) && !submitting;

  const doOpen = () => {
    setReason("");
    setAckInvoice(false);
    setWarnings([]);
    setError("");
    setOpen(true);
  };

  const doClose = () => {
    if (submitting) return;
    setOpen(false);
  };

  const doSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await api.post(`/jobs/${job.id}/unlock`, {
        reason: reason.trim(),
      });
      // If the backend surfaced a paid-invoice warning AND the
      // admin didn't ack, we would have to loop. Because we already
      // check ``ackInvoice`` client-side (see ``canSubmit``), the
      // server's ``warnings`` payload here is informational.
      if (Array.isArray(res?.warnings) && res.warnings.length > 0
          && !ackInvoice
          && res.warnings.includes("invoice_paid")) {
        // First-attempt reveal of the paid-invoice warning. Refresh
        // the modal state to require acknowledgement.
        setWarnings(res.warnings);
        setSubmitting(false);
        return;
      }
      setOpen(false);
      setSubmitting(false);
      if (typeof onUnlocked === "function") {
        onUnlocked(res);
      }
    } catch (e) {
      setSubmitting(false);
      const detail = e?.data?.detail;
      // Backend paid-invoice warning arrives as a 200 + warnings.
      // If we ever get here with warnings on a 200, capture them.
      setError(
        typeof detail === "string"
          ? detail
          : e?.message || "Failed to unlock job",
      );
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={doOpen}
        className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold"
        style={{
          backgroundColor: "#FEF3C7",
          color: "#78350F",
          border: "1px solid #FCD34D",
        }}
        data-testid="jd-unlock-button"
      >
        <Unlock size={14} />
        Unlock for Edit
      </button>

      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          data-testid="jd-unlock-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl"
            style={{ maxHeight: "90vh", overflowY: "auto" }}
          >
            <div className="flex items-start gap-3">
              <Unlock size={20} className="mt-0.5 text-amber-600" />
              <div className="flex-1">
                <h2 className="text-lg font-bold text-slate-900">
                  Unlock submitted job
                </h2>
                <p className="text-sm text-slate-600 mt-1">
                  This will reopen the service report for the assigned
                  tech to correct entries. The action is logged with
                  your reason.
                </p>
              </div>
            </div>

            <label
              className="block mt-4 text-xs font-semibold uppercase tracking-wide text-slate-700"
              htmlFor="jd-unlock-reason"
            >
              Reason (required, min 8 characters)
            </label>
            <textarea
              id="jd-unlock-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none"
              placeholder="e.g. Typo in chlorine dose — tech re-measuring pool"
              data-testid="jd-unlock-reason-input"
              disabled={submitting}
            />
            <div
              className="mt-1 text-xs"
              style={{ color: reasonValid ? "#059669" : "#94A3B8" }}
              data-testid="jd-unlock-reason-length"
            >
              {reason.trim().length}/8 characters minimum
            </div>

            {invoicePaid ? (
              <label
                className="mt-4 flex items-start gap-2 rounded-lg p-3"
                style={{ backgroundColor: "#FEF2F2", border: "1px solid #FCA5A5" }}
                data-testid="jd-unlock-invoice-paid-warning"
              >
                <AlertTriangle
                  size={16}
                  className="mt-0.5 shrink-0"
                  style={{ color: "#DC2626" }}
                />
                <div className="flex-1 text-sm" style={{ color: "#7F1D1D" }}>
                  <span className="font-semibold">
                    This job has been invoiced/paid.
                  </span>{" "}
                  Corrections may require an amended invoice.
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="jd-unlock-ack-invoice"
                      checked={ackInvoice}
                      onChange={(e) => setAckInvoice(e.target.checked)}
                      data-testid="jd-unlock-ack-invoice-checkbox"
                    />
                    <label
                      htmlFor="jd-unlock-ack-invoice"
                      className="text-xs"
                    >
                      I understand and want to proceed
                    </label>
                  </div>
                </div>
              </label>
            ) : null}

            {error ? (
              <div
                className="mt-3 rounded-lg p-2 text-sm"
                style={{ backgroundColor: "#FEF2F2", color: "#B91C1C" }}
                data-testid="jd-unlock-error"
              >
                {error}
              </div>
            ) : null}

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={doClose}
                className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100"
                data-testid="jd-unlock-cancel"
                disabled={submitting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doSubmit}
                disabled={!canSubmit}
                className="rounded-lg px-4 py-2 text-sm font-semibold text-white"
                style={{
                  backgroundColor: canSubmit ? "#B45309" : "#D6D3D1",
                  cursor: canSubmit ? "pointer" : "not-allowed",
                }}
                data-testid="jd-unlock-confirm"
              >
                {submitting ? "Unlocking…" : "Unlock"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
