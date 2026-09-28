/**
 * MTH-B · Feb-2026 — Reusable "reason required" modal.
 *
 * Mirrors the HD-A/HD-B pattern used by ``HardDeleteModal`` and
 * the various admin credit / adjustment surfaces:
 *
 *   1. 8-char minimum reason gate — Confirm button disabled until
 *      the trimmed reason hits the threshold.
 *   2. Live character counter with success / warning tint.
 *   3. Optional warning banner slot (super-only master-switch flip
 *      uses this to surface the "enable live comms" caveat).
 *   4. Optional preview slot (revert flow renders a diff preview).
 *   5. ``busy`` state while the parent's onConfirm promise resolves.
 *
 * No new visual language — Modal + Button + TextInput from
 * ``@/components/ui-kit``.
 */
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Button, Modal, TextInput } from "@/components/ui-kit";

export const REASON_MIN = 8;

/**
 * @param {object}   props
 * @param {boolean}  props.open
 * @param {string}   props.title
 * @param {string=}  props.description   Free-form paragraph above the input.
 * @param {React.ReactNode=} props.warning  Amber banner slot (optional).
 * @param {React.ReactNode=} props.preview  Neutral preview slot (optional).
 * @param {string=}  props.confirmLabel     Defaults to "Save".
 * @param {"primary"|"danger"} props.confirmVariant   Defaults to "primary".
 * @param {(reason: string) => Promise<void>} props.onConfirm
 * @param {() => void} props.onClose
 * @param {string=}  props.testidPrefix     Defaults to "ai-rules-reason".
 * @param {string=}  props.placeholder
 */
export default function RulesReasonModal({
  open,
  title,
  description,
  warning,
  preview,
  confirmLabel = "Save",
  confirmVariant = "primary",
  onConfirm,
  onClose,
  testidPrefix = "ai-rules-reason",
  placeholder = "e.g. Onboarding review · switching to admin-approval for all outbound",
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      setReason("");
      setBusy(false);
    }
  }, [open]);

  const trimmed = reason.trim();
  const reasonOk = trimmed.length >= REASON_MIN;

  const confirm = useCallback(async () => {
    if (!reasonOk || busy) return;
    setBusy(true);
    try {
      await onConfirm(trimmed);
    } finally {
      setBusy(false);
    }
  }, [reasonOk, busy, trimmed, onConfirm]);

  if (!open) return null;

  return (
    <Modal
      open={open}
      onClose={busy ? () => {} : onClose}
      title={title}
      testid={`${testidPrefix}-modal`}
      footer={
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={busy}
            testid={`${testidPrefix}-cancel`}
          >
            Cancel
          </Button>
          <Button
            variant={confirmVariant}
            onClick={confirm}
            disabled={!reasonOk || busy}
            testid={`${testidPrefix}-confirm`}
          >
            {busy ? "Saving…" : confirmLabel}
          </Button>
        </div>
      }
    >
      <div
        className="space-y-4 text-sm"
        data-testid={`${testidPrefix}-body`}
      >
        {description ? (
          <p
            className="opacity-80"
            data-testid={`${testidPrefix}-description`}
          >
            {description}
          </p>
        ) : null}

        {warning ? (
          <div
            className="rounded-md p-3 flex gap-2"
            style={{
              background: "#FEF3C7",
              color: "#92400E",
              border: "1px solid #FDE68A",
            }}
            data-testid={`${testidPrefix}-warning`}
          >
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            <div>{warning}</div>
          </div>
        ) : null}

        {preview ? (
          <div
            data-testid={`${testidPrefix}-preview`}
            className="rounded-md p-3"
            style={{
              background: "#F1F5F9",
              color: "#334155",
              border: "1px solid #E2E8F0",
            }}
          >
            {preview}
          </div>
        ) : null}

        <div>
          <TextInput
            label={`REASON (${REASON_MIN}-char min · required)`}
            testid={`${testidPrefix}-input`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={placeholder}
            disabled={busy}
          />
          <div
            className="text-xs mt-1"
            style={{ color: reasonOk ? "#059669" : "#92400E" }}
            data-testid={`${testidPrefix}-hint`}
          >
            {reasonOk
              ? `${trimmed.length} chars — good.`
              : `Need ${REASON_MIN - trimmed.length} more character(s).`}
          </div>
        </div>
      </div>
    </Modal>
  );
}
