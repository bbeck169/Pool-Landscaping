/**
 * PDFI-IV · Feb-2026 — Customer tile (LIGHT GREEN).
 * Shows the parsed customer name + address with inline edit
 * affordances. Auto-match badge when ``matchedCustomerId`` is
 * set; otherwise a "Pick customer" fallback.
 */
import React from "react";
import { User, UserCheck, UserX } from "lucide-react";

export default function CustomerTile({
  customerName,
  customerAddress,
  matchedCustomerId,
  onEditName,
  onEditAddress,
  onPickCustomer,
}) {
  const autoMatched = Boolean(matchedCustomerId);
  return (
    <div
      className="rounded-xl border-2 border-green-300 bg-green-100 p-4 shadow-sm"
      data-testid="pdfi-tile-customer"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-green-900 font-semibold uppercase tracking-wide text-xs">
          <User size={14} /> Customer
        </div>
        {autoMatched ? (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-green-700 text-white text-xs px-2 py-0.5"
            data-testid="pdfi-tile-customer-matched-badge"
          >
            <UserCheck size={12} /> Auto-matched
          </span>
        ) : (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-red-100 text-red-800 text-xs px-2 py-0.5"
            data-testid="pdfi-tile-customer-no-match-badge"
          >
            <UserX size={12} /> No match found
          </span>
        )}
      </div>
      <label className="block text-xs text-green-900 mb-1">Name</label>
      <input
        type="text"
        value={customerName || ""}
        onChange={(e) => onEditName?.(e.target.value)}
        className="w-full px-2 py-1 rounded border border-green-400 bg-white text-sm mb-3"
        data-testid="pdfi-tile-customer-name-input"
        placeholder="Customer name"
      />
      <label className="block text-xs text-green-900 mb-1">Address</label>
      <textarea
        rows={2}
        value={customerAddress || ""}
        onChange={(e) => onEditAddress?.(e.target.value)}
        className="w-full px-2 py-1 rounded border border-green-400 bg-white text-sm resize-none"
        data-testid="pdfi-tile-customer-address-input"
        placeholder="Street, city, state, zip"
      />
      {!autoMatched && (
        <button
          type="button"
          onClick={onPickCustomer}
          className="mt-3 w-full rounded-lg bg-green-700 hover:bg-green-800 text-white text-sm font-medium py-2"
          data-testid="pdfi-tile-customer-pick-btn"
        >
          Pick customer
        </button>
      )}
    </div>
  );
}
