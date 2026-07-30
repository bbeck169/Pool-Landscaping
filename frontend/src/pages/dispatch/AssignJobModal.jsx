// Phase 4 · Feb-2026 — Assign Job popup (day + tech pickers).
//
// Fallback path when the dispatcher cannot / does not want to drag
// the row onto the Route Details drop zone. Also used when the user
// clicks the row's "Assign" button.
import React from "react";
import { toast } from "sonner";
import { X, PlusCircle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const DAYS = [
  { key: "mon", label: "Monday" }, { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" }, { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" }, { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
];

function _isoForDow(dowKey) {
  const order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const target = order.indexOf(dowKey);
  if (target < 0) return null;
  const now = new Date();
  const jsDow = now.getDay();
  const isoDow = jsDow === 0 ? 6 : jsDow - 1;
  const d = new Date(now);
  d.setDate(now.getDate() + (target - isoDow));
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

export default function AssignJobModal({
  open, onClose, onAssigned, job, techs = [],
  defaultTechId = null, defaultDayKey = null,
}) {
  const [techId, setTechId] = React.useState(defaultTechId || "");
  const [dayKey, setDayKey] = React.useState(defaultDayKey || "mon");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setTechId(defaultTechId || (techs[0]?.id || ""));
      setDayKey(defaultDayKey || "mon");
    }
  }, [open, defaultTechId, defaultDayKey, techs]);

  if (!open || !job) return null;

  const submit = async () => {
    if (!techId) { toast.error("Pick a tech."); return; }
    const isoDate = _isoForDow(dayKey);
    if (!isoDate) { toast.error("Pick a day."); return; }
    setBusy(true);
    try {
      const r = await api.post("/dispatch/route/insert", {
        tech_user_id: techId,
        route_date: isoDate,
        job_id: job.id,
      });
      const title = job.title || "Job";
      toast.success(
        `Inserted "${title}" at position ${r.inserted_at + 1}/${r.total_stops} · +${(r.added_distance_km || 0).toFixed(1)} km`,
      );
      onAssigned?.(r);
      onClose?.();
    } catch (e) {
      const detail = e?.body?.detail || e?.message || "Insert failed";
      if (detail === "job_missing_coords") {
        toast.error("Job has no coords — geocode the address first.");
      } else if (detail === "job_already_scheduled") {
        toast.error("Job is already scheduled.");
      } else {
        toast.error(String(detail));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="assign-job-modal"
      role="dialog"
      style={{ position: "fixed", inset: 0, zIndex: 5000,
                background: "rgba(15,23,42,0.6)", display: "flex",
                alignItems: "center", justifyContent: "center" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
    >
      <div style={{
        background: colors.surface || "#FFFFFF", borderRadius: 14,
        width: "min(480px, 96vw)", padding: 24,
        boxShadow: "0 20px 48px rgba(15,23,42,0.24)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <PlusCircle size={18} color={colors.brand || "#0284C7"} />
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                Assign job
              </h2>
            </div>
            <div style={{ fontSize: 13, color: colors.muted, marginTop: 4 }}>
              {job.title || "(untitled)"}
              {job.address ? ` · ${job.address}` : ""}
            </div>
          </div>
          <button data-testid="assign-job-modal-close" onClick={onClose}
                   aria-label="Close"
                   style={{ background: "transparent", border: "none",
                             cursor: "pointer", color: colors.muted }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: colors.muted,
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
            Day
          </label>
          <select
            value={dayKey}
            onChange={(e) => setDayKey(e.target.value)}
            data-testid="assign-job-day"
            style={{ width: "100%", marginTop: 4, padding: "8px 10px",
                      borderRadius: 8, border: `1px solid ${colors.border}`,
                      background: colors.surfaceSecondary,
                      color: colors.onSurface, fontSize: 14 }}
          >
            {DAYS.map((d) => {
              const iso = _isoForDow(d.key);
              return <option key={d.key} value={d.key}>{d.label} ({iso})</option>;
            })}
          </select>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: colors.muted,
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
            Tech
          </label>
          <select
            value={techId}
            onChange={(e) => setTechId(e.target.value)}
            data-testid="assign-job-tech"
            style={{ width: "100%", marginTop: 4, padding: "8px 10px",
                      borderRadius: 8, border: `1px solid ${colors.border}`,
                      background: colors.surfaceSecondary,
                      color: colors.onSurface, fontSize: 14 }}
          >
            <option value="">Select a tech…</option>
            {techs.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>

        {!job.has_coords ? (
          <div style={{ padding: 10, background: "#FEF3C7",
                          border: "1px solid #FDE68A", borderRadius: 8,
                          color: "#92400E", fontSize: 12, marginBottom: 12 }}
                data-testid="assign-job-nocoords-warn">
            This job has no geocoded coordinates. Insert will fail with
            <b> job_missing_coords</b> unless the linked customer has a
            geocoded address.
          </div>
        ) : null}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button data-testid="assign-job-cancel" onClick={onClose}
                   style={{ padding: "10px 16px", background: "transparent",
                             color: colors.muted,
                             border: `1px solid ${colors.border}`,
                             borderRadius: 10, cursor: "pointer",
                             fontSize: 13, fontWeight: 600 }}>
            Cancel
          </button>
          <button data-testid="assign-job-confirm" onClick={submit}
                   disabled={busy || !techId}
                   style={{ padding: "10px 20px",
                             background: busy ? "#94A3B8" : (colors.brand || "#0284C7"),
                             color: "#FFFFFF", border: "none", borderRadius: 10,
                             cursor: busy ? "wait" : "pointer",
                             fontSize: 13, fontWeight: 600 }}>
            {busy ? "Inserting…" : "Insert into route"}
          </button>
        </div>
      </div>
    </div>
  );
}
