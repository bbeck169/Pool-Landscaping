/**
 * PDFI-IV · Feb-2026 — Line item descriptions tile (DARK GREEN).
 * One multi-line textarea per line item — the operator uses this
 * for the long narrative text that doesn't fit in the mini-table
 * above.
 */
import React from "react";
import { AlignLeft } from "lucide-react";

export default function LineItemDescriptionsTile({
  lineItems,
  onEditDescription,
}) {
  const rows = lineItems || [];
  return (
    <div
      className="rounded-xl border-2 border-emerald-700 bg-emerald-800 p-4 shadow-sm"
      data-testid="pdfi-tile-descriptions"
    >
      <div className="flex items-center gap-2 text-emerald-50 font-semibold uppercase tracking-wide text-xs mb-3">
        <AlignLeft size={14} /> Line Descriptions
      </div>
      {rows.length === 0 && (
        <div className="text-xs text-emerald-100 italic" data-testid="pdfi-tile-descriptions-empty">
          No descriptions to edit.
        </div>
      )}
      <div className="space-y-2">
        {rows.map((li, i) => (
          <div key={i} data-testid={`pdfi-tile-descriptions-row-${i}`}>
            <label className="block text-[11px] text-emerald-100 mb-1">
              #{i + 1} · {li.item_name || "untitled"}
            </label>
            <textarea
              rows={2}
              value={li.description || ""}
              onChange={(e) => onEditDescription?.(i, e.target.value)}
              className="w-full px-2 py-1 rounded border border-emerald-500 bg-emerald-50 text-emerald-900 text-sm resize-none"
              data-testid={`pdfi-tile-descriptions-row-${i}-input`}
              placeholder="Line description"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
