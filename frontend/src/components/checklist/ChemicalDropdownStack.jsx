/**
 * Phase 37 · ChemicalDropdownStack (web).
 *
 * Vertical stack of collapsible chemical rows — one per chemical type
 * (Chlorine Tablets, Liquid Chlorine, Liquid Acid, CalHypo Shock,
 * Clarifier, Phosphate Remover, Salt, Pool Enzymes, Algaecide).
 * Replaces the previous "Add a row → type Name / Qty / Unit" UX.
 *
 * State model:
 *   • `chemicalsAdded` (the backend `chemicals_added` array) is the
 *     source of truth. Entries look like
 *       { chemical, quantity, unit, raw_label, source? }
 *   • For each configured type, we find the FIRST entry with a
 *     case-insensitive `chemical` match. That entry's `raw_label`
 *     is shown; the option list shows a highlight around whichever
 *     preset matches.
 *   • Selecting a preset UPSERTs the entry (replaces any existing one
 *     for that type). Selecting "No X Used" REMOVES the entry.
 *
 * The backend `chemicals_added` array shape is untouched — we do NOT
 * introduce a new column. The extra `raw_label` and `source` fields
 * were already accepted (added_from_rec used them since Phase 34e).
 */
import React, { useState, useEffect, useRef, useMemo } from "react";
import { ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { CHEM_TYPES } from "./chemicalTypes";
import { api } from "@/api";

const colors = {
  brand: "#0EA5E9",
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#FFFFFF",
  surfaceAlt: "#F8FAFC",
  onSurface: "#0F172A",
  green: "#059669",
  greenBg: "#D1FAE5",
  optionBg: "#F1F5F9",
  optionSelBg: "#DBEAFE",
  optionSelFg: "#1E3A8A",
};

// Slug-ify an option's label for a deterministic testid segment.
const slugifyOption = (label) =>
  String(label).toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

// Find the chemicals_added entry matching a chem type (case-insensitive
// name match).
const findEntry = (chemicalsAdded, type) => {
  const target = type.name.toLowerCase();
  return chemicalsAdded.find(
    (c) => String(c?.chemical || c?.name || "").toLowerCase() === target
  );
};

export default function ChemicalDropdownStack({
  chemicalsAdded = [],
  locked = false,
  onChange,
  jobId,   // Phase 39 Step 3b — needed for `/inventory/reserve`.
}) {
  // Start all rows collapsed — techs typically only need 1-2 per visit.
  const [openSlug, setOpenSlug] = useState(null);
  // Phase 39 Step 3b — per-slug shortage warning captured from the last
  // `/inventory/reserve` response. Cleared when the row is set to "none".
  const [warnings, setWarnings] = useState({});
  const debounceTimers = useRef({});

  // Fire a debounced reservation call for a single chemical type. Persists
  // `reservation_id` back onto the corresponding chemicals_added row so
  // subsequent edits update in place. Zero-quantity or removal → DELETE.
  const reserve = (type, entry) => {
    if (!jobId) return;
    const timerKey = type.slug;
    if (debounceTimers.current[timerKey]) clearTimeout(debounceTimers.current[timerKey]);
    debounceTimers.current[timerKey] = setTimeout(async () => {
      try {
        if (!entry || !entry.quantity) {
          // Nothing on the row → release existing reservation if any.
          if (entry?.reservation_id) {
            await api.delete(`/inventory/reserve/${entry.reservation_id}`);
          }
          setWarnings((w) => { const n = { ...w }; delete n[type.slug]; return n; });
          return;
        }
        const resp = await api.post("/inventory/reserve", {
          chemical: entry.chemical || type.name,
          quantity: Number(entry.quantity) || 0,
          unit: entry.unit || type.unit,
          job_id: jobId,
          reservation_id: entry.reservation_id,
        });
        if (resp?.reservation_id && resp.reservation_id !== entry.reservation_id) {
          // Persist reservation_id back onto the row.
          const next = chemicalsAdded.map((c) =>
            String(c?.chemical || c?.name || "").toLowerCase() === type.name.toLowerCase()
              ? { ...c, reservation_id: resp.reservation_id } : c
          );
          onChange({ chemicals_added: next });
        }
        if (resp?.warning) {
          setWarnings((w) => ({
            ...w,
            [type.slug]: {
              text: resp.warning,
              suggested_restock: resp.suggested_restock,
            },
          }));
        } else {
          setWarnings((w) => { const n = { ...w }; delete n[type.slug]; return n; });
        }
      } catch (_) { /* stay quiet — reservation is advisory */ }
    }, 500);
  };

  const upsert = (type, option) => {
    // option = null → remove that chem type from the array.
    // option = { label, quantity } → upsert.
    const existingIdx = chemicalsAdded.findIndex(
      (c) => String(c?.chemical || c?.name || "").toLowerCase() === type.name.toLowerCase()
    );
    const existingRow = existingIdx >= 0 ? chemicalsAdded[existingIdx] : null;
    const next = [...chemicalsAdded];
    if (option === null) {
      if (existingIdx >= 0) next.splice(existingIdx, 1);
    } else {
      const entry = {
        chemical: type.name,
        // Preserve `name` for legacy compatibility with old rows / rec pill.
        name: type.name,
        quantity: option.quantity,
        amount: String(option.quantity),
        unit: type.unit,
        raw_label: option.label,
        source: option.source || undefined,
        snapped_from: option.snapped_from ?? undefined,
      };
      if (existingIdx >= 0) next[existingIdx] = { ...next[existingIdx], ...entry };
      else next.push(entry);
    }
    onChange({ chemicals_added: next });
    // Phase 37 hotfix — auto-collapse the row after any selection so the
    // tech immediately sees the updated current-selection line.
    setOpenSlug(null);
    // Phase 39 Step 3b — fire the reservation call. `option === null`
    // means "No X Used" which triggers a release using the prior row's id.
    const rowForReserve = option === null
      ? { ...(existingRow || {}), quantity: 0 }
      : (existingIdx >= 0 ? next[existingIdx] : next[next.length - 1]);
    reserve(type, rowForReserve);
  };

  return (
    <div data-testid="chemicals-stack" className="space-y-2">
      {CHEM_TYPES.map((type) => {
        const entry = findEntry(chemicalsAdded, type);
        const isOpen = openSlug === type.slug;
        const currentLabel = entry?.raw_label
          || (entry?.quantity != null ? `${entry.quantity} ${type.unit}` : null);
        const currentSnapped = entry?.snapped_from != null && entry?.snapped_from !== entry?.quantity
          ? `Snapped from ${entry.snapped_from} ${type.unit}` : null;
        return (
          <div
            key={type.slug}
            data-testid={`chemicals-row-${type.slug}`}
            className="rounded-lg"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
          >
            <button
              type="button"
              onClick={() => setOpenSlug(isOpen ? null : type.slug)}
              disabled={locked}
              data-testid={`chemicals-row-${type.slug}-header`}
              className="w-full flex items-center justify-between px-3 py-2 rounded-lg text-left"
              style={{
                background: entry ? colors.greenBg : colors.surface,
                border: 0,
                cursor: locked ? "default" : "pointer",
              }}
            >
              <div className="flex flex-col">
                <span className="text-sm font-bold" style={{ color: entry ? colors.green : colors.onSurface }}>
                  {type.name}
                </span>
                <span
                  className="text-xs"
                  style={{ color: entry ? colors.green : colors.muted }}
                  data-testid={`chemicals-row-${type.slug}-current`}
                >
                  {currentLabel || type.noOptionLabel}
                </span>
                {currentSnapped ? (
                  <span className="text-[10px] italic" style={{ color: colors.muted }}>
                    {currentSnapped}
                  </span>
                ) : null}
              </div>
              {isOpen
                ? <ChevronDown size={16} color={colors.muted} />
                : <ChevronRight size={16} color={colors.muted} />}
            </button>

            {warnings[type.slug] ? (
              <div
                className="px-3 pb-2 text-[11px] font-semibold flex items-center gap-1.5"
                data-testid={`chemicals-row-${type.slug}-shortage-warning`}
                style={{ background: "#FEF3C7", color: "#B45309",
                          borderBottom: `1px solid #FCD34D` }}
              >
                <AlertTriangle size={11} />
                <span className="flex-1">{warnings[type.slug].text}</span>
                {warnings[type.slug].suggested_restock ? (
                  <span
                    className="px-1.5 py-0.5 rounded text-[10px] font-bold"
                    style={{ background: "#B45309", color: "#FFFFFF" }}
                    data-testid={`chemicals-row-${type.slug}-suggested-restock`}
                  >
                    restock ≥ {warnings[type.slug].suggested_restock}
                  </span>
                ) : null}
              </div>
            ) : null}

            {isOpen && (
              <div className="p-2 border-t" style={{ borderColor: colors.border }}>
                {type.sectionLabel ? (
                  <div
                    className="text-[10px] italic text-center py-1 mb-1"
                    style={{ color: colors.muted }}
                  >
                    {type.sectionLabel}
                  </div>
                ) : null}
                {/* No-X sentinel row */}
                <button
                  type="button"
                  onClick={() => upsert(type, null)}
                  data-testid={`chemicals-row-${type.slug}-option-none`}
                  className="w-full text-left px-3 py-2 rounded-md text-xs mb-1"
                  style={{
                    background: !entry ? colors.optionSelBg : colors.optionBg,
                    color: !entry ? colors.optionSelFg : colors.onSurface,
                    border: 0,
                    cursor: "pointer",
                  }}
                >
                  {type.noOptionLabel}
                </button>
                <div className="grid grid-cols-3 gap-1.5">
                  {type.options.map((o) => {
                    const optSlug = slugifyOption(o.label);
                    const isSel = entry
                      && Math.abs(Number(entry.quantity) - Number(o.quantity)) < 0.001;
                    return (
                      <button
                        key={optSlug}
                        type="button"
                        onClick={() => upsert(type, o)}
                        data-testid={`chemicals-row-${type.slug}-option-${optSlug}`}
                        className="px-2 py-2 rounded-md text-xs font-semibold whitespace-nowrap"
                        style={{
                          background: isSel ? colors.optionSelBg : colors.optionBg,
                          color: isSel ? colors.optionSelFg : colors.onSurface,
                          border: isSel ? `2px solid ${colors.brand}` : "1px solid transparent",
                          cursor: "pointer",
                        }}
                      >
                        {o.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Given a bare chemical name and quantity (from a Phase 34e recommendation),
 * return the closest preset option so the row can "snap" to it. Returns
 * `{ type, option, snappedFrom }` or `null` if no matching chem type.
 */
export function snapRecommendationToPreset(chemicalName, quantity) {
  const target = String(chemicalName || "").toLowerCase();
  const type = CHEM_TYPES.find((t) => {
    if (t.name.toLowerCase() === target) return true;
    return (t.aliases || []).some((a) => a.toLowerCase() === target);
  });
  if (!type) return null;
  let closest = type.options[0];
  let diff = Math.abs(Number(closest.quantity) - Number(quantity));
  for (const o of type.options) {
    const d = Math.abs(Number(o.quantity) - Number(quantity));
    if (d < diff) { diff = d; closest = o; }
  }
  return { type, option: closest, snappedFrom: Number(quantity) };
}
