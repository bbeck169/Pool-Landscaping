/**
 * PDFI-IV · Feb-2026 — Totals tile (ORANGE).
 * Shows the grand_total alongside subtotal / amount_paid /
 * total_due. Only grand_total is editable; the sibling fields
 * are read-only displays taken straight from the preview.
 */
import React from "react";
import { DollarSign } from "lucide-react";

const _fmtMoney = (v) => {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "number" ? v : parseFloat(v);
  if (Number.isNaN(num)) return "—";
  return `$${num.toFixed(2)}`;
};

export default function TotalTile({
  grandTotal,
  subtotal,
  amountPaid,
  totalDue,
  onEditGrandTotal,
}) {
  return (
    <div
      className="rounded-xl border-2 border-orange-400 bg-orange-100 p-4 shadow-sm"
      data-testid="pdfi-tile-total"
    >
      <div className="flex items-center gap-2 text-orange-900 font-semibold uppercase tracking-wide text-xs mb-3">
        <DollarSign size={14} /> Invoice Total
      </div>
      <label className="block text-xs text-orange-900 mb-1">Grand total</label>
      <input
        type="number"
        step="0.01"
        value={grandTotal ?? 0}
        onChange={(e) => onEditGrandTotal?.(parseFloat(e.target.value) || 0)}
        className="w-full px-2 py-1 rounded border border-orange-400 bg-white text-sm font-semibold"
        data-testid="pdfi-tile-total-grand-input"
      />
      <div className="grid grid-cols-3 gap-2 mt-3 text-xs text-orange-900">
        <div>
          <div className="opacity-70">Subtotal</div>
          <div data-testid="pdfi-tile-total-subtotal">{_fmtMoney(subtotal)}</div>
        </div>
        <div>
          <div className="opacity-70">Paid</div>
          <div data-testid="pdfi-tile-total-paid">{_fmtMoney(amountPaid)}</div>
        </div>
        <div>
          <div className="opacity-70">Due</div>
          <div data-testid="pdfi-tile-total-due">{_fmtMoney(totalDue)}</div>
        </div>
      </div>
    </div>
  );
}
