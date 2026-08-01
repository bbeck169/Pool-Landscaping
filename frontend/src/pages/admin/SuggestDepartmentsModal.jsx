/**
 * Phase 20 · Feb-2026 · Sub-item A — Suggest Departments admin modal.
 *
 * Consumes the Phase 18 backend endpoint
 * ``POST /api/admin/suggest-departments`` and lets an admin bulk-apply
 * the inferred ``pool_tech | landscape_tech | both`` department to
 * multiple technicians in one request via
 * ``POST /api/admin/users/bulk-department`` (new in Phase 20).
 *
 * Presentation contract:
 *   * Loading spinner while the suggest call is inflight.
 *   * Table of suggestions (tech name, current dept, suggested dept,
 *     confidence, job-count basis, per-row checkbox).
 *   * "Apply selected" primary CTA.
 *   * "Cancel" closes without changes.
 *   * Empty state when the endpoint returns zero non-trivial
 *     suggestions ("All techs have departments assigned").
 *   * Admin+ only — role gating happens on the server; the button
 *     that opens this modal already sits inside `AdminOnly` scaffolding.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api";

const DEPT_LABELS = {
  pool_tech: "Pool tech",
  landscape_tech: "Landscape tech",
  both: "Both",
};

function _formatConfidence(c) {
  if (c === null || c === undefined) return "—";
  return `${Math.round(Number(c) * 100)}%`;
}

export default function SuggestDepartmentsModal({ open, onClose, onApplied }) {
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState({}); // {user_id: true}

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.post("/admin/suggest-departments", {});
      const suggestions = (r?.suggestions || []).filter(
        (s) => s.suggested_department, // hide rows with no signal
      );
      setRows(suggestions);
      // Default-check every high-confidence (≥ 0.75) row per the brief.
      const preselect = {};
      suggestions.forEach((s) => {
        if ((s.confidence ?? 0) >= 0.75) preselect[s.user_id] = true;
      });
      setSelected(preselect);
    } catch (e) {
      setError(e?.message || "Failed to load suggestions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
    if (!open) {
      // Reset on close.
      setRows([]);
      setSelected({});
      setError("");
    }
  }, [open, load]);

  const selectedCount = useMemo(
    () => Object.values(selected).filter(Boolean).length,
    [selected],
  );

  const toggleRow = (uid) =>
    setSelected((s) => ({ ...s, [uid]: !s[uid] }));

  const toggleAll = () => {
    if (selectedCount === rows.length) setSelected({});
    else setSelected(Object.fromEntries(rows.map((r) => [r.user_id, true])));
  };

  const applySelected = async () => {
    const assignments = rows
      .filter((r) => selected[r.user_id])
      .map((r) => ({
        user_id: r.user_id,
        department: r.suggested_department,
      }));
    if (!assignments.length) return;
    setApplying(true);
    try {
      const r = await api.post("/admin/users/bulk-department", {
        assignments,
      });
      toast.success(
        `${r?.updated_count ?? 0} of ${assignments.length} technicians updated`,
      );
      onApplied && onApplied(r);
      onClose && onClose();
    } catch (e) {
      toast.error(e?.message || "Bulk apply failed");
    } finally {
      setApplying(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      data-testid="suggest-departments-modal"
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h2 className="text-lg font-semibold">Suggest departments</h2>
            <p className="text-xs text-neutral-500 mt-0.5">
              Based on each tech's last-90-day service-type distribution.
              Uncheck rows you don't want to apply.
            </p>
          </div>
          <button
            data-testid="suggest-departments-close"
            onClick={onClose}
            className="text-neutral-500 hover:text-neutral-800 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div
              className="text-center text-sm text-neutral-500 py-8"
              data-testid="suggest-departments-loading"
            >
              Loading suggestions…
            </div>
          ) : error ? (
            <div
              className="p-3 border border-red-300 bg-red-50 text-red-700 rounded text-sm"
              data-testid="suggest-departments-error"
            >
              {error}
            </div>
          ) : rows.length === 0 ? (
            <div
              className="text-center text-sm text-neutral-500 py-8"
              data-testid="suggest-departments-empty"
            >
              All techs already have departments assigned — no
              suggestions to apply.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-neutral-50">
                <tr>
                  <th className="p-2 text-left">
                    <input
                      type="checkbox"
                      data-testid="suggest-departments-toggle-all"
                      checked={selectedCount === rows.length && rows.length > 0}
                      onChange={toggleAll}
                    />
                  </th>
                  <th className="p-2 text-left">Technician</th>
                  <th className="p-2 text-left">Current</th>
                  <th className="p-2 text-left">Suggested</th>
                  <th className="p-2 text-left">Confidence</th>
                  <th className="p-2 text-left">Signals (90d)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.user_id}
                    className="border-t"
                    data-testid={`suggest-row-${r.user_id}`}
                  >
                    <td className="p-2">
                      <input
                        type="checkbox"
                        data-testid={`suggest-check-${r.user_id}`}
                        checked={!!selected[r.user_id]}
                        onChange={() => toggleRow(r.user_id)}
                      />
                    </td>
                    <td className="p-2 font-medium">{r.name}</td>
                    <td className="p-2 text-neutral-500">
                      {DEPT_LABELS[r.current_department] || "—"}
                    </td>
                    <td className="p-2">
                      {DEPT_LABELS[r.suggested_department] || "—"}
                    </td>
                    <td className="p-2">{_formatConfidence(r.confidence)}</td>
                    <td className="p-2 text-xs text-neutral-500">
                      {r.signals?.pool_jobs ?? 0} pool ·{" "}
                      {r.signals?.landscape_jobs ?? 0} landscape
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="p-4 border-t flex items-center justify-between">
          <span className="text-xs text-neutral-500">
            {selectedCount} of {rows.length} selected
          </span>
          <div className="flex gap-2">
            <button
              data-testid="suggest-departments-cancel"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded border hover:bg-neutral-50"
            >
              Cancel
            </button>
            <button
              data-testid="suggest-departments-apply"
              onClick={applySelected}
              disabled={applying || selectedCount === 0}
              className="px-4 py-2 text-sm rounded bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {applying ? "Applying…" : `Apply selected (${selectedCount})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
