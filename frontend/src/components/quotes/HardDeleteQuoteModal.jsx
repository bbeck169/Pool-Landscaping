/**
 * HardDeleteQuoteModal · Feb-2026
 *
 * Confirmation modal for the destructive hard-delete of a quote.
 * Fires ``DELETE /api/quotes/{qid}?hard=true`` on Confirm. On success
 * navigates the caller (via ``onDeleted``); on failure surfaces the
 * backend detail message via ``onError`` and keeps the modal open.
 *
 * Contract per FEATURE_QUOTE_HARD_DELETE.md:
 *   * RBAC guard is on the CALLER — this modal has no role check.
 *   * NO audit-log trail is written server-side. Front-end reflects
 *     that in the warning copy so the user acknowledges it.
 *   * 409 responses surface the backend detail verbatim (e.g. the
 *     "converted to invoice" refusal).
 */
import React, { useState } from "react";
import { Button, Modal } from "@/components/ui-kit";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { Trash2 } from "lucide-react";


export default function HardDeleteQuoteModal({
  open,
  quoteId,
  quoteNumber,
  customerName,
  totalAmount,
  onClose,
  onDeleted,
  onError,
}) {
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const r = await api.del(`/quotes/${quoteId}?hard=true`);
      onDeleted?.(r);
    } catch (e) {
      // Surface the backend detail message verbatim so 409 invoice-
      // conversion refusals reach the user unmodified.
      const detail = e?.detail || e?.message || "Hard delete failed";
      onError?.(detail);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={busy ? undefined : onClose}
      title="Hard delete this quote?"
      footer={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={busy}
            testid="hard-delete-quote-cancel"
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={run}
            disabled={busy}
            testid="hard-delete-quote-confirm"
          >
            <Trash2 size={14} />
            {busy ? " Deleting…" : " Confirm Hard Delete"}
          </Button>
        </div>
      }
    >
      <div
        data-testid="hard-delete-quote-body"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr",
            columnGap: 16, rowGap: 6,
            fontSize: 14,
            color: colors.onSurfaceSecondary,
          }}
        >
          <dt>Quote #</dt>
          <dd
            data-testid="hard-delete-quote-number"
            style={{ color: colors.onSurface, fontWeight: 600 }}
          >
            {quoteNumber || quoteId}
          </dd>
          <dt>Customer</dt>
          <dd
            data-testid="hard-delete-quote-customer"
            style={{ color: colors.onSurface }}
          >
            {customerName || "—"}
          </dd>
          <dt>Total</dt>
          <dd
            data-testid="hard-delete-quote-total"
            style={{ color: colors.onSurface, fontWeight: 600 }}
          >
            {typeof totalAmount === "number"
              ? money(totalAmount)
              : (totalAmount ?? "—")}
          </dd>
        </dl>
        <p
          data-testid="hard-delete-quote-warning"
          style={{
            fontSize: 13,
            color: colors.dangerText || "#b91c1c",
            background: colors.dangerSurface || "rgba(239,68,68,0.08)",
            borderRadius: 6,
            padding: "10px 12px",
            margin: 0,
          }}
        >
          This will permanently delete this quote. This action cannot
          be undone and leaves no record.
        </p>
      </div>
    </Modal>
  );
}
