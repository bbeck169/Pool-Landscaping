/**
 * Phase 4b · Feb-2026 — Quotes bulk toolbar.
 *
 * Sticky action bar surfaced on ``/quotes`` when 1+ quotes are
 * checked.  Carries the selection count, three bulk-action CTAs
 * (``Accept`` / ``Decline`` / ``Delete``) matched to the per-row
 * variants used elsewhere on the page, and a dismiss / "clear
 * selection" affordance.
 *
 * Delete is DESTRUCTIVE — the component opens a confirm modal
 * before firing the bulk-delete POST so the user has a chance to
 * back out of an N-row destructive action.
 *
 * Purely presentational (except for the local confirm modal
 * state).  The parent (``QuotesList``) owns the API calls + toast
 * surface so the component stays testable in isolation.
 */
import React, { useState } from "react";
import { Check, X, Trash2 } from "lucide-react";


export default function QuotesBulkToolbar({
  selectedCount,
  onAccept,
  onDecline,
  onDelete,
  onClear,
  busy = false,
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  if (!selectedCount || selectedCount <= 0) return null;

  const openConfirm = () => setConfirmOpen(true);
  const cancelConfirm = () => setConfirmOpen(false);
  const confirmDelete = async () => {
    setConfirmOpen(false);
    await onDelete?.();
  };

  return (
    <>
      <div
        className="sticky top-0 z-20 mb-4 rounded-xl px-4 py-3 flex items-center flex-wrap gap-2"
        style={{
          background:    "#1E293B",   // slate-800 — strong signal that an operational mode is active
          color:         "#FFFFFF",
          border:        "1px solid #334155",
          boxShadow:     "0 2px 8px rgba(0,0,0,0.08)",
        }}
        data-testid="quotes-bulk-toolbar"
        role="toolbar"
        aria-label="Quotes bulk actions"
      >
        <span
          className="text-sm font-semibold"
          data-testid="quotes-bulk-toolbar-count"
        >
          {selectedCount} quote{selectedCount === 1 ? "" : "s"} selected
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onAccept}
          disabled={busy}
          className="text-xs font-semibold px-3 py-1.5 rounded-md inline-flex items-center gap-1 hover:brightness-110"
          style={{
            background: "#059669",   // emerald-600
            color:      "#FFFFFF",
            opacity:    busy ? 0.6 : 1,
            cursor:     busy ? "not-allowed" : "pointer",
          }}
          data-testid="quotes-bulk-accept-btn"
        >
          <Check size={13} /> Accept
        </button>
        <button
          type="button"
          onClick={onDecline}
          disabled={busy}
          className="text-xs font-semibold px-3 py-1.5 rounded-md inline-flex items-center gap-1 hover:brightness-110"
          style={{
            // Red-adjacent danger variant matching the per-row
            // Decline chip in QuotesList.jsx (FEE2E2 bg / #DC2626
            // text), inverted here because the toolbar is dark.
            background: "#DC2626",
            color:      "#FFFFFF",
            opacity:    busy ? 0.6 : 1,
            cursor:     busy ? "not-allowed" : "pointer",
          }}
          data-testid="quotes-bulk-decline-btn"
        >
          <X size={13} /> Decline
        </button>
        <button
          type="button"
          onClick={openConfirm}
          disabled={busy}
          className="text-xs font-semibold px-3 py-1.5 rounded-md inline-flex items-center gap-1 hover:brightness-110"
          style={{
            background: "#7F1D1D",   // red-900 — distinct from Decline
            color:      "#FFFFFF",
            opacity:    busy ? 0.6 : 1,
            cursor:     busy ? "not-allowed" : "pointer",
          }}
          data-testid="quotes-bulk-delete-btn"
        >
          <Trash2 size={13} /> Delete
        </button>
        <button
          type="button"
          onClick={onClear}
          disabled={busy}
          className="ml-1 inline-flex items-center justify-center rounded-md p-1 hover:bg-white/10"
          style={{ color: "#CBD5E1" }}
          data-testid="quotes-bulk-clear-btn"
          title="Clear selection"
          aria-label="Clear selection"
        >
          <X size={16} />
        </button>
      </div>

      {confirmOpen ? (
        <div
          className="fixed inset-0 z-30 flex items-center justify-center"
          style={{ background: "rgba(15,23,42,0.5)" }}
          data-testid="quotes-bulk-delete-confirm"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="rounded-xl p-5 w-[min(400px,92vw)]"
            style={{ background: "#FFFFFF", color: "#0F172A" }}
          >
            <h3
              className="text-base font-bold mb-2"
              style={{ color: "#0F172A" }}
              data-testid="quotes-bulk-delete-confirm-title"
            >
              Delete {selectedCount} quote{selectedCount === 1 ? "" : "s"}?
            </h3>
            <p className="text-sm mb-4" style={{ color: "#475569" }}>
              This cannot be undone. Any quote with a converted
              invoice will be skipped.
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={cancelConfirm}
                className="text-sm font-semibold px-3 py-1.5 rounded-md"
                style={{
                  background: "#F1F5F9", color: "#0F172A",
                  border: "1px solid #CBD5E1",
                }}
                data-testid="quotes-bulk-delete-confirm-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                className="text-sm font-semibold px-3 py-1.5 rounded-md"
                style={{ background: "#7F1D1D", color: "#FFFFFF" }}
                data-testid="quotes-bulk-delete-confirm-ok"
              >
                Delete {selectedCount} quote{selectedCount === 1 ? "" : "s"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
