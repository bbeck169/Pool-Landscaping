import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Save, Check } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import PoolChecklistForm from "./PoolChecklistForm";
import PhotoUploader from "./PhotoUploader";
// Phase W1 · Feb-2026 — shared three-button confirm dialog. Mirrors
// the C1 / C1.1 exit-flow guard already used by `<ChecklistModal>`.
import DirtyCloseConfirm from "./DirtyCloseConfirm";
// Phase CW1 · Feb-2026 — reuse the exact Required-Four gate used by
// the backend + the ServiceReport page so the wizard's close-job
// enablement matches the API's 422 boundary byte-for-byte. Only the
// Required Four (Free Chlorine, pH, Alkalinity, Cyanuric Acid) block
// close; every other row (Hardness, Salt, Phosphates, TDS, tenant
// extras) may be truly blank. `alkalinity` / `total_alkalinity` and
// `cyanuric_acid` / `cya` canonicalise together per CHEM1/CHEM1.1.
import { missingCoreReadings } from "@/utils/chemistryGate";

/**
 * Phase 56.6 — Pool Job Wizard shell.
 *
 * Wraps the existing `<PoolChecklistForm>` with a 6-step progress bar +
 * Next / Back / Save-&-Exit / Close-Job controls. Each step maps to a
 * section that already lives inside `PoolChecklistForm` (gated by the
 * new `wizardStep` prop) OR to a photo pool rendered directly here.
 *
 *   Step 1  Chemical Readings
 *   Step 2  Recommended + Chemicals Added
 *   Step 3  Checklist
 *   Step 4  Photos (general — reuses the customer-facing photo pool)
 *   Step 5  Customer Notes
 *   Step 6  Internal Notes + internal-issue photos
 *
 * Autosave is owned by the parent (`ChecklistModal`) via `onChange` /
 * refs; the wizard shell only owns step state. `wizard_step` is
 * persisted through `onChange` so a Save-&-Exit + resume lands on the
 * last step the tech was on.
 */

const STEPS = [
  { n: 1, label: "Readings",         short: "R"  },
  { n: 2, label: "Chemicals",        short: "Ch" },
  { n: 3, label: "Checklist",        short: "☑"  },
  { n: 4, label: "Photos",           short: "📷" },
  { n: 5, label: "Customer Notes",   short: "N"  },
  { n: 6, label: "Internal Notes",   short: "iN" },
];

const c = {
  brand: "#0EA5E9", brandDim: "#0284C7",
  border: "#E2E8F0", muted: "#64748B",
  surface: "#fff", surfaceAlt: "#F8FAFC",
  onSurface: "#0F172A", success: "#16A34A",
  danger: "#DC2626",
  disabledBg: "#E5E7EB", disabledFg: "#94A3B8",
};

const PHOTO_CAP = 10;

export default function PoolChecklistWizard({
  jobId,
  customerId,
  locked,
  report,
  onChange,
  onSaveExit,
  onCloseJob,
  submitting,
  // Feb-2026 · Checklist reclassifier — forwarded to
  // <PoolChecklistForm> so the Chemical Readings empty-state picker
  // works inside the wizard too.
  template = null,
  canEditServiceType = false,
  onReclassify = null,
  // Phase W1 · Feb-2026 — dirty-close guard mirror. ``isDirty`` is a
  // getter (`() => dirtyRef.current`) so the wizard reads the LATEST
  // parent-owned dirty signal without re-rendering on every edit.
  // ``flushSave`` is the parent's existing autosave-flush; the shared
  // confirm's "Save & close" primary path awaits it before dismissing.
  // Both are optional so pre-W1 embedders (older tests, legacy call
  // sites) keep working — Back on step 1 falls back to disabled and
  // Close-Job falls back to firing ``onCloseJob`` directly.
  isDirty = null,
  flushSave = null,
  // Phase W1 · Feb-2026 — Discard-changes reset. When wired, the
  // wizard's Discard handler flips the parent-owned dirty flag
  // BEFORE firing the exit intent so the parent's own C1 backdrop
  // guard doesn't pop a duplicate confirm on the same click.
  clearDirty = null,
}) {
  // TD-pool-repair-completion-wizard-notes-photos-only · Feb-2026 —
  // Pool jobs tagged ``work_class === "repair"`` skip the chemistry /
  // chemicals / checklist steps entirely.  Repair visits are photos
  // + notes only per product spec; the BE's
  // ``is_pool_job(job) and not _is_repair`` chemistry gate
  // (routers/service_reports.py:885) already loosened the submit
  // path for repair jobs, but the wizard shell was still forcing
  // techs through the three empty steps.  Filter STEPS at the shell
  // level — the delegated ``<PoolChecklistForm>`` already self-gates
  // via its ``inStep(n)`` helper, so no changes are required inside
  // the form component.  Picks up both ``report.work_class`` (the
  // standard surface) and ``job.work_class`` on the embedded report
  // (defensive fallback for a reclassified-in-flight job).
  const isRepair = useMemo(() => {
    const _rwc = String(report?.work_class || "").toLowerCase();
    const _jwc = String(report?.job?.work_class || "").toLowerCase();
    return _rwc === "repair" || _jwc === "repair";
  }, [report?.work_class, report?.job?.work_class]);

  // The visible step set + its first/last cursor positions.  Repair
  // mode drops steps 1-3; service mode keeps all six.
  const effectiveSteps = useMemo(
    () => (isRepair ? STEPS.filter((s) => s.n >= 4) : STEPS),
    [isRepair],
  );
  const firstStep = effectiveSteps[0].n;
  const lastStep = effectiveSteps[effectiveSteps.length - 1].n;

  // `report.wizard_step` is the persistent cursor. Falls back to the
  // first visible step when unset. Clamp into the visible range so a
  // reclassified-mid-report job (service → repair with wizard_step=2
  // persisted) doesn't render a blank step body.
  const step = useMemo(() => {
    const raw = Number(report?.wizard_step) || firstStep;
    return Math.max(firstStep, Math.min(lastStep, raw));
  }, [report?.wizard_step, firstStep, lastStep]);

  // TD-pool-repair-completion-wizard-notes-photos-only · Feb-2026 —
  // One-shot persist when the stored cursor falls outside the
  // visible range (e.g. the job was reclassified from service to
  // repair with ``wizard_step=2`` already saved).  Clamping at render
  // time alone would leave the stale value in Mongo; next mount
  // would re-clamp indefinitely.  The ref gate ensures the effect
  // fires exactly once per mount — never a feedback loop with
  // ``onChange`` re-triggering itself.
  const _staleCursorPersistedRef = useRef(false);
  useEffect(() => {
    if (_staleCursorPersistedRef.current) return;
    const raw = Number(report?.wizard_step) || firstStep;
    const clamped = Math.max(firstStep, Math.min(lastStep, raw));
    if (clamped !== raw) {
      _staleCursorPersistedRef.current = true;
      onChange({ wizard_step: clamped });
    }
    // Only runs on mount — intentionally omit deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const goTo = useCallback((n) => {
    // Snap to the nearest visible step; skips the filtered-out
    // positions in repair mode.
    const _visible = effectiveSteps.map((s) => s.n);
    const _target = _visible.includes(n)
      ? n
      : _visible.reduce(
          (best, cur) => Math.abs(cur - n) < Math.abs(best - n) ? cur : best,
          _visible[0],
        );
    if (_target !== step) {
      onChange({ wizard_step: _target });
    }
  }, [step, onChange, effectiveSteps]);

  const _currentIdx = effectiveSteps.findIndex((s) => s.n === step);
  const goNext = useCallback(() => {
    const nxt = effectiveSteps[Math.min(_currentIdx + 1, effectiveSteps.length - 1)];
    goTo(nxt.n);
  }, [goTo, effectiveSteps, _currentIdx]);
  const goBack = useCallback(() => {
    const prv = effectiveSteps[Math.max(_currentIdx - 1, 0)];
    goTo(prv.n);
  }, [goTo, effectiveSteps, _currentIdx]);

  // ─── Phase W1 · Feb-2026 · dirty-close guard mirror ─────────────
  // Local UI state for the shared confirm dialog. The wizard is a
  // pure child — the actual ``dirtyRef`` / ``flushSave`` live in the
  // parent (`<ChecklistModal>`) and are threaded in as props. The
  // wizard only owns the confirm-open + in-flight-save flags because
  // those are UI-only.
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmIntent, setConfirmIntent] = useState(null); // "back" | "close-job"
  const [isSaving, setIsSaving] = useState(false);

  // Snapshot whether the parent's dirty getter is truthy. Guarded so
  // callers that forget to pass the prop (older tests) fall back to
  // "not dirty" — matches pre-W1 behaviour exactly.
  const _dirty = useCallback(() => {
    if (typeof isDirty !== "function") return false;
    try { return !!isDirty(); } catch { return false; }
  }, [isDirty]);

  // Resolve what a given intent should ultimately do once the tech
  // has confirmed / discarded / a clean form was detected.
  const _fireIntent = useCallback((intent) => {
    if (intent === "back") {
      // Exit-from-step-1 lands on the parent's onClose handler
      // (mounted as ``onSaveExit``).
      onSaveExit?.();
    } else if (intent === "close-job") {
      onCloseJob?.();
    }
  }, [onSaveExit, onCloseJob]);

  const attemptClose = useCallback((intent) => {
    if (intent === "next") {
      // Forward action — no data-loss risk. Never gate on dirty.
      goNext();
      return;
    }
    if (intent === "back") {
      // Intra-wizard Back walks the step index down and NEVER
      // triggers the confirm — techs expect step-to-step Back to be
      // immediate. Only Back on the first visible step (which would
      // EXIT the wizard) gates on dirty.
      if (step > firstStep) {
        goBack();
        return;
      }
      // step === firstStep — leaving the wizard entirely.
      if (_dirty()) {
        setConfirmIntent("back");
        setConfirmOpen(true);
      } else {
        _fireIntent("back");
      }
      return;
    }
    if (intent === "close-job") {
      // Same C1 semantics: clean form closes silently (delegates to
      // the parent's submit path); dirty form pops the confirm.
      if (_dirty()) {
        setConfirmIntent("close-job");
        setConfirmOpen(true);
      } else {
        _fireIntent("close-job");
      }
      return;
    }
  }, [step, goNext, goBack, _dirty, _fireIntent, firstStep]);

  // Save & close primary handler for the shared confirm. Mirrors
  // ChecklistModal's own ``saveAndClose``:
  //   * flushSave succeeded (isDirty flipped false) → close via intent
  //   * flushSave failed → truthful toast, keep wizard open, dirty preserved
  const handleSaveAndClose = useCallback(async () => {
    if (typeof flushSave !== "function") {
      // No flusher supplied → treat as instant-save (no-op) and close.
      setConfirmOpen(false);
      _fireIntent(confirmIntent);
      return;
    }
    setIsSaving(true);
    try {
      await flushSave();
    } finally {
      setIsSaving(false);
    }
    if (!_dirty()) {
      setConfirmOpen(false);
      _fireIntent(confirmIntent);
    } else {
      toast.error(
        "Couldn't save your changes — please check your connection and try again.",
      );
    }
  }, [flushSave, confirmIntent, _dirty, _fireIntent]);

  const handleDiscard = useCallback(() => {
    // Discard clears the parent-owned dirty flag BEFORE firing the
    // exit intent so a stray autosave-in-flight can't reopen the
    // state, and (critically) the parent's C1 backdrop-tap guard
    // doesn't pop a duplicate confirm on the same click. When the
    // parent didn't supply ``clearDirty`` we fall back to firing
    // the intent directly — matches pre-W1 behaviour and keeps
    // legacy tests / call-sites working.
    setConfirmOpen(false);
    if (typeof clearDirty === "function") {
      try { clearDirty(); } catch { /* non-blocking */ }
    }
    _fireIntent(confirmIntent);
  }, [confirmIntent, clearDirty, _fireIntent]);

  const handleKeepEditing = useCallback(() => {
    setConfirmOpen(false);
  }, []);

  // Phase 56.6 bugfix — step gating rules (RELAXED from the initial
  // ship). Autosave means data isn't lost even when incomplete, so the
  // Next button never blocks; it only surfaces a helper hint when the
  // tech hasn't answered anything yet. Hard validation is enforced only
  // when they hit "Close Job" on step 6.
  //
  // Phase CW1 · Feb-2026 — LOOSENED FURTHER. Every visible row was
  // being treated as required, which meant a tech had to fill (or
  // "Not Tested"-tag) every optional row — Hardness, Salt, Phosphates,
  // TDS, tenant extras — before Close Job would light up. Product
  // decision: only the "Required Four" (Free Chlorine, pH,
  // Alkalinity, Cyanuric Acid) block close. Other readings may be
  // truly blank. Mirrors the backend chemistry-gate contract byte-for-
  // byte via ``missingCoreReadings`` so an admin's UI-gated Close Job
  // button never lets a submit through that the API then 422s.
  const { t } = useTranslation("checklist");
  const missingRequiredFour = useMemo(() => {
    const rows = report?.chemical_readings || [];
    // Preserve pre-CW1 behaviour: an empty readings list means the
    // tech hasn't loaded the form yet — don't block. Only enforce
    // the Required Four ONCE there are readings to validate.
    if (!rows.length) return [];
    return missingCoreReadings(rows);
  }, [report]);
  const readingsAllAnswered = missingRequiredFour.length === 0;
  // TD-pool-repair-completion-wizard-notes-photos-only · Feb-2026 —
  // readingsHint is a chemistry-step prompt; repair jobs don't have
  // a chemistry step so the hint is permanently empty for them.
  const readingsHint = !isRepair && step === 1 && !readingsAllAnswered
    ? t(
        "required_four_hint",
        "Free Chlorine, pH, Alkalinity, and Cyanuric Acid are required to close the job. Other readings are optional.",
      )
    : "";
  const stepValid = true;   // Next is never hard-blocked in the wizard.
  // TD-pool-repair-completion-wizard-notes-photos-only · Feb-2026 —
  // closeJobValid gates "Close Job" on service-pool jobs having the
  // Required Four readings; repair jobs are chemistry-less so the
  // close is always valid.  Matches the BE
  // ``is_pool_job(job) and not _is_repair`` gate — a tech can
  // submit a repair-pool report without any chemistry data.
  const closeJobValid = isRepair ? true : readingsAllAnswered;

  const allPhotos = report?.photos || [];
  const generalPhotos = allPhotos.filter((p) => (p?.tag || "general") !== "internal_issue");
  const internalPhotos = allPhotos.filter((p) => p?.tag === "internal_issue");

  const setPhotos = (next, tag) => {
    // Merge tagged photos back onto the master list.
    if (tag === "internal_issue") {
      const merged = [...generalPhotos, ...(next || []).map((p) => ({ ...p, tag: "internal_issue" }))];
      onChange({ photos: merged });
    } else {
      const merged = [...(next || []).map((p) => ({ ...p, tag: p?.tag || "general" })), ...internalPhotos];
      onChange({ photos: merged });
    }
  };

  const isLast = step === lastStep;

  return (
    <div
      className="flex flex-col"
      data-testid="pool-checklist-wizard"
      // Phase W1 · Feb-2026 — anchor the confirm dialog overlay so
      // its own backdrop can't dismiss the surrounding checklist
      // modal.
      style={{ position: "relative" }}
    >
      {/* Progress bar */}
      <div
        className="flex items-center gap-2 px-1 py-3 sticky top-0 z-10"
        style={{ background: c.surfaceAlt, borderBottom: `1px solid ${c.border}` }}
        data-testid="wizard-progress"
      >
        <div className="text-xs font-bold flex-shrink-0" style={{ color: c.onSurface }}>
          Step {_currentIdx + 1} of {effectiveSteps.length}
        </div>
        <div className="flex-1 flex items-center gap-1 overflow-x-auto">
          {effectiveSteps.map((s) => {
            const active = s.n === step;
            const done = s.n < step;
            return (
              <button
                key={s.n}
                type="button"
                onClick={() => goTo(s.n)}
                className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full whitespace-nowrap transition"
                style={{
                  background: active ? c.brand : done ? "#DCFCE7" : "transparent",
                  color: active ? "#fff" : done ? c.success : c.muted,
                  border: `1px solid ${active ? c.brand : done ? "#86EFAC" : c.border}`,
                  cursor: "pointer",
                }}
                data-testid={`wizard-step-dot-${s.n}`}
              >
                {done ? <Check size={10} /> : s.n}. {s.label}
              </button>
            );
          })}
        </div>
        {onSaveExit ? (
          <button
            type="button"
            onClick={onSaveExit}
            className="flex-shrink-0 inline-flex items-center gap-1 text-xs font-bold px-2 py-1 rounded-md"
            style={{
              background: "transparent",
              border: `1px solid ${c.border}`,
              color: c.onSurface,
              cursor: "pointer",
            }}
            title="Save progress and return to Workstream"
            data-testid="wizard-save-exit"
          >
            <Save size={12} /> Save &amp; exit
          </button>
        ) : null}
      </div>

      {/* Step body */}
      <div className="flex-1 p-4" data-testid={`wizard-step-body-${step}`}>
        {step === 4 ? (
          <div className="space-y-2">
            <div className="text-sm font-bold" style={{ color: c.onSurface }}>Photos</div>
            <div className="text-xs" style={{ color: c.muted }}>
              Attach photos of the pool, equipment, or before/after shots. Customer-visible.
            </div>
            <PhotoUploader
              jobId={String(jobId)}
              photos={generalPhotos}
              onPhotosChange={(next) => setPhotos(next, "general")}
              max={PHOTO_CAP}
              disabled={locked}
            />
          </div>
        ) : (
          <PoolChecklistForm
            jobId={jobId}
            customerId={customerId}
            locked={locked}
            readings={report?.chemical_readings || []}
            readingFields={report?.chemical_reading_fields || []}
            chemicalsAdded={report?.chemicals_added || []}
            chemicalsCatalog={report?.chemicals_catalog || []}
            chemicalUnits={report?.chemical_units || ["gal", "lbs", "oz", "tabs"]}
            checklistItems={report?.checklist_items || []}
            notes={report?.notes || ""}
            internalNotes={report?.internal_notes || ""}
            observations={report?.observations || {}}
            onChange={onChange}
            wizardStep={step}
            template={template}
            canEditServiceType={canEditServiceType}
            onReclassify={onReclassify}
          />
        )}
        {step === 6 ? (
          <div className="mt-4 rounded-lg p-3"
               style={{ background: c.surfaceAlt, border: `1px solid ${c.border}` }}
               data-testid="wizard-internal-photos-card">
            <div className="text-sm font-bold mb-1" style={{ color: c.onSurface }}>
              Photos for issue (internal)
            </div>
            <div className="text-xs mb-2" style={{ color: c.muted }}>
              Attach photos tied to an internal issue or follow-up. Not shared with the customer.
            </div>
            <PhotoUploader
              jobId={String(jobId)}
              photos={internalPhotos}
              onPhotosChange={(next) => setPhotos(next, "internal_issue")}
              max={PHOTO_CAP}
              disabled={locked}
            />
          </div>
        ) : null}
      </div>

      {/* Nav footer */}
      <div
        className="flex flex-col gap-1 px-4 py-3 sticky bottom-0"
        style={{ background: c.surfaceAlt, borderTop: `1px solid ${c.border}` }}
        data-testid="wizard-nav-footer"
      >
        {readingsHint ? (
          <div className="text-[11px] text-center" style={{ color: c.muted }}
               data-testid="wizard-readings-hint">
            {readingsHint}
          </div>
        ) : null}
        <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => attemptClose("back")}
          className="inline-flex items-center gap-1 text-sm font-semibold px-3 py-1.5 rounded-md"
          style={{
            background: "transparent",
            border: `1px solid ${c.border}`,
            color: c.onSurface,
            cursor: "pointer",
          }}
          data-testid="wizard-back"
        >
          <ChevronLeft size={14} /> Back
        </button>

        {!isLast ? (
          <button
            type="button"
            onClick={() => attemptClose("next")}
            disabled={!stepValid}
            className="inline-flex items-center gap-1 text-sm font-bold px-4 py-1.5 rounded-md"
            style={{
              background: stepValid ? c.brand : c.disabledBg,
              color: stepValid ? "#fff" : c.disabledFg,
              border: 0,
              cursor: stepValid ? "pointer" : "not-allowed",
            }}
            data-testid="wizard-next"
          >
            Next <ChevronRight size={14} />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => {
              if (!closeJobValid) {
                // TD-pool-repair-completion-wizard-notes-photos-only
                // · Feb-2026 — this alert + jump-to-step-1 only
                // fires on service-pool jobs; closeJobValid is
                // forced to true for repair so this branch is
                // unreachable there.
                // Phase CW1 · Feb-2026 — narrow the alert wording to
                // the Required Four rule that now drives closeJobValid.
                window.alert(
                  "Free Chlorine, pH, Alkalinity, and Cyanuric Acid are " +
                  "required to close the job. Please fill any missing " +
                  "Required Four readings; other readings are optional."
                );
                goTo(1);
                return;
              }
              attemptClose("close-job");
            }}
            disabled={locked || submitting}
            className="inline-flex items-center gap-1 text-sm font-bold px-4 py-1.5 rounded-md"
            style={{
              background: closeJobValid ? c.success : c.disabledBg,
              color: closeJobValid ? "#fff" : c.disabledFg,
              border: 0,
              cursor: (locked || submitting) ? "wait" : "pointer",
              opacity: (locked || submitting) ? 0.6 : 1,
            }}
            data-testid="wizard-close-job"
            // Phase CW1 · Feb-2026 — expose the gate state as a
            // ``data-close-valid`` attribute so tests + E2E can
            // observe enablement without depending on CSS colours
            // or the disabled DOM property (the button is never DOM-
            // disabled — the click handler nudges the tech back to
            // step 1 with an alert instead of silently swallowing).
            data-close-valid={closeJobValid ? "true" : "false"}
            title={closeJobValid
              ? "Submit the service report and mark the job complete."
              : "Missing Required Four readings — click to jump back and fix."}
          >
            {submitting ? "Submitting…" : "Close Job"}
          </button>
        )}
        </div>
      </div>

      {/* Phase W1 · Feb-2026 — shared dirty-close confirm. Rendered
          absolutely inside the wizard root so its backdrop tap only
          dismisses the confirm (never the surrounding checklist
          modal). Testids are wizard-scoped and NEVER collide with
          the C1 / C1.1 checklist-scoped ones. */}
      <DirtyCloseConfirm
        open={confirmOpen}
        isSaving={isSaving}
        onKeepEditing={handleKeepEditing}
        onDiscard={handleDiscard}
        onSaveAndClose={handleSaveAndClose}
        backdropTestId="wizard-discard-confirm-backdrop"
        bodyTestId="wizard-discard-confirm"
        keepEditingTestId="wizard-discard-keep-editing"
        discardTestId="wizard-discard-confirm-btn"
        saveTestId="wizard-save-and-close"
        hintId="wizard-discard-hint"
      />
    </div>
  );
}
