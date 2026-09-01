/**
 * TypedConfirmModal · Phase H2 · Feb-2026 (F5 Wave 2).
 *
 * Typed-keyword confirm gate for catastrophic actions where a plain
 * two-click arm-and-execute isn't enough context to prevent a
 * disaster — the operator must literally type the tenant slug /
 * campaign name / an all-caps sentinel before the destructive button
 * enables.
 *
 * Used by:
 *   • TenantsAdminPage.jsx     — Deactivate tenant  (keyword = slug)
 *   • QuickBooksIntegrationPage.jsx — Force full sync (keyword = "FORCE SYNC")
 *   • M2Campaigns.jsx          — Cancel campaign    (keyword = campaign name)
 *
 * Deliberately case-sensitive: catastrophic actions deserve the
 * friction. The parent supplies the keyword; comparison is exact.
 */
import React, { useState, useEffect, useCallback } from "react";

export default function TypedConfirmModal({
  open,
  title,
  description,
  keyword,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
  busy = false,
  testIdPrefix = "typed-confirm",
}) {
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  const armed = typed === keyword;

  const handleKey = useCallback((e) => {
    if (!open) return;
    if (e.key === "Escape" && !busy) onCancel?.();
  }, [open, busy, onCancel]);

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onCancel?.();
      }}
      data-testid={`${testIdPrefix}-modal`}
    >
      <div
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl bg-white"
        style={{ border: "1px solid rgba(15,23,42,0.10)" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-900"
            data-testid={`${testIdPrefix}-title`}>
          {title}
        </h2>
        <p className="text-sm mt-2 text-slate-700"
           data-testid={`${testIdPrefix}-desc`}>
          {description}
        </p>
        <input
          type="text"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoFocus
          placeholder={keyword}
          className="mt-4 w-full px-3 py-2 rounded-lg text-sm outline-none border border-slate-300"
          data-testid={`${testIdPrefix}-input`}
        />
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 text-slate-800 disabled:opacity-40"
            data-testid={`${testIdPrefix}-cancel`}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!armed || busy}
            className="px-4 py-2 rounded-xl text-sm font-bold text-white bg-red-600 hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid={`${testIdPrefix}-confirm`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
