// Feb-2026 · Item 1 — Global destructive-action confirmation dialog.
//
// Every delete / cancel / purge / remove flow in the admin UI should
// funnel through this component. Two safety levels:
//
//   • Standard — red Confirm button + Cancel. Escape closes as
//     cancel. Confirm button gets focus so keyboard flow is fast.
//   • Heavy-blast — pass ``requireTypeConfirm`` + a
//     ``typeConfirmString`` (default "DELETE"). Confirm stays
//     disabled until the user types the exact string.
//
// Test IDs (stable):
//   confirm-delete-dialog        — the modal root
//   confirm-delete-title         — H2 title
//   confirm-delete-body          — descriptive paragraph
//   confirm-delete-type-input    — text input for the heavy blast
//   confirm-delete-confirm-btn   — the destructive CTA
//   confirm-delete-cancel-btn    — cancel
import React from "react";
import { X, AlertTriangle } from "lucide-react";
import { colors } from "@/theme";

export default function ConfirmDeleteDialog({
  open,
  title = "Delete item",
  body = "This action cannot be undone.",
  confirmLabel = "Delete",
  destructive = true,
  // Feb 2026 · Type-to-confirm friction removed app-wide. These
  // props stay in the signature so existing callers keep type-
  // checking cleanly, but they're intentionally not read below.
  // Underscore prefix satisfies the ``^_`` unused-vars allowlist.
  requireTypeConfirm: _requireTypeConfirm = false,
  typeConfirmString: _typeConfirmString = "DELETE",
  onConfirm,
  onCancel,
  busy = false,
}) {
  // Feb 2026 · Type-to-confirm friction removed app-wide.
  // ``requireTypeConfirm`` + ``typeConfirmString`` remain in the
  // API surface for backwards-compat but are intentionally
  // ignored — the text input is no longer rendered and the
  // Confirm button starts immediately enabled. Two-click safety
  // (click Delete to open modal → click Confirm inside) is
  // preserved.
  const confirmRef = React.useRef(null);

  React.useEffect(() => {
    if (open) {
      // Focus the confirm button on open for keyboard-first flow.
      const t = setTimeout(() => {
        if (confirmRef.current) confirmRef.current.focus();
      }, 50);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [open]);

  React.useEffect(() => {
    if (!open) return undefined;
    const handler = (e) => { if (e.key === "Escape") onCancel?.(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onCancel]);

  if (!open) return null;
  const disabled = busy;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center"
      style={{ backgroundColor: "rgba(15, 23, 42, 0.55)" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-delete-title"
      data-testid="confirm-delete-dialog"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel?.(); }}
    >
      <div
        className="w-full max-w-md rounded-2xl shadow-2xl"
        style={{ backgroundColor: colors.surface }}
      >
        <div
          className="flex items-start justify-between px-5 py-3"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="flex items-start gap-2">
            {destructive ? (
              <AlertTriangle size={18} style={{ color: "#B91C1C" }} className="mt-0.5" />
            ) : null}
            <h2
              id="confirm-delete-title"
              className="text-base font-bold"
              style={{ color: destructive ? "#991B1B" : colors.onSurface }}
              data-testid="confirm-delete-title"
            >{title}</h2>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="p-1 rounded-md hover:brightness-95"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
            aria-label="Close"
          ><X size={14} /></button>
        </div>

        <div className="p-5 space-y-3">
          <div className="text-sm leading-relaxed"
               style={{ color: colors.onSurface }}
               data-testid="confirm-delete-body">
            {body}
          </div>
          {/* Feb 2026 · Type-to-confirm input removed — see comment
              at top of the component. The ``requireTypeConfirm`` +
              ``typeConfirmString`` props are still accepted so
              callers don't need to be updated en masse. */}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3"
             style={{ borderTop: `1px solid ${colors.border}` }}>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold hover:brightness-95 disabled:opacity-60"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="confirm-delete-cancel-btn"
          >Cancel</button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={disabled}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ backgroundColor: destructive ? "#B91C1C" : colors.brand }}
            data-testid="confirm-delete-confirm-btn"
          >{busy ? "…" : confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
