/**
 * Phase 31 · Step 2b — GenericChecklistForm (web).
 *
 * Fallback form for jobs that aren't pool or landscaping.
 * "Work performed" is folded into `notes` under a [Work Performed]
 * marker rather than inventing a new backend field, matching the
 * mobile implementation.
 */
import React from "react";

const colors = {
  brand: "#0EA5E9",
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#FFFFFF",
  surfaceAlt: "#F8FAFC",
  success: "#059669",
  successBg: "#D1FAE5",
  onSurface: "#0F172A",
};

export default function GenericChecklistForm({
  locked,
  checklistItems = [],
  workPerformed = "",
  notes = "",
  onChange,
}) {
  const toggleCheck = (idx) => {
    const next = checklistItems.map((c, i) =>
      i === idx ? { ...c, checked: !c.checked } : c
    );
    onChange({ checklist_items: next });
  };

  return (
    <div data-testid="checklist-modal-generic" className="space-y-4">
      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Work Performed
        </div>
        <textarea
          rows={4}
          disabled={locked}
          value={workPerformed || ""}
          placeholder="Describe what was done for the customer…"
          onChange={(e) => onChange({ work_performed: e.target.value })}
          className="w-full px-2 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${colors.border}`,
            background: locked ? colors.surfaceAlt : colors.surface,
            color: colors.onSurface,
            resize: "vertical",
          }}
          data-testid="generic-work-performed"
        />
      </div>

      {checklistItems.length > 0 && (
        <div>
          <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
            Checklist
          </div>
          {checklistItems.map((c, i) => (
            <label
              key={c.id}
              className="flex items-center gap-2 px-3 py-2 rounded-md mb-1 cursor-pointer"
              style={{
                border: `1px solid ${c.checked ? colors.success : colors.border}`,
                background: c.checked ? colors.successBg : colors.surface,
              }}
              data-testid={`generic-check-${c.id}`}
            >
              <input
                type="checkbox"
                disabled={locked}
                checked={!!c.checked}
                onChange={() => toggleCheck(i)}
              />
              <span className="text-sm" style={{ color: colors.onSurface }}>{c.label}</span>
            </label>
          ))}
        </div>
      )}

      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>Notes</div>
        <textarea
          rows={3}
          disabled={locked}
          value={notes || ""}
          onChange={(e) => onChange({ notes: e.target.value })}
          placeholder="Anything the customer or dispatcher should know…"
          className="w-full px-2 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${colors.border}`,
            background: locked ? colors.surfaceAlt : colors.surface,
            color: colors.onSurface,
            resize: "vertical",
          }}
          data-testid="generic-notes"
        />
      </div>
    </div>
  );
}
