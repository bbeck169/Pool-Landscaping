/**
 * SendToCustomerModal · Feb-2026 · UX Polish Batch B
 *
 * Modal + endpoint wiring for the "Send" toolbar action on a quote
 * detail page. Fires ``POST /api/quotes/{qid}/send-to-customer``
 * with an optional recipient override + an optional admin note.
 *
 * On success: fires ``onSent({quote_id, status, sent_at, email_sent,
 * recipient})`` and closes.
 * On failure: fires ``onError(detail)`` and keeps the modal open so
 * the admin can adjust the input.
 *
 * See /app/memory/FEATURE_SEND_TO_CUSTOMER_AND_COST_TELEMETRY.md § 1.
 */
import React, { useEffect, useState } from "react";
import { Button, Modal } from "@/components/ui-kit";
import { api } from "@/api";
import { colors } from "@/theme";
import { Send } from "lucide-react";


export default function SendToCustomerModal({
  open,
  quoteId,
  primaryEmail,
  onClose,
  onSent,
  onError,
}) {
  const [busy, setBusy] = useState(false);
  const [useOverride, setUseOverride] = useState(false);
  const [override, setOverride] = useState("");
  const [note, setNote] = useState("");

  // Reset on every open so a prior draft doesn't leak into a new send.
  useEffect(() => {
    if (open) {
      setBusy(false);
      setUseOverride(false);
      setOverride("");
      setNote("");
    }
  }, [open, quoteId]);

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    const body = {};
    if (useOverride) {
      body.recipient_email = (override || "").trim();
    }
    if ((note || "").trim()) {
      body.note = note.trim().slice(0, 500);
    }
    try {
      const r = await api.post(`/quotes/${quoteId}/send-to-customer`, body);
      onSent && onSent(r);
    } catch (e) {
      onError && onError(e?.message || "Send failed.");
    } finally {
      setBusy(false);
    }
  };

  const recipientPreview = useOverride
    ? (override || "").trim() || "(enter an address)"
    : primaryEmail || "(no primary email on file)";

  return (
    <Modal open={open} onClose={onClose} title="Send quote to customer"
              testid="send-to-customer-modal">
      <div className="space-y-4">
        <div>
          <div className="text-xs uppercase tracking-wide mb-1"
                  style={{ color: colors.muted }}>
            Recipient
          </div>
          <div className="text-sm" data-testid="send-to-customer-recipient-preview">
            {recipientPreview}
          </div>
          <label className="mt-2 flex items-center gap-2 text-sm cursor-pointer"
                    data-testid="send-to-customer-override-row">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={useOverride}
              onChange={(e) => setUseOverride(!!e.target.checked)}
              data-testid="send-to-customer-override-toggle"
            />
            <span>Send to a different address</span>
          </label>
          {useOverride ? (
            <input
              type="email"
              className="mt-2 w-full border rounded px-2 py-1.5 text-sm"
              value={override}
              onChange={(e) => setOverride(e.target.value)}
              placeholder="name@example.com"
              data-testid="send-to-customer-override-input"
            />
          ) : null}
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide mb-1"
                  style={{ color: colors.muted }}>
            Admin note (audit only — not shown to customer)
          </div>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value.slice(0, 500))}
            rows={3}
            maxLength={500}
            className="w-full border rounded px-2 py-1.5 text-sm"
            placeholder="Optional context recorded on the send audit log."
            data-testid="send-to-customer-note-input"
          />
          <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
            {note.length}/500
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}
                    testid="send-to-customer-cancel">Cancel</Button>
          <Button
            onClick={submit}
            disabled={busy || (useOverride && !override.trim())}
            testid="send-to-customer-submit"
          >
            <Send size={14} /> {busy ? "Sending…" : "Send"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
