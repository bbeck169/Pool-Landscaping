/**
 * PDFI-IV · Feb-2026 — Date tile (PURPLE).
 * Editable date + invoice number side-by-side.
 */
import React from "react";
import { Calendar } from "lucide-react";

export default function DateTile({
  docDate,
  docNumber,
  onEditDate,
  onEditNumber,
}) {
  return (
    <div
      className="rounded-xl border-2 border-purple-400 bg-purple-100 p-4 shadow-sm"
      data-testid="pdfi-tile-date"
    >
      <div className="flex items-center gap-2 text-purple-900 font-semibold uppercase tracking-wide text-xs mb-3">
        <Calendar size={14} /> Date & Number
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-purple-900 mb-1">Invoice date</label>
          <input
            type="date"
            value={docDate || ""}
            onChange={(e) => onEditDate?.(e.target.value)}
            className="w-full px-2 py-1 rounded border border-purple-400 bg-white text-sm"
            data-testid="pdfi-tile-date-input"
          />
        </div>
        <div>
          <label className="block text-xs text-purple-900 mb-1">Invoice #</label>
          <input
            type="text"
            value={docNumber || ""}
            onChange={(e) => onEditNumber?.(e.target.value)}
            className="w-full px-2 py-1 rounded border border-purple-400 bg-white text-sm"
            data-testid="pdfi-tile-date-number-input"
            placeholder="e.g. 10774"
          />
        </div>
      </div>
    </div>
  );
}
