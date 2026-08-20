/**
 * Feb-2026 · Phase 1 finisher — Job Outcome Reasons admin settings.
 *
 * Drives the pre-existing endpoints in
 * ``backend/routers/could_not_service.py``:
 *
 *   GET    /api/settings/job-outcome-reasons?include_inactive=true
 *   POST   /api/settings/job-outcome-reasons          {label, sort_order?}
 *   PATCH  /api/settings/job-outcome-reasons/{id}     {label?, sort_order?, active?}
 *   DELETE /api/settings/job-outcome-reasons/{id}
 *
 * Server auto-hydrates 7 seeded defaults on first GET. Defaults are
 * flagged ``is_default: true`` — the backend blocks hard-delete on them,
 * so the UI only offers "deactivate" for defaults and hard-delete for
 * tenant-added reasons.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Plus, Pencil, Trash2, ArrowUp, ArrowDown, X, EyeOff, Eye } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";
import { Button } from "@/components/ui-kit";


function ReasonForm({ initial, onClose, onSaved }) {
  const [label, setLabel] = useState(initial?.label || "");
  const [sortOrder, setSortOrder] = useState(
    Number.isFinite(initial?.sort_order) ? String(initial.sort_order) : "",
  );
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const editing = Boolean(initial?.id);

  const save = async () => {
    const trimmed = label.trim();
    if (!trimmed) { setErr("Label is required."); return; }
    setBusy(true); setErr("");
    try {
      const payload = { label: trimmed };
      if (sortOrder !== "" && Number.isFinite(Number(sortOrder))) {
        payload.sort_order = Number(sortOrder);
      }
      const res = editing
        ? await api.patch(`/settings/job-outcome-reasons/${initial.id}`, payload)
        : await api.post("/settings/job-outcome-reasons", payload);
      onSaved?.(res);
    } catch (e) {
      const detail = e?.message || "";
      if (/already exists/i.test(detail)) setErr("A reason with that label already exists.");
      else setErr(detail || "Save failed.");
    } finally { setBusy(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onClick={onClose}
      data-testid="jor-form-backdrop"
    >
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="jor-form"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold" style={{ color: colors.onSurface }}>
            {editing ? "Edit outcome reason" : "New outcome reason"}
          </div>
          <button onClick={onClose} data-testid="jor-form-close" style={{ color: colors.muted }}>
            <X size={18} />
          </button>
        </header>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label
              className="text-xs uppercase font-semibold block mb-1"
              style={{ color: colors.muted }}
            >
              Label *
            </label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              autoFocus
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid="jor-form-label"
            />
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              The server generates a stable slug key from the label.
              Renaming does not change the key.
            </div>
          </div>
          <div>
            <label
              className="text-xs uppercase font-semibold block mb-1"
              style={{ color: colors.muted }}
            >
              Sort order
            </label>
            <input
              type="number"
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
              placeholder="auto"
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid="jor-form-sort"
            />
          </div>
          {err ? (
            <div
              className="rounded-xl p-2 text-xs"
              style={{ background: "#FEE2E2", color: "#7F1D1D", border: "1px solid #FCA5A5" }}
              data-testid="jor-form-error"
            >
              {err}
            </div>
          ) : null}
        </div>
        <footer
          className="px-5 py-3 flex justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}`, background: colors.surfaceSecondary }}
        >
          <Button variant="ghost" onClick={onClose} testid="jor-form-cancel">
            Cancel
          </Button>
          <Button onClick={save} disabled={busy} testid="jor-form-save">
            {busy ? "Saving…" : "Save"}
          </Button>
        </footer>
      </div>
    </div>
  );
}


export default function JobOutcomeReasonsPage() {
  const [items, setItems] = useState(null);
  const [includeInactive, setIncludeInactive] = useState(true);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState("");
  const [toast, setToast] = useState("");

  const load = useCallback(async () => {
    try {
      const suffix = includeInactive ? "?include_inactive=true" : "";
      const r = await api.get(`/settings/job-outcome-reasons${suffix}`);
      setItems(Array.isArray(r?.reasons) ? r.reasons : []);
    } catch (e) {
      setItems([]);
      setToast(e?.message || "Failed to load reasons.");
    }
  }, [includeInactive]);

  useEffect(() => { load(); }, [load]);

  const patchOne = async (id, payload, successMsg) => {
    setBusyId(id);
    try {
      await api.patch(`/settings/job-outcome-reasons/${id}`, payload);
      if (successMsg) setToast(successMsg);
      await load();
    } catch (e) {
      setToast(e?.message || "Update failed.");
    } finally { setBusyId(""); }
  };

  const toggleActive = (r) =>
    patchOne(
      r.id,
      { active: !r.active },
      r.active ? `"${r.label}" deactivated.` : `"${r.label}" reactivated.`,
    );

  const move = (r, direction) => {
    // Swap sort_order with the neighbouring item in the current sort.
    if (!items || items.length < 2) return;
    const sorted = [...items].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
    const idx = sorted.findIndex((x) => x.id === r.id);
    const swapIdx = direction === "up" ? idx - 1 : idx + 1;
    if (idx < 0 || swapIdx < 0 || swapIdx >= sorted.length) return;
    const a = sorted[idx];
    const b = sorted[swapIdx];
    const aOrd = a.sort_order ?? 0;
    const bOrd = b.sort_order ?? 0;
    Promise.all([
      api.patch(`/settings/job-outcome-reasons/${a.id}`, { sort_order: bOrd }),
      api.patch(`/settings/job-outcome-reasons/${b.id}`, { sort_order: aOrd }),
    ])
      .then(load)
      .catch((e) => setToast(e?.message || "Reorder failed."));
  };

  const hardDelete = async (r) => {
    if (r.is_default) {
      setToast('Seeded default — use "Deactivate" instead.');
      return;
    }
    if (!window.confirm(`Delete "${r.label}"? This cannot be undone.`)) return;
    setBusyId(r.id);
    try {
      await api.del(`/settings/job-outcome-reasons/${r.id}`);
      setToast(`"${r.label}" deleted.`);
      await load();
    } catch (e) {
      setToast(e?.message || "Delete failed.");
    } finally { setBusyId(""); }
  };

  const sortedItems = items
    ? [...items].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))
    : null;

  return (
    <div className="max-w-4xl mx-auto p-4" data-testid="job-outcome-reasons-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-black" style={{ color: colors.onSurface }}>
            Job Outcome Reasons
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Preset list shown in the "Could Not Service" modal on the schedule.
            Techs pick one when a job can't be completed. Seven defaults are
            provisioned automatically for every tenant.
          </p>
        </div>
        <Button onClick={() => setEditing({})} testid="jor-new">
          <Plus size={14} /> New reason
        </Button>
      </div>

      <label className="flex items-center gap-2 mb-3 text-sm">
        <input
          type="checkbox"
          checked={includeInactive}
          onChange={(e) => setIncludeInactive(e.target.checked)}
          data-testid="jor-show-inactive"
        />
        <span style={{ color: colors.muted }}>Show inactive reasons</span>
      </label>

      {toast ? (
        <div
          className="rounded-xl p-2 mb-3 text-xs flex items-center justify-between"
          style={{ background: "#FEF3C7", color: "#78350F", border: "1px solid #FCD34D" }}
          data-testid="jor-toast"
        >
          <span>{toast}</span>
          <button onClick={() => setToast("")} style={{ color: "#78350F" }} aria-label="Dismiss">
            <X size={12} />
          </button>
        </div>
      ) : null}

      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <table className="w-full text-sm" data-testid="jor-table">
          <thead style={{ background: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Order</th>
              <th className="text-left px-3 py-2 font-semibold">Label</th>
              <th className="text-left px-3 py-2 font-semibold">Key</th>
              <th className="text-center px-3 py-2 font-semibold">Origin</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
              <th className="w-44 px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {sortedItems === null ? (
              <tr>
                <td colSpan="6" className="px-3 py-4 text-center" style={{ color: colors.muted }}>
                  Loading…
                </td>
              </tr>
            ) : sortedItems.length === 0 ? (
              <tr>
                <td colSpan="6" className="px-3 py-4 text-center" style={{ color: colors.muted }}>
                  No outcome reasons yet.
                </td>
              </tr>
            ) : sortedItems.map((r, idx) => (
              <tr
                key={r.id}
                style={{
                  borderTop: `1px solid ${colors.border}`,
                  opacity: r.active ? 1 : 0.55,
                }}
                data-testid={`jor-row-${r.id}`}
              >
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => move(r, "up")}
                      disabled={busyId === r.id || idx === 0}
                      className="p-1"
                      style={{ color: colors.brand, opacity: idx === 0 ? 0.3 : 1 }}
                      data-testid={`jor-up-${r.id}`}
                      title="Move up"
                    >
                      <ArrowUp size={13} />
                    </button>
                    <button
                      onClick={() => move(r, "down")}
                      disabled={busyId === r.id || idx === sortedItems.length - 1}
                      className="p-1"
                      style={{
                        color: colors.brand,
                        opacity: idx === sortedItems.length - 1 ? 0.3 : 1,
                      }}
                      data-testid={`jor-down-${r.id}`}
                      title="Move down"
                    >
                      <ArrowDown size={13} />
                    </button>
                    <span className="ml-1 font-mono text-xs" style={{ color: colors.muted }}>
                      {r.sort_order ?? 0}
                    </span>
                  </div>
                </td>
                <td
                  className="px-3 py-2 font-semibold"
                  style={{ color: colors.onSurface }}
                  data-testid={`jor-label-${r.id}`}
                >
                  {r.label}
                </td>
                <td className="px-3 py-2 font-mono text-xs" style={{ color: colors.muted }}>
                  {r.key}
                </td>
                <td className="px-3 py-2 text-center text-xs">
                  {r.is_default ? (
                    <span
                      className="px-2 py-0.5 rounded-full"
                      style={{ background: "#E0E7FF", color: "#3730A3" }}
                    >
                      Default
                    </span>
                  ) : (
                    <span
                      className="px-2 py-0.5 rounded-full"
                      style={{ background: "#F3F4F6", color: "#374151" }}
                    >
                      Custom
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-center text-xs">
                  {r.active ? (
                    <span
                      className="px-2 py-0.5 rounded-full"
                      style={{ background: "#DCFCE7", color: "#166534" }}
                      data-testid={`jor-status-${r.id}`}
                    >
                      Active
                    </span>
                  ) : (
                    <span
                      className="px-2 py-0.5 rounded-full"
                      style={{ background: "#FEE2E2", color: "#7F1D1D" }}
                      data-testid={`jor-status-${r.id}`}
                    >
                      Inactive
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => setEditing(r)}
                    disabled={busyId === r.id}
                    className="p-1 mr-1"
                    style={{ color: colors.brand }}
                    data-testid={`jor-edit-${r.id}`}
                    title="Rename"
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    onClick={() => toggleActive(r)}
                    disabled={busyId === r.id}
                    className="p-1 mr-1"
                    style={{ color: r.active ? "#B45309" : "#0891B2" }}
                    data-testid={`jor-toggle-${r.id}`}
                    title={r.active ? "Deactivate" : "Reactivate"}
                  >
                    {r.active ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                  <button
                    onClick={() => hardDelete(r)}
                    disabled={busyId === r.id || r.is_default}
                    className="p-1"
                    style={{
                      color: colors.error,
                      opacity: r.is_default ? 0.3 : 1,
                    }}
                    data-testid={`jor-delete-${r.id}`}
                    title={
                      r.is_default
                        ? "Seeded defaults cannot be deleted — deactivate instead"
                        : "Delete permanently"
                    }
                  >
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing ? (
        <ReasonForm
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      ) : null}
    </div>
  );
}
