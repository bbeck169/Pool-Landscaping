/**
 * Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — Admin Jobs list.
 *
 * The primary jobs view is the unified CalendarSchedule; this admin
 * table-view exists specifically to expose the /jobs/bulk-delete +
 * /jobs/bulk-update endpoints via the shared BulkSelectToolkit. Keep
 * this page thin — one filter row + one table + the toolkit-driven
 * action bar. Full editing lives on the JobDetail route.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Briefcase, RefreshCw, X as XIcon } from "lucide-react";
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

const STATUS_OPTIONS = [
  { value: "scheduled", label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "canceled", label: "Canceled" },
];

function formatFriendly(dateStr) {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString(undefined, { weekday: "long", year: "numeric",
                                                  month: "long", day: "numeric" });
  } catch { return dateStr; }
}

export default function JobsList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [status, setStatus] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});
  // Reschedule modal state.
  const [rescheduleOpen, setRescheduleOpen] = useState(false);
  const [rescheduleDate, setRescheduleDate] = useState("");
  const [rescheduleConfirmOpen, setRescheduleConfirmOpen] = useState(false);
  const [rescheduleBusy, setRescheduleBusy] = useState(false);

  const load = () => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    api.get(`/jobs${qs}`).then((r) => setRows(r || [])).catch(() => setRows([]));
  };

  useEffect(load, [status]);

  const visibleIds = useMemo(() => (rows || []).map((r) => r.id), [rows]);
  const {
    selected, selectedCount, allVisibleSelected, indeterminate,
    toggleAll, toggleOne, clear,
  } = useBulkSelect(visibleIds);

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
      const res = await api.post("/jobs/bulk-delete", { ids: Array.from(selected) });
      setRows((prev) => (prev || []).filter((r) => !(res.deleted || []).includes(r.id)));
      applyFailures(res.failed);
      clear(); setConfirmOpen(false);
      const okC = res.deleted_count || 0;
      const failC = (res.failed || []).length;
      if (failC === 0) toast.success(`${okC} job${okC === 1 ? "" : "s"} deleted`);
      else toast(`${okC} deleted · ${failC} locked`, {
        description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
      });
    } catch (e) {
      toast.error(e?.message || "Bulk delete failed");
    } finally { setBusy(false); }
  };

  const doBulkStatus = async (nextStatus) => {
    try {
      const res = await api.post("/jobs/bulk-update", {
        ids: Array.from(selected),
        patch: { status: nextStatus },
      });
      applyFailures(res.failed);
      toast.success(`${res.updated_count || 0} job${(res.updated_count || 0) === 1 ? "" : "s"} → ${nextStatus}`);
      clear();
      load();
    } catch (e) { toast.error(e?.message || "Bulk update failed"); }
  };

  const doBulkReschedule = async () => {
    if (!rescheduleDate) return;
    setRescheduleBusy(true);
    try {
      const res = await api.post("/jobs/bulk-update", {
        ids: Array.from(selected),
        patch: { scheduled_date: rescheduleDate },
      });
      applyFailures(res.failed);
      toast.success(`Rescheduled ${res.updated_count || 0} job${(res.updated_count || 0) === 1 ? "" : "s"} to ${formatFriendly(rescheduleDate)}`);
      setRescheduleConfirmOpen(false);
      setRescheduleOpen(false);
      setRescheduleDate("");
      clear();
      load();
    } catch (e) { toast.error(e?.message || "Bulk reschedule failed"); }
    finally { setRescheduleBusy(false); }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="jobs-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <Briefcase size={20} className="inline mr-2" />
            Jobs (admin)
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Bulk-manage work orders. Individual editing lives on the job detail page.
          </p>
        </div>
        <button onClick={load}
                className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="jobs-refresh-btn">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      <div className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <label className="text-xs font-semibold" style={{ color: colors.muted }}>Status</label>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
                className="text-xs font-semibold px-3 py-2 rounded-lg"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="jobs-filter-status">
          <option value="">All</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm" data-testid="jobs-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="px-3 py-2 w-8">
                <BulkSelectAll checked={allVisibleSelected}
                                 indeterminate={indeterminate}
                                 onChange={toggleAll} />
              </th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Title</th>
              <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Customer</th>
              <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>Scheduled</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).length === 0 && rows !== null ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="jobs-empty">
                No jobs match this filter.
              </td></tr>
            ) : null}
            {(rows || []).map((r) => (
              <tr key={r.id}
                  className="cursor-pointer hover:bg-zinc-50"
                  style={{ borderTop: `1px solid ${colors.divider}`,
                            backgroundColor: selected.has(r.id) ? "#EFF6FF" : "transparent" }}
                  data-testid={`job-row-${r.id}`}>
                <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                  <BulkSelectRow id={r.id} checked={selected.has(r.id)}
                                    onChange={() => toggleOne(r.id)} />
                </td>
                <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}
                    onClick={() => navigate(`/jobs/${r.id}`)}>
                  {r.title || r.service_name || `Job ${r.id.slice(0, 8)}`}
                  {lockedFailures[r.id] ? <LockedPill reason={lockedFailures[r.id]} /> : null}
                </td>
                <td className="px-3 py-3 hidden md:table-cell"
                    style={{ color: colors.onSurfaceSecondary }}
                    onClick={() => navigate(`/jobs/${r.id}`)}>
                  {r.customer_name || "—"}
                </td>
                <td className="px-3 py-3 hidden lg:table-cell text-xs"
                    style={{ color: colors.muted }}
                    onClick={() => navigate(`/jobs/${r.id}`)}>
                  {r.scheduled_date || "—"}
                </td>
                <td className="px-3 py-3 text-xs" onClick={() => navigate(`/jobs/${r.id}`)}>
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full font-bold uppercase tracking-wider text-[10px]"
                        style={{ backgroundColor: colors.surfaceSecondary,
                                  color: colors.onSurfaceSecondary,
                                  border: `1px solid ${colors.border}` }}>
                    {r.status || "scheduled"}
                  </span>
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
          { key: "status", label: "Change status", dropdown: STATUS_OPTIONS,
            onClick: (v) => doBulkStatus(v) },
          { key: "reschedule", label: "Reschedule to date…",
            onClick: () => setRescheduleOpen(true) },
          { key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setConfirmOpen(true) },
        ]}
      />
      <BulkConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={doBulkDelete}
        title={`Delete ${selectedCount} job${selectedCount === 1 ? "" : "s"}?`}
        description="Locked jobs (active timers or completed with an invoice) will be skipped."
        confirmLabel={busy ? "Deleting…" : `Delete ${selectedCount}`}
        busy={busy}
      />

      {/* Reschedule to date modal (Feb 2026 · Task LL follow-up). */}
      {rescheduleOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
              style={{ background: "rgba(15,23,42,0.55)" }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) setRescheduleOpen(false); }}
              data-testid="bulk-edit-modal">
          <div className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  Reschedule {selectedCount} job{selectedCount === 1 ? "" : "s"}
                </h2>
                <p className="text-sm mt-1" style={{ color: colors.muted }}>
                  Pick a target date. This preserves each job's time-of-day and technician assignment.
                </p>
              </div>
              <button type="button" onClick={() => setRescheduleOpen(false)}
                        className="p-1" style={{ color: colors.muted }}
                        aria-label="Close reschedule modal">
                <XIcon size={18} />
              </button>
            </div>
            <label className="block text-xs font-semibold mb-1 uppercase tracking-wider"
                     style={{ color: colors.muted }}>Target date</label>
            <input type="date" value={rescheduleDate}
                     onChange={(e) => setRescheduleDate(e.target.value)}
                     className="w-full px-3 py-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.surfaceSecondary,
                                color: colors.onSurface,
                                border: `1px solid ${colors.border}` }}
                     data-testid="bulk-reschedule-datepicker" />
            <div className="mt-5 flex items-center justify-end gap-2">
              <button type="button" onClick={() => setRescheduleOpen(false)}
                        className="px-4 py-2 rounded-xl text-sm font-semibold"
                        style={{ backgroundColor: colors.surfaceSecondary,
                                  color: colors.onSurface }}
                        data-testid="bulk-reschedule-cancel">
                Cancel
              </button>
              <button type="button"
                        onClick={() => setRescheduleConfirmOpen(true)}
                        disabled={!rescheduleDate || rescheduleBusy}
                        className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-40"
                        style={{ backgroundColor: "#1D4ED8" }}
                        data-testid="bulk-reschedule-open-confirm">
                Continue →
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <BulkConfirmModal
        open={rescheduleConfirmOpen}
        onClose={() => setRescheduleConfirmOpen(false)}
        onConfirm={doBulkReschedule}
        title={`Reschedule ${selectedCount} job${selectedCount === 1 ? "" : "s"} to ${formatFriendly(rescheduleDate)}?`}
        description="This preserves each job's time-of-day and technician assignment. Jobs with active timers or completed+invoiced will be skipped."
        confirmLabel={rescheduleBusy ? "Rescheduling…" : `Reschedule ${selectedCount}`}
        busy={rescheduleBusy}
        testidRoot="bulk-reschedule-confirm"
      />
    </div>
  );
}
