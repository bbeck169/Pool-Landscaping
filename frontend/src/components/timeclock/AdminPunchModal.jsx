/**
 * Phase 12 · Feb-2026 — Admin punch create/edit modal.
 *
 * Local-time pickers that serialize to UTC ISO on submit. Required
 * reason textarea (min 3 chars). Source dropdown defaults to
 * ``admin_manual``. Backend validation errors surface inline + via
 * the parent's toast.
 */
import React, { useMemo, useState } from "react";
import { X } from "lucide-react";
import { colors } from "@/theme";


function _toLocalInput(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
           `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return "";
  }
}


function _toUtcISO(localValue) {
  if (!localValue) return null;
  // Parse local-time input (no TZ suffix) as device-local time, then
  // serialize to UTC.
  const d = new Date(localValue);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}


const _SOURCES = ["admin_manual", "web", "mobile"];


export default function AdminPunchModal({
  mode, row, lockedUserId, teamMembers, onCancel, onSave,
}) {
  const isEdit = mode === "edit";
  const [userId, setUserId] = useState(
    lockedUserId || row?.user_id || "",
  );
  const [clockIn, setClockIn] = useState(
    _toLocalInput(row?.clock_in),
  );
  const [clockOut, setClockOut] = useState(
    _toLocalInput(row?.clock_out),
  );
  const [source, setSource] = useState(row?.source || "admin_manual");
  const [reason, setReason] = useState("");
  const [jobId, setJobId] = useState(row?.job_id || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const memberOptions = useMemo(
    () => (teamMembers || []).map((t) => ({
      value: t.user_id, label: t.name || t.user_id,
    })),
    [teamMembers],
  );

  const canSubmit = useMemo(() => {
    if (!reason || reason.trim().length < 3) return false;
    if (!userId) return false;
    if (!isEdit && !clockIn) return false;
    return true;
  }, [reason, userId, clockIn, isEdit]);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const payload = {
        reason: reason.trim(),
        source,
      };
      if (!isEdit) {
        payload.user_id = userId;
        payload.clock_in = _toUtcISO(clockIn);
        if (clockOut) payload.clock_out = _toUtcISO(clockOut);
      } else {
        if (clockIn) payload.clock_in = _toUtcISO(clockIn);
        if (clockOut) {
          payload.clock_out = _toUtcISO(clockOut);
        } else if (row?.clock_out) {
          // Admin cleared the clock_out field — tell the backend to
          // reopen the shift.
          payload.clear_clock_out = true;
        }
      }
      if (jobId) payload.job_id = jobId;
      await onSave(payload);
    } catch (err) {
      setError(err?.message || "Save failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15, 23, 42, 0.6)" }}
      data-testid="admin-punch-modal"
    >
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl p-5 relative"
        style={{ background: colors.surface,
                  border: `1px solid ${colors.border}` }}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-bold"
              style={{ color: colors.onSurface }}>
            {isEdit ? "Edit punch" : "Add punch"}
          </h3>
          <button
            type="button"
            onClick={onCancel}
            className="p-1 rounded-md"
            style={{ color: colors.muted }}
            data-testid="admin-punch-modal-close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold block mb-1"
                    style={{ color: colors.muted }}>
              Team member {isEdit ? "(locked)" : ""}
            </label>
            <select
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              disabled={isEdit}
              className="w-full text-sm px-2 py-1.5 rounded-md"
              style={{ border: `1px solid ${colors.border}`,
                        background: isEdit ? colors.surfaceSecondary
                                              : "#FFFFFF",
                        color: "#0F172A" }}
              data-testid="admin-punch-modal-user"
            >
              <option value="">Select…</option>
              {memberOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold block mb-1"
                    style={{ color: colors.muted }}>
              Clock In (local time)
            </label>
            <input
              type="datetime-local"
              value={clockIn}
              onChange={(e) => setClockIn(e.target.value)}
              className="w-full text-sm px-2 py-1.5 rounded-md"
              style={{ border: `1px solid ${colors.border}`,
                        background: "#FFFFFF", color: "#0F172A" }}
              data-testid="admin-punch-modal-clock-in"
            />
          </div>

          <div>
            <label className="text-xs font-semibold block mb-1"
                    style={{ color: colors.muted }}>
              Clock Out (optional, leave blank for open shift)
            </label>
            <input
              type="datetime-local"
              value={clockOut}
              onChange={(e) => setClockOut(e.target.value)}
              className="w-full text-sm px-2 py-1.5 rounded-md"
              style={{ border: `1px solid ${colors.border}`,
                        background: "#FFFFFF", color: "#0F172A" }}
              data-testid="admin-punch-modal-clock-out"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs font-semibold block mb-1"
                      style={{ color: colors.muted }}>
                Source
              </label>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
                className="w-full text-sm px-2 py-1.5 rounded-md"
                style={{ border: `1px solid ${colors.border}`,
                          background: "#FFFFFF", color: "#0F172A" }}
                data-testid="admin-punch-modal-source"
              >
                {_SOURCES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1"
                      style={{ color: colors.muted }}>
                Job ID (optional)
              </label>
              <input
                type="text"
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
                className="w-full text-sm px-2 py-1.5 rounded-md"
                style={{ border: `1px solid ${colors.border}`,
                          background: "#FFFFFF", color: "#0F172A" }}
                data-testid="admin-punch-modal-job-id"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold block mb-1"
                    style={{ color: colors.muted }}>
              Reason (required, min 3 chars)
            </label>
            <textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Tech forgot to clock out · Correcting duplicate entry"
              className="w-full text-sm px-2 py-1.5 rounded-md"
              style={{ border: `1px solid ${colors.border}`,
                        background: "#FFFFFF", color: "#0F172A" }}
              data-testid="admin-punch-modal-reason"
            />
          </div>

          {error ? (
            <div
              className="text-xs px-2 py-1.5 rounded-md"
              style={{ background: "#FEF2F2",
                        border: "1px solid #FECACA",
                        color: "#B91C1C" }}
              data-testid="admin-punch-modal-error"
            >
              {error}
            </div>
          ) : null}
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="text-sm px-3 py-1.5 rounded-md"
            style={{ background: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface }}
            data-testid="admin-punch-modal-cancel"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit || submitting}
            className="text-sm font-semibold px-3 py-1.5 rounded-md"
            style={{ background: canSubmit && !submitting
                      ? colors.brand : colors.surfaceSecondary,
                      color: canSubmit && !submitting
                      ? "#fff" : colors.muted,
                      border: 0,
                      cursor: canSubmit && !submitting
                      ? "pointer" : "not-allowed" }}
            data-testid="admin-punch-modal-submit"
          >
            {submitting ? "Saving…" : isEdit ? "Save changes" : "Create punch"}
          </button>
        </div>
      </form>
    </div>
  );
}
