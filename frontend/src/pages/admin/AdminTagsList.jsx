/**
 * Task OO · Feb 2026 — Admin Customer Tags list (bulk-select surface).
 * Exposes /customer-tags/bulk-delete + /customer-tags/bulk-update.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Tag as TagIcon, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  useBulkSelect, BulkSelectAll, BulkSelectRow,
  BulkActionBar, BulkConfirmModal, LockedPill,
} from "@/components/bulk-select/BulkSelectToolkit";

export default function AdminTagsList() {
  const [rows, setRows] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});
  const load = () => api.get("/customer-tags")
    .then((r) => setRows(Array.isArray(r) ? r : (r?.tags || [])))
    .catch(() => setRows([]));
  useEffect(load, []);
  const visibleIds = useMemo(() => (rows || []).map((r) => r.id), [rows]);
  const { selected, selectedCount, allVisibleSelected, indeterminate,
             toggleAll, toggleOne, clear } = useBulkSelect(visibleIds);
  const applyFailures = (failed) => {
    if (!failed?.length) return;
    const map = {}; failed.forEach((f) => { map[f.id] = f.reason; });
    setLockedFailures(map); setTimeout(() => setLockedFailures({}), 10000);
  };
  const doBulkDelete = async () => {
    setBusy(true);
    try {
      const res = await api.post("/customer-tags/bulk-delete", { ids: Array.from(selected) });
      applyFailures(res.failed);
      toast.success(`${res.deleted_count || 0} tag${(res.deleted_count || 0) === 1 ? "" : "s"} deleted`);
      clear(); setConfirmOpen(false); load();
    } catch (e) { toast.error(e?.message || "Bulk delete failed"); }
    finally { setBusy(false); }
  };
  const doBulkArchive = async (state) => {
    try {
      const res = await api.post("/customer-tags/bulk-update", {
        ids: Array.from(selected),
        patch: { is_archived: state === "archived" },
      });
      applyFailures(res.failed);
      toast.success(`${res.updated_count || 0} → ${state}`);
      clear(); load();
    } catch (e) { toast.error(e?.message || "Archive update failed"); }
  };
  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-tags-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <TagIcon size={20} className="inline mr-2" /> Customer Tags
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Bulk-manage customer tags. Assignment lives on the customer detail page.
          </p>
        </div>
        <button onClick={load}
                className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="admin-tags-refresh-btn">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm" data-testid="admin-tags-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="px-3 py-2 w-8">
                <BulkSelectAll checked={allVisibleSelected} indeterminate={indeterminate}
                                 onChange={toggleAll} />
              </th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Name</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Color</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Archived</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).length === 0 && rows !== null ? (
              <tr><td colSpan={4} className="px-3 py-6 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="admin-tags-empty">
                No tags yet.
              </td></tr>
            ) : null}
            {(rows || []).map((r) => (
              <tr key={r.id}
                  style={{ borderTop: `1px solid ${colors.divider}`,
                            backgroundColor: selected.has(r.id) ? "#EFF6FF" : "transparent" }}
                  data-testid={`admin-tag-row-${r.id}`}>
                <td className="px-3 py-3">
                  <BulkSelectRow id={r.id} checked={selected.has(r.id)}
                                    onChange={() => toggleOne(r.id)} />
                </td>
                <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}>
                  {r.name || r.label || "—"}
                  {lockedFailures[r.id] ? (
                    <LockedPill reason={lockedFailures[r.id]}
                                  testid={`bulk-locked-pill-${r.id}`} />
                  ) : null}
                </td>
                <td className="px-3 py-3">
                  <span className="inline-block w-6 h-6 rounded-full"
                        style={{ backgroundColor: r.color || "#94A3B8",
                                  border: `1px solid ${colors.border}` }} />
                </td>
                <td className="px-3 py-3 text-xs" style={{ color: colors.muted }}>
                  {r.is_archived ? "Archived" : "Active"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <BulkActionBar
        selectedCount={selectedCount}
        onClear={clear}
        actions={[
          { key: "archive", label: "Set archive state",
            dropdown: [{ value: "archived", label: "Archived" }, { value: "active", label: "Active" }],
            onClick: (v) => doBulkArchive(v) },
          { key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setConfirmOpen(true) },
        ]}
      />
      <BulkConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={doBulkDelete}
        title={`Delete ${selectedCount} tag${selectedCount === 1 ? "" : "s"}?`}
        description="Tags assigned to customers will be unassigned. This action cannot be undone."
        confirmLabel={busy ? "Deleting…" : `Delete ${selectedCount}`}
        busy={busy}
      />
    </div>
  );
}
