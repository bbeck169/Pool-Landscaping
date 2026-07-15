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

// Phase 39 · Step 2 — Visit Recap prompt shown after Close Job succeeds.
import VisitRecapModal from "./VisitRecapModal";

// Phase 36 — mini relative-time formatter for the autosave "Saved 3s ago"
// caption on the pill.
const _fmtRelSaved = (d) => {
  if (!d) return "";
  try {
    const ms = Date.now() - d.getTime();
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    return d.toLocaleTimeString();
  } catch { return ""; }
};
import { Loader2, Save, ShieldCheck, X } from "lucide-react";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { getChecklistType } from "@/lib/checklistType";
import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";
import LandscapingChecklistForm from "@/components/checklist/LandscapingChecklistForm";
import GenericChecklistForm from "@/components/checklist/GenericChecklistForm";
import PhotoUploader from "@/components/checklist/PhotoUploader";

const AUTOSAVE_DEBOUNCE_MS = 800;
// Phase 37 — minimum time the pill stays on "Saving…" so techs actually
// see the state change after a chip tap. Prevents the pill from flashing
// through "saving → saved" faster than the eye can register.
const MIN_SAVING_MS = 400;
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
  // Phase 37 — track when "Saving…" was first shown, so the pill holds
  // for at least MIN_SAVING_MS before flipping to "Saved". Techs need to
  // actually see the transition after a chip tap.
  const savingShownAtRef = useRef(0);
  // Phase 34e third hotfix — reportRef mirrors the latest `report` state
  // so the debounced autosave never PATCHes with a stale closure snapshot.
  const reportRef = useRef(null);
  // Phase 36 — track the last successful save so the autosave pill can
  // render a relative "Saved 3s ago" caption.
  const [lastSavedAt, setLastSavedAt] = useState(null);
  // Phase 39 · Step 2 — Visit Recap modal state. Populated on close-job
  // success so the tech can text/email the customer without leaving
  // the checklist context.
  const [recapOpen, setRecapOpen] = useState(false);
  const [recapCustomer, setRecapCustomer] = useState(null);

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
      setJob(j); setReport(r); reportRef.current = r;
    }).catch((e) => {
      if (cancelled) return;
      setLoadErr(e?.message || "Unable to load checklist.");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, jobId, canWrite]);

  const flushSave = useCallback(async () => {
    const cur = reportRef.current;
    if (!cur || cur.submitted_at) return;
    if (!dirtyRef.current || savingRef.current) return;
    savingRef.current = true;
    // If patchReport already flipped us to "saving", keep the timestamp;
    // otherwise stamp it now so the min-hold still applies.
    if (!savingShownAtRef.current) savingShownAtRef.current = Date.now();
    setSaveState("saving");
    try {
      const patched = await api.patch(`/jobs/${jobId}/service-report`, {
        chemical_readings: cur.chemical_readings,
        chemicals_added: cur.chemicals_added,
        checklist_items: cur.checklist_items,
        notes: cur.notes,
      });
      if (patched && typeof patched === "object") {
        setReport(patched);
        reportRef.current = patched;
      }
      dirtyRef.current = false;
      // Hold "Saving…" for at least MIN_SAVING_MS before flipping to
      // "Saved", so the transition is visible to the tech.
      const elapsed = Date.now() - (savingShownAtRef.current || Date.now());
      const holdMs = Math.max(0, MIN_SAVING_MS - elapsed);
      setTimeout(() => {
        setSaveState("saved");
        setLastSavedAt(new Date());
        savingShownAtRef.current = 0;
        setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1200);
      }, holdMs);
    } catch (e) {
      setSaveState("error");
      savingShownAtRef.current = 0;
    } finally {
      savingRef.current = false;
    }
  }, [jobId]);

  const scheduleAutosave = useCallback(() => {
    dirtyRef.current = true;
    // Phase 37 — flip the pill to "saving" immediately on any edit, so
    // the tech sees feedback even before the 800ms debounce window ends.
    if (!savingRef.current) {
      savingShownAtRef.current = Date.now();
      setSaveState("saving");
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => { flushSave(); }, AUTOSAVE_DEBOUNCE_MS);
  }, [flushSave]);

  const patchReport = useCallback((patch) => {
    setReport((prev) => {
      const next = { ...prev, ...patch };
      reportRef.current = next;
      return next;
    });
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
      // Phase 39 · Step 2 — before auto-closing, pop the Visit Recap prompt.
      // We need contact info; fetch the customer inline (cheap, one round-trip).
      try {
        if (job?.customer_id) {
          const cust = await api.get(`/customers/${job.customer_id}`);
          setRecapCustomer({
            id: cust?.id, name: cust?.name,
            email: cust?.email, phone: cust?.phone,
            alert_phone: cust?.alert_phone,
          });
        } else {
          setRecapCustomer({ name: job?.customer_name });
        }
      } catch { setRecapCustomer({ name: job?.customer_name }); }
      setRecapOpen(true);
      // Do NOT auto-close the checklist modal yet — the recap modal is
      // rendered on top and will close everything when the tech chooses
      // Send or Skip. See `handleRecapClose` below.
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
        <div
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider"
          style={{
            background:
              saveState === "saving" ? "rgba(255,255,255,0.18)"
              : saveState === "saved" ? "rgba(16,185,129,0.22)"
              : saveState === "error" ? "rgba(220,38,38,0.28)"
              : "rgba(255,255,255,0.1)",
            color: "#fff",
            border: saveState === "error" ? "1px solid #fecaca" : "1px solid transparent",
          }}
          data-testid="checklist-autosave-pill"
          data-savestate={saveState}
        >
          {saveState === "saving" ? (
            <>
              <span
                style={{
                  width: 10, height: 10, borderRadius: "50%",
                  border: "2px solid rgba(255,255,255,0.35)",
                  borderTopColor: "#fff",
                  animation: "spin 0.7s linear infinite",
                  display: "inline-block",
                }}
              />
              <span>Saving…</span>
              <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
            </>
          ) : saveState === "saved" ? (
            <>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#10b981" }} />
              <span>Saved</span>
              {lastSavedAt ? (
                <span style={{ opacity: 0.75 }}>· {_fmtRelSaved(lastSavedAt)}</span>
              ) : null}
            </>
          ) : saveState === "error" ? (
            <>
              <span style={{ color: "#fecaca" }}>✕</span>
              <span>Save failed</span>
              <button
                type="button"
                onClick={() => { dirtyRef.current = true; flushSave(); }}
                className="ml-1 underline"
                style={{ background: "transparent", border: 0, color: "#fff", cursor: "pointer", font: "inherit" }}
                data-testid="checklist-autosave-retry"
              >
                Retry
              </button>
            </>
          ) : (
            <span style={{ opacity: 0.7 }}>Ready</span>
          )}
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
            onPhotosChange={(next) => {
              const nr = { ...report, photos: next };
              setReport(nr);
              reportRef.current = nr;
            }}
            max={PHOTO_CAP}
            disabled={locked}
          />
        </div>

        {clientType === "pool" && (
          <PoolChecklistForm
            jobId={String(jobId)}
            customerId={job?.customer_id}
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

  return (
    <>
      {backdrop}
      {recapOpen && report?.id ? (
        <VisitRecapModal
          serviceReportId={report.id}
          customer={recapCustomer}
          onClose={() => { setRecapOpen(false); onClose?.(); }}
        />
      ) : null}
    </>
  );
}
