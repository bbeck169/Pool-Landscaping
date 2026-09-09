/**
 * Feb-2026 · Editable Sent Docs · Phase 1 — shared confirmation
 * dialog rendered before mutating a document whose status has passed
 * ``draft`` (sent / accepted / paid).
 *
 * Two warnings can stack:
 *   • Stripe-paid → "This invoice has been paid via Stripe. Editing
 *     will NOT refund or alter the payment. Continue?"
 *   • Signed     → "Editing this document will invalidate the existing
 *     customer signature. A new signature will be required. Continue?"
 *
 * Both banners are exact copy approved by the user for Phase 1. Copy
 * MUST NOT be altered without a design ping.
 */
import React from "react";
import { AlertTriangle } from "lucide-react";
import { colors } from "@/theme";
import { Button, Modal } from "@/components/ui-kit";


export default function EditLockConfirmDialog({
  open,
  onCancel,
  onConfirm,
  isStripePaid = false,
  isSigned = false,
  busy = false,
  status = "",
}) {
  const statusLabel = String(status || "").toLowerCase();
  const genericLine = statusLabel
    ? `This document has status "${statusLabel}". Editing after send may create audit or bookkeeping issues.`
    : "This document has already been sent. Editing may create audit or bookkeeping issues.";
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Confirm edit"
      testid="edit-lock-confirm-dialog"
      footer={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={onCancel}
            testid="edit-lock-confirm-cancel"
            disabled={busy}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={onConfirm}
            disabled={busy}
            testid="edit-lock-confirm-continue"
          >
            {busy ? "Saving…" : "Continue editing"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {isStripePaid ? (
          <div
            className="rounded-xl p-3 text-sm flex items-start gap-2"
            style={{ background: "#FEE2E2", color: "#7F1D1D",
                      border: "1px solid #FCA5A5" }}
            data-testid="edit-lock-stripe-warning"
          >
            <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
            <span>
              This invoice has been paid via Stripe. Editing will NOT refund
              or alter the payment. Continue?
            </span>
          </div>
        ) : null}
        {isSigned ? (
          <div
            className="rounded-xl p-3 text-sm flex items-start gap-2"
            style={{ background: "#FEF3C7", color: "#78350F",
                      border: "1px solid #FCD34D" }}
            data-testid="edit-lock-signature-warning"
          >
            <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
            <span>
              Editing this document will invalidate the existing customer
              signature. A new signature will be required. Continue?
            </span>
          </div>
        ) : null}
        {!isStripePaid && !isSigned ? (
          <p className="text-sm"
             style={{ color: colors.onSurfaceSecondary }}
             data-testid="edit-lock-generic-warning">
            {genericLine}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
