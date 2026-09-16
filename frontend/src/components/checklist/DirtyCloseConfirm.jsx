/**
 * Phase W1 · Feb-2026 — DirtyCloseConfirm (shared).
 *
 * Extracted verbatim from the C1 / C1.1 confirm dialog that
 * previously lived inline inside `<ChecklistModal>`. Now shared
 * between:
 *
 *   • ChecklistModal      → prefix `checklist-discard-*` + testid
 *                           `checklist-save-and-close` (kept identical
 *                           to the original C1/C1.1 contract so every
 *                           legacy test stays green).
 *   • PoolChecklistWizard → prefix `wizard-discard-*` + testid
 *                           `wizard-save-and-close` (Phase W1 mirror
 *                           for Back-from-step-1 and Close-Job dirty
 *                           exit paths).
 *
 * Three-button contract (order left → right):
 *
 *   1. Keep editing      · neutral · always enabled (tech escape hatch)
 *   2. Discard changes   · destructive red · disabled while `isSaving`
 *   3. Save & close      · brand blue · disabled while `isSaving`
 *
 * The dialog renders as an absolute-positioned overlay inside its
 * host modal so a backdrop tap on the confirm's OWN backdrop dismisses
 * only the confirm (never the host). Callers must render this inside
 * a `position: relative` container.
 */
import React from "react";
import { Loader2 } from "lucide-react";

const _c = {
  brand: "#0EA5E9",
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#FFFFFF",
  surfaceAlt: "#F8FAFC",
  onSurface: "#0F172A",
  danger: "#DC2626",
};

export default function DirtyCloseConfirm({
  open,
  isSaving = false,
  title = "Save before closing?",
  description = "You have unsaved changes on this checklist. Save now, or discard them?",
  onKeepEditing,
  onDiscard,
  onSaveAndClose,
  // Testids — defaults preserve the C1 / C1.1 legacy contract so
  // no downstream test needs to change when ChecklistModal switches
  // to the shared component.
  backdropTestId  = "checklist-discard-confirm-backdrop",
  bodyTestId      = "checklist-discard-confirm",
  keepEditingTestId = "checklist-discard-keep-editing",
  discardTestId    = "checklist-discard-confirm-btn",
  saveTestId       = "checklist-save-and-close",
  hintId           = "checklist-discard-hint",
  discardTitle     = "Chemistry values entered since your last save will be lost.",
}) {
  if (!open) return null;
  return (
    <div
      onClick={() => { if (!isSaving) onKeepEditing?.(); }}
      style={{
        position: "absolute", inset: 0, zIndex: 60,
        background: "rgba(15,23,42,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        borderRadius: 12,
      }}
      data-testid={backdropTestId}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: _c.surface, borderRadius: 10, padding: 20,
          width: "min(440px, 92vw)",
          boxShadow: "0 12px 40px rgba(0,0,0,0.45)",
        }}
        data-testid={bodyTestId}
      >
        <div style={{
          fontSize: 16, fontWeight: 700, color: _c.onSurface,
          marginBottom: 8,
        }}>
          {title}
        </div>
        <div
          id={hintId}
          style={{ fontSize: 13, color: _c.muted, marginBottom: 16 }}
        >
          {description}
        </div>
        <div style={{
          display: "flex", justifyContent: "flex-end",
          flexWrap: "wrap", gap: 8,
        }}>
          <button
            type="button"
            onClick={() => onKeepEditing?.()}
            className="px-3 py-1.5 rounded-md text-sm font-semibold"
            style={{
              background: _c.surfaceAlt, color: _c.onSurface,
              border: `1px solid ${_c.border}`,
            }}
            data-testid={keepEditingTestId}
          >
            Keep editing
          </button>
          <button
            type="button"
            onClick={() => { if (!isSaving) onDiscard?.(); }}
            aria-describedby={hintId}
            disabled={isSaving}
            className="px-3 py-1.5 rounded-md text-sm font-semibold text-white"
            style={{ background: _c.danger, opacity: isSaving ? 0.5 : 1 }}
            data-testid={discardTestId}
            title={discardTitle}
          >
            Discard changes
          </button>
          <button
            type="button"
            onClick={() => { if (!isSaving) onSaveAndClose?.(); }}
            disabled={isSaving}
            className="px-3 py-1.5 rounded-md text-sm font-semibold text-white inline-flex items-center gap-1"
            style={{
              background: _c.brand,
              opacity: isSaving ? 0.7 : 1,
            }}
            data-testid={saveTestId}
          >
            {isSaving ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                Saving…
              </>
            ) : (
              <>Save &amp; close</>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
