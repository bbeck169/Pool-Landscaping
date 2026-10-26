/**
 * Ticket X · Feb-2026 — MarkOpenAction
 *
 * Reusable inline action rendered on MISSED job cards across every
 * Schedule surface (GridPanel route-planner rows, MonthCustomGrid
 * cells, and the RBC Agenda event rows). Self-contained: holds the
 * API-call lifecycle, optimistic patch, sonner toast with Undo
 * (5-second window), and error rollback.
 *
 * Contract:
 *   * Visible ONLY when ``job.status === "missed"`` (case-insensitive).
 *   * Click → optimistic patch to ``status="scheduled"`` + call
 *     ``POST /api/jobs/{id}/mark-open``.
 *     - 2xx: success toast with Undo (5s). Undo → PUT /api/jobs/{id}
 *       with ``{status: "missed", missed_at: <saved>}``.
 *     - 409 / 403 / 404 / network error: rollback optimistic patch
 *       via ``onPatch(originalJob)``, show error toast with the
 *       server detail (if present) or a stock message.
 *
 * The component carries its own event-propagation guard so a click
 * never bubbles up to the parent card's ``onSelectEvent`` (which
 * would otherwise open the job detail drawer concurrently with
 * the status flip).
 */
import React, { useState, useCallback } from "react";
import { toast } from "sonner";
import { CheckCircle2 } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";


const UNDO_WINDOW_MS = 5000;


function _isMissed(job) {
  return String(job?.status || "").toLowerCase() === "missed";
}


function _formatErr(err) {
  try {
    const d = err?.data?.detail || err?.detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && d.detail) return d.detail;
    if (err?.message) return err.message;
  } catch { /* fallthrough */ }
  return "Failed to mark job open";
}


export default function MarkOpenAction({
  job, onPatch, size = "sm", testIdSuffix,
}) {
  const [busy, setBusy] = useState(false);

  const handleUndo = useCallback(async (originalJob) => {
    // Undo: PUT /jobs/{id} back to missed, preserving the
    // original ``missed_at`` so the row is indistinguishable
    // from pre-flip state. BE PUT already admin-gates arbitrary
    // status writes (routers/jobs.py::update_job).
    try {
      onPatch({ ...originalJob });
      await api.put(`/jobs/${encodeURIComponent(originalJob.id)}`, {
        status: "missed",
        missed_at: originalJob.missed_at || null,
      });
      toast.success("Mark-open undone");
    } catch (err) {
      // Rollback failed — surface + reconcile UI to whatever
      // the server-of-record thinks is current status by
      // refetching the job row.
      toast.error(`Undo failed: ${_formatErr(err)}`);
      try {
        const fresh = await api.get(
          `/jobs/${encodeURIComponent(originalJob.id)}`,
        );
        if (fresh?.id) onPatch(fresh);
      } catch { /* best effort */ }
    }
  }, [onPatch]);

  const handleClick = useCallback(async (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (busy || !_isMissed(job)) return;
    setBusy(true);
    const originalJob = { ...job };
    // Optimistic update first — the Schedule surfaces re-render
    // on patchJobInPlace, so the card visibly flips to the open
    // palette before the network round-trip completes.
    onPatch({ ...job, status: "scheduled" });
    try {
      const updated = await api.post(
        `/jobs/${encodeURIComponent(job.id)}/mark-open`, {},
      );
      // Reconcile with server-of-record (adds
      // ``reopened_from_missed_at`` + clears ``missed_at``).
      if (updated?.id) onPatch(updated);
      toast.success("Marked as Open", {
        description: `${job.customer_name || "Job"} · ${
          job.service_type || ""}`,
        duration: UNDO_WINDOW_MS,
        action: {
          label: "Undo",
          onClick: () => handleUndo(originalJob),
        },
      });
    } catch (err) {
      // Rollback optimistic patch — restore the full original
      // job doc so no fields silently drift.
      onPatch(originalJob);
      toast.error(_formatErr(err));
    } finally {
      setBusy(false);
    }
  }, [busy, job, onPatch, handleUndo]);

  if (!_isMissed(job)) return null;

  const dims = size === "xs"
    ? { padX: 6, padY: 2, font: 10, icon: 10 }
    : { padX: 10, padY: 4, font: 12, icon: 12 };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      data-testid={testIdSuffix
        ? `mark-open-btn-${testIdSuffix}`
        : "mark-open-btn"}
      data-job-id={job?.id}
      data-status={String(job?.status || "").toLowerCase()}
      aria-label="Mark job as open"
      className="inline-flex items-center gap-1 rounded-md font-semibold transition hover:brightness-95 disabled:opacity-60"
      style={{
        paddingLeft: dims.padX, paddingRight: dims.padX,
        paddingTop: dims.padY, paddingBottom: dims.padY,
        fontSize: dims.font,
        backgroundColor: "#059669",  // emerald-600 — matches the
                                     // "active" status pill and
                                     // the "scheduled" FE bucket
                                     // target state.
        color: "#FFFFFF",
        border: "1px solid #047857",
      }}
    >
      <CheckCircle2 size={dims.icon} strokeWidth={2.5} />
      <span>Mark as Open</span>
    </button>
  );
}
