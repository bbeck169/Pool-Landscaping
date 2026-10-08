import React from "react";
import { colors } from "@/theme";
import { Button, Modal } from "@/components/ui-kit";

/**
 * BULK-PORTAL-INVITE-FILTER · Feb-2026 — confirmation dialog for
 * the "Bulk Portal Invite" button sitting inline in the Customers
 * filter bar.  Spec:
 *
 *   * Shows the total eligible count (customers who have never
 *     signed into the portal — ``first_access=never`` cohort).
 *   * Warns when ``total > 200`` because the existing Phase-H1
 *     bulk endpoint caps batches at 200 per request — the user
 *     needs to know only the first 200 ship in this round.
 *   * Progress spinner while POSTing.
 *   * Cancel / Send Invites CTAs.
 *
 * Purely presentational — the parent (``CustomersList``) owns the
 * fetch/post state so the component stays testable in isolation.
 */
const _BATCH_CAP = 200;

export default function BulkPortalInviteConfirm({
  open,
  preview,
  onCancel,
  onConfirm,
  busy = false,
}) {
  if (!open) return null;

  const total = Number(preview?.total || 0);
  const willSend = Math.min(total, _BATCH_CAP);
  const remainder = Math.max(0, total - _BATCH_CAP);
  const hasAny = total > 0;

  return (
    <Modal
      open={open}
      onClose={busy ? () => {} : onCancel}
      title="Bulk Portal Invite"
      testid="bulk-portal-invite-modal"
    >
      <div className="space-y-4"
            data-testid="bulk-portal-invite-modal-body">
        {hasAny ? (
          <p className="text-sm" style={{ color: colors.onSurface }}>
            You are about to send portal invites to{" "}
            <b data-testid="bulk-portal-invite-count">{total}</b>{" "}
            customer{total === 1 ? "" : "s"} who have never signed
            into the portal.
          </p>
        ) : (
          <p className="text-sm"
              style={{ color: colors.muted }}
              data-testid="bulk-portal-invite-zero">
            No eligible customers match the current filter — everyone
            visible has already signed into the portal.
          </p>
        )}

        {remainder > 0 && (
          <div
            className="p-3 rounded-xl text-xs flex items-start gap-2"
            style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
            data-testid="bulk-portal-invite-cap-warning"
          >
            <div>
              The bulk invite endpoint caps each run at{" "}
              <b>{_BATCH_CAP}</b> customers.  Only the first{" "}
              <b>{willSend}</b> will be sent in this batch —{" "}
              <b>{remainder}</b> remaining.  Re-run the invite after
              the first batch completes to send the rest, or narrow
              the filter.
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={onCancel}
            disabled={busy}
            testid="bulk-portal-invite-cancel-btn"
          >
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={busy || !hasAny}
            testid="bulk-portal-invite-confirm-btn"
          >
            {busy ? "Sending…" : `Send ${willSend} Invite${willSend === 1 ? "" : "s"}`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
