/**
 * Task OO · Feb 2026 — Admin Users / Team list (bulk-select surface).
 *
 * The primary team view is `TeamRoster` inside `OpsHub.jsx`; this admin
 * table exists to expose `/users/bulk-delete` + `/users/bulk-update`
 * via the shared toolkit. Individual editing lives on the team detail
 * pages.
 */
import React, { useEffect, useMemo, useState } from "react";
import { UserCog, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  useBulkSelect,
  BulkSelectAll,
  BulkSelectRow,
  BulkActionBar,
  BulkConfirmModal,
  LockedPill,
} from "@/components/bulk-select/BulkSelectToolkit";

const ROLE_OPTIONS = [
  { value: "tech", label: "Technician" },
  { value: "admin", label: "Admin" },
  { value: "office", label: "Office" },
  { value: "owner", label: "Owner" },
];

export default function AdminUsersList() {
  const [rows, setRows] = useState(null);
  const [role, setRole] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});

  const load = () => api.get("/team")
    .then((r) => setRows(Array.isArray(r) ? r : (r?.members || r?.items || [])))
    .catch(() => setRows([]));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    if (!rows) return [];
    return role ? rows.filter((r) => (r.role || "").toLowerCase() === role) : rows;
  }, [rows, role]);
  const visibleIds = useMemo(() => filtered.map((r) => r.id), [filtered]);
  const { selected, selectedCount, allVisibleSelected, indeterminate,
             toggleAll, toggleOne, clear } = useBulkSelect(visibleIds);

  const applyFailures = (failed) => {
    if (!failed?.length) return;
    const map = {};
    failed.forEach((f) => { map[f.id] = f.reason; });
    setLockedFailures(map);
    setTimeout(() => setLockedFailures({}), 10000);
  };

  const doBulkDelete = async () => {
    setBusy(true);
    try {
      const res = await api.post("/users/bulk-delete", { ids: Array.from(selected) });
      applyFailures(res.failed);
      const okC = res.deleted_count || 0;
      const failC = (res.failed || []).length;
      if (failC === 0) toast.success(`${okC} user${okC === 1 ? "" : "s"} deleted`);
      else toast(`${okC} deleted · ${failC} locked`, {
        description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
      });
      clear(); setConfirmOpen(false); load();
    } catch (e) { toast.error(e?.message || "Bulk delete failed"); }
    finally { setBusy(false); }
  };

  const doBulkRole = async (nextRole) => {
    try {
      const res = await api.post("/users/bulk-update", {
        ids: Array.from(selected), patch: { role: nextRole },
      });
      applyFailures(res.failed);
      toast.success(`${res.updated_count || 0} → ${nextRole}`);
      clear(); load();
    } catch (e) { toast.error(e?.message || "Role update failed"); }
  };

  const doBulkActive = async (activeState) => {
    try {
      const res = await api.post("/users/bulk-update", {
        ids: Array.from(selected),
        patch: { is_active: activeState === "active" },
      });
      applyFailures(res.failed);
      toast.success(`${res.updated_count || 0} → ${activeState}`);
      clear(); load();
    } catch (e) { toast.error(e?.message || "Activation update failed"); }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-users-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <UserCog size={20} className="inline mr-2" />
            Team (admin)
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Bulk-manage staff members. Individual editing lives on /team.
          </p>
        </div>
        <button onClick={load}
                className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="admin-users-refresh-btn">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      <div className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <label className="text-xs font-semibold" style={{ color: colors.muted }}>Role</label>
        <select value={role} onChange={(e) => setRole(e.target.value)}
                className="text-xs font-semibold px-3 py-2 rounded-lg"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="admin-users-filter-role">
          <option value="">All</option>
          {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm" data-testid="admin-users-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="px-3 py-2 w-8">
                <BulkSelectAll checked={allVisibleSelected}
                                 indeterminate={indeterminate}
                                 onChange={toggleAll} />
              </th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Name</th>
              <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Email</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Role</th>
              <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>Active</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && rows !== null ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="admin-users-empty">
                No users match this filter.
              </td></tr>
            ) : null}
            {filtered.map((r) => (
              <tr key={r.id}
                  style={{ borderTop: `1px solid ${colors.divider}`,
                            backgroundColor: selected.has(r.id) ? "#EFF6FF" : "transparent" }}
                  data-testid={`admin-user-row-${r.id}`}>
                <td className="px-3 py-3">
                  <BulkSelectRow id={r.id} checked={selected.has(r.id)}
                                    onChange={() => toggleOne(r.id)} />
                </td>
                <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}>
                  {r.name || r.full_name || r.email || "—"}
                  {lockedFailures[r.id] ? (
                    <LockedPill reason={lockedFailures[r.id]}
                                  testid={`bulk-locked-pill-${r.id}`} />
                  ) : null}
                </td>
                <td className="px-3 py-3 hidden md:table-cell text-xs" style={{ color: colors.muted }}>{r.email || "—"}</td>
                <td className="px-3 py-3 text-xs">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full font-bold uppercase tracking-wider text-[10px]"
                        style={{ backgroundColor: colors.surfaceSecondary,
                                  color: colors.onSurfaceSecondary,
                                  border: `1px solid ${colors.border}` }}>
                    {r.role || "—"}
                  </span>
                </td>
                <td className="px-3 py-3 hidden lg:table-cell text-xs" style={{ color: colors.muted }}>
                  {r.is_active !== false ? "Active" : "Inactive"}
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
          { key: "role", label: "Change role", dropdown: ROLE_OPTIONS,
            onClick: (v) => doBulkRole(v) },
          { key: "active", label: "Set active state",
            dropdown: [{ value: "active", label: "Active" }, { value: "inactive", label: "Inactive" }],
            onClick: (v) => doBulkActive(v) },
          { key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setConfirmOpen(true) },
        ]}
      />
      <BulkConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={doBulkDelete}
        title={`Delete ${selectedCount} user${selectedCount === 1 ? "" : "s"}?`}
        description="Your own session, the last owner in this tenant, and admin-locked users will be skipped."
        confirmLabel={busy ? "Deleting…" : `Delete ${selectedCount}`}
        busy={busy}
      />
    </div>
  );
}
