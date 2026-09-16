/**
 * Feb-2026 · Multi-body service reports (Phase 2 · web).
 *
 * Orchestrates the water-body section of the tech checklist:
 *
 *   ┌────────────────────────────────────────────────────────┐
 *   │  Primary body — renders through the existing            │
 *   │  <PoolChecklistWizard>. Baseline UX is untouched for    │
 *   │  single-body jobs so techs feel zero friction.          │
 *   ├────────────────────────────────────────────────────────┤
 *   │  Additional bodies (index >= 1) render below the wizard │
 *   │  as compact <WaterBodyPanel> accordions. Each has its   │
 *   │  own trimmed reading + chemical allow-list (spa/water_  │
 *   │  feature/fountain/other).                                │
 *   └────────────────────────────────────────────────────────┘
 *
 * Wire-up:
 *   * Reads the canonical `report.water_bodies` array (Phase 1 backend
 *     always provides at least body[0]).
 *   * When `report.water_bodies` is missing (very old client cache),
 *     falls back to a single default pool body constructed from the
 *     legacy top-level fields.
 *   * The primary body is a live proxy over `report.chemical_readings`
 *     / `report.chemicals_added` / `report.photos` / `report.notes` —
 *     the wizard writes those legacy top-level fields via `patchReport`,
 *     and this component keeps `water_bodies[0]` in sync.
 *   * Extra bodies write directly into `water_bodies[i]`. The manager
 *     never touches the top-level fields for bodies past index 0
 *     (backend's `chemicals_added` mirror is rebuilt on the PATCH so
 *     auto-invoice still picks them up).
 */
import React, { useCallback, useMemo, useState } from "react";
import { Plus } from "lucide-react";

import PoolChecklistWizard from "@/components/checklist/PoolChecklistWizard";
import WaterBodyPanel from "@/components/checklist/WaterBodyPanel";
import {
  MAX_BODIES,
  WATER_BODY_TYPES,
  makeEmptyBody,
} from "../../lib/waterBodies";


const c = {
  brand: "#0EA5E9", brandBg: "#E0F2FE",
  border: "#E2E8F0", muted: "#64748B",
  surface: "#FFFFFF", surfaceAlt: "#F8FAFC",
  onSurface: "#0F172A",
};


// Materialise the water_bodies array from the report, falling back to
// a single pool body constructed from legacy top-level fields.
function _materialize(report) {
  const list = Array.isArray(report?.water_bodies) ? report.water_bodies : [];
  if (list.length > 0) return list;
  // Legacy safety — one pool body carrying the legacy top-level state.
  return [{
    id: "legacy-primary",
    type: "pool",
    label: "Pool",
    sequence: 0,
    readings: report?.chemical_readings || [],
    chemicals_used: report?.chemicals_added || [],
    media: (report?.photos || []).map((p) => ({ kind: "photo", ...(p || {}) })),
    notes: report?.notes || "",
  }];
}


export default function WaterBodyManager({
  jobId,
  customerId,
  locked,
  report,
  onChange,
  onSaveExit,
  onCloseJob,
  submitting,
  template,
  canEditServiceType,
  onReclassify,
  // Phase W1 · Feb-2026 — forwarded to <PoolChecklistWizard> so
  // its Back-from-step-1 + Close-Job exit paths can gate on the
  // modal-owned ``dirtyRef`` via the shared confirm dialog.
  isDirty,
  flushSave,
  clearDirty,
}) {
  const bodies = useMemo(() => _materialize(report), [report]);
  const primary = bodies[0];
  const extras = bodies.slice(1);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Primary body proxies onto the legacy top-level fields via the
  // parent's `patchReport`. When the wizard writes ``chemical_readings``
  // (etc.), we also update `water_bodies[0]` so the two stay in sync.
  const onPrimaryChange = useCallback((patch) => {
    const next = { ...patch };
    const nextBodies = [...bodies];
    const primaryUpdated = { ...(nextBodies[0] || primary) };
    if ("chemical_readings" in patch) {
      primaryUpdated.readings = patch.chemical_readings || [];
    }
    if ("chemicals_added" in patch) {
      primaryUpdated.chemicals_used = patch.chemicals_added || [];
    }
    if ("notes" in patch) {
      primaryUpdated.notes = patch.notes || "";
    }
    if ("photos" in patch) {
      primaryUpdated.media = (patch.photos || []).map(
        (p) => ({ kind: "photo", ...(p || {}) }),
      );
    }
    // Only send the water_bodies array when we actually have extras
    // beyond the primary — otherwise the legacy single-body flow keeps
    // its plain top-level shape (matches the tester's ‘no-friction
    // baseline’ ask).
    if (extras.length > 0
        || "chemical_readings" in patch
        || "chemicals_added" in patch
        || "notes" in patch
        || "photos" in patch) {
      nextBodies[0] = primaryUpdated;
      next.water_bodies = nextBodies;
    }
    onChange(next);
  }, [bodies, extras.length, onChange, primary]);

  const onExtraChange = useCallback((index, updatedBody) => {
    const nextBodies = [...bodies];
    nextBodies[index] = { ...updatedBody, sequence: index };
    onChange({ water_bodies: nextBodies });
  }, [bodies, onChange]);

  const onExtraRemove = useCallback((index) => {
    if (bodies.length <= 1) return; // Guardrail.
    const nextBodies = bodies.filter((_, i) => i !== index)
                              .map((b, i) => ({ ...b, sequence: i }));
    onChange({ water_bodies: nextBodies });
  }, [bodies, onChange]);

  const addBody = useCallback((type) => {
    if (locked) return;
    if (bodies.length >= MAX_BODIES) return;
    const body = makeEmptyBody(type, bodies.length);
    const nextBodies = [...bodies, body];
    onChange({ water_bodies: nextBodies });
    setPickerOpen(false);
  }, [bodies, locked, onChange]);

  const showAddButton = !locked && bodies.length < MAX_BODIES;
  // Primary body's proxy report for the existing wizard — every value
  // stays wired to the top-level fields, which the wizard already
  // knows how to write.
  const proxyReport = report;

  return (
    <div data-testid="water-body-manager" data-body-count={bodies.length}>
      {/* Primary body — existing Pool Wizard */}
      <PoolChecklistWizard
        jobId={jobId}
        customerId={customerId}
        locked={locked}
        report={proxyReport}
        onChange={onPrimaryChange}
        onSaveExit={onSaveExit}
        onCloseJob={onCloseJob}
        submitting={submitting}
        template={template}
        canEditServiceType={canEditServiceType}
        onReclassify={onReclassify}
        isDirty={isDirty}
        flushSave={flushSave}
        clearDirty={clearDirty}
      />

      {/* Extras — accordion cards */}
      {extras.length > 0 ? (
        <div
          className="px-3 pb-3 space-y-3"
          data-testid="water-body-extras"
          style={{ borderTop: `1px solid ${c.border}` }}
        >
          <div
            className="pt-3 text-xs uppercase tracking-wider font-bold"
            style={{ color: c.muted }}
          >
            Additional Bodies of Water ({extras.length})
          </div>
          {extras.map((b, extraIdx) => {
            const absoluteIndex = extraIdx + 1;
            return (
              <WaterBodyPanel
                key={b.id || `extra-${extraIdx}`}
                body={b}
                index={absoluteIndex}
                locked={locked}
                canRemove={bodies.length > 1}
                onChange={(next) => onExtraChange(absoluteIndex, next)}
                onRemove={() => onExtraRemove(absoluteIndex)}
              />
            );
          })}
        </div>
      ) : null}

      {/* Add-body affordance */}
      {showAddButton ? (
        <div
          className="px-3 pb-4 pt-3"
          style={{ borderTop: extras.length === 0 ? `1px solid ${c.border}` : "none" }}
          data-testid="water-body-add-region"
        >
          {pickerOpen ? (
            <div
              className="rounded-lg p-3"
              style={{ border: `1px solid ${c.border}`, background: c.surfaceAlt }}
              data-testid="water-body-add-picker"
            >
              <div
                className="text-xs font-bold mb-2"
                style={{ color: c.onSurface }}
              >
                Select body type
              </div>
              <div className="flex flex-wrap gap-2">
                {WATER_BODY_TYPES.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => addBody(t.value)}
                    className="px-3 py-1.5 rounded-full text-xs font-bold"
                    style={{
                      background: c.surface, color: c.brand,
                      border: `1px solid ${c.brand}`,
                    }}
                    data-testid={`water-body-add-${t.value}`}
                  >
                    {t.label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setPickerOpen(false)}
                  className="px-3 py-1.5 rounded-full text-xs"
                  style={{
                    background: c.surface, color: c.muted,
                    border: `1px solid ${c.border}`,
                  }}
                  data-testid="water-body-add-cancel"
                >
                  Cancel
                </button>
              </div>
              <div
                className="text-[11px] mt-2"
                style={{ color: c.muted }}
              >
                {bodies.length}/{MAX_BODIES} bodies · pool bodies still gate submit;
                spa / water feature / fountain / other are optional-warn only.
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setPickerOpen(true)}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm font-bold"
              style={{
                background: c.brandBg, color: c.brand,
                border: `1px dashed ${c.brand}`,
              }}
              data-testid="water-body-add-btn"
            >
              <Plus size={14} /> Add body of water
            </button>
          )}
        </div>
      ) : null}

      {locked && extras.length === 0 ? null : locked ? (
        <div
          className="px-3 pb-3 text-[11px]"
          style={{ color: c.muted }}
          data-testid="water-body-locked-note"
        >
          Report submitted — bodies read-only.
        </div>
      ) : null}
    </div>
  );
}
