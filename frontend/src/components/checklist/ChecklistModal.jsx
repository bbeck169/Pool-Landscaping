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
import { toast } from "sonner";
import { mustConfirm } from "@/components/ui/confirm-dialog";

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

// Phase 50.B — compute display names of readings whose current value is
// more than 2× or less than 0.5× the rolling median of the last 4
// submitted values for the customer. Returns [] when nothing looks off.
async function _computeOutlierNames(report, job) {
  const customerId = job?.customer_id || report?.job?.customer_id;
  if (!customerId) return [];
  const readings = report?.chemical_readings || [];
  if (!readings.length) return [];
  const res = await api.get(`/service-reports/last-readings?customer_id=${customerId}`);
  const recentMap = res?.recent_readings || {};
  const outliers = [];
  for (const r of readings) {
    const val = Number(r?.value);
    if (!Number.isFinite(val) || val <= 0) continue;
    const key = String(r?.key || r?.name || "").toLowerCase();
    const arr = (recentMap[key] || recentMap[r?.key] || recentMap[r?.name] || [])
      .filter((x) => Number.isFinite(x));
    if (arr.length < 2) continue;
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    if (!median) continue;
    if (val > 2 * median || val < 0.5 * median) {
      outliers.push(r?.name || key);
    }
  }
  return outliers;
}
import { Loader2, Save, ShieldCheck, X } from "lucide-react";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { getChecklistType } from "@/lib/checklistType";
// Phase P45 · Feb-2026 — client-side idempotency-key belt to the
// backend atomic-stamp gate.  Same UUID sits on every submit
// attempt for one form session; regenerates on success so a
// reopen-and-resubmit flow is treated as a new action.
import { useIdempotencyKey } from "@/hooks/useIdempotencyKey";
import { AddressLink } from "@/components/customer";
// Phase MI1.1 · Feb 2026 — non-pool / non-landscape jobs are routed
// through the industry-aware form so HVAC / Pest / Cleaning / Solar
// / Handyman techs stop seeing the Pool template.
// Phase D2 · Feb 2026 — the ``NEW_INDUSTRIES`` set below is derived
// from ``CANONICAL_INDUSTRIES`` so future additions to the canonical
// list flow into the dispatcher without a second edit here.
import {
  deriveIndustryForJob,
  CANONICAL_INDUSTRIES,
} from "@/lib/deriveIndustry";
import IndustryChecklistForm from "@/components/checklist/IndustryChecklistForm";
import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";
import WaterBodyManager from "@/components/checklist/WaterBodyManager";
import LandscapingChecklistForm from "@/components/checklist/LandscapingChecklistForm";
// Phase MI1.1 · Feb 2026 — legacy fallback form kept only for the
// mocked test (``checklist-modal-backdrop-dirty-guard``). The
// dispatcher below routes generic jobs through IndustryChecklistForm
// now, so the import must remain to satisfy the vi.mock() contract.
// eslint-disable-next-line no-unused-vars
import GenericChecklistForm from "@/components/checklist/GenericChecklistForm";
import PhotoUploader from "@/components/checklist/PhotoUploader";
// Phase W1 · Feb-2026 — dirty-close confirm now lives in a shared
// component so the wizard can mount an identical dialog. C1 / C1.1
// testids are preserved via default props on the shared component.
import DirtyCloseConfirm from "@/components/checklist/DirtyCloseConfirm";

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
  // Phase P45 · idempotency-key.  Stable across the session and
  // across retries after network errors.  ``regenerate()`` is
  // called on submit SUCCESS below so a reopen-and-resubmit is
  // treated as a distinct action.
  const { headers: idempotencyHeaders, regenerate: regenerateIdempotencyKey } =
    useIdempotencyKey();

  const [job, setJob] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [saveState, setSaveState] = useState("idle"); // idle|saving|saved|error
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
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

  // Phase C1 · Feb-2026 — guarded close.  ``dirtyRef.current`` already
  // tracks every autosave-worthy edit (scheduleAutosave sets it true,
  // successful flushSave sets it false).  ``attemptClose`` intercepts
  // the three implicit-close triggers (backdrop tap, header "×",
  // Escape key) and either closes silently on a clean form OR opens
  // a small Discard confirm on a dirty form.  Explicit save-then-exit
  // paths (Save & exit button, submit success, recap dismissal)
  // still call ``onClose`` directly — they're not implicit closes.
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  // Phase C1.1 · Feb-2026 — in-flight save-and-close state so the
  // Discard dialog can disable its destructive path while a
  // flushSave() is running.  ``isSaving`` is a state (not a ref)
  // because the dialog's disabled/label attributes need to react.
  const [isSaving, setIsSaving] = useState(false);
  const attemptClose = useCallback(() => {
    if (!open) return;
    if (dirtyRef.current) {
      setDiscardConfirmOpen(true);
    } else {
      onClose?.();
    }
  }, [open, onClose]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      // Ignore Esc while the Discard confirm itself is open —
      // that dialog handles its own dismissal path.
      if (e.key === "Escape" && !discardConfirmOpen) {
        e.stopPropagation();
        attemptClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, discardConfirmOpen, attemptClose]);

  // Reset when the modal closes / re-opens for a different job.
  useEffect(() => {
    if (!open) {
      setJob(null); setReport(null); setLoadErr("");
      setSaveState("idle"); setWsWarning(""); setSubmitError("");
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
      // Feb-2026 · Multi-body Phase 2 — include ``water_bodies`` in the
      // PATCH when the report has any (Phase 1 backend seeds body[0] on
      // bootstrap, so this is effectively always set). Legacy single-
      // body flows still send the top-level fields as the source of
      // truth; the backend keeps them mirrored automatically. When both
      // are present, the backend validates + rebuilds the mirrors from
      // ``water_bodies`` (per Phase 1 spec).
      const patchPayload = {
        chemical_readings: cur.chemical_readings,
        chemicals_added: cur.chemicals_added,
        checklist_items: cur.checklist_items,
        notes: cur.notes,
        // Phase 56.6 — persist wizard cursor + internal notes + photos
        // through the autosave loop; otherwise the response replaces the
        // in-memory report and wipes these fields on every save.
        internal_notes: cur.internal_notes || "",
        // Phase 56.16 — customer_notes is a distinct customer-facing
        // textarea on the landscape form; pool wizard step 5 will
        // pick it up later.
        customer_notes: cur.customer_notes || "",
        photos: cur.photos || [],
        wizard_step: cur.wizard_step ?? 1,
      };
      if (Array.isArray(cur.water_bodies) && cur.water_bodies.length > 0) {
        patchPayload.water_bodies = cur.water_bodies;
      }
      const patched = await api.patch(
        `/jobs/${jobId}/service-report`,
        patchPayload,
      );
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
    } catch (_e) {
      setSaveState("error");
      savingShownAtRef.current = 0;
    } finally {
      savingRef.current = false;
    }
  }, [jobId]);

  // Phase C1.1 · Feb-2026 — Save & close primary path.  ``flushSave``
  // swallows its own errors and flips ``dirtyRef.current`` to false
  // ONLY on success, so we can trust that flag as the post-condition:
  //   * dirtyRef.current === false   → save succeeded → close
  //   * dirtyRef.current === true    → save failed → keep modal open
  //                                     + surface a truthful toast
  const saveAndClose = useCallback(async () => {
    setIsSaving(true);
    try {
      await flushSave();
    } finally {
      setIsSaving(false);
    }
    if (!dirtyRef.current) {
      setDiscardConfirmOpen(false);
      onClose?.();
    } else {
      toast.error(
        "Couldn't save your changes — please check your connection and try again.",
      );
    }
  }, [flushSave, onClose]);


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

  // Feb-2026 · Checklist reclassifier — invoked from the Chemical
  // Readings empty-state picker when the tech (or admin) retags a
  // misclassified job. Writes `service_type` on the job via the
  // existing `PUT /api/jobs/{jid}` endpoint (Feb-2026 model whitelist
  // extension), then re-fetches BOTH the job + the service-report so
  // the reading-field matrix repopulates from the fresh template.
  const handleReclassify = useCallback(async (nextServiceType) => {
    if (!jobId || !nextServiceType) return;
    // Flush any pending checklist edits before we swap in a new
    // report snapshot — otherwise the autosave-in-flight would race
    // the refetch and stomp the newly-hydrated `chemical_reading_fields`.
    try { await flushSave(); } catch { /* non-blocking */ }
    await api.put(`/jobs/${jobId}`, { service_type: nextServiceType });
    const [j, r] = await Promise.all([
      api.get(`/jobs/${jobId}`),
      api.get(`/jobs/${jobId}/service-report`),
    ]);
    setJob(j);
    setReport(r);
    reportRef.current = r;
    dirtyRef.current = false;
    setSaveState("idle");
  }, [jobId, flushSave]);

  const saveDraft = async () => {
    dirtyRef.current = true;
    await flushSave();
  };

  const closeJob = async () => {
    if (!report || submitting) return;
    // Phase 50.B — if any reading is an outlier vs recent median,
    // show a Radix confirm before the regular Close-job confirm.
    try {
      const outlierNames = await _computeOutlierNames(report, job);
      if (outlierNames.length > 0) {
        const proceed = await mustConfirm({
          title: "One of your readings looks off — proceed anyway?",
          description: `The following look out-of-range vs recent visits: ${outlierNames.join(", ")}. Double-check before closing?`,
          confirmText: "Proceed anyway",
          cancelText: "Let me recheck",
          tone: "default",
        });
        if (!proceed) return;
      }
    } catch (_e) {
      // Non-blocking — a network hiccup fetching recent readings must
      // never prevent the tech from closing a job.
    }
    // Phase 31 · Step 2c — Radix-driven confirm (was window.confirm).
    const ok = await mustConfirm({
      title: "Close job?",
      description: "Customer will see final report.",
      confirmText: "Close job",
      tone: "danger",
    });
    if (!ok) return;
    setSubmitting(true); setWsWarning(""); setSubmitError("");
    try {
      // 1) Final PATCH flush.
      dirtyRef.current = true;
      await flushSave();
      // 2) Submit / close.
      // Phase P45 · pass X-Idempotency-Key via api.request so the
      // backend replay guard treats a network-retry as a dedupe hit.
      const submitted = await api.request(
        `/jobs/${jobId}/service-report/submit`,
        { method: "POST", body: JSON.stringify({}),
          headers: idempotencyHeaders },
      );
      // Regenerate for the NEXT submission (e.g. if the user
      // reopens the form and edits) — a new action gets a new key.
      regenerateIdempotencyKey();
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
      // Feb-2026 · Multi-body Phase 2 — surface backend 422s for the
      // chemistry gate + water-body allow-list breaches inline instead
      // of a plain `alert("Close failed: …")` string. The gate returns
      // ``detail: { detail: "chemistry_core_readings_missing", missing_fields, missing_labels, message }``;
      // allow-list breaches return ``detail: { message, index, type, key|slug }``.
      const raw = e?.detail || e?.data?.detail || e?.body?.detail || null;
      if (raw && typeof raw === "object") {
        if (raw.detail === "chemistry_core_readings_missing") {
          const missing = (raw.missing_labels || raw.missing_fields || []).join(", ");
          setSubmitError(
            missing
              ? `Missing required pool readings: ${missing}. Fill them on the primary Pool body before closing.`
              : (raw.message || "Missing required pool readings."),
          );
          // Highlight the primary body — it's always the pool one.
          try {
            const el = document.querySelector('[data-testid="water-body-manager"]');
            if (el && typeof el.scrollIntoView === "function") {
              el.scrollIntoView({ behavior: "smooth", block: "start" });
            }
          } catch { /* jsdom / older browsers */ }
        } else if (raw.message === "reading_not_allowed_for_body_type"
                    || raw.message === "chemical_not_allowed_for_body_type") {
          const bodyIdx = raw.index ?? 0;
          const detail = raw.key || raw.slug || "";
          setSubmitError(
            `Body #${bodyIdx + 1} (${raw.type || "?"}) has a disallowed ${raw.key ? "reading" : "chemical"}` +
            (detail ? `: ${detail}` : "") +
            ". Remove it before closing.",
          );
          try {
            const el = document.querySelector(`[data-testid="water-body-panel-${bodyIdx}"]`);
            if (el && typeof el.scrollIntoView === "function") {
              el.scrollIntoView({ behavior: "smooth", block: "start" });
            }
          } catch { /* jsdom / older browsers */ }
        } else {
          setSubmitError(raw.message || e?.message || "Close failed.");
        }
      } else {
        setSubmitError(e?.message || "Close failed. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  // ─── Overlay + shell ────────────────────────────────────────────────
  const backdrop = (
    <div
      onClick={attemptClose}
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
          position: "relative",   /* Phase C1 · anchor the Discard confirm overlay */
        }}
        data-testid="checklist-modal"
      >
        {renderHeader()}
        {renderBody()}
        {renderFooter()}
        <DirtyCloseConfirm
          open={discardConfirmOpen}
          isSaving={isSaving}
          onKeepEditing={() => { if (!isSaving) setDiscardConfirmOpen(false); }}
          onDiscard={() => {
            dirtyRef.current = false;
            setDiscardConfirmOpen(false);
            onClose?.();
          }}
          onSaveAndClose={saveAndClose}
        />
      </div>
    </div>
  );

  // Phase W1 · Feb-2026 — legacy renderer removed; the confirm dialog
  // now lives in the shared ``DirtyCloseConfirm`` component (mounted
  // above). All C1 / C1.1 testids are preserved by the shared
  // component's default prop values, so no downstream test needs to
  // change.

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
            {job?.customer_name || "—"}{job?.address ? <> · <AddressLink address={job.address} /></> : ""}
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
          onClick={attemptClose}
          style={{ background: "transparent", border: 0, cursor: "pointer", color: "#fff" }}
          aria-label="Close checklist"
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

    // Feb-2026 · Checklist reclassifier — admins/managers can always
    // retag; technicians only when the job is assigned to them (matches
    // the 403 boundary at `routers/jobs.py::update_job:925`). Locked
    // reports never expose the picker — the report is submitted and
    // no further edits are permitted.
    const canEditServiceType = !locked && (
      role === "admin" || role === "super_admin" || role === "manager" ||
      (role === "technician" && !!user?.technician_id
        && user.technician_id === job.technician_id)
    );

    // Phase 56.6 — pool jobs default to the 6-step wizard. Tack on
    // `?legacy=true` to any route hosting the modal to fall back to the
    // old single-scroll form. Landscape / generic clients keep the
    // original form (wizard is pool-only per brief).
    const useWizard = clientType === "pool" &&
      !(typeof window !== "undefined" &&
        window.location.search.includes("legacy=true"));

    return (
      <div style={{ overflow: "auto", padding: useWizard ? 0 : 20 }}>
        {wsWarning ? (
          <div className="text-xs px-3 py-2 rounded mb-3"
               style={{ color: c.warnFg, background: c.warnBg, margin: useWizard ? 12 : 0 }}
               data-testid="checklist-workstream-warning">
            {wsWarning}
          </div>
        ) : null}
        {submitError ? (
          <div className="text-xs px-3 py-2 rounded mb-3"
               style={{ color: c.errFg, background: c.errBg, margin: useWizard ? 12 : 0 }}
               data-testid="checklist-submit-error">
            {submitError}
          </div>
        ) : null}

        {useWizard ? (
          <WaterBodyManager
            jobId={String(jobId)}
            customerId={job?.customer_id}
            locked={locked}
            report={report}
            onChange={patchReport}
            onSaveExit={onClose}
            onCloseJob={closeJob}
            submitting={submitting}
            template={report?.template || null}
            canEditServiceType={canEditServiceType}
            onReclassify={handleReclassify}
            // Phase W1 · Feb-2026 — thread the modal-owned dirty
            // signal + flushSave + clearDirty setter into the
            // wizard so the wizard's Back-from-step-1 and Close-Job
            // exit paths can reuse the same three-button confirm
            // dialog without cloning the state machine. Passed as
            // a getter to avoid a re-render on every dirty toggle.
            // ``clearDirty`` lets the wizard's Discard path wipe
            // pending edits BEFORE firing the exit intent — this
            // prevents the parent's own C1 backdrop-tap guard from
            // popping a duplicate confirm on the same click.
            isDirty={() => dirtyRef.current}
            flushSave={flushSave}
            clearDirty={() => { dirtyRef.current = false; }}
          />
        ) : (
          <>
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
                readingFields={report.chemical_reading_fields || []}
            chemicalsAdded={report.chemicals_added || []}
            chemicalsCatalog={report.chemicals_catalog || []}
            chemicalUnits={report.chemical_units || ["gal", "lbs", "oz", "tabs"]}
            checklistItems={report.checklist_items || []}
            notes={report.notes || ""}
            onChange={patchReport}
            template={report?.template || null}
            canEditServiceType={canEditServiceType}
            onReclassify={handleReclassify}
          />
        )}
        {clientType === "landscaping" && (
          <LandscapingChecklistForm
            locked={locked}
            checklistItems={report.checklist_items || []}
            notes={report.notes || ""}
            internalNotes={report.internal_notes || ""}
            customerNotes={report.customer_notes || ""}
            onChange={patchReport}
          />
        )}
        {clientType === "generic" && (() => {
          // Phase MI1.1 · Feb 2026 — reach into ``deriveIndustryForJob``
          // ONLY on the generic branch so pool / landscaping keep
          // their existing dispatch. The five new industries route
          // to ``IndustryChecklistForm``; anything unknown falls
          // through to a Handyman template with a console warn so
          // ops can see the mis-classification.
          const derived = deriveIndustryForJob(job);
          // Phase D2 · Feb 2026 — derive the routable-industry set
          // from the canonical list so a future addition doesn't
          // require editing two files. Pool + Landscaping keep
          // their own dispatch branches upstream, so they're
          // filtered out here.
          const NEW_INDUSTRIES = new Set(
            CANONICAL_INDUSTRIES.filter(
              (s) => s !== "pool" && s !== "landscaping",
            ),
          );
          if (NEW_INDUSTRIES.has(derived)) {
            return (
              <IndustryChecklistForm
                industry={derived}
                locked={locked}
                checklistItems={report.checklist_items || []}
                notes={report.notes || ""}
                onChange={patchReport}
              />
            );
          }
          // Fallback branch — keep the historic GenericChecklistForm
          // work-performed merge for any job that landed in the
          // ``generic`` bucket with no industry keyword signal. The
          // console.warn keeps the mis-classification observable in
          // production dev-tools without spamming Sentry.
          // eslint-disable-next-line no-console
          console.warn(
            "[MI1.1] No industry keyword matched; falling back to " +
              "Handyman template. job=", job?.id, "derived=", derived,
          );
          return (
            <IndustryChecklistForm
              industry="handyman"
              locked={locked}
              checklistItems={report.checklist_items || []}
              notes={report.notes || ""}
              onChange={patchReport}
            />
          );
        })()}
          </>
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
    // Phase 56.6 — the wizard renders its own Back / Next / Close Job
    // footer per step; suppress the legacy modal footer to avoid two
    // Close-Job buttons stacked on top of each other.
    const clientType = job ? getChecklistType(job) : "";
    const useWizard = clientType === "pool" &&
      !(typeof window !== "undefined" &&
        window.location.search.includes("legacy=true"));
    if (useWizard) return null;
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
