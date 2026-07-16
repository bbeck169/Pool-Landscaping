/**
 * Phase 46.5 — Web parity for the mobile ChemicalPickerSheet.
 *
 * Renders the shared CHEMICALS_CATALOG as a single modal for the web
 * pool checklist. Same commit semantics as mobile: onChange feeds the
 * parent autosave debounce which PATCHes /jobs/{id}/service-report.
 */
import React, { useRef, useState } from "react";
import { X as CloseX } from "lucide-react";
import { colors } from "@/theme";

// Duplicated here (not imported) to avoid a mobile → web import loop.
// Mirror of /app/backend/config_chemicals.py + /app/mobile/src/config/chemicalsCatalog.ts.
export const CHEMICALS_CATALOG = [
  { slug: "chlorine_tabs",     name: "Chlorine Tabs",     unit: "tabs",     unit_kind: "integer" },
  { slug: "liquid_chlorine",   name: "Liquid Chlorine",   unit: "gal",      unit_kind: "decimal" },
  { slug: "muriatic_acid",     name: "Muriatic Acid",     unit: "gal",      unit_kind: "decimal" },
  { slug: "soda_ash",          name: "Soda Ash",          unit: "lbs",      unit_kind: "decimal" },
  { slug: "shock",             name: "Shock",             unit: "lbs",      unit_kind: "decimal" },
  { slug: "clarifier",         name: "Clarifier",         unit: "oz",       unit_kind: "decimal" },
  { slug: "phosphate_remover", name: "Phosphate Remover", unit: "oz",       unit_kind: "decimal" },
  { slug: "salt",              name: "Salt",              unit: "40lb bag", unit_kind: "integer" },
  { slug: "enzymes",           name: "Enzymes",           unit: "oz",       unit_kind: "decimal" },
];

export function normalizeChemQty(entry, raw) {
  if (raw === "" || raw == null) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return null;
  if (entry.unit_kind === "integer") return Math.round(n);
  return Math.round(n * 100) / 100;
}

export default function ChemicalPickerModal({
  open, onClose, chemicalsAdded, onChange, locked,
}) {
  const draftsRef = useRef({});
  const [, force] = useState(0);

  if (!open) return null;

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
    <div
      className="fixed inset-0 flex items-end md:items-center justify-center z-50"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
      data-testid="chem-picker-modal-backdrop"
    >
      <div
        className="w-full md:max-w-lg rounded-t-2xl md:rounded-2xl overflow-hidden"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
        onClick={(e) => e.stopPropagation()}
        data-testid="chem-picker-modal"
      >
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold" style={{ color: colors.onSurface }}>
            Chemicals Added
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-black/5"
            data-testid="chem-picker-modal-close"
            aria-label="Close chemical picker"
          >
            <CloseX size={18} />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-3 space-y-2">
          {CHEMICALS_CATALOG.map((entry) => {
            const idx = findIdx(entry);
            const existing = idx >= 0 ? chemicalsAdded[idx] : null;
            const seed = existing?.quantity != null ? String(existing.quantity) : "";
            const draft = draftsRef.current[entry.slug] ?? seed;
            const invalid = draft.trim() !== "" && normalizeChemQty(entry, draft) == null;
            return (
              <div
                key={entry.slug}
                className="flex items-center gap-3 px-3 py-2 rounded-lg"
                style={{
                  border: `1px solid ${invalid ? "#DC2626" : colors.border}`,
                  background: colors.surface,
                }}
                data-testid={`chem-row-${entry.slug}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                    {entry.name}
                  </div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    {entry.unit}
                  </div>
                </div>
                <input
                  type="text"
                  inputMode={entry.unit_kind === "integer" ? "numeric" : "decimal"}
                  value={draft}
                  disabled={locked}
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
                      commit(entry, draftsRef.current[entry.slug] ?? "");
                    }
                  }}
                  className="w-24 text-right rounded-md px-2 py-1.5 text-sm font-semibold"
                  style={{
                    border: `1px solid ${colors.border}`,
                    background: locked ? colors.surfaceSecondary : colors.surface,
                    color: colors.onSurface,
                  }}
                  data-testid={`chem-input-${entry.slug}`}
                />
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
                  data-testid={`chem-clear-${entry.slug}`}
                  aria-label={`Clear ${entry.name}`}
                >
                  <CloseX size={16} />
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
