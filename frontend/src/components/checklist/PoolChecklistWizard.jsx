import React, { useCallback, useMemo } from "react";
import { ChevronLeft, ChevronRight, Save, Check } from "lucide-react";

import PoolChecklistForm from "./PoolChecklistForm";
import PhotoUploader from "./PhotoUploader";
// Feb-2026 · Hide-web-chem-readings — when the section is gated off,
// the wizard MUST NOT block Close Job on unfilled readings and MUST
// NOT surface the "enter values or Not Tested" hint on step 1.
import { FEATURE_FLAGS } from "@/config/featureFlags";

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
}) {
  // `report.wizard_step` is the persistent cursor. Falls back to step 1
  // when unset. Clamp between 1 and 6 for safety.
  const step = useMemo(() => {
    const raw = Number(report?.wizard_step) || 1;
    return Math.max(1, Math.min(6, raw));
  }, [report?.wizard_step]);

  const goTo = useCallback((n) => {
    const target = Math.max(1, Math.min(6, n));
    if (target !== step) {
      onChange({ wizard_step: target });
    }
  }, [step, onChange]);

  const goNext = useCallback(() => goTo(step + 1), [step, goTo]);
  const goBack = useCallback(() => goTo(step - 1), [step, goTo]);

  // Phase 56.6 bugfix — step gating rules (RELAXED from the initial
  // ship). Autosave means data isn't lost even when incomplete, so the
  // Next button never blocks; it only surfaces a helper hint when the
  // tech hasn't answered anything yet. Hard validation is enforced only
  // when they hit "Close Job" on step 6. Reason: the original strict
  // gate silently disabled Next on step 1 because default readings
  // arrive with `value: null` — techs saw no hint about why.
  const readingsAllAnswered = useMemo(() => {
    // Feb-2026 · Hide-web-chem-readings — when the section is hidden
    // there is nothing to answer, so Close Job must never be gated.
    if (!FEATURE_FLAGS.SHOW_CHECKLIST_CHEMICAL_READINGS) return true;
    const rows = report?.chemical_readings || [];
    if (!rows.length) return true;
    return rows.every(
      (x) => (x?.value !== undefined && x?.value !== null && x?.value !== "") ||
             x?.not_tested === true,
    );
  }, [report]);
  const readingsHint = step === 1 && !readingsAllAnswered
    ? "Tip: enter values or toggle Not Tested for each row before closing the job."
    : "";
  const stepValid = true;   // Next is never hard-blocked in the wizard.
  const closeJobValid = readingsAllAnswered;

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

  const isLast = step === 6;

  return (
    <div className="flex flex-col" data-testid="pool-checklist-wizard">
      {/* Progress bar */}
      <div
        className="flex items-center gap-2 px-1 py-3 sticky top-0 z-10"
        style={{ background: c.surfaceAlt, borderBottom: `1px solid ${c.border}` }}
        data-testid="wizard-progress"
      >
        <div className="text-xs font-bold flex-shrink-0" style={{ color: c.onSurface }}>
          Step {step} of 6
        </div>
        <div className="flex-1 flex items-center gap-1 overflow-x-auto">
          {STEPS.map((s) => {
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
          onClick={goBack}
          disabled={step === 1}
          className="inline-flex items-center gap-1 text-sm font-semibold px-3 py-1.5 rounded-md"
          style={{
            background: "transparent",
            border: `1px solid ${step === 1 ? c.disabledBg : c.border}`,
            color: step === 1 ? c.disabledFg : c.onSurface,
            cursor: step === 1 ? "not-allowed" : "pointer",
          }}
          data-testid="wizard-back"
        >
          <ChevronLeft size={14} /> Back
        </button>

        {!isLast ? (
          <button
            type="button"
            onClick={goNext}
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
                window.alert(
                  "Some chemical readings are still blank. Please enter values or " +
                  "toggle Not Tested on each row before closing the job."
                );
                goTo(1);
                return;
              }
              onCloseJob?.();
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
            title={closeJobValid
              ? "Submit the service report and mark the job complete."
              : "Missing chemical readings — click to jump back and fix."}
          >
            {submitting ? "Submitting…" : "Close Job"}
          </button>
        )}
        </div>
      </div>
    </div>
  );
}
