/**
 * Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — Shared bulk-select toolkit.
 *
 * Drop-in components + hook that any admin list page can reuse to
 * ship the Task-BB pattern in ~30 lines of caller code. Consumed by
 * the Customers list in this batch; wire up the remaining 4 surfaces
 * (Jobs / Tasks / Communications / Email+SMS templates) by importing
 * from this module.
 *
 * Testids follow the Task-BB convention exactly so the Jest scaffolding
 * (`/app/frontend/src/test/phase34-bulk-select-shared.test.jsx`)
 * auto-covers every new surface.
 */
import React, { useMemo, useState } from "react";
import { Trash2, X as XIcon, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";

/** State + helpers hook — one call per surface. */
export function useBulkSelect(visibleIds) {
  const [selected, setSelected] = useState(() => new Set());
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
  const indeterminate = visibleIds.some((id) => selected.has(id)) && !allVisibleSelected;
  const selectedCount = selected.size;
  const toggleAll = () => setSelected((prev) => {
    const next = new Set(prev);
    if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
    else visibleIds.forEach((id) => next.add(id));
    return next;
  });
  const toggleOne = (id) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const clear = () => setSelected(new Set());
  return { selected, selectedCount, allVisibleSelected, indeterminate,
             toggleAll, toggleOne, clear };
}

/** Header checkbox. */
export function BulkSelectAll({ checked, indeterminate, onChange, label }) {
  return (
    <input
      type="checkbox"
      checked={checked}
      ref={(el) => { if (el) el.indeterminate = indeterminate; }}
      onChange={onChange}
      aria-label={label || "Select all rows on this page"}
      data-testid="bulk-select-all"
      className="cursor-pointer"
    />
  );
}

/** Per-row checkbox. */
export function BulkSelectRow({ id, checked, onChange, label }) {
  return (
    <input
      type="checkbox"
      checked={checked}
      onChange={onChange}
      aria-label={label || `Select row ${id}`}
      data-testid={`bulk-select-row-${id}`}
      className="cursor-pointer"
    />
  );
}

/**
 * Floating action bar + confirmation modal. Actions is an array of:
 *   { key, label, tone: "danger"|"primary", onClick, dropdown?: [{value, label}] }
 * Selecting a dropdown entry calls onClick(selectedDropdownValue).
 */
export function BulkActionBar({ selectedCount, actions, onClear }) {
  const [openDropdown, setOpenDropdown] = useState(null);
  if (selectedCount <= 0) return null;
  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-2xl shadow-2xl flex items-center gap-3 px-4 py-3 z-40"
      style={{ backgroundColor: colors.onSurface, color: "#FFFFFF",
                border: "1px solid rgba(255,255,255,0.08)" }}
      data-testid="bulk-action-bar"
    >
      <div className="text-sm font-semibold" data-testid="bulk-action-bar-count">
        {selectedCount} selected
      </div>
      {actions.map((a) => (
        <div key={a.key} className="relative">
          <button
            type="button"
            onClick={() => a.dropdown ? setOpenDropdown(openDropdown === a.key ? null : a.key) : a.onClick()}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{ backgroundColor: a.tone === "danger" ? "#DC2626" : "#1D4ED8",
                      color: "#FFFFFF" }}
            data-testid={a.key === "delete" ? "bulk-delete-button" : `bulk-${a.key}-button`}
          >
            {a.tone === "danger" ? <Trash2 size={12} /> : null}
            {a.label}
            {a.dropdown ? <ChevronDown size={12} /> : null}
          </button>
          {a.dropdown && openDropdown === a.key ? (
            <div className="absolute bottom-full mb-2 left-0 w-56 rounded-xl shadow-2xl overflow-hidden"
                  style={{ backgroundColor: colors.surface,
                            border: `1px solid ${colors.border}` }}
                  data-testid={`bulk-${a.key}-menu`}>
              {a.dropdown.map((opt) => (
                <button key={opt.value}
                          type="button"
                          onClick={() => { setOpenDropdown(null); a.onClick(opt.value); }}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50"
                          style={{ color: colors.onSurface }}
                          data-testid={`bulk-${a.key}-option-${opt.value}`}>
                  {opt.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ))}
      <button type="button" onClick={onClear}
                className="text-xs font-semibold underline"
                style={{ color: "rgba(255,255,255,0.85)" }}
                data-testid="bulk-clear-selection">
        Clear selection
      </button>
    </div>
  );
}

/** Confirmation modal — reused for delete + status change. */
export function BulkConfirmModal({ open, onClose, onConfirm, title, description,
                                       confirmLabel, testidRoot = "bulk-delete-confirm",
                                       busy }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
          data-testid={`${testidRoot}-modal`}>
      <div className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              {title}
            </h2>
            <p className="text-sm mt-1" style={{ color: colors.muted }}>
              {description}
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1"
                    style={{ color: colors.muted }} aria-label="Close">
            <XIcon size={18} />
          </button>
        </div>
        <div className="mt-5 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose}
                    className="px-4 py-2 rounded-xl text-sm font-semibold"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface }}
                    data-testid={`${testidRoot}-cancel`}>
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
                    className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                    style={{ backgroundColor: "#DC2626" }}
                    data-testid={`${testidRoot}-btn`}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** "Select all N matching this filter" secondary link. */
export function SelectAllMatchingLink({ pageCount, totalMatching, onSelectAllMatching }) {
  if (!totalMatching || totalMatching <= pageCount) return null;
  return (
    <button type="button" onClick={onSelectAllMatching}
              className="text-xs font-semibold underline"
              style={{ color: "rgba(255,255,255,0.95)" }}
              data-testid="bulk-select-all-matching">
      · Select all {totalMatching} matching this filter →
    </button>
  );
}

/** Inline locked-pill for a row that failed the bulk operation. */
export function LockedPill({ reason, testid }) {
  return (
    <span
      className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold"
      style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
      data-testid={testid || "bulk-locked-pill"}
      title={reason}
    >
      Locked · {reason}
    </span>
  );
}
