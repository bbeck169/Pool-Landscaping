/**
 * PDFI-V · Feb-2026 — Line Items tile (YELLOW).
 *
 * Mini-table with inline-editable item_name / quantity /
 * unit_price / line_total. Per-row catalogue-match chip +
 * inline ``PricebookItemPicker`` on the no-match rows — the
 * operator opens the picker, searches, selects an item; the
 * parent dispatches ``patchPreview`` with the line_items
 * partial on ``onPickPricebook(lineIdx, item)``.
 */
import React, { useState } from "react";
import { List, Package, Plus, X as XIcon } from "lucide-react";

import PricebookItemPicker from "@/components/pricebook/PricebookItemPicker";

export default function LineItemsTile({
  lineItems,
  onEditLine,
  onPickPricebook,
  onAddLine,
}) {
  const rows = lineItems || [];
  const [openPickerIdx, setOpenPickerIdx] = useState(null);
  const [pickerQueries, setPickerQueries] = useState({});

  const _closePicker = () => setOpenPickerIdx(null);
  const _onPick = (lineIdx, row) => {
    onPickPricebook?.(lineIdx, row);
    _closePicker();
  };

  return (
    <div
      className="rounded-xl border-2 border-yellow-400 bg-yellow-100 p-4 shadow-sm"
      data-testid="pdfi-tile-lineitems"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-yellow-900 font-semibold uppercase tracking-wide text-xs">
          <List size={14} /> Line Items ({rows.length})
        </div>
        <button
          type="button"
          onClick={onAddLine}
          className="inline-flex items-center gap-1 text-xs text-yellow-900 hover:text-yellow-700"
          data-testid="pdfi-tile-lineitems-add-btn"
        >
          <Plus size={12} /> Add line
        </button>
      </div>
      <div className="space-y-2">
        {rows.length === 0 && (
          <div className="text-xs text-yellow-800 italic" data-testid="pdfi-tile-lineitems-empty">
            No line items parsed yet.
          </div>
        )}
        {rows.map((li, i) => {
          const matched = Boolean(li.pricebook_item_id);
          const pickerOpen = openPickerIdx === i;
          return (
            <div
              key={i}
              className="rounded-md bg-white border border-yellow-300 p-2"
              data-testid={`pdfi-tile-lineitems-row-${i}`}
            >
              <div className="flex items-center gap-2 mb-2">
                <input
                  type="text"
                  value={li.item_name || ""}
                  onChange={(e) => onEditLine?.(i, { item_name: e.target.value })}
                  placeholder="Item"
                  className="flex-1 px-2 py-1 rounded border border-yellow-200 text-sm"
                  data-testid={`pdfi-tile-lineitems-row-${i}-name`}
                />
                {matched ? (
                  <span
                    className="inline-flex items-center gap-1 rounded-full bg-yellow-700 text-white text-xs px-2 py-0.5"
                    data-testid={`pdfi-tile-lineitems-row-${i}-matched-badge`}
                  >
                    <Package size={12} /> pb-match
                  </span>
                ) : !pickerOpen ? (
                  <button
                    type="button"
                    onClick={() => setOpenPickerIdx(i)}
                    className="inline-flex items-center gap-1 rounded-md bg-yellow-200 hover:bg-yellow-300 text-yellow-900 text-xs px-2 py-0.5"
                    data-testid={`pdfi-tile-lineitems-row-${i}-pick-btn`}
                  >
                    <Package size={12} /> Pick from catalog
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={_closePicker}
                    className="inline-flex items-center gap-1 rounded-md bg-yellow-200 hover:bg-yellow-300 text-yellow-900 text-xs px-2 py-0.5"
                    data-testid={`pdfi-tile-lineitems-row-${i}-picker-cancel`}
                  >
                    <XIcon size={12} /> Cancel
                  </button>
                )}
              </div>
              {pickerOpen && (
                <div
                  className="mb-2"
                  data-testid={`pdfi-tile-lineitems-row-${i}-picker-container`}
                >
                  <PricebookItemPicker
                    value={pickerQueries[i] || li.item_name || ""}
                    onChange={(next) => setPickerQueries((q) => ({ ...q, [i]: next }))}
                    onSelect={(row) => _onPick(i, row)}
                    inputTestid={`pdfi-tile-lineitems-row-${i}-picker-input`}
                    wrapperTestid={`pdfi-tile-lineitems-row-${i}-picker-wrapper`}
                    placeholder="Search catalog…"
                  />
                </div>
              )}
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="block text-[10px] text-yellow-900">Qty</label>
                  <input
                    type="number"
                    step="0.01"
                    value={li.quantity ?? 1}
                    onChange={(e) => onEditLine?.(i, { quantity: parseFloat(e.target.value) || 0 })}
                    className="w-full px-2 py-1 rounded border border-yellow-200 text-sm"
                    data-testid={`pdfi-tile-lineitems-row-${i}-qty`}
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-yellow-900">Unit price</label>
                  <input
                    type="number"
                    step="0.01"
                    value={li.unit_price ?? 0}
                    onChange={(e) => onEditLine?.(i, { unit_price: parseFloat(e.target.value) || 0 })}
                    className="w-full px-2 py-1 rounded border border-yellow-200 text-sm"
                    data-testid={`pdfi-tile-lineitems-row-${i}-price`}
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-yellow-900">Line total</label>
                  <input
                    type="number"
                    step="0.01"
                    value={li.line_total ?? 0}
                    onChange={(e) => onEditLine?.(i, { line_total: parseFloat(e.target.value) || 0 })}
                    className="w-full px-2 py-1 rounded border border-yellow-200 text-sm"
                    data-testid={`pdfi-tile-lineitems-row-${i}-total`}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
