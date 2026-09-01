/**
 * Feb-2026 · Slice 6 — 24h Post-Completion Edit Window (frontend).
 *
 * Encapsulates:
 *   * ``isWithinEditWindow(job)`` client-mirror of the backend helper
 *     (``backend/services/edit_window.py``). Kept in sync manually —
 *     the backend is the source of truth (PATCH re-checks server-
 *     side; this only decides whether to SHOW the Edit button).
 *   * ``<JobEditPanel>`` — Edit button + notes-edit modal + Edit
 *     History section. Renders inline on the job-detail page for
 *     admin / assigned technician.
 *
 * Scope notes:
 *   * Notes edits are the common case and are handled inline. For
 *     chemistry / checklist edits the tech reopens the Service
 *     Report form (existing page); the underlying PATCH endpoint
 *     accepts any of the allowed fields, so future surfaces can
 *     re-use the same panel.
 *   * On 403 ``edit_window_expired`` we surface a soft inline
 *     warning. On 422 chemistry-gate failure we bubble the message
 *     verbatim (same shape the ServiceReport banner uses).
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, Modal, Toast } from "@/components/ui-kit";
import { Pencil, History, AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { formatCompletedAt } from "@/lib/dateTimeFormat";


// Client-side mirror of ``services.edit_window.EDIT_WINDOW_HOURS``.
export const EDIT_WINDOW_HOURS = 24;


/** ``true`` iff the job is completed AND its ``completed_at`` is
 * within :data:`EDIT_WINDOW_HOURS` of now. Returns ``false`` for
 * missing / unparseable timestamps — the backend re-checks on
 * every PATCH so a false positive here just yields a 403.
 */
export function isWithinEditWindow(job) {
  if (!job || String(job.status || "").toLowerCase() !== "completed") return false;
  const raw = job.completed_at;
  if (!raw) return false;
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return false;
  const hours = (Date.now() - dt.getTime()) / 3_600_000;
  return hours <= EDIT_WINDOW_HOURS && hours >= 0;
}


export function hoursSinceCompletion(job) {
  if (!job?.completed_at) return null;
  const dt = new Date(job.completed_at);
  if (Number.isNaN(dt.getTime())) return null;
  return (Date.now() - dt.getTime()) / 3_600_000;
}


function _formatDiff(v) {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return `${v.length} item${v.length === 1 ? "" : "s"}`;
  if (typeof v === "object") return JSON.stringify(v).slice(0, 120);
  return String(v);
}


function _formatWhen(iso) {
  // Phase K16 · Feb-2026 — canonical formatter (see top-level import).
  return formatCompletedAt(iso);
}


export default function JobEditPanel({ job, onEdited }) {
  const [editOpen, setEditOpen] = useState(false);
  const [notes, setNotes] = useState(job?.notes || "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [toast, setToast] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    setNotes(job?.notes || "");
  }, [job?.id, job?.notes]);

  const canEdit = isWithinEditWindow(job);
  const hoursLeft = canEdit
    ? Math.max(0, EDIT_WINDOW_HOURS - (hoursSinceCompletion(job) || 0))
    : null;

  const loadHistory = async () => {
    if (!job?.id) return;
    setHistoryLoading(true);
    try {
      const r = await api.get(`/jobs/${job.id}/edits`);
      setHistory(r);
    } catch (e) {
      setHistory({ count: 0, edits: [], error: e?.message || "Failed to load history" });
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (historyOpen && !history) loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyOpen]);

  const onSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaveError("");
    try {
      const trimmedReason = reason.trim();
      const body = { notes };
      if (trimmedReason) body.edit_reason = trimmedReason;
      body.edit_source = "web";
      const updated = await api.patch(`/jobs/${job.id}`, body);
      setEditOpen(false);
      setReason("");
      setToast({ tone: "success", message: "Edit saved" });
      // Refresh Edit History if the section is open.
      if (historyOpen) await loadHistory();
      if (onEdited) onEdited(updated);
    } catch (e) {
      // The backend returns HTTPException.detail as a dict — the api
      // helper surfaces it on ``e.detail`` or nested ``e.data.detail``.
      const detail = e?.detail || e?.data?.detail || e?.response?.data?.detail;
      if (detail && typeof detail === "object") {
        if (detail.detail === "edit_window_expired") {
          setSaveError(
            `Edit window closed (${detail.edit_window_hours || EDIT_WINDOW_HOURS}h). ` +
              `This job was completed ${(detail.hours_since_completion || 0).toFixed(1)}h ago.`,
          );
        } else if (detail.detail === "chemistry_gate_failed") {
          setSaveError(detail.message || "Chemistry gate blocked the save.");
        } else if (detail.detail === "immutable_field") {
          setSaveError(detail.message || `Field ${detail.field} cannot be edited via this path.`);
        } else {
          setSaveError(detail.message || detail.detail || "Save failed.");
        }
      } else {
        setSaveError(e?.message || "Save failed.");
      }
    } finally {
      setSaving(false);
    }
  };

  if (!job) return null;

  return (
    <div className="mt-5" data-testid="job-edit-panel">
      {canEdit ? (
        <div
          className="flex items-center justify-between gap-3 rounded-xl px-4 py-3 mb-3"
          style={{
            backgroundColor: "#FFFBEB",
            border: "1px solid #FDE68A",
            color: "#78350F",
          }}
          data-testid="job-edit-window-banner"
        >
          <div className="text-sm">
            <b>Edit window open.</b> You can fix mistakes on this
            completed job for another{" "}
            <b data-testid="job-edit-window-hours-left">
              {hoursLeft !== null ? hoursLeft.toFixed(1) : "—"}h
            </b>
            . Edits do not re-send customer notifications.
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setEditOpen(true)}
            testid="job-edit-open"
          >
            <Pencil size={14} /> Edit
          </Button>
        </div>
      ) : null}

      {/* Edit History (always visible so admin/tech can review past
          corrections even after the window closes). */}
      <button
        type="button"
        onClick={() => setHistoryOpen((v) => !v)}
        className="w-full flex items-center justify-between text-sm font-semibold py-2 rounded-lg px-3"
        style={{
          backgroundColor: colors.surfaceSubtle,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="job-edit-history-toggle"
      >
        <span className="flex items-center gap-2">
          <History size={14} /> Edit history
          {history?.count ? (
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{ backgroundColor: colors.surface, color: colors.muted }}
              data-testid="job-edit-history-count"
            >
              {history.count}
            </span>
          ) : null}
        </span>
        {historyOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {historyOpen ? (
        <div
          className="rounded-lg p-3 mt-1 space-y-2"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="job-edit-history-body"
        >
          {historyLoading ? (
            <div className="text-sm" style={{ color: colors.muted }}>
              Loading…
            </div>
          ) : history?.error ? (
            <div
              className="text-sm flex items-center gap-2"
              style={{ color: "#991B1B" }}
              data-testid="job-edit-history-error"
            >
              <AlertTriangle size={14} /> {history.error}
            </div>
          ) : (history?.edits || []).length === 0 ? (
            <div
              className="text-sm"
              style={{ color: colors.muted }}
              data-testid="job-edit-history-empty"
            >
              No edits yet.
            </div>
          ) : (
            history.edits.map((row, i) => (
              <div
                key={row.id || i}
                className="text-sm rounded-md p-2"
                style={{
                  backgroundColor: colors.surfaceSubtle,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid={`job-edit-history-row-${i}`}
              >
                <div
                  className="text-xs"
                  style={{ color: colors.muted }}
                >
                  <b style={{ color: colors.onSurface }}>
                    {row.edited_by_name || row.edited_by || "Unknown"}
                  </b>{" "}
                  ({row.edited_by_role}) — {_formatWhen(row.edited_at)}
                  {row.source ? ` · ${row.source}` : ""}
                </div>
                {row.reason ? (
                  <div
                    className="text-xs italic mt-1"
                    style={{ color: colors.muted }}
                    data-testid={`job-edit-history-reason-${i}`}
                  >
                    “{row.reason}”
                  </div>
                ) : null}
                <div className="mt-1 space-y-0.5">
                  {Object.entries(row.changes || {}).map(([field, delta]) => (
                    <div
                      key={field}
                      className="text-xs"
                      style={{ color: colors.onSurface }}
                      data-testid={`job-edit-history-diff-${i}-${field}`}
                    >
                      <span style={{ color: colors.muted }}>{field}:</span>{" "}
                      <s style={{ color: colors.muted }}>
                        {_formatDiff(delta.before)}
                      </s>{" "}
                      → <b>{_formatDiff(delta.after)}</b>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      ) : null}

      {editOpen ? (
        <Modal
          isOpen
          onClose={() => setEditOpen(false)}
          title="Edit completed job"
          testid="job-edit-modal"
        >
          <div className="space-y-3">
            <div
              className="text-xs"
              style={{ color: colors.muted }}
              data-testid="job-edit-modal-hint"
            >
              Edits within the {EDIT_WINDOW_HOURS}h window do NOT
              re-send customer notifications. Larger changes (chemistry,
              checklist) should be made in the Service Report.
            </div>
            <div>
              <label
                className="text-xs font-semibold"
                style={{ color: colors.muted }}
              >
                Notes
              </label>
              <textarea
                className="w-full rounded-md p-2 text-sm mt-1"
                rows={5}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="job-edit-notes-input"
              />
            </div>
            <div>
              <label
                className="text-xs font-semibold"
                style={{ color: colors.muted }}
              >
                Reason (optional)
              </label>
              <input
                type="text"
                className="w-full rounded-md p-2 text-sm mt-1"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g., Fixed typo, added missed detail"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="job-edit-reason-input"
              />
            </div>
            {saveError ? (
              <div
                className="text-sm rounded-md p-2 flex items-start gap-2"
                style={{
                  backgroundColor: "#FEE2E2",
                  color: "#991B1B",
                  border: "1px solid #FCA5A5",
                }}
                data-testid="job-edit-error"
              >
                <AlertTriangle size={14} className="mt-0.5" />
                <span>{saveError}</span>
              </div>
            ) : null}
            <div className="flex justify-end gap-2 pt-2">
              <Button
                variant="ghost"
                onClick={() => setEditOpen(false)}
                testid="job-edit-cancel"
              >
                Cancel
              </Button>
              <Button
                onClick={onSave}
                disabled={saving}
                testid="job-edit-save"
              >
                {saving ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}

      {toast ? (
        <Toast
          tone={toast.tone}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      ) : null}
    </div>
  );
}
