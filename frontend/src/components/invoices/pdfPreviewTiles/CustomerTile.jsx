/**
 * PDFI-VB · Feb-2026 — Customer tile (LIGHT GREEN).
 *
 * Shows the parsed customer name + address with inline edit
 * affordances. Auto-match badge when ``matchedCustomerId`` is
 * set; otherwise the no-match path exposes TWO affordances:
 *
 *   * "Pick customer" → inline ``CustomerCombobox`` so the
 *     operator can snap to an existing customer; parent
 *     dispatches ``patchPreview`` with the picked id + name +
 *     address on ``onPickCustomer``.
 *   * "New" → mounts a lightweight shadcn ``Dialog`` with
 *     name / address / email / phone fields pre-filled from
 *     the parsed PDF.  On save it calls ``createCustomer`` and
 *     hands the result up via ``onCreateCustomer``; the parent
 *     dispatches a follow-up ``patchPreview`` to link the new
 *     customer id to the preview.  Full CustomerForm page
 *     remains the destination for deep editing — this modal
 *     is intentionally minimal.
 *
 * Recovery path: if ``patchPreview`` fails *after* the create
 * succeeds, the parent passes a ``createRecoveryCustomer``
 * descriptor back down; the tile renders an amber
 * "Customer created, retry link" chip so the operator can
 * re-fire the link without creating a duplicate.
 */
import React, { useState } from "react";
import {
  User, UserCheck, UserX, UserPlus, AlertCircle,
} from "lucide-react";
import { toast } from "sonner";

import { CustomerCombobox } from "@/components/customers/CustomerCombobox";
import { createCustomer } from "@/api/customers";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

export default function CustomerTile({
  customerName,
  customerAddress,
  matchedCustomerId,
  customers,
  onEditName,
  onEditAddress,
  onPickCustomer,
  onCreateCustomer,
  createRecoveryCustomer,
  onRetryCreateLink,
}) {
  const autoMatched = Boolean(matchedCustomerId);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createAddress, setCreateAddress] = useState("");
  const [createEmail, setCreateEmail] = useState("");
  const [createPhone, setCreatePhone] = useState("");

  const _onComboboxChange = (pickedId) => {
    const row = (customers || []).find((c) => c.id === pickedId);
    if (!row) return;
    onPickCustomer?.(row);
    setPickerOpen(false);
  };

  const _openCreate = () => {
    // Re-seed from latest tile state on each open so edits to the
    // tile name/address inputs after upload flow through.
    setCreateName(customerName || "");
    setCreateAddress(customerAddress || "");
    setCreateEmail("");
    setCreatePhone("");
    setCreateOpen(true);
  };

  const _onCreateSave = async () => {
    const trimmed = (createName || "").trim();
    if (!trimmed) return;
    setCreateBusy(true);
    try {
      const addr = (createAddress || "").trim();
      const payload = {
        name: trimmed,
        address: addr,
        billing_address: addr,
        email: (createEmail || "").trim(),
        phone: (createPhone || "").trim(),
      };
      const created = await createCustomer(payload);
      // Hand off to parent for the follow-up patchPreview link.
      // Parent catches link failures and surfaces the recovery chip.
      await onCreateCustomer?.(created);
      setCreateOpen(false);
    } catch (err) {
      toast.error(err?.message || "Failed to create customer.");
      // Keep modal open so user input is preserved.
    } finally {
      setCreateBusy(false);
    }
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
      {createRecoveryCustomer && (
        <div
          className="mt-3 flex items-center justify-between gap-2 rounded-md bg-amber-100 border border-amber-400 px-3 py-2"
          data-testid="pdfi-tile-customer-create-recovery-chip"
        >
          <span className="flex items-center gap-2 text-xs text-amber-900">
            <AlertCircle size={12} />
            Customer created, retry link
          </span>
          <button
            type="button"
            onClick={() => onRetryCreateLink?.(createRecoveryCustomer)}
            className="rounded-md bg-amber-700 hover:bg-amber-800 text-white text-xs px-2 py-1"
            data-testid="pdfi-tile-customer-create-recovery-retry-btn"
          >
            Retry link
          </button>
        </div>
      )}
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
            onClick={_openCreate}
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

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent data-testid="pdfi-tile-customer-create-modal">
          <DialogHeader>
            <DialogTitle>Create new customer</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="block text-xs text-slate-700 mb-1">
                Name <span className="text-red-700">*</span>
              </label>
              <input
                type="text"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                className="w-full px-2 py-1 rounded border border-slate-400 text-sm"
                data-testid="pdfi-tile-customer-create-name-input"
                placeholder="Full name"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs text-slate-700 mb-1">
                Address
              </label>
              <textarea
                rows={2}
                value={createAddress}
                onChange={(e) => setCreateAddress(e.target.value)}
                className="w-full px-2 py-1 rounded border border-slate-400 text-sm resize-none"
                data-testid="pdfi-tile-customer-create-address-input"
                placeholder="Street, city, state, zip"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-700 mb-1">
                Email
              </label>
              <input
                type="email"
                value={createEmail}
                onChange={(e) => setCreateEmail(e.target.value)}
                className="w-full px-2 py-1 rounded border border-slate-400 text-sm"
                data-testid="pdfi-tile-customer-create-email-input"
                placeholder="customer@example.com"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-700 mb-1">
                Phone
              </label>
              <input
                type="tel"
                value={createPhone}
                onChange={(e) => setCreatePhone(e.target.value)}
                className="w-full px-2 py-1 rounded border border-slate-400 text-sm"
                data-testid="pdfi-tile-customer-create-phone-input"
                placeholder="(555) 123-4567"
              />
            </div>
          </div>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              disabled={createBusy}
              className="rounded-md border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 text-sm px-3 py-1.5"
              data-testid="pdfi-tile-customer-create-cancel-btn"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={_onCreateSave}
              disabled={createBusy || !createName.trim()}
              className="rounded-md bg-green-700 hover:bg-green-800 disabled:bg-slate-300 disabled:cursor-not-allowed text-white text-sm px-3 py-1.5"
              data-testid="pdfi-tile-customer-create-save-btn"
            >
              {createBusy ? "Creating…" : "Create & link"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
