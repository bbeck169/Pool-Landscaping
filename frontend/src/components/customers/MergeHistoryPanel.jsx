/**
 * Feb-2026 · MergeHistoryPanel — collapsible merge-history
 * panel on the admin customer-profile page.
 *
 * Backs ``GET /api/customers/{customer_id}/merge-history`` +
 * ``POST /api/customer-merges/{audit_id}/rollback``
 * (BE SHA d8dd7eb49).
 *
 * Each row lists:
 *   • counterpart customer name
 *   • merged_at
 *   • actor id
 *   • remaining_rollback_days (0 = expired OR rolled back)
 *   • Rollback button (admin-only, enabled while
 *     remaining_rollback_days > 0 AND rolled_back_at === null)
 *
 * Clicking Rollback opens a small confirm modal; confirm →
 * POST ``/api/customer-merges/{audit_id}/rollback {confirm:true}``
 * → toast + refresh.
 *
 * ``props``:
 *   • customerId  — the profile customer's id.
 *   • canRollback — operator role flag.  Admin: show the
 *                   Rollback button.  Manager/other: panel
 *                   stays read-only (list still visible).
 */
import React, { useCallback, useEffect, useState } from "react";

import { api } from "@/api";
import { Button } from "@/components/ui-kit";


function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch { return String(iso); }
}


export function MergeHistoryPanel({
  customerId, canRollback = false,
}) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [rollbackTarget, setRollbackTarget] = useState(null);
  const [rollbackBusy, setRollbackBusy] = useState(false);
  const [rollbackError, setRollbackError] = useState(null);
  const [toast, setToast] = useState(null);
  const [refetchToken, setRefetchToken] = useState(0);

  useEffect(() => {
    if (!open || !customerId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await api.get(
          `/customers/${customerId}/merge-history`,
        );
        if (cancelled) return;
        setEntries(Array.isArray(resp?.entries) ? resp.entries : []);
      } catch (err) {
        if (!cancelled) {
          setError(err?.data?.detail?.message
                    || err?.message
                    || "Failed to load merge history.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, customerId, refetchToken]);

  const doRollback = useCallback(async () => {
    if (!rollbackTarget) return;
    setRollbackBusy(true);
    setRollbackError(null);
    try {
      await api.post(
        `/customer-merges/${rollbackTarget.audit_id}/rollback`,
        { confirm: true },
      );
      setRollbackTarget(null);
      setRefetchToken((t) => t + 1);
      setToast(
        `Rolled back the ${rollbackTarget.role === "winner"
          ? "merge from" : "merge into"
        } ${rollbackTarget.counterpart_customer_name
          || "the other customer"}.`,
      );
    } catch (err) {
      const detail = err?.data?.detail || {};
      setRollbackError(
        detail?.message
        || detail?.error_code
        || err?.message
        || "Rollback failed.",
      );
    } finally {
      setRollbackBusy(false);
    }
  }, [rollbackTarget]);

  return (
    <section
      className="rounded-xl border mb-4"
      style={{ borderColor: "#E5E7EB", backgroundColor: "white" }}
      data-testid="merge-history-panel"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
        data-testid="merge-history-panel-toggle"
      >
        <div>
          <div className="text-sm font-semibold">Merge history</div>
          <div className="text-xs text-gray-600 mt-0.5">
            Past merges where this customer was the winner or
            loser.  Rollback available for 90 days.
          </div>
        </div>
        <span className="text-xs text-gray-500">
          {open ? "Hide" : "Show"}
        </span>
      </button>
      {open ? (
        <div
          className="px-4 pb-4 border-t"
          style={{ borderColor: "#E5E7EB" }}
          data-testid="merge-history-panel-body"
        >
          {loading ? (
            <div className="py-3 text-xs text-gray-600"
                  data-testid="merge-history-loading">
              Loading…
            </div>
          ) : error ? (
            <div
              className="py-2 text-xs text-red-700"
              data-testid="merge-history-error"
            >{error}</div>
          ) : entries.length === 0 ? (
            <div
              className="py-3 text-xs text-gray-600"
              data-testid="merge-history-empty"
            >No merges on record for this customer.</div>
          ) : (
            <table className="w-full text-xs mt-2"
                     data-testid="merge-history-table">
              <thead>
                <tr style={{ backgroundColor: "#F9FAFB" }}>
                  <th className="text-left px-2 py-1.5">Role</th>
                  <th className="text-left px-2 py-1.5">Other customer</th>
                  <th className="text-left px-2 py-1.5">Merged at</th>
                  <th className="text-left px-2 py-1.5">Rollback window</th>
                  <th className="text-left px-2 py-1.5">&nbsp;</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => {
                  const canRollbackRow = (
                    canRollback
                    && !e.rolled_back_at
                    && (e.remaining_rollback_days || 0) > 0
                  );
                  return (
                    <tr key={e.audit_id} className="border-t"
                         style={{ borderColor: "#E5E7EB" }}
                         data-testid={`merge-history-row-${e.audit_id}`}>
                      <td className="px-2 py-1.5">
                        <span className="font-semibold uppercase tracking-wider text-[10px]">
                          {e.role}
                        </span>
                      </td>
                      <td className="px-2 py-1.5">
                        {e.counterpart_customer_name || "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        {_fmtDate(e.merged_at)}
                      </td>
                      <td className="px-2 py-1.5">
                        {e.rolled_back_at ? (
                          <span
                            className="text-[10px] rounded-full px-2 py-0.5"
                            style={{ backgroundColor: "#F3F4F6",
                                       color: "#4B5563" }}
                            data-testid={`merge-history-rolled-back-${e.audit_id}`}
                          >Rolled back {_fmtDate(e.rolled_back_at)}</span>
                        ) : e.remaining_rollback_days > 0 ? (
                          <span
                            className="text-[10px]"
                            style={{ color: "#1F2937" }}
                          >
                            {e.remaining_rollback_days}d remaining
                          </span>
                        ) : (
                          <span
                            className="text-[10px]"
                            style={{ color: "#9CA3AF" }}
                            data-testid={`merge-history-expired-${e.audit_id}`}
                          >Expired</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {canRollbackRow ? (
                          <Button
                            variant="secondary"
                            onClick={() => setRollbackTarget(e)}
                            testid={`merge-history-rollback-btn-${e.audit_id}`}
                          >Rollback</Button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {toast ? (
            <div
              className="mt-3 text-xs rounded-lg px-3 py-2"
              style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
              data-testid="merge-history-toast"
            >
              {toast}
              <button
                className="ml-3 text-[11px] underline"
                onClick={() => setToast(null)}
              >dismiss</button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Rollback confirm modal */}
      {rollbackTarget ? (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
          data-testid="merge-history-rollback-modal"
        >
          <div className="bg-white rounded-xl p-6 max-w-md w-full shadow-xl">
            <h3 className="text-base font-bold mb-2">
              Rollback this merge?
            </h3>
            <p className="text-xs text-gray-700 mb-3">
              Reverses the merge with{" "}
              <strong>{rollbackTarget.counterpart_customer_name
                       || "(unnamed)"}</strong>.
              Child records (jobs / invoices / payments / etc.)
              captured in the audit snapshot flip back to the
              loser; new activity assigned to the winner after
              the merge stays on the winner.  Credit balance,
              portal user, and Stripe payment-method remap are
              reversed too.
            </p>
            {rollbackError ? (
              <div
                className="mb-3 text-xs text-red-700"
                data-testid="merge-history-rollback-error"
              >{rollbackError}</div>
            ) : null}
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setRollbackTarget(null)}
                disabled={rollbackBusy}
                className="px-4 py-2 rounded-md border text-sm"
                data-testid="merge-history-rollback-cancel-btn"
              >Cancel</button>
              <button
                type="button"
                onClick={doRollback}
                disabled={rollbackBusy}
                className="px-4 py-2 rounded-md text-sm font-semibold text-white"
                style={{
                  backgroundColor: rollbackBusy ? "#9CA3AF" : "#1F2937",
                }}
                data-testid="merge-history-rollback-confirm-btn"
              >{rollbackBusy ? "Rolling back…" : "Confirm rollback"}</button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}


export default MergeHistoryPanel;
