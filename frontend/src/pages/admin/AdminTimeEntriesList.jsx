/**
 * Task OO · Feb 2026 — Admin Time Entries list.
 * Exposes /time-entries/bulk-delete + /time-entries/bulk-update.
 * Locked-state: entries on paid payroll runs refuse hard delete.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Clock, RefreshCw, Pencil } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import {
  useBulkSelect, BulkSelectAll, BulkSelectRow,
  BulkActionBar, BulkConfirmModal, LockedPill,
} from "@/components/bulk-select/BulkSelectToolkit";
import {
  TimecardEditModal, AuditHistoryPopover, canEditTimecards,
} from "./TimecardEditModal";

export default function AdminTimeEntriesList() {
  const { user } = useAuth() || {};
  const canEdit = canEditTimecards(user);
  const [rows, setRows] = useState(null);
  const [approvedFilter, setApprovedFilter] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});
  const [editingRow, setEditingRow] = useState(null);
  const handleRowUpdated = (updated) => {
    if (!updated || !updated.id) return;
    setRows((prev) => (prev || []).map((r) => (r.id === updated.id ? updated : r)));
  };
  const load = () => {
    const qs = approvedFilter === "yes" ? "?is_approved=true"
      : approvedFilter === "no" ? "?is_approved=false" : "";
    api.get(`/time-entries${qs}`)
      .then((r) => setRows(Array.isArray(r) ? r : (r?.entries || [])))
      .catch(() => setRows([]));
  };
  useEffect(load, [approvedFilter]);
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
      const res = await api.post("/time-entries/bulk-delete", { ids: Array.from(selected) });
      applyFailures(res.failed);
      const okC = res.deleted_count || 0;
      const failC = (res.failed || []).length;
      if (failC === 0) toast.success(`${okC} time entry${okC === 1 ? "" : " entries"} deleted`);
      else toast(`${okC} deleted · ${failC} locked`, {
        description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
      });
      clear(); setConfirmOpen(false); load();
    } catch (e) { toast.error(e?.message || "Bulk delete failed"); }
    finally { setBusy(false); }
  };
  const doBulkApprove = async (state) => {
    try {
      const res = await api.post("/time-entries/bulk-update", {
        ids: Array.from(selected),
        patch: { is_approved: state === "approved" },
      });
      applyFailures(res.failed);
      toast.success(`${res.updated_count || 0} → ${state}`);
      clear(); load();
    } catch (e) { toast.error(e?.message || "Approval update failed"); }
  };
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-time-entries-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <Clock size={20} className="inline mr-2" /> Time Entries
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Bulk-approve or bulk-delete time entries. Entries on paid payroll runs stay locked.
          </p>
        </div>
        <button onClick={load}
                className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="admin-time-entries-refresh-btn">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      <div className="rounded-2xl p-3 mb-3 flex items-center gap-2"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <label className="text-xs font-semibold" style={{ color: colors.muted }}>Approved</label>
        <select value={approvedFilter} onChange={(e) => setApprovedFilter(e.target.value)}
                className="text-xs font-semibold px-3 py-2 rounded-lg"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="admin-time-entries-filter-approved">
          <option value="">All</option>
          <option value="yes">Approved</option>
          <option value="no">Pending</option>
        </select>
      </div>
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm" data-testid="admin-time-entries-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="px-3 py-2 w-8">
                <BulkSelectAll checked={allVisibleSelected} indeterminate={indeterminate}
                                 onChange={toggleAll} />
              </th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Tech</th>
              <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Job</th>
              <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Date</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Hours</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Approved</th>
              {canEdit ? (
                <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                  Actions
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {(rows || []).length === 0 && rows !== null ? (
              <tr><td colSpan={canEdit ? 7 : 6} className="px-3 py-6 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="admin-time-entries-empty">
                No time entries match this filter.
              </td></tr>
            ) : null}
            {(rows || []).map((r) => (
              <tr key={r.id}
                  style={{ borderTop: `1px solid ${colors.divider}`,
                            backgroundColor: selected.has(r.id) ? "#EFF6FF" : "transparent" }}
                  data-testid={`admin-time-entry-row-${r.id}`}>
                <td className="px-3 py-3">
                  <BulkSelectRow id={r.id} checked={selected.has(r.id)}
                                    onChange={() => toggleOne(r.id)} />
                </td>
                <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}>
                  {r.user_name || r.tech_name || `User ${(r.user_id || "").slice(0, 8)}`}
                  {r.payroll_paid_at ? (
                    <span className="ml-2 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                          style={{ background: "#FEF3C7", color: "#78350F" }}>paid payroll</span>
                  ) : null}
                  {lockedFailures[r.id] ? (
                    <LockedPill reason={lockedFailures[r.id]}
                                  testid={`bulk-locked-pill-${r.id}`} />
                  ) : null}
                  {(r.edits || []).length > 0 ? (
                    <AuditHistoryPopover
                      edits={r.edits}
                      testid={`timecard-audit-badge-${r.id}`}
                    />
                  ) : null}
                </td>
                <td className="px-3 py-3 hidden md:table-cell text-xs" style={{ color: colors.muted }}>{r.assigned_job_id || "—"}</td>
                <td className="px-3 py-3 hidden md:table-cell text-xs" style={{ color: colors.muted }}>{(r.date || r.created_at || "").slice(0, 10)}</td>
                <td className="px-3 py-3 text-xs" style={{ color: colors.onSurface }}>{r.hours || 0}</td>
                <td className="px-3 py-3 text-xs" style={{ color: colors.muted }}>{r.is_approved ? "Yes" : "No"}</td>
                {canEdit ? (
                  <td className="px-3 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => setEditingRow(r)}
                      className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-lg border hover:bg-slate-50"
                      style={{ borderColor: colors.border, color: colors.onSurface }}
                      data-testid={`timecard-edit-btn-${r.id}`}
                    >
                      <Pencil size={11} /> Edit
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <BulkActionBar
        selectedCount={selectedCount}
        onClear={clear}
        actions={[
          { key: "approve", label: "Set approval",
            dropdown: [{ value: "approved", label: "Approved" }, { value: "pending", label: "Pending" }],
            onClick: (v) => doBulkApprove(v) },
          { key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setConfirmOpen(true) },
        ]}
      />
      <BulkConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={doBulkDelete}
        title={`Delete ${selectedCount} time entry${selectedCount === 1 ? "" : " entries"}?`}
        description="Entries already on a paid payroll run will show as locked and be skipped — archive them instead."
        confirmLabel={busy ? "Deleting…" : `Delete ${selectedCount}`}
        busy={busy}
      />
      {canEdit && editingRow ? (
        <TimecardEditModal
          key={editingRow.id}
          row={editingRow}
          open={!!editingRow}
          onClose={() => setEditingRow(null)}
          onUpdated={handleRowUpdated}
        />
      ) : null}
    </div>
  );
}
