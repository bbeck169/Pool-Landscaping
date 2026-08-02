/**
 * Phase 26 · Feb-2026 — Super-admin Review Department Suggestions modal.
 *
 * Distinct from the Phase-20 modal at
 * ``src/pages/admin/SuggestDepartmentsModal.jsx``:
 *   • Loads the same ``POST /api/admin/suggest-departments`` list.
 *   • Applies via the NEW ``POST /api/admin/apply-department-suggestions``
 *     endpoint — super-admin gated, writes to
 *     ``db.department_change_audit``.
 *   • Suggested department per row is editable — the admin can
 *     override the AI suggestion via a dropdown before applying.
 *   • Response contract:
 *         { applied: N, failed: [{user_id, reason}] }
 *     Success toast if ``failed`` is empty; warning toast with counts
 *     otherwise; error toast on non-2xx.
 *
 * The component is fully controlled — parent owns ``open`` /
 * ``onClose`` — so any admin surface can drop it in.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api";

const DEPT_OPTIONS = [
  { value: "pool_tech",       label: "Pool tech" },
  { value: "landscape_tech",  label: "Landscape tech" },
  { value: "both",            label: "Both" },
];
const DEPT_LABELS = Object.fromEntries(
  DEPT_OPTIONS.map((o) => [o.value, o.label]),
);

function _formatConfidence(c) {
  if (c === null || c === undefined) return "—";
  return `${Math.round(Number(c) * 100)}%`;
}

export default function SuggestDepartmentsModal({ open, onClose, onApplied }) {
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState({});    // {user_id: true}
  const [overrides, setOverrides] = useState({});  // {user_id: dept}

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // The Phase-18 endpoint is a POST (no body needed). Same
      // wire-format as the Phase-20 modal — we just consume the
      // review-shape and apply via the Phase-26 endpoint.
      const r = await api.post("/admin/suggest-departments", {});
      const suggestions = (r?.suggestions || []).filter(
        (s) => s.suggested_department,
      );
      setRows(suggestions);
      // Preselect high-confidence rows so the common case is a
      // single click. Overrides mirror the AI suggestion until the
      // admin picks something different.
      const preselect = {};
      const preOverrides = {};
      suggestions.forEach((s) => {
        preOverrides[s.user_id] = s.suggested_department;
        if ((s.confidence ?? 0) >= 0.75) preselect[s.user_id] = true;
      });
      setSelected(preselect);
      setOverrides(preOverrides);
    } catch (e) {
      setError(e?.message || "Failed to load suggestions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      load();
    } else {
      // Reset on close so a re-open shows fresh data.
      setRows([]);
      setSelected({});
      setOverrides({});
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

  const setOverride = (uid, dept) =>
    setOverrides((o) => ({ ...o, [uid]: dept }));

  const applySelected = async () => {
    const applications = rows
      .filter((r) => selected[r.user_id])
      .map((r) => ({
        user_id: r.user_id,
        department: overrides[r.user_id] || r.suggested_department,
      }));
    if (!applications.length) return;

    setApplying(true);
    try {
      const r = await api.post(
        "/admin/apply-department-suggestions",
        { applications },
      );
      const applied = r?.applied ?? 0;
      const failed = Array.isArray(r?.failed) ? r.failed : [];
      if (failed.length === 0) {
        toast.success(
          `${applied} department${applied === 1 ? "" : "s"} updated`,
        );
      } else {
        toast(
          `${applied} applied · ${failed.length} failed`,
          { description: failed.map((f) => f.reason).join(", ") },
        );
      }
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
      data-testid="phase26-suggest-departments-modal"
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h2 className="text-lg font-semibold">
              Review department suggestions
            </h2>
            <p className="text-xs text-neutral-500 mt-0.5">
              Super-admin only. Each applied change is audit-logged
              to ``department_change_audit``.
            </p>
          </div>
          <button
            data-testid="phase26-close"
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
              data-testid="phase26-loading"
            >
              Loading suggestions…
            </div>
          ) : error ? (
            <div
              className="p-3 border border-red-300 bg-red-50 text-red-700 rounded text-sm"
              data-testid="phase26-error"
            >
              {error}
            </div>
          ) : rows.length === 0 ? (
            <div
              className="text-center text-sm text-neutral-500 py-8"
              data-testid="phase26-empty"
            >
              No suggestions available — every tech already has a
              department assigned.
            </div>
          ) : (
            <table className="w-full text-sm" data-testid="phase26-table">
              <thead className="bg-neutral-50">
                <tr>
                  <th className="p-2 text-left">
                    <input
                      type="checkbox"
                      data-testid="phase26-toggle-all"
                      checked={selectedCount === rows.length && rows.length > 0}
                      onChange={toggleAll}
                      aria-label="Select all"
                    />
                  </th>
                  <th className="p-2 text-left">Technician</th>
                  <th className="p-2 text-left">Current</th>
                  <th className="p-2 text-left">Suggested</th>
                  <th className="p-2 text-left">Confidence</th>
                  <th className="p-2 text-left">Rationale</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.user_id}
                    className="border-t"
                    data-testid={`phase26-row-${r.user_id}`}
                  >
                    <td className="p-2">
                      <input
                        type="checkbox"
                        data-testid={`phase26-check-${r.user_id}`}
                        checked={!!selected[r.user_id]}
                        onChange={() => toggleRow(r.user_id)}
                        aria-label={`Select ${r.name}`}
                      />
                    </td>
                    <td className="p-2 font-medium">{r.name}</td>
                    <td className="p-2 text-neutral-500">
                      {DEPT_LABELS[r.current_department] || "—"}
                    </td>
                    <td className="p-2">
                      <select
                        value={overrides[r.user_id] || r.suggested_department}
                        onChange={(e) => setOverride(r.user_id, e.target.value)}
                        className="text-sm border rounded px-1 py-0.5"
                        data-testid={`phase26-override-${r.user_id}`}
                      >
                        {DEPT_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="p-2">{_formatConfidence(r.confidence)}</td>
                    <td className="p-2 text-xs text-neutral-500">
                      {r.signals?.pool_jobs ?? 0} pool ·{" "}
                      {r.signals?.landscape_jobs ?? 0} landscape ·{" "}
                      {r.signals?.days_window ?? 90}d
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="p-4 border-t flex items-center justify-between">
          <span
            className="text-xs text-neutral-500"
            data-testid="phase26-selected-count"
          >
            {selectedCount} of {rows.length} selected
          </span>
          <div className="flex gap-2">
            <button
              data-testid="phase26-cancel"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded border hover:bg-neutral-50"
            >
              Cancel
            </button>
            <button
              data-testid="phase26-apply"
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
