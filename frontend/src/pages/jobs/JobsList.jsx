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
import { useNavigate, useSearchParams } from "react-router-dom";
import { Briefcase, RefreshCw, X as XIcon } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { formatCustomerName } from "@/utils/formatCustomerName";
import {
  useBulkSelect,
  BulkSelectAll,
  BulkSelectRow,
  BulkActionBar,
  BulkConfirmModal,
  LockedPill,
} from "@/components/bulk-select/BulkSelectToolkit";
// Task L+P · Commit 6 · Feb-2026 — new "Photos" column strip.
// Reads ``photo_ids`` + ``photo_thumb_urls`` already present on
// list rows (Commit-3 widening).
import { JobPhotoThumbs } from "@/components/jobs/JobPhotoThumbs";
// Feb-2026 · N5-T1 · PageHeader adoption sweep (Option A: replace).
import PageHeader from "@/components/layout/PageHeader";

// Phase 34 · Feb 2026 — Dashboard KPI tiles link into this list
// with ``?status=active`` / ``?status=pending`` (backend job docs
// carry these as ``status`` values; JobsList treats them as a
// straight passthrough to /api/jobs). Adding the two entries here
// keeps the ``<select>`` label honest when the KPI drill-down lands.
const STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "pending", label: "Pending" },
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
  // Feb-2026 · Priority 7 — hydrate the status filter from the URL
  // so Dashboard KPI drill-downs land pre-filtered (e.g. Active
  // Jobs → /jobs?status=active). Two-way binding: user changes to
  // the ``<select>`` push the new value back into the URL, keeping
  // deep-links / back-button honest.
  const [searchParams, setSearchParams] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [status, setStatus] = useState(searchParams.get("status") || "");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});
  // Reschedule modal state.
  const [rescheduleOpen, setRescheduleOpen] = useState(false);
  const [rescheduleMode, setRescheduleMode] = useState("absolute"); // absolute | relative
  const [rescheduleDate, setRescheduleDate] = useState("");
  const [shiftValue, setShiftValue] = useState(1);
  const [shiftUnit, setShiftUnit] = useState("days"); // days | weeks
  const [shiftDirection, setShiftDirection] = useState(1); // 1 | -1
  const [anchorUnscheduled, setAnchorUnscheduled] = useState(false);
  const [rescheduleConfirmOpen, setRescheduleConfirmOpen] = useState(false);
  const [rescheduleBusy, setRescheduleBusy] = useState(false);

  const shiftDays = useMemo(() => {
    const magnitude = Math.max(0, parseInt(shiftValue, 10) || 0);
    const perUnit = shiftUnit === "weeks" ? 7 : 1;
    return shiftDirection * magnitude * perUnit;
  }, [shiftValue, shiftUnit, shiftDirection]);

  const canConfirmReschedule = rescheduleMode === "absolute"
    ? Boolean(rescheduleDate)
    : shiftDays !== 0;

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
    if (!canConfirmReschedule) return;
    setRescheduleBusy(true);
    try {
      const patch = rescheduleMode === "absolute"
        ? { scheduled_date: rescheduleDate }
        : {
            scheduled_date_shift_days: shiftDays,
            ...(anchorUnscheduled ? { anchor_unscheduled_from_today: true } : {}),
          };
      const res = await api.post("/jobs/bulk-update", {
        ids: Array.from(selected), patch,
      });
      applyFailures(res.failed);
      const okC = res.updated_count || 0;
      const failC = (res.failed || []).length;
      const anchoredC = res.anchored_count || 0;
      const anchorSuffix = anchoredC
        ? ` (${anchoredC} backlog job${anchoredC === 1 ? "" : "s"} scheduled from today)`
        : "";
      const msg = rescheduleMode === "absolute"
        ? `Rescheduled ${okC} job${okC === 1 ? "" : "s"} to ${formatFriendly(rescheduleDate)}`
        : `Shifted ${okC} job${okC === 1 ? "" : "s"} by ${shiftDays > 0 ? "+" : ""}${shiftDays} day${Math.abs(shiftDays) === 1 ? "" : "s"}${anchorSuffix}`;
      if (failC === 0) toast.success(msg);
      else toast(`${msg} · ${failC} locked`, {
        description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
      });
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
      {/* Feb-2026 · N5-T1 · PageHeader adoption. Replaces the
          inline title + subtitle + refresh-button row with the
          shared <PageHeader/>. Existing ``jobs-refresh-btn``
          testid is preserved via the actions slot. */}
      <PageHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Briefcase size={20} />
            <span>Jobs (admin)</span>
          </span>
        }
        subtitle="Bulk-manage work orders. Individual editing lives on the job detail page."
        actions={
          <button onClick={load}
                  className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            color: colors.onSurfaceSecondary,
                            border: `1px solid ${colors.border}` }}
                  data-testid="jobs-refresh-btn">
            <RefreshCw size={12} /> Refresh
          </button>
        }
      />

      <div className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <label className="text-xs font-semibold" style={{ color: colors.muted }}>Status</label>
        <select value={status} onChange={(e) => {
                  const v = e.target.value;
                  setStatus(v);
                  // Priority 7 · Feb 2026 — mirror the filter into
                  // the URL so refresh / share preserves the drill-
                  // down state that Dashboard KPI clicks arrived
                  // with. ``replace: true`` avoids polluting the
                  // history stack with every filter toggle.
                  const next = new URLSearchParams(searchParams);
                  if (v) next.set("status", v); else next.delete("status");
                  setSearchParams(next, { replace: true });
                }}
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
              <th className="text-left px-3 py-2 font-semibold hidden md:table-cell"
                  style={{ color: colors.onSurfaceSecondary, width: 128 }}
                  data-testid="jobs-col-photos">
                Photos
              </th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).length === 0 && rows !== null ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-sm"
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
                    onClick={() => navigate(`/jobs/${r.id}`)}
                    data-testid={`job-row-customer-${r.id}`}>
                  {formatCustomerName(r)}
                </td>
                <td className="px-3 py-3 hidden lg:table-cell text-xs"
                    style={{ color: colors.muted }}
                    onClick={() => navigate(`/jobs/${r.id}`)}>
                  {r.scheduled_date || "—"}
                </td>
                <td className="px-3 py-3 hidden md:table-cell"
                    onClick={() => navigate(`/jobs/${r.id}`)}>
                  <JobPhotoThumbs
                    jobId={r.id}
                    photoIds={r.photo_ids}
                    photoThumbUrls={r.photo_thumb_urls}
                  />
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
              </div>
              <button type="button" onClick={() => setRescheduleOpen(false)}
                        className="p-1" style={{ color: colors.muted }}
                        aria-label="Close reschedule modal">
                <XIcon size={18} />
              </button>
            </div>

            {/* Mode toggle */}
            <div className="flex gap-1 mb-4 p-1 rounded-xl"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}` }}>
              <button type="button"
                        onClick={() => setRescheduleMode("absolute")}
                        className="flex-1 text-xs font-bold uppercase tracking-wider px-3 py-2 rounded-lg transition"
                        style={{
                          backgroundColor: rescheduleMode === "absolute" ? colors.brandTertiary : "transparent",
                          color: rescheduleMode === "absolute" ? colors.onBrandTertiary : colors.muted,
                        }}
                        data-testid="bulk-reschedule-mode-absolute">
                Absolute date
              </button>
              <button type="button"
                        onClick={() => setRescheduleMode("relative")}
                        className="flex-1 text-xs font-bold uppercase tracking-wider px-3 py-2 rounded-lg transition"
                        style={{
                          backgroundColor: rescheduleMode === "relative" ? colors.brandTertiary : "transparent",
                          color: rescheduleMode === "relative" ? colors.onBrandTertiary : colors.muted,
                        }}
                        data-testid="bulk-reschedule-mode-relative">
                Relative shift
              </button>
            </div>

            {rescheduleMode === "absolute" ? (
              <>
                <p className="text-sm mb-2" style={{ color: colors.muted }}>
                  Reschedule all selected to this date. Preserves each job's
                  time-of-day and technician assignment.
                </p>
                <label className="block text-xs font-semibold mb-1 uppercase tracking-wider"
                         style={{ color: colors.muted }}>Target date</label>
                <input type="date" value={rescheduleDate}
                         onChange={(e) => setRescheduleDate(e.target.value)}
                         className="w-full px-3 py-2 rounded-lg text-sm"
                         style={{ backgroundColor: colors.surfaceSecondary,
                                    color: colors.onSurface,
                                    border: `1px solid ${colors.border}` }}
                         data-testid="bulk-reschedule-datepicker" />
              </>
            ) : (
              <>
                <p className="text-sm mb-2" style={{ color: colors.muted }}>
                  Shift all selected by a relative amount. Each job's new date
                  is computed individually from its current schedule.
                </p>
                <div className="flex items-stretch gap-2">
                  <div className="flex rounded-lg overflow-hidden"
                        style={{ border: `1px solid ${colors.border}` }}>
                    <button type="button"
                              onClick={() => setShiftDirection(-1)}
                              className="w-9 text-sm font-bold"
                              style={{
                                backgroundColor: shiftDirection === -1 ? "#DC2626" : colors.surfaceSecondary,
                                color: shiftDirection === -1 ? "#FFFFFF" : colors.onSurface,
                              }}
                              data-testid="bulk-reschedule-shift-direction-minus"
                              aria-label="Shift backward">
                      −
                    </button>
                    <button type="button"
                              onClick={() => setShiftDirection(1)}
                              className="w-9 text-sm font-bold"
                              style={{
                                backgroundColor: shiftDirection === 1 ? "#1D4ED8" : colors.surfaceSecondary,
                                color: shiftDirection === 1 ? "#FFFFFF" : colors.onSurface,
                              }}
                              data-testid="bulk-reschedule-shift-direction-plus"
                              aria-label="Shift forward">
                      +
                    </button>
                  </div>
                  {/* Hidden signed input exposes the same intent for
                       tools that prefer a single testid. Value = signed magnitude. */}
                  <input type="hidden"
                            value={String(shiftDirection * (parseInt(shiftValue, 10) || 0))}
                            data-testid="bulk-reschedule-shift-direction"
                            readOnly />
                  <input type="number" min="0" step="1"
                            value={shiftValue}
                            onChange={(e) => setShiftValue(e.target.value)}
                            className="flex-1 px-3 py-2 rounded-lg text-sm"
                            style={{ backgroundColor: colors.surfaceSecondary,
                                        color: colors.onSurface,
                                        border: `1px solid ${colors.border}` }}
                            data-testid="bulk-reschedule-shift-value"
                            aria-label="Shift magnitude" />
                  <select value={shiftUnit}
                            onChange={(e) => setShiftUnit(e.target.value)}
                            className="px-3 py-2 rounded-lg text-sm"
                            style={{ backgroundColor: colors.surfaceSecondary,
                                        color: colors.onSurface,
                                        border: `1px solid ${colors.border}` }}
                            data-testid="bulk-reschedule-shift-unit">
                    <option value="days">Days</option>
                    <option value="weeks">Weeks</option>
                  </select>
                </div>
                <div className="mt-2 text-xs" style={{ color: colors.muted }}>
                  Effective shift: <b>{shiftDays > 0 ? "+" : ""}{shiftDays} day{Math.abs(shiftDays) === 1 ? "" : "s"}</b>
                </div>
                <label className="mt-3 flex items-start gap-2 cursor-pointer text-xs"
                         style={{ color: colors.onSurface }}>
                  <input type="checkbox"
                           checked={anchorUnscheduled}
                           onChange={(e) => setAnchorUnscheduled(e.target.checked)}
                           className="cursor-pointer mt-0.5"
                           data-testid="bulk-reschedule-anchor-unscheduled" />
                  <span>
                    <b>Also schedule unscheduled jobs</b> — anchor from today
                    <div className="text-[11px] mt-0.5" style={{ color: colors.muted }}>
                      Backlog jobs without a current date get a fresh date of
                      today {shiftDays > 0 ? "+" : "−"} {Math.abs(shiftDays)} day{Math.abs(shiftDays) === 1 ? "" : "s"}.
                    </div>
                  </span>
                </label>
              </>
            )}

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
                        disabled={!canConfirmReschedule || rescheduleBusy}
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
        title={rescheduleMode === "absolute"
          ? `Reschedule ${selectedCount} job${selectedCount === 1 ? "" : "s"} to ${formatFriendly(rescheduleDate)}?`
          : `Shift ${selectedCount} job${selectedCount === 1 ? "" : "s"} by ${shiftDays > 0 ? "+" : ""}${shiftDays} day${Math.abs(shiftDays) === 1 ? "" : "s"}?`}
        description={rescheduleMode === "absolute"
          ? "This preserves each job's time-of-day and technician assignment. Jobs with active timers or completed+invoiced will be skipped."
          : "Each job's new date is computed individually from its existing schedule. Jobs without a scheduled date will be skipped."}
        confirmLabel={rescheduleBusy
          ? "Rescheduling…"
          : (rescheduleMode === "absolute" ? `Reschedule ${selectedCount}` : `Shift ${selectedCount}`)}
        busy={rescheduleBusy}
        testidRoot="bulk-reschedule-confirm"
      />
    </div>
  );
}
