/**
 * Feb-2026 · Customer Delete UX overhaul — dedicated 3-button
 * confirmation modal for the CustomerDetail delete flow.
 *
 * Distinct from the global ``ConfirmDeleteDialog`` (which has 15+
 * callers app-wide and a 2-button contract that would destabilise
 * on a variant-prop refactor). This component is purpose-built:
 *
 *   [Cancel]  [Soft Delete]  [Hard Delete 🛡]
 *
 * • Soft Delete → red-tinted secondary. Stamps ``deleted_at`` and
 *   the row can be restored via the CustomersList Restore chip
 *   (admin-tier). Preserves child rows / invoices / audit trail.
 * • Hard Delete → solid red destructive with a ``ShieldAlert``
 *   icon. Removes the customer row from ``db.customers``. Does
 *   NOT cascade — jobs / invoices / service reports / recurring
 *   templates keep a dangling ``customer_id`` and reads render
 *   "Unknown Customer" via ``utils/formatCustomerName``.
 *
 * No type-to-confirm friction (matches the app-wide Feb-2026
 * friction-removal + the explicit spec). Two-click safety is
 * preserved (click Delete on the detail page → click a mode inside
 * this modal).
 *
 * Test IDs (stable):
 *   customer-delete-modal        — the modal root
 *   customer-delete-title        — H2 title
 *   customer-delete-body         — descriptive paragraph
 *   customer-delete-cancel-btn   — cancel
 *   customer-delete-soft-btn     — soft-delete CTA
 *   customer-delete-hard-btn     — hard-delete CTA (red + shield)
 */
import React, { useEffect, useRef } from "react";
import { X, AlertTriangle, ShieldAlert } from "lucide-react";
import { colors } from "@/theme";

export default function CustomerDeleteModal({
  open,
  customer,               // { id, name, ... } — used only for the copy.
  busyMode = null,        // null | "soft" | "hard" — disables buttons + shows label.
  onCancel,
  onSoftDelete,           // () => Promise<void>
  onHardDelete,           // () => Promise<void>
}) {
  // Focus the soft-delete button on open (safer default than
  // focusing Hard).
  const softRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const t = setTimeout(() => {
      if (softRef.current) softRef.current.focus();
    }, 50);
    return () => clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape" && !busyMode) onCancel?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel, busyMode]);

  if (!open) return null;
  const name = (customer && customer.name) || "this customer";
  const disabled = Boolean(busyMode);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center px-4"
      style={{ backgroundColor: "rgba(15, 23, 42, 0.55)" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="customer-delete-title"
      data-testid="customer-delete-modal"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !disabled) onCancel?.();
      }}
    >
      <div
        className="w-full max-w-lg rounded-2xl shadow-2xl"
        style={{ backgroundColor: colors.surface }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-start justify-between px-5 py-3"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="flex items-start gap-2">
            <AlertTriangle
              size={18}
              style={{ color: "#B91C1C" }}
              className="mt-0.5"
            />
            <h2
              id="customer-delete-title"
              className="text-base font-bold"
              style={{ color: "#991B1B" }}
              data-testid="customer-delete-title"
            >
              Delete {name}?
            </h2>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={disabled}
            className="p-1 rounded-md hover:brightness-95 disabled:opacity-60"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
            }}
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-3">
          <div
            className="text-sm leading-relaxed"
            style={{ color: colors.onSurface }}
            data-testid="customer-delete-body"
          >
            <p>Pick how you'd like to remove this customer:</p>
            <ul className="mt-2 list-disc list-inside space-y-1">
              <li>
                <b>Soft Delete</b> — archives {name} and hides them
                from active lists. Jobs, invoices, reports, and
                history are preserved. An admin can Restore them
                from the Customers page.
              </li>
              <li>
                <b style={{ color: "#B91C1C" }}>Hard Delete</b> —
                permanently removes the customer row. Jobs, invoices,
                and service reports are <b>not</b> cascaded — they
                stay in place with the customer's snapshotted name
                (or "Unknown Customer" if the snapshot is missing).
                Blocked if the customer has any unpaid invoice. A
                super_admin can review the deletion in the audit
                trail.
              </li>
            </ul>
          </div>
        </div>

        {/* Footer buttons */}
        <div
          className="flex flex-wrap items-center justify-end gap-2 px-5 py-3"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <button
            type="button"
            onClick={onCancel}
            disabled={disabled}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold hover:brightness-95 disabled:opacity-60"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customer-delete-cancel-btn"
          >
            Cancel
          </button>
          <button
            ref={softRef}
            type="button"
            onClick={onSoftDelete}
            disabled={disabled}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              backgroundColor: "#FEE2E2",
              color: "#991B1B",
              border: `1px solid #FCA5A5`,
            }}
            data-testid="customer-delete-soft-btn"
          >
            {busyMode === "soft" ? "Soft-deleting…" : "Soft Delete"}
          </button>
          <button
            type="button"
            onClick={onHardDelete}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-bold text-white hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ backgroundColor: "#B91C1C" }}
            data-testid="customer-delete-hard-btn"
          >
            <ShieldAlert size={14} />
            {busyMode === "hard" ? "Hard-deleting…" : "Hard Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
