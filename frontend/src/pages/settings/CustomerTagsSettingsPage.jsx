/**
 * Feb-2026 · P36 — Customer Tags Settings Manager.
 *
 * Mirrors ``MutedReasonsPage.jsx`` (P29b UX pattern) with an added
 * merge-duplicates modal. Drives ``backend/routers/customer_tags.py``:
 *
 *   GET   /api/customer-tags?include_inactive=true
 *   POST  /api/customer-tags                       {name, color?}
 *   PATCH /api/customer-tags/{id}                  {name?, is_active?, sort_order?}
 *   DELETE /api/customer-tags/{id}                 (soft-archive)
 *   POST  /api/customer-tags/{id}/restore
 *   POST  /api/customer-tags/merge                 {canonical_id, victim_ids[]}
 *
 * RBAC is enforced at the App.js route wrapper — this page assumes
 * the user is admin / manager / super_admin.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";


export default function CustomerTagsSettingsPage() {
  const [rows, setRows] = useState([]);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState({});  // id → new label
  const [mergeState, setMergeState] = useState(null);
  // ^ null | { canonicalId, victimIds: Set<string> }

  const load = useCallback(async () => {
    setErr("");
    try {
      const q = includeInactive ? "?include_inactive=true" : "";
      const res = await api.get(`/customer-tags${q}`);
      setRows(Array.isArray(res?.items) ? res.items : []);
    } catch (e) {
      setErr(e?.message || "Failed to load tags");
    }
  }, [includeInactive]);

  useEffect(() => { load(); }, [load]);

  const submitNew = useCallback(async () => {
    const label = newLabel.trim();
    if (!label) { setErr("Tag name is required."); return; }
    setBusy(true); setErr(""); setOk("");
    try {
      await api.post("/customer-tags", { name: label });
      setNewLabel("");
      setOk(`Added "${label}"`);
      await load();
    } catch (e) {
      const msg = e?.body?.detail?.message || e?.body?.detail
                     || e?.message || "Add failed";
      setErr(typeof msg === "string" ? msg : "Add failed");
    } finally {
      setBusy(false);
    }
  }, [newLabel, load]);

  const startRename = (id, current) =>
    setRenaming((r) => ({ ...r, [id]: current }));
  const cancelRename = (id) =>
    setRenaming((r) => { const c = { ...r }; delete c[id]; return c; });
  const commitRename = useCallback(async (id) => {
    const next = (renaming[id] || "").trim();
    if (!next) { setErr("Tag name is required."); return; }
    setBusy(true); setErr(""); setOk("");
    try {
      await api.patch(`/customer-tags/${id}`, { name: next });
      cancelRename(id);
      setOk("Saved");
      await load();
    } catch (e) {
      const msg = e?.body?.detail?.message || e?.body?.detail
                     || e?.message || "Rename failed";
      setErr(typeof msg === "string" ? msg : "Rename failed");
    } finally {
      setBusy(false);
    }
  }, [renaming, load]);

  const archive = useCallback(async (id) => {
    setBusy(true); setErr(""); setOk("");
    try {
      await api.delete(`/customer-tags/${id}`);
      setOk("Archived");
      await load();
    } catch (e) {
      setErr(e?.message || "Archive failed");
    } finally {
      setBusy(false);
    }
  }, [load]);

  const restore = useCallback(async (id) => {
    setBusy(true); setErr(""); setOk("");
    try {
      await api.post(`/customer-tags/${id}/restore`, {});
      setOk("Restored");
      await load();
    } catch (e) {
      setErr(e?.message || "Restore failed");
    } finally {
      setBusy(false);
    }
  }, [load]);

  // ── Merge flow ─────────────────────────────────────────────────
  const openMerge = (canonicalId) => setMergeState({
    canonicalId, victimIds: new Set(),
  });
  const closeMerge = () => setMergeState(null);
  const toggleVictim = (id) => setMergeState((s) => {
    if (!s) return s;
    const next = new Set(s.victimIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    return { ...s, victimIds: next };
  });
  const submitMerge = useCallback(async () => {
    if (!mergeState) return;
    const victim_ids = Array.from(mergeState.victimIds);
    if (victim_ids.length === 0) {
      setErr("Select at least one victim tag."); return;
    }
    setBusy(true); setErr(""); setOk("");
    try {
      const res = await api.post("/customer-tags/merge", {
        canonical_id: mergeState.canonicalId,
        victim_ids,
      });
      setOk(`Merged ${res?.merged_victims || victim_ids.length} tag(s). `
              + `${res?.customers_updated || 0} customer(s) updated.`);
      closeMerge();
      await load();
    } catch (e) {
      const msg = e?.body?.detail?.message || e?.body?.detail
                     || e?.message || "Merge failed";
      setErr(typeof msg === "string" ? msg : "Merge failed");
    } finally {
      setBusy(false);
    }
  }, [mergeState, load]);

  const activeRows = useMemo(
    () => rows.filter((r) => r.is_active !== false),
    [rows],
  );

  return (
    <div className="max-w-3xl mx-auto p-6" data-testid="customer-tags-page">
      <h1 className="text-2xl font-bold mb-1" style={{ color: "#0F172A" }}>
        Customer Tags
      </h1>
      <p className="text-sm mb-6" style={{ color: "#64748B" }}>
        Curate the tenant-scoped tag catalog. Archived tags stay on any
        customer that already carries them (snapshots are immutable) —
        use <b>Merge</b> to consolidate typos and near-duplicates.
      </p>

      {/* Add-new inline input */}
      <div className="flex items-center gap-2 mb-4">
        <input
          type="text"
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          placeholder="Add a new tag…"
          data-testid="customer-tags-add-input"
          className="flex-1 text-sm px-3 py-2 rounded border"
          style={{ borderColor: "#E5E7EB" }}
        />
        <button
          type="button"
          onClick={submitNew}
          disabled={busy}
          data-testid="customer-tags-add-submit"
          className="px-3 py-2 text-sm font-semibold rounded"
          style={{ background: "#0EA5E9", color: "#fff",
                     opacity: busy ? 0.6 : 1 }}
        >Add</button>
      </div>

      {/* Show archived toggle */}
      <label className="flex items-center gap-2 mb-4 cursor-pointer">
        <input
          type="checkbox"
          checked={includeInactive}
          onChange={(e) => setIncludeInactive(e.target.checked)}
          data-testid="customer-tags-include-inactive"
        />
        <span className="text-sm" style={{ color: "#64748B" }}>
          Show archived
        </span>
      </label>

      {err ? (
        <div className="text-sm mb-3 p-2 rounded"
              style={{ background: "rgba(220,38,38,0.06)", color: "#7F1D1D" }}
              data-testid="customer-tags-error">
          {err}
        </div>
      ) : null}
      {ok ? (
        <div className="text-sm mb-3 p-2 rounded"
              style={{ background: "rgba(16,185,129,0.06)", color: "#065F46" }}
              data-testid="customer-tags-ok">
          {ok}
        </div>
      ) : null}

      {/* Rows */}
      <ul className="space-y-2">
        {rows.map((row) => {
          const isArchived = row.is_active === false;
          const isSystem = !!row.is_system;
          const isRenaming = Object.prototype.hasOwnProperty
                                  .call(renaming, row.id);
          return (
            <li
              key={row.id}
              data-testid={`customer-tags-row-${row.id}`}
              className="flex items-center gap-2 border rounded p-2"
              style={{
                borderColor: "#E5E7EB",
                opacity: isArchived ? 0.55 : 1,
              }}
            >
              {isRenaming ? (
                <>
                  <input
                    type="text"
                    value={renaming[row.id]}
                    onChange={(e) => setRenaming((r) => ({
                      ...r, [row.id]: e.target.value,
                    }))}
                    data-testid={`customer-tags-rename-input-${row.id}`}
                    className="flex-1 text-sm px-2 py-1 rounded border"
                    style={{ borderColor: "#E5E7EB" }}
                  />
                  <button
                    type="button"
                    onClick={() => commitRename(row.id)}
                    disabled={busy}
                    data-testid={`customer-tags-rename-save-${row.id}`}
                    className="px-2 py-1 text-xs font-semibold rounded"
                    style={{ background: "#0EA5E9", color: "#fff" }}
                  >Save</button>
                  <button
                    type="button"
                    onClick={() => cancelRename(row.id)}
                    className="px-2 py-1 text-xs rounded border"
                    style={{ borderColor: "#E5E7EB" }}
                  >Cancel</button>
                </>
              ) : (
                <>
                  <span className="flex-1 text-sm font-medium"
                          style={{ color: "#0F172A" }}>
                    {row.name}
                    {isSystem ? (
                      <span
                        className="ml-2 text-xs px-1.5 py-0.5 rounded"
                        style={{ background: "#F1F5F9", color: "#475569" }}>
                        SYSTEM
                      </span>
                    ) : null}
                    {isArchived ? (
                      <span
                        className="ml-2 text-xs px-1.5 py-0.5 rounded"
                        style={{ background: "#FEF2F2", color: "#7F1D1D" }}
                        data-testid={`customer-tags-archived-badge-${row.id}`}>
                        Archived
                      </span>
                    ) : null}
                    <span className="ml-2 text-xs"
                            style={{ color: "#94A3B8" }}>
                      {row.usage_count ?? 0} uses
                    </span>
                  </span>
                  {!isArchived && !isSystem ? (
                    <button
                      type="button"
                      onClick={() => startRename(row.id, row.name)}
                      disabled={busy}
                      data-testid={`customer-tags-rename-${row.id}`}
                      className="px-2 py-1 text-xs rounded border"
                      style={{ borderColor: "#E5E7EB" }}
                    >Rename</button>
                  ) : null}
                  {!isArchived && !isSystem ? (
                    <button
                      type="button"
                      onClick={() => openMerge(row.id)}
                      disabled={busy}
                      data-testid={`customer-tags-merge-${row.id}`}
                      className="px-2 py-1 text-xs rounded border"
                      style={{ borderColor: "#E5E7EB" }}
                    >Merge…</button>
                  ) : null}
                  {!isArchived && !isSystem ? (
                    <button
                      type="button"
                      onClick={() => archive(row.id)}
                      disabled={busy}
                      data-testid={`customer-tags-archive-${row.id}`}
                      className="px-2 py-1 text-xs rounded"
                      style={{ background: "#FEF2F2", color: "#7F1D1D" }}
                    >Archive</button>
                  ) : null}
                  {isArchived ? (
                    <button
                      type="button"
                      onClick={() => restore(row.id)}
                      disabled={busy}
                      data-testid={`customer-tags-restore-${row.id}`}
                      className="px-2 py-1 text-xs rounded"
                      style={{ background: "#F0FDF4", color: "#166534" }}
                    >Restore</button>
                  ) : null}
                </>
              )}
            </li>
          );
        })}
      </ul>

      {/* Merge modal */}
      {mergeState ? (
        <div
          data-testid="customer-tags-merge-modal"
          className="fixed inset-0 flex items-center justify-center"
          style={{ background: "rgba(15, 23, 42, 0.55)", zIndex: 40 }}
        >
          <div className="bg-white rounded-lg p-6 max-w-md w-full">
            <h2 className="text-lg font-bold mb-2" style={{ color: "#0F172A" }}>
              Merge tags
            </h2>
            <p className="text-sm mb-3" style={{ color: "#64748B" }}>
              Select the victim tag(s) to merge into&nbsp;
              <b>
                {(rows.find((r) => r.id === mergeState.canonicalId) || {}).name}
              </b>
              . Victims will be archived; every customer that carries a
              victim tag will have it rewritten to the canonical.
            </p>
            <ul className="mb-4 max-h-64 overflow-y-auto">
              {activeRows
                .filter((r) => r.id !== mergeState.canonicalId && !r.is_system)
                .map((r) => (
                  <li key={r.id} className="flex items-center gap-2 py-1">
                    <input
                      type="checkbox"
                      checked={mergeState.victimIds.has(r.id)}
                      onChange={() => toggleVictim(r.id)}
                      data-testid={`customer-tags-merge-victim-${r.id}`}
                    />
                    <span className="text-sm" style={{ color: "#0F172A" }}>
                      {r.name}
                    </span>
                  </li>
                ))}
            </ul>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeMerge}
                data-testid="customer-tags-merge-cancel"
                className="px-3 py-2 text-sm rounded border"
                style={{ borderColor: "#E5E7EB" }}
              >Cancel</button>
              <button
                type="button"
                onClick={submitMerge}
                disabled={busy}
                data-testid="customer-tags-merge-submit"
                className="px-3 py-2 text-sm font-semibold rounded"
                style={{ background: "#0EA5E9", color: "#fff",
                           opacity: busy ? 0.6 : 1 }}
              >Merge</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
