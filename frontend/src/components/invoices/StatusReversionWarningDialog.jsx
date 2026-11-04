/**
 * TD-paid-invoice-admin-edit-unblock · Feb-2026 — status-reversion
 * warning dialog for paid-invoice financial edits.
 *
 * Fired by InvoiceEditModal AFTER the shared
 * <EditLockConfirmDialog> arms the acknowledged_lock_bypass +
 * typed-number proof, when the pending diff would push the
 * recomputed ``total`` ABOVE the recorded ``amount_paid``.  The
 * BE's ``remaining_balance = max(total - amount_paid, 0)``
 * formula will silently flip status from ``paid`` back to
 * ``partial`` on save; this dialog surfaces that side effect so
 * the admin consciously opts in.
 *
 * Single-button confirm.  Copy approved by the operator.
 */
import React from "react";
import { AlertTriangle } from "lucide-react";
import { colors, money } from "@/theme";
import { Button, Modal } from "@/components/ui-kit";


export default function StatusReversionWarningDialog({
  open, onCancel, onConfirm,
  amountPaid = 0,
  newTotal = 0,
  busy = false,
}) {
  const _paid = Number(amountPaid || 0);
  const _total = Number(newTotal || 0);
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Status will revert to Partially Paid"
      testid="invoice-edit-status-reversion-warning-dialog"
      footer={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={onCancel}
            disabled={busy}
            testid="invoice-edit-status-reversion-warning-cancel"
          >
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={busy}
            testid="invoice-edit-status-reversion-warning-btn"
          >
            Confirm
          </Button>
        </div>
      }
    >
      <div
        className="rounded-xl p-3 text-sm flex items-start gap-2"
        style={{
          background: "#FEE2E2",
          color: "#7F1D1D",
          border: "1px solid #FCA5A5",
        }}
        data-testid="invoice-edit-status-reversion-warning-body"
      >
        <AlertTriangle size={16} />
        <span>
          Saving will flip this invoice's status from{" "}
          <b>Paid</b> back to <b>Partially Paid</b>.
          <br />
          Amount paid: <b
            data-testid="invoice-edit-status-reversion-warning-amount-paid"
          >{money(_paid)}</b>
          {" · "}
          New total: <b
            data-testid="invoice-edit-status-reversion-warning-new-total"
          >{money(_total)}</b>
          {" · "}
          Remaining balance after save: <b
            data-testid="invoice-edit-status-reversion-warning-remaining"
          >{money(Math.max(_total - _paid, 0))}</b>.
          <br />
          Stripe reconciliation is NOT automatic — you'll need to
          collect the difference or issue a refund manually.
        </span>
      </div>
    </Modal>
  );
}
