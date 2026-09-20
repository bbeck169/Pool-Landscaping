/**
 * Phase C1 · Feb-2026 — admin follow-up controls on JobDetail.
 *
 * Small panel that lets admin/super_admin/manager tune the
 * ``follow_up_at`` / ``needs_follow_up`` values that surface on
 * the Sales Pipeline Follow-up column. Non-admin/manager roles
 * never see this component — the parent gates the render.
 *
 * Contract
 * --------
 * *   `job` — current job document (accepts snake_case keys).
 * *   `onSaved(nextJob)` — parent reloads the job after save.
 * *   `onToast({tone, message})` — parent surfaces toasts.
 */
import React, { useMemo, useState, useEffect } from "react";
import { CalendarClock, Save } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";


function _isoToDatetimeLocal(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    // Trim to "YYYY-MM-DDTHH:MM" for <input type="datetime-local">.
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
      d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return "";
  }
}


function _datetimeLocalToIso(v) {
  if (!v) return "";
  try {
    return new Date(v).toISOString();
  } catch {
    return "";
  }
}


export default function FollowUpEditor({ job, onSaved, onToast }) {
  const initialFu = useMemo(
    () => _isoToDatetimeLocal(job?.follow_up_at || ""),
    [job?.follow_up_at],
  );
  const [followUp, setFollowUp]     = useState(initialFu);
  const [needs,    setNeeds]        = useState(!!job?.needs_follow_up);
  const [saving,   setSaving]       = useState(false);

  useEffect(() => {
    setFollowUp(_isoToDatetimeLocal(job?.follow_up_at || ""));
    setNeeds(!!job?.needs_follow_up);
  }, [job?.follow_up_at, job?.needs_follow_up]);

  const onSave = async () => {
    setSaving(true);
    try {
      const body = { needs_follow_up: !!needs };
      if (followUp) {
        body.follow_up_at = _datetimeLocalToIso(followUp);
      }
      await api.put(`/jobs/${job.id}`, body);
      onToast?.({ tone: "success", message: "Follow-up saved" });
      onSaved?.();
    } catch (e) {
      onToast?.({ tone: "error",
                  message: e?.message || "Failed to save follow-up" });
    } finally {
      setSaving(false);
    }
  };

  const auto = job?.follow_up_at
    && !job?.needs_follow_up_manually_set
    ? "Auto-populated from job completion — override any time."
    : "";

  return (
    <section
      className="rounded-xl p-4 mt-4"
      style={{ background: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid="jd-follow-up-editor"
    >
      <div className="flex items-center gap-2 mb-2">
        <CalendarClock size={16} style={{ color: colors.brand }} />
        <h3 className="text-sm font-semibold"
             style={{ color: colors.onSurface }}>
          Follow-up
        </h3>
      </div>
      <p className="text-xs mb-3"
          style={{ color: colors.muted }}>
        Shown in <span className="font-semibold">Sales Pipeline →
        Follow-up</span> column.
      </p>

      <label className="flex flex-col text-xs mb-3"
              style={{ color: colors.onSurfaceSecondary }}>
        <span>Follow-up date &amp; time</span>
        <input
          type="datetime-local"
          value={followUp}
          onChange={(e) => setFollowUp(e.target.value)}
          data-testid="jd-follow-up-at-input"
          className="mt-1 rounded-lg px-2 py-1 text-sm"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    color: colors.onSurface }}
        />
      </label>

      <label className="flex items-center gap-2 text-xs mb-3"
              style={{ color: colors.onSurfaceSecondary }}
              data-testid="jd-needs-follow-up-toggle">
        <input
          type="checkbox"
          checked={needs}
          onChange={(e) => setNeeds(e.target.checked)}
          data-testid="jd-needs-follow-up-checkbox"
        />
        <span>Flag this job as needing follow-up</span>
      </label>

      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        data-testid="jd-follow-up-save-btn"
        className="inline-flex items-center gap-1 text-xs rounded-full px-3 py-1"
        style={{ background: colors.brand,
                  color: colors.onBrandPrimary || "#FFFFFF",
                  opacity: saving ? 0.6 : 1 }}
      >
        <Save size={12} />
        {saving ? "Saving…" : "Save follow-up"}
      </button>

      {job?.follow_up_at ? (
        <div className="mt-3 text-[11px]"
              style={{ color: colors.muted }}
              data-testid="jd-follow-up-current-value">
          Current server value: <span className="font-mono">
            {job.follow_up_at}
          </span>
          {auto ? ` · ${auto}` : ""}
        </div>
      ) : null}
    </section>
  );
}
