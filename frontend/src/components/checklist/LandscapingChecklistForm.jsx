/**
 * Phase 31 (initial) · Phase 56.16 (rewrite) — LandscapingChecklistForm (web).
 *
 * Phase 56.16 changes:
 * - Per-item optional note field REMOVED (was cluttering the mobile
 *   workflow). Pool checklist per-item notes remain unchanged.
 * - Notes split into TWO distinct fields:
 *     • Job Notes (Internal — admin/tech only)  → `internal_notes`
 *     • Customer Notes (visible to customer)    → `customer_notes`
 * - Fallback labels updated to the canonical 10-item ordered list.
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

// Kept in sync with backend/config_landscape_checklist.py — used only
// when the API template ships empty (which should never happen with a
// live server, but is nice for offline dev).
const FALLBACK_LABELS = [
  "Sprayed or Pulled Weeds",
  "Checked Irrigation",
  "Trimmed Bushes",
  "Mowed Grass",
  "Edged Grass",
  "Blow Property",
  "Raked Rocks",
  "Locked Gate",
  "Trimmed Trees",
  "Irrigation Repair",
];

export default function LandscapingChecklistForm({
  locked,
  checklistItems = [],
  notes = "",              // legacy — kept in the API for backwards compat
  internalNotes = "",
  customerNotes = "",
  onChange,
}) {
  const items = checklistItems.length
    ? checklistItems
    : FALLBACK_LABELS.map((label, i) => ({
        id: `fallback-${i}`, label, checked: false,
      }));

  const toggleCheck = (idx) => {
    const next = items.map((c, i) => (i === idx ? { ...c, checked: !c.checked } : c));
    onChange({ checklist_items: next });
  };

  return (
    <div data-testid="checklist-modal-landscape" className="space-y-5">
      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Grooming Checklist
        </div>
        {items.map((c, i) => (
          <div key={c.id} className="mb-2">
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
            {/* Phase 56.16 — per-item note textarea REMOVED. */}
          </div>
        ))}
      </div>

      <div data-testid="landscape-internal-notes-section">
        <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
          Job Notes <span className="font-normal" style={{ color: colors.muted }}>(Internal — not visible to customer)</span>
        </div>
        <textarea
          rows={3}
          disabled={locked}
          value={internalNotes || notes || ""}
          onChange={(e) => onChange({ internal_notes: e.target.value })}
          placeholder="Private notes for admins + dispatchers…"
          className="w-full mt-1 px-2 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${colors.border}`,
            background: locked ? colors.surfaceAlt : colors.surface,
            color: colors.onSurface,
            resize: "vertical",
          }}
          data-testid="landscape-internal-notes"
        />
      </div>

      <div data-testid="landscape-customer-notes-section">
        <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
          Customer Notes <span className="font-normal" style={{ color: colors.muted }}>(visible to customer)</span>
        </div>
        <textarea
          rows={3}
          disabled={locked}
          value={customerNotes || ""}
          onChange={(e) => onChange({ customer_notes: e.target.value })}
          placeholder="Anything the customer should see on their service report…"
          className="w-full mt-1 px-2 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${colors.border}`,
            background: locked ? colors.surfaceAlt : colors.surface,
            color: colors.onSurface,
            resize: "vertical",
          }}
          data-testid="landscape-customer-notes"
        />
      </div>
    </div>
  );
}
