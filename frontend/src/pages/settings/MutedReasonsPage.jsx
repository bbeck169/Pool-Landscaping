/**
 * Feb-2026 · P29b — Muted Reasons manager (super_admin / admin / manager).
 *
 * Drives ``backend/routers/muted_reasons.py``:
 *   GET    /api/settings/muted-reasons?include_inactive=true
 *   POST   /api/settings/muted-reasons          {label, sort_order?}
 *   PATCH  /api/settings/muted-reasons/{id}     {label?, sort_order?, is_active?}
 *   DELETE /api/settings/muted-reasons/{id}     (soft-deactivate)
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";


export default function MutedReasonsPage() {
  const [rows, setRows] = useState([]);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState({});   // id → new label

  const load = useCallback(async () => {
    setErr("");
    try {
      const q = includeInactive ? "?include_inactive=true" : "";
      const res = await api.get(`/settings/muted-reasons${q}`);
      setRows(Array.isArray(res?.items) ? res.items : []);
    } catch (e) {
      setErr(e?.message || "Failed to load muted reasons");
    }
  }, [includeInactive]);

  useEffect(() => { load(); }, [load]);

  const submitNew = useCallback(async () => {
    const label = newLabel.trim();
    if (!label) { setErr("Label is required."); return; }
    setBusy(true); setErr("");
    try {
      await api.post("/settings/muted-reasons", { label });
      setNewLabel("");
      await load();
    } catch (e) {
      const msg = e?.body?.detail?.message || e?.body?.detail
        || e?.message || "Failed to add reason";
      setErr(typeof msg === "string" ? msg : "Failed to add reason");
    } finally { setBusy(false); }
  }, [newLabel, load]);

  const rename = useCallback(async (id) => {
    const label = (renaming[id] || "").trim();
    if (!label) return;
    setBusy(true); setErr("");
    try {
      await api.patch(`/settings/muted-reasons/${id}`, { label });
      setRenaming((s) => { const n = { ...s }; delete n[id]; return n; });
      await load();
    } catch (e) {
      setErr(e?.message || "Failed to rename reason");
    } finally { setBusy(false); }
  }, [renaming, load]);

  const reorder = useCallback(async (id, delta) => {
    const idx = rows.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const neighbour = rows[idx + delta];
    if (!neighbour) return;
    setBusy(true);
    try {
      await api.patch(`/settings/muted-reasons/${id}`,
        { sort_order: neighbour.sort_order });
      await api.patch(`/settings/muted-reasons/${neighbour.id}`,
        { sort_order: rows[idx].sort_order });
      await load();
    } finally { setBusy(false); }
  }, [rows, load]);

  const archive = useCallback(async (id) => {
    setBusy(true); setErr("");
    try {
      await api.delete(`/settings/muted-reasons/${id}`);
      await load();
    } finally { setBusy(false); }
  }, [load]);

  const restore = useCallback(async (id) => {
    setBusy(true); setErr("");
    try {
      await api.patch(`/settings/muted-reasons/${id}`, { is_active: true });
      await load();
    } finally { setBusy(false); }
  }, [load]);

  return (
    <div className="max-w-3xl mx-auto p-6" data-testid="muted-reasons-page">
      <h1 className="text-2xl font-bold mb-1" style={{ color: "#0F172A" }}>
        Muted reasons
      </h1>
      <p className="text-sm mb-6" style={{ color: "#64748B" }}>
        Reasons available to admins when muting a customer.  Historical
        muted reasons on customer records are immutable — renaming or
        archiving a reason here does not rewrite past mutes.
      </p>

      {/* Add-new row */}
      <div className="flex items-center gap-2 mb-4">
        <input
          type="text"
          maxLength={120}
          placeholder="Add a new reason…"
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          disabled={busy}
          data-testid="muted-reasons-add-input"
          className="flex-1 text-sm px-3 py-2 rounded border"
          style={{ borderColor: "#E5E7EB" }}
        />
        <button
          type="button"
          onClick={submitNew}
          disabled={busy || !newLabel.trim()}
          data-testid="muted-reasons-add-submit"
          className="px-3 py-2 text-sm font-semibold rounded"
          style={{ background: "#0EA5E9", color: "#fff",
                     opacity: busy || !newLabel.trim() ? 0.6 : 1 }}
        >
          Add
        </button>
      </div>

      {err ? (
        <div
          className="text-sm mb-3 p-2 rounded"
          style={{ background: "rgba(220,38,38,0.06)", color: "#7F1D1D" }}
          data-testid="muted-reasons-error"
        >
          {err}
        </div>
      ) : null}

      {/* include-inactive toggle */}
      <label className="text-xs mb-3 flex items-center gap-2 cursor-pointer"
                style={{ color: "#334155" }}>
        <input
          type="checkbox"
          checked={includeInactive}
          onChange={(e) => setIncludeInactive(e.target.checked)}
          data-testid="muted-reasons-include-inactive"
        />
        Show archived
      </label>

      <ul className="divide-y" style={{ borderColor: "#E5E7EB" }}
           data-testid="muted-reasons-list">
        {rows.map((r, idx) => {
          const isRenaming = r.id in renaming;
          const inactive = r.is_active === false;
          return (
            <li
              key={r.id}
              className="py-3 flex items-center gap-3"
              data-testid={`muted-reasons-row-${r.id}`}
              style={{ opacity: inactive ? 0.55 : 1 }}
            >
              {isRenaming ? (
                <>
                  <input
                    type="text"
                    value={renaming[r.id]}
                    onChange={(e) => setRenaming((s) =>
                      ({ ...s, [r.id]: e.target.value }))}
                    maxLength={120}
                    className="flex-1 text-sm px-2 py-1 rounded border"
                    style={{ borderColor: "#E5E7EB" }}
                    data-testid={`muted-reasons-rename-input-${r.id}`}
                  />
                  <button type="button" onClick={() => rename(r.id)}
                     data-testid={`muted-reasons-rename-save-${r.id}`}
                     className="text-xs px-2 py-1 rounded"
                     style={{ background: "#0EA5E9", color: "#fff" }}>
                    Save
                  </button>
                </>
              ) : (
                <>
                  <span className="flex-1 text-sm" style={{ color: "#0F172A" }}>
                    {r.label}
                    {inactive ? (
                      <span
                        className="ml-2 text-[10px] font-semibold px-1.5 py-0.5 rounded"
                        style={{ background: "#E5E7EB", color: "#475569" }}
                        data-testid={`muted-reasons-archived-badge-${r.id}`}
                      >
                        Archived
                      </span>
                    ) : null}
                  </span>
                  {!inactive ? (
                    <>
                      <button type="button"
                        onClick={() => reorder(r.id, -1)}
                        disabled={idx === 0}
                        data-testid={`muted-reasons-up-${r.id}`}
                        className="text-xs px-2 py-1 rounded border"
                        style={{ borderColor: "#E5E7EB", opacity: idx === 0 ? 0.4 : 1 }}>
                        ↑
                      </button>
                      <button type="button"
                        onClick={() => reorder(r.id, 1)}
                        disabled={idx === rows.length - 1}
                        data-testid={`muted-reasons-down-${r.id}`}
                        className="text-xs px-2 py-1 rounded border"
                        style={{ borderColor: "#E5E7EB",
                                   opacity: idx === rows.length - 1 ? 0.4 : 1 }}>
                        ↓
                      </button>
                      <button type="button"
                        onClick={() => setRenaming((s) =>
                          ({ ...s, [r.id]: r.label }))}
                        data-testid={`muted-reasons-rename-${r.id}`}
                        className="text-xs px-2 py-1 rounded border"
                        style={{ borderColor: "#E5E7EB" }}>
                        Rename
                      </button>
                      <button type="button"
                        onClick={() => archive(r.id)}
                        data-testid={`muted-reasons-archive-${r.id}`}
                        className="text-xs px-2 py-1 rounded border"
                        style={{ borderColor: "#FCA5A5", color: "#7F1D1D" }}>
                        Archive
                      </button>
                    </>
                  ) : (
                    <button type="button"
                      onClick={() => restore(r.id)}
                      data-testid={`muted-reasons-restore-${r.id}`}
                      className="text-xs px-2 py-1 rounded border"
                      style={{ borderColor: "#0EA5E9", color: "#0EA5E9" }}>
                      Restore
                    </button>
                  )}
                </>
              )}
            </li>
          );
        })}
        {rows.length === 0 ? (
          <li className="py-6 text-sm text-center"
              style={{ color: "#94A3B8" }}
              data-testid="muted-reasons-empty">
            No reasons yet.  Add one above.
          </li>
        ) : null}
      </ul>
    </div>
  );
}
