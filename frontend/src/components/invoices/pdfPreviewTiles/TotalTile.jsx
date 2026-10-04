/**
 * PDFI-IV · Feb-2026 — Totals tile (ORANGE).
 * PDFI-PAID-C · Feb-2026 — paid sub-row + operator date-pick.
 *
 * Shows the grand_total alongside subtotal / amount_paid /
 * total_due. The grand_total is editable; the sibling fields
 * are read-only displays taken straight from the preview.
 *
 * When ``isPaid === true`` an additional sub-row renders with
 * editable ``amount_paid`` + ``paid_at`` inputs (the operator
 * sets a payment date at preview-confirm when the extractor
 * couldn't derive one). A green PAID chip renders in the tile
 * header; if ``paid_at`` is missing an amber warning chip
 * blocks commit and the date input gets a red border + is
 * auto-focused on mount or when the parent increments
 * ``focusPaidAtKey`` (e.g. after a 422 ``paid_without_date``).
 */
import React, { useEffect, useRef } from "react";
import { DollarSign, CheckCircle2, AlertTriangle } from "lucide-react";

const _fmtMoney = (v) => {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "number" ? v : parseFloat(v);
  if (Number.isNaN(num)) return "—";
  return `$${num.toFixed(2)}`;
};

const _fmtDate = (iso) => {
  if (!iso) return "—";
  const s = String(iso);
  // ISO strings are already YYYY-MM-DD at the front; trim any time
  // suffix for the sub-row display without re-parsing.
  return s.length >= 10 ? s.slice(0, 10) : s;
};

export default function TotalTile({
  grandTotal,
  subtotal,
  amountPaid,
  totalDue,
  isPaid,
  paidAt,
  focusPaidAtKey = 0,
  onEditGrandTotal,
  onEditAmountPaid,
  onEditPaidAt,
}) {
  const paidAtRef = useRef(null);
  const tileRef = useRef(null);
  const needsPaidAt = isPaid === true && !paidAt;
  const dueIsRed = isPaid !== true && Number(totalDue) > 0;

  // PDFI-PAID-C focus lane. Unified effect handles three cases:
  //   1. Mount with ``needsPaidAt=true`` + ``focusPaidAtKey=0``
  //      (fresh preview opens with is_paid=true + paid_at=null).
  //   2. Mount with any ``focusPaidAtKey > 0`` after the parent
  //      cycled step preview_ready → committing → preview_ready
  //      following a 422 (the TotalTile remounts; focusPaidAtKey
  //      persists in parent state so we still re-focus).
  //   3. Parent bumps ``focusPaidAtKey`` while the tile stays
  //      mounted (another 422 round-trip without a step cycle).
  // Deliberately depends ONLY on ``focusPaidAtKey`` so operator
  // typing into the date input does not re-trigger focus mid-edit.
  useEffect(() => {
    if ((needsPaidAt || focusPaidAtKey > 0) && paidAtRef.current) {
      paidAtRef.current.focus();
      tileRef.current?.scrollIntoView?.({ block: "nearest" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusPaidAtKey]);

  return (
    <div
      ref={tileRef}
      className="rounded-xl border-2 border-orange-400 bg-orange-100 p-4 shadow-sm"
      data-testid="pdfi-tile-total"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-orange-900 font-semibold uppercase tracking-wide text-xs">
          <DollarSign size={14} /> Invoice Total
        </div>
        {isPaid === true && (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-green-600 text-white text-[10px] px-2 py-0.5 font-bold uppercase tracking-wider"
            data-testid="pdfi-tile-total-paid-chip"
          >
            <CheckCircle2 size={10} /> Paid
          </span>
        )}
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
          <div
            data-testid="pdfi-tile-total-due"
            className={dueIsRed ? "text-red-700 font-semibold" : ""}
          >
            {_fmtMoney(totalDue)}
          </div>
        </div>
      </div>

      {/* PDFI-PAID-C paid sub-row — only renders when the preview
          carries is_paid=true (operator-marked or extractor-derived
          under the STRICT ruling). Editable paid_at + amount_paid
          hit the PATCH /preview whitelist landed in PDFI-PAID-B. */}
      {isPaid === true && (
        <div
          className="mt-3 pt-3 border-t border-orange-300"
          data-testid="pdfi-tile-total-paid-row"
        >
          <div
            className="text-[11px] text-orange-900 opacity-80 mb-2"
            data-testid="pdfi-tile-total-paid-row-summary"
          >
            Amount paid: {_fmtMoney(amountPaid)} · on: {_fmtDate(paidAt)}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] text-orange-900 mb-0.5 uppercase tracking-wide">
                Amount paid
              </label>
              <input
                type="number"
                step="0.01"
                value={amountPaid ?? 0}
                onChange={(e) => onEditAmountPaid?.(parseFloat(e.target.value) || 0)}
                className="w-full px-2 py-1 rounded border border-orange-400 bg-white text-sm"
                data-testid="pdfi-tile-total-amount-paid-input"
              />
            </div>
            <div>
              <label className="block text-[10px] text-orange-900 mb-0.5 uppercase tracking-wide">
                Payment date
              </label>
              <input
                ref={paidAtRef}
                type="date"
                value={paidAt || ""}
                onChange={(e) => onEditPaidAt?.(e.target.value || null)}
                className={
                  needsPaidAt
                    ? "w-full px-2 py-1 rounded border-2 border-red-500 bg-red-50 text-sm"
                    : "w-full px-2 py-1 rounded border border-orange-400 bg-white text-sm"
                }
                data-testid="pdfi-tile-total-paid-at-input"
              />
            </div>
          </div>
          {needsPaidAt && (
            <div
              className="mt-2 inline-flex items-center gap-1 rounded-md bg-amber-100 border border-amber-400 text-amber-900 text-[10px] px-2 py-1 font-semibold"
              data-testid="pdfi-tile-total-paid-at-warning"
            >
              <AlertTriangle size={10} /> Payment date required to commit
            </div>
          )}
        </div>
      )}
    </div>
  );
}
