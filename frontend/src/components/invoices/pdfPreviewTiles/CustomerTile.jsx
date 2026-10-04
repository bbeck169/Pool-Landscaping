/**
 * PDFI-V · Feb-2026 — Customer tile (LIGHT GREEN).
 *
 * Shows the parsed customer name + address with inline edit
 * affordances. Auto-match badge when ``matchedCustomerId`` is
 * set; otherwise the no-match path reveals an inline
 * ``CustomerCombobox`` so the operator can snap to an existing
 * customer (parent dispatches ``patchPreview`` with the picked
 * id + name + address on ``onPickCustomer``).
 *
 * The "Create new customer" affordance remains a stub for now
 * (toast placeholder) — full modal wiring was deferred out of
 * PDFI-V to keep scope on the auto-match + pick-existing happy
 * paths, which cover the common operator flow.
 */
import React, { useState } from "react";
import { User, UserCheck, UserX, UserPlus } from "lucide-react";
import { toast } from "sonner";

import { CustomerCombobox } from "@/components/customers/CustomerCombobox";

export default function CustomerTile({
  customerName,
  customerAddress,
  matchedCustomerId,
  customers,
  onEditName,
  onEditAddress,
  onPickCustomer,
}) {
  const autoMatched = Boolean(matchedCustomerId);
  const [pickerOpen, setPickerOpen] = useState(false);

  const _onComboboxChange = (pickedId) => {
    const row = (customers || []).find((c) => c.id === pickedId);
    if (!row) return;
    onPickCustomer?.(row);
    setPickerOpen(false);
  };

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
      {!autoMatched && !pickerOpen && (
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="flex-1 rounded-lg bg-green-700 hover:bg-green-800 text-white text-sm font-medium py-2"
            data-testid="pdfi-tile-customer-pick-btn"
          >
            Pick customer
          </button>
          <button
            type="button"
            onClick={() => toast.info("New-customer modal wiring lands in a follow-up atomic.")}
            className="inline-flex items-center gap-1 rounded-lg border border-green-700 text-green-800 hover:bg-green-50 text-xs font-medium px-3 py-2"
            data-testid="pdfi-tile-customer-create-btn"
          >
            <UserPlus size={12} /> New
          </button>
        </div>
      )}
      {!autoMatched && pickerOpen && (
        <div className="mt-3" data-testid="pdfi-tile-customer-picker-container">
          <CustomerCombobox
            value={null}
            onChange={_onComboboxChange}
            customers={customers || []}
            testid="pdfi-tile-customer-combobox"
            placeholder="Search customers…"
          />
          <button
            type="button"
            onClick={() => setPickerOpen(false)}
            className="mt-2 text-xs text-green-900 underline"
            data-testid="pdfi-tile-customer-picker-cancel"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
