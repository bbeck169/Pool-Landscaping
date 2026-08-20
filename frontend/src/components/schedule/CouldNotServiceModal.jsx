/**
 * Feb-2026 · Phase 1 — Tech "Could Not Service" modal.
 *
 * Preset reason picker + notes (required when reason=other) + photo
 * uploader (≥1 photo). Submits to
 * ``POST /api/jobs/{job_id}/could-not-service`` — server-side flips
 * status + fires customer SMS. Reuses ``FileUpload`` (job-photos
 * purpose) and the existing ``sonner`` toast surface.
 */
import React, { useEffect, useState, useCallback } from "react";
import { X, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api";
import { FileUpload } from "@/components/files/FileUpload";


function _humanizeSmsReason(reason) {
  switch (reason) {
    case "sms_opt_in_false":  return "Customer opted out of SMS — not notified.";
    case "customer_blocked":  return "Customer blocked/demo — SMS suppressed.";
    case "no_phone":          return "No phone on file — SMS not sent.";
    case "outbound_disabled": return "Outbound SMS is disabled by config.";
    case "send_failed":       return "SMS provider rejected the send.";
    default:                  return null;
  }
}


export default function CouldNotServiceModal({ job, onClose, onDone }) {
  const [reasons, setReasons] = useState([]);
  const [reasonId, setReasonId] = useState("");
  const [notes, setNotes] = useState("");
  const [photoIds, setPhotoIds] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.get("/settings/job-outcome-reasons")
      .then((r) => setReasons(r?.reasons || []))
      .catch(() => setReasons([]));
  }, []);

  const selected = reasons.find((r) => r.id === reasonId);
  const isOther = (selected?.key || "") === "other";
  const canSubmit = !!reasonId && photoIds.length >= 1 &&
                     (!isOther || notes.trim().length > 0) &&
                     !submitting;

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const resp = await api.post(
        `/jobs/${job.id}/could-not-service`,
        { reason_id: reasonId, reason_notes: notes,
          photo_file_ids: photoIds },
      );
      toast.success("Job marked 'Could Not Service'");
      const sr = resp?.sms_result;
      const secondary = sr?.sent
        ? "Customer notified"
        : _humanizeSmsReason(sr?.reason);
      if (secondary) toast.message(secondary);
      onDone?.(resp);
      onClose?.();
    } catch (e) {
      toast.error(e?.message || "Could not mark job.");
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, job?.id, reasonId, notes, photoIds, onDone, onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(15,23,42,0.5)" }}
      data-testid="could-not-service-modal"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <AlertTriangle size={18} className="text-amber-600" />
            <h2 className="text-lg font-bold">Mark 'Could Not Service'</h2>
          </div>
          <button onClick={onClose} data-testid="cns-close" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="text-xs text-slate-500 mb-3">
          Requires a reason and at least one photo. The customer will be
          notified via SMS.
        </div>

        <label className="text-sm font-semibold">Reason</label>
        <select
          value={reasonId}
          onChange={(e) => setReasonId(e.target.value)}
          data-testid="cns-reason"
          className="w-full border rounded-lg px-3 py-2 mb-3 mt-1"
        >
          <option value="">Select a reason…</option>
          {reasons.map((r) => (
            <option key={r.id} value={r.id}>{r.label}</option>
          ))}
        </select>

        <label className="text-sm font-semibold">
          Notes {isOther && <span className="text-amber-600">(required)</span>}
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          data-testid="cns-notes"
          rows={3}
          className="w-full border rounded-lg px-3 py-2 mb-3 mt-1"
          placeholder={isOther ? "Describe what happened…" : "Optional context…"}
        />

        <label className="text-sm font-semibold">
          Photo{photoIds.length !== 1 ? "s" : ""} · {photoIds.length}/1+
        </label>
        <div className="mt-1 mb-4" data-testid="cns-photo-upload">
          <FileUpload
            purpose="job_could_not_service"
            linkedEntityType="job"
            linkedEntityId={job?.id}
            multiple
            accept="image/*"
            onUploaded={(p) => setPhotoIds((prev) => [...prev, p.id])}
          />
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-sm"
            data-testid="cns-cancel"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white disabled:opacity-50"
            style={{ backgroundColor: "#D97706" }}
            data-testid="cns-submit"
          >
            {submitting ? "Marking…" : "Mark Could Not Service"}
          </button>
        </div>
      </div>
    </div>
  );
}
