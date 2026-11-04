/**
 * TD-paid-invoice-admin-edit-unblock · Feb-2026 — category-change
 * confirm dialog for paid-invoice edits.
 *
 * Fired by InvoiceEditModal when an admin edits any of a paid
 * invoice's line-item category keys (``category``,
 * ``income_category_id``, ``service_category``,
 * ``service_category_id``).  Single-button confirm — no typed
 * proof, no captcha — because the retroactive side effect
 * (revenue-by-category reports for the paid period re-slice) is
 * visible and recoverable via the invoice_edit_history audit trail.
 *
 * Copy approved by the operator.  Changing the text requires a
 * product ping; the dialog is specifically about retroactive
 * category reporting drift, not the generic lock bypass.
 */
import React from "react";
import { AlertTriangle } from "lucide-react";
import { colors } from "@/theme";
import { Button, Modal } from "@/components/ui-kit";


export default function CategoryEditConfirmDialog({
  open, onCancel, onConfirm, busy = false,
}) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Confirm category change"
      testid="invoice-edit-category-change-confirm-dialog"
      footer={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={onCancel}
            disabled={busy}
            testid="invoice-edit-category-change-confirm-cancel"
          >
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={busy}
            testid="invoice-edit-category-change-confirm-btn"
          >
            Confirm
          </Button>
        </div>
      }
    >
      <div
        className="rounded-xl p-3 text-sm flex items-start gap-2"
        style={{
          background: "#FEF3C7",
          color: "#78350F",
          border: "1px solid #FCD34D",
        }}
        data-testid="invoice-edit-category-change-confirm-body"
      >
        <AlertTriangle size={16} />
        <span>
          Changing categories on a paid invoice will retroactively
          affect revenue-by-category reports for the period this
          invoice was paid in.  Monthly P&amp;L exports regenerated
          after this edit will reflect the new category.  The full
          before/after diff is captured in the invoice audit log.
        </span>
      </div>
    </Modal>
  );
}
