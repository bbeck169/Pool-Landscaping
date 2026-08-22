// Feb-2026 · P26 — Super_admin "Restore" surface for soft-deleted
// customers. Renders a small pill button inline in the customers-list
// row; clicking opens a confirmation modal that calls
// PATCH /customers/{cid}/restore and reports back via a toast + list
// refresh. Not rendered for non-super_admin — the P25 backend also
// blocks include_deleted=true for non-super_admin so this button
// should never be reachable, but we double-gate on the client for
// belt-and-suspenders.

import React, { useState, useCallback } from "react";
import { api } from "@/api";


export default function RestoreCustomerButton({
  customer,
  onRestored,      // (payload) => void
  onError,         // (message) => void
  disabled,
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const wasAnonymized = Boolean(customer?.anonymized_at);

  const stop = useCallback((e) => {
    e.stopPropagation();
    e.preventDefault();
  }, []);

  const openModal = useCallback((e) => {
    stop(e);
    if (disabled || busy) return;
    setOpen(true);
  }, [disabled, busy, stop]);

  const closeModal = useCallback((e) => {
    if (e) stop(e);
    if (busy) return;
    setOpen(false);
  }, [busy, stop]);

  const confirm = useCallback(async (e) => {
    stop(e);
    setBusy(true);
    try {
      const res = await api.patch(
        `/customers/${customer.id}/restore`, {},
      );
      setOpen(false);
      onRestored?.(res);
    } catch (err) {
      onError?.(err?.message || "Failed to restore customer");
    } finally {
      setBusy(false);
    }
  }, [customer, onRestored, onError, stop]);

  return (
    <>
      <button
        type="button"
        onClick={openModal}
        disabled={disabled || busy}
        data-testid={`restore-customer-btn-${customer.id}`}
        className="text-xs font-semibold px-2 py-1 rounded border transition"
        style={{
          borderColor: "#0EA5E9",
          color: "#0EA5E9",
          background: "transparent",
          opacity: disabled || busy ? 0.5 : 1,
        }}
      >
        {busy ? "Restoring…" : "Restore"}
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(15, 23, 42, 0.55)" }}
          onClick={closeModal}
          data-testid={`restore-customer-modal-${customer.id}`}
        >
          <div
            className="max-w-md w-full mx-4 rounded-lg shadow-xl p-6"
            style={{ background: "#fff" }}
            onClick={stop}
          >
            <h2
              className="text-lg font-bold mb-2"
              style={{ color: "#0F172A" }}
            >
              Restore this customer?
            </h2>
            <p className="text-sm mb-3" style={{ color: "#334155" }}>
              They&apos;ll appear in the active customer list again.
            </p>

            {wasAnonymized ? (
              <div
                className="text-sm mb-4 p-3 rounded border"
                style={{
                  borderColor: "#F59E0B",
                  background: "rgba(245, 158, 11, 0.08)",
                  color: "#78350F",
                }}
                data-testid={`restore-anonymized-warning-${customer.id}`}
              >
                <b>Warning:</b> This customer&apos;s personal information
                was previously scrubbed and cannot be recovered. Only
                the deletion state will be restored — name, email, phone,
                and address will remain blank.
              </div>
            ) : null}

            <div className="flex items-center justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={closeModal}
                disabled={busy}
                data-testid={`restore-customer-cancel-${customer.id}`}
                className="px-3 py-2 text-sm font-semibold rounded border"
                style={{
                  borderColor: "#E5E7EB", color: "#334155",
                  background: "#fff",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirm}
                disabled={busy}
                data-testid={`restore-customer-confirm-${customer.id}`}
                className="px-3 py-2 text-sm font-semibold rounded"
                style={{
                  background: "#0EA5E9", color: "#fff",
                  opacity: busy ? 0.6 : 1,
                }}
              >
                {busy ? "Restoring…" : "Yes, restore"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
