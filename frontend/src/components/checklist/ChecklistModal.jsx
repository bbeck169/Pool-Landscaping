/**
 * Phase 31 · Step 2b — ChecklistModal (web).
 *
 * Opens over the Schedule when a tech (or admin) taps a job on the
 * Grid row body or the react-big-calendar event. Loads job + service
 * report in parallel, resolves the template via `getChecklistType(job)`
 * (shared helper), and mounts the matching form. Autosaves via a
 * debounced PATCH; closes the job via the submit endpoint and fires
 * a workstream telemetry event on success.
 *
 * All endpoints are pre-existing (Step 1 discovery). No new backend.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Save, ShieldCheck, X } from "lucide-react";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { getChecklistType } from "@/lib/checklistType";
import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";
import LandscapingChecklistForm from "@/components/checklist/LandscapingChecklistForm";
import GenericChecklistForm from "@/components/checklist/GenericChecklistForm";
import PhotoUploader from "@/components/checklist/PhotoUploader";

const AUTOSAVE_DEBOUNCE_MS = 800;
const PHOTO_CAP = 10;

const c = {
  brand: "#0EA5E9",
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#FFFFFF",
  surfaceAlt: "#F8FAFC",
  danger: "#DC2626",
  onSurface: "#0F172A",
  successBg: "#D1FAE5",
  successFg: "#065F46",
  errBg: "#FEE2E2",
  errFg: "#991B1B",
  warnBg: "#FEF3C7",
  warnFg: "#92400E",
};

export default function ChecklistModal({ jobId, open, onClose, onSubmitted }) {
  const { user } = useAuth();
  const role = user?.role || "";
  const canWrite = role === "admin" || role === "super_admin" || role === "technician";

  const [job, setJob] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [saveState, setSaveState] = useState("idle"); // idle|saving|saved|error
  const [submitting, setSubmitting] = useState(false);
  const [wsWarning, setWsWarning] = useState("");

  const dirtyRef = useRef(false);
  const savingRef = useRef(false);
  const timerRef = useRef(null);

  // Reset when the modal closes / re-opens for a different job.
  useEffect(() => {
    if (!open) {
      setJob(null); setReport(null); setLoadErr("");
      setSaveState("idle"); setWsWarning("");
      dirtyRef.current = false;
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    }
  }, [open]);

  // Load job + service-report.
  useEffect(() => {
    if (!open || !jobId || !canWrite) return;
    let cancelled = false;
    setLoading(true); setLoadErr("");
    Promise.all([
      api.get(`/jobs/${jobId}`),
      api.get(`/jobs/${jobId}/service-report`),
    ]).then(([j, r]) => {
      if (cancelled) return;
      setJob(j); setReport(r);
    }).catch((e) => {
      if (cancelled) return;
      setLoadErr(e?.message || "Unable to load checklist.");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, jobId, canWrite]);

  const flushSave = useCallback(async () => {
    if (!report || report.submitted_at) return;
    if (!dirtyRef.current || savingRef.current) return;
    savingRef.current = true;
    setSaveState("saving");
    try {
      const patched = await api.patch(`/jobs/${jobId}/service-report`, {
        chemical_readings: report.chemical_readings,
        chemicals_added: report.chemicals_added,
        checklist_items: report.checklist_items,
        notes: report.notes,
      });
      if (patched && typeof patched === "object") setReport(patched);
      dirtyRef.current = false;
      setSaveState("saved");
      setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1200);
    } catch (e) {
      setSaveState("error");
    } finally {
      savingRef.current = false;
    }
  }, [jobId, report]);

  const scheduleAutosave = useCallback(() => {
    dirtyRef.current = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => { flushSave(); }, AUTOSAVE_DEBOUNCE_MS);
  }, [flushSave]);

  const patchReport = useCallback((patch) => {
    setReport((prev) => ({ ...prev, ...patch }));
    scheduleAutosave();
  }, [scheduleAutosave]);

  const saveDraft = async () => {
    dirtyRef.current = true;
    await flushSave();
  };

  const closeJob = async () => {
    if (!report || submitting) return;
    // eslint-disable-next-line no-alert
    const ok = window.confirm("Close job? Customer will see final report.");
    if (!ok) return;
    setSubmitting(true); setWsWarning("");
    try {
      // 1) Final PATCH flush.
      dirtyRef.current = true;
      await flushSave();
      // 2) Submit / close.
      const submitted = await api.post(`/jobs/${jobId}/service-report/submit`, {});
      // 3) Fire workstream event — best effort.
      const template = getChecklistType(job);
      try {
        await api.post("/workstream/events", {
          type: "job.completed",
          payload: {
            job_id: jobId,
            customer_name: job?.customer_name,
            tech_name: user?.name || user?.email,
            service_type: job?.service_type,
            chemicals_added_count: (report.chemicals_added || []).length,
            photos_count: (report.photos || []).length,
            template,
          },
          related_ref: { type: "job", id: String(jobId) },
        });
      } catch (e) {
        setWsWarning(`Job closed, workstream event failed: ${e?.message || "unknown"}`);
      }
      if (onSubmitted) onSubmitted(submitted);
      // Auto-close only if the workstream event succeeded — otherwise
      // keep the modal open so the tech can see the warning banner.
      if (!wsWarning) onClose?.();
    } catch (e) {
      // eslint-disable-next-line no-alert
      alert(`Close failed: ${e?.message || "Try again."}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  // ─── Overlay + shell ────────────────────────────────────────────────
  const backdrop = (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 50,
        background: "rgba(15,23,42,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
      data-testid="checklist-modal-backdrop"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: c.surface, borderRadius: 12,
          width: "min(760px, 96vw)", maxHeight: "92vh",
          display: "flex", flexDirection: "column",
          boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
        }}
        data-testid="checklist-modal"
      >
        {renderHeader()}
        {renderBody()}
        {renderFooter()}
      </div>
    </div>
  );

  function renderHeader() {
    const clientType = job ? getChecklistType(job) : "";
    const backendKind = report?.template || "";
    return (
      <div
        className="flex items-center gap-3 px-5 py-4"
        style={{ borderBottom: `1px solid ${c.border}`, background: c.brand, color: "#fff", borderTopLeftRadius: 12, borderTopRightRadius: 12 }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="text-[10px] font-bold uppercase tracking-wider opacity-90"
               data-testid="checklist-modal-template-label">
            {clientType || "…"}{backendKind ? ` · backend:${backendKind}` : ""}
            {report?.submitted_at ? " · LOCKED" : ""}
          </div>
          <div className="text-base font-bold truncate">
            {job?.title || job?.service_type || "Job Checklist"}
          </div>
          <div className="text-xs opacity-90 truncate">
            {job?.customer_name || "—"}{job?.address ? ` · ${job.address}` : ""}
          </div>
        </div>
        <div className="text-[10px] font-bold uppercase" data-testid="checklist-save-state">
          {saveState === "saving" ? "Saving…"
            : saveState === "saved" ? "Saved"
            : saveState === "error" ? "Save error"
            : "Ready"}
        </div>
        <button
          type="button"
          onClick={onClose}
          style={{ background: "transparent", border: 0, cursor: "pointer", color: "#fff" }}
          aria-label="Close"
          data-testid="checklist-modal-close"
        >
          <X size={18} />
        </button>
      </div>
    );
  }

  function renderBody() {
    if (!canWrite) {
      return (
        <div className="p-6 text-sm" data-testid="checklist-forbidden"
             style={{ color: c.muted }}>
          You don't have permission to open this checklist.
        </div>
      );
    }
    if (loading) {
      return (
        <div className="p-10 flex items-center justify-center" data-testid="checklist-loading">
          <Loader2 size={22} className="animate-spin" color={c.brand} />
        </div>
      );
    }
    if (loadErr) {
      return (
        <div className="p-6 text-sm" data-testid="checklist-error"
             style={{ color: c.errFg, background: c.errBg, borderRadius: 8, margin: 16 }}>
          {loadErr}
        </div>
      );
    }
    if (!report || !job) return null;

    const clientType = getChecklistType(job);
    const locked = !!report.submitted_at;

    return (
      <div style={{ overflow: "auto", padding: 20 }}>
        {wsWarning ? (
          <div className="text-xs px-3 py-2 rounded mb-3"
               style={{ color: c.warnFg, background: c.warnBg }}
               data-testid="checklist-workstream-warning">
            {wsWarning}
          </div>
        ) : null}

        <div className="mb-4 rounded-lg p-3"
             style={{ border: `1px solid ${c.border}`, background: c.surfaceAlt }}
             data-testid="checklist-photos-card">
          <div className="text-sm font-bold mb-2" style={{ color: c.onSurface }}>Photos</div>
          <PhotoUploader
            jobId={String(jobId)}
            photos={report.photos || []}
            onPhotosChange={(next) => setReport({ ...report, photos: next })}
            max={PHOTO_CAP}
            disabled={locked}
          />
        </div>

        {clientType === "pool" && (
          <PoolChecklistForm
            jobId={String(jobId)}
            locked={locked}
            readings={report.chemical_readings || []}
            chemicalsAdded={report.chemicals_added || []}
            chemicalsCatalog={report.chemicals_catalog || []}
            chemicalUnits={report.chemical_units || ["gal", "lbs", "oz", "tabs"]}
            checklistItems={report.checklist_items || []}
            notes={report.notes || ""}
            onChange={patchReport}
          />
        )}
        {clientType === "landscaping" && (
          <LandscapingChecklistForm
            locked={locked}
            checklistItems={report.checklist_items || []}
            notes={report.notes || ""}
            onChange={patchReport}
          />
        )}
        {clientType === "generic" && (
          <GenericChecklistForm
            locked={locked}
            checklistItems={report.checklist_items || []}
            workPerformed={report.work_performed || ""}
            notes={report.notes || ""}
            onChange={(patch) => {
              if ("work_performed" in patch) {
                const wp = patch.work_performed || "";
                const currentNotes = report.notes || "";
                const marker = "[Work Performed]";
                const rx = /\[Work Performed\][\s\S]*?(?=\n\n|$)/;
                let mergedNotes = currentNotes;
                if (rx.test(mergedNotes)) {
                  mergedNotes = mergedNotes.replace(rx, `${marker}\n${wp}`);
                } else {
                  mergedNotes = wp
                    ? `${marker}\n${wp}${currentNotes ? "\n\n" + currentNotes : ""}`
                    : currentNotes;
                }
                patchReport({ work_performed: wp, notes: mergedNotes });
                return;
              }
              patchReport(patch);
            }}
          />
        )}
      </div>
    );
  }

  function renderFooter() {
    if (!report || !canWrite || loadErr) return null;
    if (report.submitted_at) {
      return (
        <div className="px-5 py-3 text-xs" style={{ borderTop: `1px solid ${c.border}`, color: c.muted, background: c.surfaceAlt }}>
          Report submitted {new Date(report.submitted_at).toLocaleString()} — read-only.
        </div>
      );
    }
    return (
      <div className="px-5 py-3 flex items-center gap-2"
           style={{ borderTop: `1px solid ${c.border}`, background: c.surfaceAlt }}>
        <button
          type="button"
          onClick={saveDraft}
          disabled={submitting}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-bold"
          style={{
            border: `1px solid ${c.brand}`, background: c.surface, color: c.brand,
            cursor: submitting ? "wait" : "pointer",
          }}
          data-testid="checklist-save-draft"
        >
          <Save size={14} /> Save draft
        </button>
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={closeJob}
          disabled={submitting}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-bold"
          style={{
            border: 0, background: c.brand, color: "#fff",
            cursor: submitting ? "wait" : "pointer",
            opacity: submitting ? 0.7 : 1,
          }}
          data-testid="checklist-close-job"
        >
          {submitting
            ? <Loader2 size={14} className="animate-spin" />
            : <ShieldCheck size={14} />}
          {submitting ? "Closing…" : "Close job"}
        </button>
      </div>
    );
  }

  return backdrop;
}
