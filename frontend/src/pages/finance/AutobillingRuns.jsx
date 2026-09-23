/**
 * Phase 56.17-followup — Autobilling Runs Audit UI.
 *
 * Admin-only surface at /admin/autobilling-runs. Consumes the
 * `GET /api/autobilling-runs?plan_id=&status=&since=` endpoint that
 * shipped in 56.17.
 *
 * Columns: plan name, schedule (human-readable), anchor date,
 * status (colored pill), message, timestamp. Filters: plan
 * dropdown, status multi-select, and a "since" date. Sortable by
 * every column. CSV export via client-side blob (same pattern as
 * the training leaderboard export in AdminTraining.jsx).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Download, Repeat, XCircle, Trash2, RotateCcw, AlertOctagon } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import { PageHeader } from "@/components/ui-kit";

const SCHEDULE_LABELS = {
  first_friday: "1st Friday of the month",
  second_friday: "2nd Friday of the month",
  third_friday: "3rd Friday of the month",
  fourth_friday: "4th Friday of the month",
  first_of_month: "1st of the month",
};

const STATUS_STYLES = {
  fired: { bg: "#DCFCE7", fg: "#166534", label: "Fired" },
  manual: { bg: "#DBEAFE", fg: "#1E40AF", label: "Manual" },
  skipped: { bg: "#F1F5F9", fg: "#475569", label: "Skipped" },
  error: { bg: "#FEE2E2", fg: "#991B1B", label: "Error" },
  late_missed: { bg: "#FEF3C7", fg: "#92400E", label: "Late missed" },
};

function fmtTs(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return String(iso); }
}

function StatusPill({ status }) {
  const s = STATUS_STYLES[status] || { bg: "#F1F5F9", fg: "#475569", label: status || "—" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
      style={{ backgroundColor: s.bg, color: s.fg }}
      data-testid={`autobilling-runs-status-${status}`}
    >
      {s.label}
    </span>
  );
}

export default function AutobillingRuns() {
  const { user } = useAuth();
  const canSoftDelete = ["admin", "super_admin", "owner"].includes(user?.role);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState(""); // "" = all
  const [since, setSince] = useState("");
  const [sort, setSort] = useState({ key: "ts", dir: "desc" });
  // Aug-2026 · Soft-delete surface — default hides deleted rows.
  const [showDeleted, setShowDeleted] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const qs = new URLSearchParams();
      if (planFilter) qs.set("plan_id", planFilter);
      if (statusFilter) qs.set("status", statusFilter);
      if (since) qs.set("since", since);
      if (showDeleted) qs.set("include_deleted", "true");
      const r = await api.get(`/autobilling-runs${qs.toString() ? `?${qs}` : ""}`);
      setRows(Array.isArray(r) ? r : []);
    } catch (e) {
      setError(e?.message || "Failed to load audit log.");
    } finally {
      setLoading(false);
    }
  }, [planFilter, statusFilter, since, showDeleted]);

  useEffect(() => { load(); }, [load]);

  const planOptions = useMemo(() => {
    const seen = new Map();
    for (const r of rows) {
      if (r.plan_id && !seen.has(r.plan_id)) {
        seen.set(r.plan_id, r.plan_name || r.plan_id);
      }
    }
    return Array.from(seen, ([id, label]) => ({ id, label }));
  }, [rows]);

  const sorted = useMemo(() => {
    const s = [...rows];
    s.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const an = av == null ? "" : String(av).toLowerCase();
      const bn = bv == null ? "" : String(bv).toLowerCase();
      if (an < bn) return sort.dir === "asc" ? -1 : 1;
      if (an > bn) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });
    return s;
  }, [rows, sort]);

  const bump = (key) => setSort((s) =>
    s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }
  );

  // Phase AB1 · Feb-2026 — bulk-select + bulk-cancel state.
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelResult, setCancelResult] = useState(null);

  const visibleIds = useMemo(() => sorted.map((r) => r.id), [sorted]);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const selectedCount = selectedIds.size;

  const toggleAllVisible = () => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
    else visibleIds.forEach((id) => next.add(id));
    return next;
  });
  const toggleOne = (id) => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const clearSelection = () => setSelectedIds(new Set());

  const doBulkCancel = async () => {
    setCancelBusy(true);
    try {
      const res = await api.post("/autobilling/runs/bulk-cancel", {
        ids: Array.from(selectedIds),
        reason: cancelReason || null,
      });
      setCancelResult(res);
      const cancelled = res.cancelled || 0;
      const skipped = res.skipped || 0;
      if (skipped === 0) {
        sonnerToast.success(`${cancelled} run${cancelled === 1 ? "" : "s"} cancelled`);
      } else {
        sonnerToast(`${cancelled} cancelled · ${skipped} skipped`, {
          description: (res.results || [])
            .filter((r) => r.status === "skipped")
            .slice(0, 3)
            .map((r) => r.reason || "skipped")
            .join(" · "),
        });
      }
      // Optimistic UI: flip cancelled rows locally so the pill turns
      // grey without a full refetch.
      const cancelledSet = new Set(
        (res.results || [])
          .filter((r) => r.status === "cancelled")
          .map((r) => r.id),
      );
      setRows((prev) => prev.map((r) => (
        cancelledSet.has(r.id) ? { ...r, status: "cancelled" } : r
      )));
      clearSelection();
      setConfirmCancelOpen(false);
      setCancelReason("");
      // Then background-refresh to catch anything else the backend
      // adjusted (e.g. an audit-driven message field).
      load();
    } catch (e) {
      sonnerToast.error(e?.message || "Bulk cancel failed");
    } finally {
      setCancelBusy(false);
    }
  };

  // Aug-2026 · Soft-delete state — per-row + bulk + restore.
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState(null); // null → bulk
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [confirmRestoreOpen, setConfirmRestoreOpen] = useState(false);
  const [restoreTargetId, setRestoreTargetId] = useState(null);
  const [restoreBusy, setRestoreBusy] = useState(false);

  const openRowDelete = (id) => {
    setDeleteTargetId(id);
    setConfirmDeleteOpen(true);
  };
  const openBulkDelete = () => {
    setDeleteTargetId(null);
    setConfirmDeleteOpen(true);
  };
  const closeDeleteConfirm = () => {
    if (deleteBusy) return;
    setConfirmDeleteOpen(false);
    setDeleteTargetId(null);
  };

  const doSoftDelete = async () => {
    setDeleteBusy(true);
    try {
      if (deleteTargetId) {
        await api.del(`/autobilling/runs/${deleteTargetId}`);
        sonnerToast.success("Run deleted");
        setRows((prev) => showDeleted
          ? prev.map((r) => (r.id === deleteTargetId
              ? { ...r, deleted_at: new Date().toISOString() }
              : r))
          : prev.filter((r) => r.id !== deleteTargetId),
        );
      } else {
        const ids = Array.from(selectedIds);
        const res = await api.post("/autobilling/runs/bulk-delete", { ids });
        const d = res.deleted || 0;
        const s = res.skipped || 0;
        sonnerToast[s === 0 ? "success" : "info"](
          `${d} deleted${s ? ` · ${s} skipped` : ""}`,
        );
        const doneSet = new Set(
          (res.results || [])
            .filter((r) => r.status === "deleted")
            .map((r) => r.id),
        );
        setRows((prev) => showDeleted
          ? prev.map((r) => (doneSet.has(r.id)
              ? { ...r, deleted_at: new Date().toISOString() }
              : r))
          : prev.filter((r) => !doneSet.has(r.id)),
        );
        clearSelection();
      }
      setConfirmDeleteOpen(false);
      setDeleteTargetId(null);
    } catch (e) {
      sonnerToast.error(e?.message || "Delete failed");
    } finally {
      setDeleteBusy(false);
    }
  };

  const openRestore = (id) => {
    setRestoreTargetId(id);
    setConfirmRestoreOpen(true);
  };
  const closeRestoreConfirm = () => {
    if (restoreBusy) return;
    setConfirmRestoreOpen(false);
    setRestoreTargetId(null);
  };
  const doRestore = async () => {
    if (!restoreTargetId) return;
    setRestoreBusy(true);
    try {
      await api.post(`/autobilling/runs/${restoreTargetId}/restore`, {});
      sonnerToast.success("Run restored");
      setRows((prev) => prev.map((r) => (r.id === restoreTargetId
        ? { ...r, deleted_at: null, restored_at: new Date().toISOString() }
        : r)));
      setConfirmRestoreOpen(false);
      setRestoreTargetId(null);
    } catch (e) {
      sonnerToast.error(e?.message || "Restore failed");
    } finally {
      setRestoreBusy(false);
    }
  };

  // ═════════════════════════════════════════════════════════════════
  // Phase P41 · Feb-2026 — HARD DELETE state + handlers.
  //
  // Distinct from soft-delete: physical removal via
  //   DELETE /api/autobilling-runs/{run_id}         (single)
  //   POST   /api/autobilling-runs/hard-delete-bulk (bulk, ids body)
  // The confirmation modal is MANDATORY — irreversible action.
  // ═════════════════════════════════════════════════════════════════
  const [confirmHardDeleteOpen, setConfirmHardDeleteOpen] = useState(false);
  const [hardDeleteTargetId, setHardDeleteTargetId] = useState(null);
  const [hardDeleteBusy, setHardDeleteBusy] = useState(false);

  const openRowHardDelete = (id) => {
    setHardDeleteTargetId(id);
    setConfirmHardDeleteOpen(true);
  };
  const openBulkHardDelete = () => {
    setHardDeleteTargetId(null);
    setConfirmHardDeleteOpen(true);
  };
  const closeHardDeleteConfirm = () => {
    if (hardDeleteBusy) return;
    setConfirmHardDeleteOpen(false);
    setHardDeleteTargetId(null);
  };

  const doHardDelete = async () => {
    setHardDeleteBusy(true);
    try {
      if (hardDeleteTargetId) {
        // Single hard-delete.
        await api.del(`/autobilling-runs/${hardDeleteTargetId}`);
        sonnerToast.success("Billing run permanently deleted.");
        setRows((prev) => prev.filter((r) => r.id !== hardDeleteTargetId));
        // Clear the selection membership too, in case the row was
        // ticked in the bulk selection.
        setSelectedIds((prev) => {
          if (!prev.has(hardDeleteTargetId)) return prev;
          const next = new Set(prev);
          next.delete(hardDeleteTargetId);
          return next;
        });
      } else {
        // Bulk hard-delete.
        const ids = Array.from(selectedIds);
        const requested = ids.length;
        const res = await api.post(
          "/autobilling-runs/hard-delete-bulk", { ids },
        );
        const deleted = Number(res?.deleted_count || 0);
        const notFound = new Set(res?.not_found || []);
        // Optimistic remove — drop the ids that MongoDB confirmed
        // as gone. Ids in `not_found` stay in the table (they may
        // still exist for another tenant, but not for this one —
        // effectively they were never in the visible list).
        setRows((prev) => prev.filter(
          (r) => !ids.includes(r.id) || notFound.has(r.id)));
        const msg = deleted === requested
          ? `Permanently deleted ${deleted} billing run${
              deleted === 1 ? "" : "s"}.`
          : `Permanently deleted ${deleted} of ${requested} billing runs.`;
        sonnerToast[deleted === requested ? "success" : "info"](msg);
        clearSelection();
      }
      setConfirmHardDeleteOpen(false);
      setHardDeleteTargetId(null);
    } catch (e) {
      sonnerToast.error(e?.message || "Permanent delete failed");
    } finally {
      setHardDeleteBusy(false);
    }
  };


  const exportCsv = () => {
    const header = ["Timestamp", "Plan", "Schedule", "Anchor date", "Current month", "Status", "Message", "Invoice"];
    const body = sorted.map((r) => [
      r.ts, r.plan_name || r.plan_id || "",
      SCHEDULE_LABELS[r.run_schedule] || r.run_schedule || "",
      r.anchor_date || "", r.current_month || "", r.status || "",
      r.message || "", r.invoice_id || "",
    ]);
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [header, ...body].map((row) => row.map(esc).join(",")).join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `autobilling-runs-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  };

  const COLS = [
    { k: "ts", label: "Timestamp" },
    { k: "plan_name", label: "Plan" },
    { k: "run_schedule", label: "Schedule" },
    { k: "anchor_date", label: "Anchor" },
    { k: "status", label: "Status" },
    { k: "message", label: "Message" },
  ];

  return (
    <div className="max-w-6xl mx-auto py-6 px-4 space-y-4" data-testid="autobilling-runs-page">
      <Link to="/auto-billing" className="inline-flex items-center gap-1 text-xs font-bold"
            style={{ color: colors.brand, textDecoration: "none" }}>
        <ArrowLeft size={12} /> Auto-billing
      </Link>

      <PageHeader
        icon={Repeat}
        title="Autobilling runs"
        subtitle="Audit log of every billing plan fire attempt — scheduled, manual, skipped, error, and late-missed. Rows are tenant-scoped."
      />

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
               style={{ color: colors.muted, letterSpacing: 0.4 }}>Plan</div>
          <select
            value={planFilter}
            onChange={(e) => setPlanFilter(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[180px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="autobilling-runs-filter-plan"
          >
            <option value="">All plans</option>
            {planOptions.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </div>

        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
               style={{ color: colors.muted, letterSpacing: 0.4 }}>Status</div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[140px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="autobilling-runs-filter-status"
          >
            <option value="">All statuses</option>
            {Object.keys(STATUS_STYLES).map((s) => (
              <option key={s} value={s}>{STATUS_STYLES[s].label}</option>
            ))}
          </select>
        </div>

        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
               style={{ color: colors.muted, letterSpacing: 0.4 }}>Since</div>
          <input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            className="text-sm px-2 py-2 rounded-md"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="autobilling-runs-filter-since"
          />
        </div>

        <div className="flex-1" />

        {canSoftDelete ? (
          <label
            className="inline-flex items-center gap-2 text-xs font-semibold cursor-pointer"
            style={{ color: colors.onSurface }}
            data-testid="autobilling-runs-show-deleted-label"
          >
            <input
              type="checkbox"
              checked={showDeleted}
              onChange={(e) => setShowDeleted(e.target.checked)}
              data-testid="autobilling-runs-show-deleted-toggle"
              className="cursor-pointer"
            />
            Show deleted
          </label>
        ) : null}

        {canSoftDelete && selectedCount > 0 ? (
          <button
            type="button"
            onClick={openBulkDelete}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md"
            style={{ background: "#DC2626", color: "#fff", border: 0 }}
            data-testid="autobilling-runs-bulk-delete-button"
          >
            <Trash2 size={12} /> Delete Selected ({selectedCount})
          </button>
        ) : null}

        {canSoftDelete && selectedCount > 0 ? (
          <button
            type="button"
            onClick={openBulkHardDelete}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md"
            style={{ background: "#7F1D1D", color: "#fff", border: 0 }}
            data-testid="autobilling-runs-bulk-hard-delete-button"
            title="Physically remove selected billing runs (cannot be undone)"
          >
            <AlertOctagon size={12} /> Delete Permanently ({selectedCount})
          </button>
        ) : null}

        <button
          type="button"
          onClick={exportCsv}
          disabled={sorted.length === 0}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md"
          style={{ background: colors.brand, color: "#fff", border: 0,
                   opacity: sorted.length === 0 ? 0.5 : 1,
                   cursor: sorted.length === 0 ? "not-allowed" : "pointer" }}
          data-testid="autobilling-runs-csv-export"
        >
          <Download size={12} /> Export CSV
        </button>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}
             data-testid="autobilling-runs-error">{error}</div>
      ) : (
        <div
          className="rounded-lg overflow-hidden"
          style={{ background: "#fff", border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-xs" data-testid="autobilling-runs-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="px-3 py-2 w-8" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    disabled={visibleIds.length === 0}
                    aria-label="Select all visible runs"
                    data-testid="autobilling-runs-select-all"
                    className="cursor-pointer"
                  />
                </th>
                {COLS.map((c) => (
                  <th
                    key={c.k}
                    className="text-left px-3 py-2 cursor-pointer select-none"
                    style={{ color: colors.muted }}
                    onClick={() => bump(c.k)}
                    data-testid={`autobilling-runs-col-${c.k}`}
                  >
                    {c.label}
                    {sort.key === c.k ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
                {canSoftDelete ? (
                  <th
                    className="text-right px-3 py-2 w-14"
                    style={{ color: colors.muted }}
                    data-testid="autobilling-runs-col-actions"
                  >
                    &nbsp;
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={COLS.length + (canSoftDelete ? 2 : 1)} className="px-3 py-6 text-center"
                      style={{ color: colors.muted }}
                      data-testid="autobilling-runs-empty">
                    No autobilling runs yet. Runs appear here when the daily
                    scheduler fires a plan or an admin uses "Run now".
                  </td>
                </tr>
              ) : sorted.map((r) => {
                const isDeleted = Boolean(r.deleted_at);
                const rowBg = selectedIds.has(r.id)
                  ? "#EFF6FF"
                  : (isDeleted ? "#F9FAFB" : "transparent");
                const mutedFg = isDeleted ? "#9CA3AF" : colors.onSurface;
                const mutedSub = isDeleted ? "#B0B7C0" : colors.muted;
                const strike = isDeleted ? { textDecoration: "line-through" } : {};
                return (
                <tr key={r.id}
                     data-testid={`autobilling-runs-row-${r.id}`}
                     data-deleted={isDeleted ? "true" : "false"}
                     style={{ backgroundColor: rowBg }}>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(r.id)}
                      onChange={() => toggleOne(r.id)}
                      aria-label={`Select run ${r.id}`}
                      data-testid={`autobilling-runs-row-select-${r.id}`}
                      className="cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-2" style={{ color: mutedFg }}>{fmtTs(r.ts)}</td>
                  <td className="px-3 py-2 font-bold" style={{ color: mutedFg }}>
                    {r.plan_name || r.plan_id || "—"}
                  </td>
                  <td className="px-3 py-2" style={{ color: mutedSub }}>
                    {SCHEDULE_LABELS[r.run_schedule] || r.run_schedule || "—"}
                  </td>
                  <td className="px-3 py-2" style={{ color: mutedSub }}>{r.anchor_date || "—"}</td>
                  <td className="px-3 py-2">
                    {isDeleted ? (
                      <span
                        className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
                        style={{ backgroundColor: "#E5E7EB", color: "#6B7280" }}
                        data-testid={`autobilling-runs-row-deleted-pill-${r.id}`}
                      >
                        Deleted
                      </span>
                    ) : <StatusPill status={r.status} />}
                  </td>
                  <td className="px-3 py-2" style={{ color: mutedSub, ...strike }}>
                    {r.message || "—"}
                  </td>
                  {canSoftDelete ? (
                    <td className="px-3 py-2 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}>
                      {isDeleted ? (
                        <button
                          type="button"
                          onClick={() => openRestore(r.id)}
                          aria-label={`Restore run ${r.id}`}
                          title="Restore"
                          className="inline-flex items-center justify-center p-1.5 rounded-md hover:bg-slate-100"
                          style={{ color: "#0F766E" }}
                          data-testid={`autobilling-runs-row-restore-${r.id}`}
                        >
                          <RotateCcw size={14} />
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => openRowDelete(r.id)}
                            aria-label={`Delete run ${r.id}`}
                            title="Delete (soft)"
                            className="inline-flex items-center justify-center p-1.5 rounded-md hover:bg-red-50"
                            style={{ color: "#DC2626" }}
                            data-testid={`autobilling-runs-row-delete-${r.id}`}
                          >
                            <Trash2 size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => openRowHardDelete(r.id)}
                            aria-label={`Permanently delete run ${r.id}`}
                            title="Delete Permanently (cannot be undone)"
                            className="inline-flex items-center justify-center p-1.5 rounded-md hover:bg-red-50 ml-1"
                            style={{ color: "#7F1D1D" }}
                            data-testid={`autobilling-runs-row-hard-delete-${r.id}`}
                          >
                            <AlertOctagon size={13} />
                          </button>
                        </>
                      )}
                    </td>
                  ) : null}
                </tr>
              );})}
            </tbody>
          </table>
        </div>
      )}

      {/* Phase AB1 · Bulk-cancel action bar. Visible only when ≥1 selected. */}
      {selectedCount > 0 ? (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-2xl shadow-2xl flex items-center gap-3 px-4 py-3 z-40"
          style={{ backgroundColor: colors.onSurface, color: "#FFFFFF",
                    border: "1px solid rgba(255,255,255,0.08)" }}
          data-testid="autobilling-runs-bulk-action-bar"
        >
          <div className="text-sm font-semibold"
                data-testid="autobilling-runs-bulk-action-bar-count">
            {selectedCount} selected
          </div>
          <button
            type="button"
            onClick={() => setConfirmCancelOpen(true)}
            disabled={cancelBusy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{ backgroundColor: "#B45309", color: "#FFFFFF" }}
            data-testid="autobilling-runs-bulk-cancel-button"
          >
            <XCircle size={12} /> Bulk cancel
          </button>
          <button
            type="button"
            onClick={clearSelection}
            className="text-xs font-semibold underline"
            style={{ color: "rgba(255,255,255,0.85)" }}
            data-testid="autobilling-runs-bulk-clear-selection"
          >
            Clear selection
          </button>
        </div>
      ) : null}

      {/* Phase AB1 · Bulk-cancel confirmation modal. */}
      {confirmCancelOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmCancelOpen(false); }}
          data-testid="autobilling-runs-bulk-cancel-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ background: "#fff", border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-1" style={{ color: colors.onSurface }}>
              Cancel {selectedCount} run{selectedCount === 1 ? "" : "s"}?
            </h2>
            <p className="text-sm mb-3" style={{ color: colors.muted }}>
              Only pending / scheduled / queued runs will be cancelled.
              Completed, failed, and already-cancelled runs will be
              skipped and listed in the result summary.
            </p>
            <label className="block text-[10px] uppercase font-bold mb-1"
                    style={{ color: colors.muted }}>
              Reason (optional)
            </label>
            <textarea
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              placeholder="e.g., plans consolidated into a single monthly invoice"
              data-testid="autobilling-runs-bulk-cancel-reason"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmCancelOpen(false)}
                disabled={cancelBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface,
                          opacity: cancelBusy ? 0.5 : 1 }}
                data-testid="autobilling-runs-bulk-cancel-cancel"
              >
                Keep runs
              </button>
              <button
                type="button"
                onClick={doBulkCancel}
                disabled={cancelBusy}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#B45309" }}
                data-testid="autobilling-runs-bulk-cancel-confirm-btn"
              >
                {cancelBusy ? "Cancelling…" : `Cancel ${selectedCount}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Phase AB1 · Post-run result summary (auto-hides on next selection). */}
      {cancelResult ? (
        <div
          className="rounded-lg p-3 text-xs"
          style={{ background: "#FEF3C7",
                    border: "1px solid #FCD34D",
                    color: "#92400E" }}
          data-testid="autobilling-runs-bulk-cancel-summary"
        >
          <b>Bulk cancel:</b> {cancelResult.cancelled || 0} cancelled ·{" "}
          {cancelResult.skipped || 0} skipped.{" "}
          <button
            type="button"
            onClick={() => setCancelResult(null)}
            className="ml-2 underline font-semibold"
            data-testid="autobilling-runs-bulk-cancel-summary-dismiss"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {/* Aug-2026 · Soft-delete confirmation modal — per-row + bulk. */}
      {confirmDeleteOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeDeleteConfirm(); }}
          data-testid="autobilling-runs-delete-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ background: "#fff", border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}
                data-testid="autobilling-runs-delete-confirm-title">
              {deleteTargetId
                ? "Delete this autobill run?"
                : `Delete ${selectedCount} autobill run${selectedCount === 1 ? "" : "s"}?`}
            </h2>
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              {deleteTargetId
                ? "This will be soft-deleted and hidden from the default view but preserved for auditing."
                : "Same soft-delete semantics — hidden from the default view but preserved for auditing."}
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeDeleteConfirm}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface,
                          opacity: deleteBusy ? 0.5 : 1 }}
                data-testid="autobilling-runs-delete-cancel-btn"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doSoftDelete}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid="autobilling-runs-delete-confirm-btn"
              >
                {deleteBusy
                  ? "Deleting…"
                  : deleteTargetId
                    ? "Confirm"
                    : `Confirm (${selectedCount})`}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Phase P41 · Feb-2026 — HARD DELETE confirmation modal.
          Mandatory confirm: physical delete cannot be undone.
          Distinct testids from the soft-delete modal so the two
          flows never cross wires in tests. */}
      {confirmHardDeleteOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeHardDeleteConfirm();
          }}
          data-testid="autobilling-runs-hard-delete-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ background: "#fff", border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2"
                style={{ color: "#7F1D1D" }}
                data-testid="autobilling-runs-hard-delete-confirm-title">
              {hardDeleteTargetId
                ? "Permanently delete this billing run?"
                : `Permanently delete ${selectedCount} billing run${
                    selectedCount === 1 ? "" : "s"}?`}
            </h2>
            <p className="text-sm mb-4"
               style={{ color: colors.onSurface }}
               data-testid="autobilling-runs-hard-delete-confirm-body">
              {hardDeleteTargetId
                ? (
                  <>
                    This will permanently remove billing run{" "}
                    <span className="font-mono font-bold">
                      {String(hardDeleteTargetId).slice(0, 8)}
                    </span>{" "}
                    from your account. This action cannot be undone.
                  </>
                ) : (
                  <>
                    This will permanently remove {selectedCount} billing
                    run{selectedCount === 1 ? "" : "s"}. This action cannot
                    be undone.
                  </>
                )}
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeHardDeleteConfirm}
                disabled={hardDeleteBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface,
                          opacity: hardDeleteBusy ? 0.5 : 1 }}
                data-testid="autobilling-runs-hard-delete-cancel-btn"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doHardDelete}
                disabled={hardDeleteBusy}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#7F1D1D" }}
                data-testid="autobilling-runs-hard-delete-confirm-btn"
              >
                {hardDeleteBusy
                  ? "Deleting…"
                  : hardDeleteTargetId
                    ? "Delete Permanently"
                    : `Delete Permanently (${selectedCount})`}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Aug-2026 · Restore confirmation modal (deleted rows only). */}
      {confirmRestoreOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeRestoreConfirm(); }}
          data-testid="autobilling-runs-restore-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ background: "#fff", border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>
              Restore this autobill run?
            </h2>
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              Restore this autobill run to the default view?
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeRestoreConfirm}
                disabled={restoreBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface,
                          opacity: restoreBusy ? 0.5 : 1 }}
                data-testid="autobilling-runs-restore-cancel-btn"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doRestore}
                disabled={restoreBusy}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#0F766E" }}
                data-testid="autobilling-runs-restore-confirm-btn"
              >
                {restoreBusy ? "Restoring…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
