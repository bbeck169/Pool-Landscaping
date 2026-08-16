/**
 * Queue Item 4 · Feb-2026 — Per-record Demo-account toggle.
 *
 * Renders a small pill-style toggle beside a customer or user row
 * that hits PATCH /api/comms/demo-flag. Because flipping the flag
 * changes whether that record will receive outbound comms, the
 * toggle is guarded by a hard-confirm modal (no soft dismiss —
 * user must click either Cancel or Confirm).
 *
 * Props:
 *   recordType   — "user" | "customer"
 *   recordId     — string
 *   isDemo       — current boolean state (controlled)
 *   recordLabel  — human-friendly identifier for the confirm modal
 *   onChange     — (nextValue: boolean) => void, fires after success
 *   size         — "sm" | "md" (default "md")
 *   compact      — boolean, hides the outer "Demo" label copy
 */
import React, { useState } from "react";
import { ShieldCheck, ShieldOff, X as XIcon } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";

export default function DemoAccountToggle({
  recordType,
  recordId,
  isDemo,
  recordLabel,
  onChange,
  size = "md",
  compact = false,
}) {
  const [pending, setPending] = useState(false);
  const [modal, setModal] = useState({ open: false, nextValue: null });

  const active = !!isDemo;
  const nextVal = !active;
  const openConfirm = () => setModal({ open: true, nextValue: nextVal });
  const closeConfirm = () => { if (!pending) setModal({ open: false, nextValue: null }); };

  const confirm = async () => {
    setPending(true);
    try {
      await api.patch("/comms/demo-flag", {
        record_type: recordType,
        record_id: recordId,
        is_demo_account: modal.nextValue,
      });
      onChange?.(modal.nextValue);
      toast.success(
        modal.nextValue
          ? "Demo whitelist flag ENABLED — this record can receive outbound comms"
          : "Demo whitelist flag DISABLED — comms suppressed",
      );
      setModal({ open: false, nextValue: null });
    } catch (e) {
      const msg = (e?.message || "").includes("demo_flag_requires_admin_or_manager")
        ? "Admin or manager access required"
        : (e?.message || "Toggle failed");
      toast.error(msg);
    } finally { setPending(false); }
  };

  const isSm = size === "sm";
  const iconSize = isSm ? 12 : 14;

  return (
    <>
      <button
        type="button"
        onClick={openConfirm}
        className={`inline-flex items-center gap-1.5 rounded-full font-semibold transition ${
          isSm ? "px-2 py-0.5 text-[11px]" : "px-3 py-1 text-xs"
        }`}
        style={{
          backgroundColor: active ? "#DCFCE7" : colors.surfaceSecondary,
          color: active ? "#166534" : colors.onSurfaceSecondary,
          border: `1px solid ${active ? "#86EFAC" : colors.border}`,
        }}
        title={active
          ? "Demo whitelist ENABLED — this record can send/receive outbound comms"
          : "Demo whitelist DISABLED — comms suppressed"}
        data-testid={`demo-flag-toggle-${recordType}-${recordId}`}
        aria-pressed={active}
      >
        {active ? (
          <ShieldCheck size={iconSize} />
        ) : (
          <ShieldOff size={iconSize} />
        )}
        {compact ? null : (active ? "Demo: ON" : "Demo: OFF")}
      </button>

      {modal.open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeConfirm(); }}
          data-testid={`demo-flag-confirm-modal-${recordType}-${recordId}`}
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  {modal.nextValue ? "Enable" : "Disable"} demo whitelist
                  {recordLabel ? ` for ${recordLabel}` : ""}?
                </h2>
                <p className="text-sm mt-2" style={{ color: colors.muted }}>
                  {modal.nextValue ? (
                    <>
                      Setting <b>is_demo_account = true</b> means this{" "}
                      {recordType} will bypass the outbound-comms safety
                      gate. Real emails / SMS may be sent. This is
                      audit-logged.
                    </>
                  ) : (
                    <>
                      Setting <b>is_demo_account = false</b> immediately
                      suppresses all future outbound emails and SMS to
                      this {recordType}. This is audit-logged.
                    </>
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={closeConfirm}
                className="p-1"
                style={{ color: colors.muted }}
                aria-label="Close"
                data-testid={`demo-flag-confirm-close-${recordType}-${recordId}`}
              >
                <XIcon size={18} />
              </button>
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeConfirm}
                className="px-4 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                data-testid={`demo-flag-confirm-cancel-${recordType}-${recordId}`}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirm}
                disabled={pending}
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                style={{
                  backgroundColor: modal.nextValue ? colors.brandSecondary : colors.error,
                }}
                data-testid={`demo-flag-confirm-btn-${recordType}-${recordId}`}
              >
                {pending
                  ? "Saving…"
                  : (modal.nextValue ? "Enable demo comms" : "Disable demo comms")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
