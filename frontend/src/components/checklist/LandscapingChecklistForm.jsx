/**
 * Phase 31 · Step 2b — LandscapingChecklistForm (web).
 *
 * Web mirror of the mobile LandscapingChecklistForm. Checklist items
 * come from the backend template (LANDSCAPE_CHECKLIST_DEFAULT) via the
 * bootstrap GET. Fallback list is used only if the template ships empty.
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

const FALLBACK_LABELS = [
  "Mow all turf areas",
  "Edge sidewalks and driveways",
  "Blow all hard surfaces",
  "Trim shrubs/hedges as needed",
  "Pull/spray visible weeds",
  "Fertilize where scheduled",
  "Empty and haul debris",
  "Notes for customer",
];

export default function LandscapingChecklistForm({
  locked, checklistItems = [], notes = "", onChange,
}) {
  const items = checklistItems.length
    ? checklistItems
    : FALLBACK_LABELS.map((label, i) => ({
        id: `fallback-${i}`, label, checked: false, notes: "",
      }));

  const toggleCheck = (idx) => {
    const next = items.map((c, i) => (i === idx ? { ...c, checked: !c.checked } : c));
    onChange({ checklist_items: next });
  };
  const updNote = (idx, v) => {
    const next = items.map((c, i) => (i === idx ? { ...c, notes: v } : c));
    onChange({ checklist_items: next });
  };

  return (
    <div data-testid="checklist-modal-landscape" className="space-y-4">
      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Grooming Checklist
        </div>
        {items.map((c, i) => (
          <div key={c.id} className="mb-3">
            <label
              className="flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer"
              style={{
                border: `1px solid ${c.checked ? colors.success : colors.border}`,
                background: c.checked ? colors.successBg : colors.surface,
              }}
              data-testid={`landscape-check-${c.id}`}
            >
              <input
                type="checkbox"
                disabled={locked}
                checked={!!c.checked}
                onChange={() => toggleCheck(i)}
              />
              <span className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                {c.label}
              </span>
            </label>
            <input
              type="text"
              disabled={locked}
              value={c.notes || ""}
              placeholder="Notes (optional)"
              onChange={(e) => updNote(i, e.target.value)}
              className="w-full mt-1 px-2 py-1.5 rounded-md text-xs"
              style={{
                border: `1px solid ${colors.border}`,
                background: locked ? colors.surfaceAlt : colors.surface,
                color: colors.onSurface,
              }}
              data-testid={`landscape-note-${c.id}`}
            />
          </div>
        ))}
      </div>
      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>Job Notes</div>
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
          data-testid="landscape-notes"
        />
      </div>
    </div>
  );
}
