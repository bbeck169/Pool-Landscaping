/**
 * Phase 48 · Chemicals Added — inline manual text entry (web).
 *
 * Replaces the Phase 37 dropdown-preset stack with plain numeric text
 * inputs, one per shared `CHEMICALS_CATALOG` entry. All 9 rows are
 * always visible so techs can see every option at a glance. Empty or
 * 0 removes the entry from `chemicals_added`; typing a number upserts
 * it. Persistence is unchanged — commit fires the parent onChange
 * which flows into the existing autosave path.
 *
 * The `snapRecommendationToPreset` helper is preserved as a no-op
 * export so `add_from_recommendation` callers keep working; there are
 * no more presets to snap to, so the raw quantity passes through.
 */
import React, { useRef, useState } from "react";
import { X as CloseX } from "lucide-react";
import { colors } from "@/theme";
import {
  CHEMICALS_CATALOG_WEB as CATALOG,
  normalizeChemQty,
} from "./ChemicalPickerModal";

const noOptShim = (label, _unit) => `No ${label} added`;

// Phase 34e compat — the `add_from_recommendation` flow calls this to
// pre-snap an LLM-suggested quantity to the closest UI preset. We no
// longer have presets, so pass through the raw quantity unchanged.
export function snapRecommendationToPreset(quantity /* , type */) {
  return { quantity, snappedFrom: null };
}

export default function ChemicalDropdownStack({
  chemicalsAdded = [],
  locked = false,
  onChange,
  _jobId,   // kept for signature compat (inventory reserve wired later)
}) {
  const draftsRef = useRef({});
  const [, force] = useState(0);

  const findIdx = (entry) =>
    chemicalsAdded.findIndex(
      (c) => c?.slug === entry.slug
        || String(c?.name || c?.chemical || "").toLowerCase() === entry.name.toLowerCase(),
    );

  const commit = (entry, text) => {
    if (locked) return;
    const qty = normalizeChemQty(entry, text);
    const idx = findIdx(entry);
    const next = [...chemicalsAdded];
    if (qty == null || qty === 0) {
      if (idx >= 0) next.splice(idx, 1);
    } else {
      const row = {
        slug: entry.slug,
        chemical: entry.name, name: entry.name,
        quantity: qty, amount: String(qty),
        unit: entry.unit,
        raw_label: `${qty} ${entry.unit}`,
      };
      if (idx >= 0) next[idx] = { ...next[idx], ...row };
      else next.push(row);
    }
    onChange({ chemicals_added: next });
    delete draftsRef.current[entry.slug];
    force((n) => n + 1);
  };

  return (
    <div data-testid="chemicals-stack" className="space-y-2">
      {CATALOG.map((entry) => {
        const idx = findIdx(entry);
        const existing = idx >= 0 ? chemicalsAdded[idx] : null;
        const seed = existing?.quantity != null ? String(existing.quantity) : "";
        const draft = draftsRef.current[entry.slug] ?? seed;
        const invalid = draft.trim() !== "" && normalizeChemQty(entry, draft) == null;
        const hasValue = existing?.quantity != null && Number(existing.quantity) > 0;
        return (
          <div
            key={entry.slug}
            data-testid={`chemicals-row-${entry.slug}`}
            className="flex items-center gap-3 px-3 py-2 rounded-lg"
            style={{
              background: hasValue ? "#ECFDF5" : colors.surface,
              border: `1px solid ${invalid ? "#DC2626" : (hasValue ? "#A7F3D0" : colors.border)}`,
            }}
          >
            <div className="flex-1 min-w-0">
              <div
                className="text-sm font-bold"
                style={{ color: hasValue ? "#047857" : colors.onSurface }}
                data-testid={`chemicals-row-${entry.slug}-name`}
              >
                {entry.name}
              </div>
              <div
                className="text-xs"
                style={{ color: hasValue ? "#047857" : colors.muted }}
                data-testid={`chemicals-row-${entry.slug}-current`}
              >
                {hasValue
                  ? `${existing.quantity} ${entry.unit}`
                  : noOptShim(entry.name, entry.unit)}
              </div>
            </div>
            <input
              type="number"
              inputMode={entry.unit_kind === "integer" ? "numeric" : "decimal"}
              step={entry.unit_kind === "integer" ? "1" : "0.01"}
              min="0"
              disabled={locked}
              value={draft}
              placeholder="0"
              onChange={(e) => {
                const clean = entry.unit_kind === "integer"
                  ? e.target.value.replace(/[^0-9]/g, "")
                  : e.target.value.replace(/[^0-9.]/g, "");
                draftsRef.current[entry.slug] = clean;
                force((n) => n + 1);
              }}
              onBlur={() => commit(entry, draftsRef.current[entry.slug] ?? "")}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit(entry, draftsRef.current[entry.slug] ?? "");
                }
              }}
              className="w-24 text-right rounded-md px-2 py-1.5 text-sm font-semibold"
              style={{
                border: `1px solid ${invalid ? "#DC2626" : colors.border}`,
                background: locked ? colors.surfaceSecondary : colors.surface,
                color: colors.onSurface,
              }}
              data-testid={`chemicals-row-${entry.slug}-input`}
            />
            <span
              className="text-xs font-semibold min-w-[52px]"
              style={{ color: colors.muted }}
              data-testid={`chemicals-row-${entry.slug}-unit`}
            >
              {entry.unit}
            </span>
            <button
              type="button"
              onClick={() => commit(entry, "")}
              disabled={locked || !existing}
              className="p-1 rounded"
              style={{
                color: existing ? "#DC2626" : colors.muted,
                opacity: existing ? 1 : 0.4,
                cursor: locked || !existing ? "not-allowed" : "pointer",
              }}
              data-testid={`chemicals-row-${entry.slug}-clear`}
              aria-label={`Clear ${entry.name}`}
            >
              <CloseX size={16} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
