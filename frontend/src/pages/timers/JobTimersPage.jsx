/**
 * Feb-2026 · Job Timers Phase 1 — /job-timers page (fresh build).
 *
 * Two tabs via ``?t=timers`` (default) and ``?t=avgtime``.
 * Reporting-only surface — auto-start (GPS geofence) + auto-close
 * (service-report submit) live on the backend / mobile.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui-kit";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";


function _fmtDur(seconds) {
  if (!seconds && seconds !== 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}


function _fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  } catch { return iso; }
}


function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined,
      { month: "short", day: "numeric", year: "numeric" });
  } catch { return iso; }
}


function _defaultRange() {
  // This week (Sun→today), aligns with the schedule tab default.
  const today = new Date();
  const dow = today.getUTCDay();
  const start = new Date(today);
  start.setUTCDate(today.getUTCDate() - dow);
  return {
    date_from: start.toISOString().slice(0, 10),
    date_to: today.toISOString().slice(0, 10),
  };
}


// ═════════════════════════════════════════════════════════════════════
// TIMERS TAB
// ═════════════════════════════════════════════════════════════════════
function TimersTab({ isAdmin }) {
  const [filters, setFilters] = useState(() => ({
    ..._defaultRange(), tech_id: "", crew_id: "", customer_id: "",
  }));
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editRow, setEditRow] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.date_from) params.set("date_from", filters.date_from);
      if (filters.date_to) params.set("date_to", filters.date_to);
      if (filters.tech_id) params.set("tech_id", filters.tech_id);
      if (filters.crew_id) params.set("crew_id", filters.crew_id);
      if (filters.customer_id) params.set("customer_id", filters.customer_id);
      const r = await api.get(`/job-timers?${params.toString()}`);
      setRows(r?.items || []);
    } catch (_e) {
      toast.error("Failed to load timers");
    } finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [filters]);

  const downloadCsv = () => {
    const header = ["date", "job_title", "customer", "tech", "crew",
                      "started", "ended", "duration_seconds",
                      "start_source", "end_source"];
    const csv = [
      header.join(","),
      ...rows.map((r) => header.map((h) => {
        const v = h === "date" ? (r.started_at || "").slice(0, 10)
              : h === "job_title" ? (r.job_title || "")
              : h === "customer" ? (r.customer_name || "")
              : h === "tech" ? (r.tech_name || "")
              : h === "crew" ? (r.crew_name || "")
              : h === "started" ? (r.started_at || "")
              : h === "ended" ? (r.ended_at || "")
              : h === "duration_seconds" ? String(r.duration_seconds ?? "")
              : h === "start_source" ? (r.start_source || "")
              : h === "end_source" ? (r.end_source || "") : "";
        return `"${String(v).replace(/"/g, '""')}"`;
      }).join(","))
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `job-timers-${filters.date_from}-to-${filters.date_to}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div data-testid="timers-tab">
      <div className="flex flex-wrap gap-3 items-end mb-4 p-4 rounded-2xl"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
        <label className="text-sm">
          <div className="text-xs opacity-70 mb-1">From</div>
          <input type="date" value={filters.date_from}
                  onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))}
                  data-testid="jt-filter-from"
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm">
          <div className="text-xs opacity-70 mb-1">To</div>
          <input type="date" value={filters.date_to}
                  onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
                  data-testid="jt-filter-to"
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm flex-1 min-w-[160px]">
          <div className="text-xs opacity-70 mb-1">Tech id</div>
          <input value={filters.tech_id} onChange={(e) => setFilters((f) => ({ ...f, tech_id: e.target.value }))}
                  placeholder="Filter by tech id"
                  data-testid="jt-filter-tech"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm flex-1 min-w-[160px]">
          <div className="text-xs opacity-70 mb-1">Customer id</div>
          <input value={filters.customer_id}
                  onChange={(e) => setFilters((f) => ({ ...f, customer_id: e.target.value }))}
                  placeholder="Filter by customer id"
                  data-testid="jt-filter-customer"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <Button onClick={downloadCsv} testid="jt-export-csv" variant="secondary">
          Export CSV
        </Button>
      </div>

      {loading ? (
        <div className="text-sm opacity-70" data-testid="jt-loading">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="text-sm opacity-70 p-6 text-center rounded-2xl"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="jt-empty">
          No timer entries in this range.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm" data-testid="jt-table">
            <thead>
              <tr style={{ background: colors.background }}>
                {["Date", "Job", "Tech / Crew", "Started", "Ended",
                    "Duration", "Start", "End", ...(isAdmin ? ["Edit"] : [])].map((h) => (
                  <th key={h} className="text-left px-3 py-2 text-xs font-semibold opacity-70">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} data-testid={`jt-row-${r.id}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td className="px-3 py-2">{_fmtDate(r.started_at)}</td>
                  <td className="px-3 py-2">
                    {r.job_title ? (
                      <Link to={`/jobs/${r.job_id}`} className="hover:underline"
                              style={{ color: colors.brand }}>
                        {r.job_title}
                      </Link>
                    ) : <span className="opacity-60">—</span>}
                    <div className="text-xs opacity-70">{r.customer_name || ""}</div>
                  </td>
                  <td className="px-3 py-2">
                    {r.entity_type === "crew"
                      ? <span>{r.crew_name || r.crew_id || "—"} <span className="text-xs opacity-60">(crew)</span></span>
                      : <span>{r.tech_name || r.tech_id || "—"}</span>}
                  </td>
                  <td className="px-3 py-2">{_fmtDateTime(r.started_at)}</td>
                  <td className="px-3 py-2">{_fmtDateTime(r.ended_at)}</td>
                  <td className="px-3 py-2 font-medium">{_fmtDur(r.duration_seconds)}</td>
                  <td className="px-3 py-2 text-xs opacity-70">{r.start_source || "—"}</td>
                  <td className="px-3 py-2 text-xs opacity-70">{r.end_source || "—"}</td>
                  {isAdmin ? (
                    <td className="px-3 py-2">
                      <button
                        onClick={() => setEditRow(r)}
                        className="text-xs px-2 py-1 rounded"
                        style={{ background: colors.background,
                                    border: `1px solid ${colors.border}`,
                                    color: colors.onSurface }}
                        data-testid={`jt-edit-${r.id}`}
                      >Edit</button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editRow ? (
        <EditTimerModal
          row={editRow}
          onClose={() => setEditRow(null)}
          onSave={async (patch) => {
            try {
              await api.patch(`/job-timers/${editRow.id}`, patch);
              toast.success("Timer updated");
              setEditRow(null);
              await load();
            } catch (_e) {
              toast.error("Failed to update timer");
            }
          }}
        />
      ) : null}
    </div>
  );
}


function EditTimerModal({ row, onClose, onSave }) {
  const [started, setStarted] = useState((row.started_at || "").slice(0, 16));
  const [ended, setEnded] = useState((row.ended_at || "").slice(0, 16));
  const [techId, setTechId] = useState(row.tech_id || "");
  const [crewId, setCrewId] = useState(row.crew_id || "");
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent data-testid="jt-edit-modal">
        <DialogHeader>
          <DialogTitle>Edit timer entry</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <label className="text-sm block">
            <div className="text-xs opacity-70 mb-1">Started at</div>
            <input type="datetime-local" value={started}
                    onChange={(e) => setStarted(e.target.value)}
                    data-testid="jt-edit-started"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ background: colors.surface,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }} />
          </label>
          <label className="text-sm block">
            <div className="text-xs opacity-70 mb-1">Ended at</div>
            <input type="datetime-local" value={ended}
                    onChange={(e) => setEnded(e.target.value)}
                    data-testid="jt-edit-ended"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ background: colors.surface,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }} />
          </label>
          <label className="text-sm block">
            <div className="text-xs opacity-70 mb-1">Tech id</div>
            <input value={techId} onChange={(e) => setTechId(e.target.value)}
                    data-testid="jt-edit-tech-id"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ background: colors.surface,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }} />
          </label>
          <label className="text-sm block">
            <div className="text-xs opacity-70 mb-1">Crew id</div>
            <input value={crewId} onChange={(e) => setCrewId(e.target.value)}
                    data-testid="jt-edit-crew-id"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ background: colors.surface,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }} />
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} testid="jt-edit-cancel">Cancel</Button>
          <Button onClick={() => {
            const patch = {};
            if (started !== (row.started_at || "").slice(0, 16))
              patch.started_at = new Date(started).toISOString();
            if (ended !== (row.ended_at || "").slice(0, 16))
              patch.ended_at = new Date(ended).toISOString();
            if (techId !== (row.tech_id || "")) patch.tech_id = techId || null;
            if (crewId !== (row.crew_id || "")) patch.crew_id = crewId || null;
            onSave(patch);
          }} testid="jt-edit-save">Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


// ═════════════════════════════════════════════════════════════════════
// AVG TIME TAB
// ═════════════════════════════════════════════════════════════════════
function AvgTimeTab() {
  const [filters, setFilters] = useState(() => ({
    ..._defaultRange(), tech_id: "", customer_id: "", group_by: "service_category",
  }));
  const [buckets, setBuckets] = useState([]);
  const [totals, setTotals] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.date_from) params.set("date_from", filters.date_from);
      if (filters.date_to) params.set("date_to", filters.date_to);
      if (filters.tech_id) params.set("tech_id", filters.tech_id);
      if (filters.customer_id) params.set("customer_id", filters.customer_id);
      params.set("group_by", filters.group_by);
      const r = await api.get(`/job-timers/aggregates?${params.toString()}`);
      setBuckets(r?.buckets || []);
      setTotals(r?.totals || null);
    } catch { toast.error("Failed to load aggregates"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [filters]);

  return (
    <div data-testid="avgtime-tab">
      <div className="flex flex-wrap gap-3 items-end mb-4 p-4 rounded-2xl"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
        <label className="text-sm">
          <div className="text-xs opacity-70 mb-1">From</div>
          <input type="date" value={filters.date_from}
                  onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))}
                  data-testid="avg-filter-from"
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm">
          <div className="text-xs opacity-70 mb-1">To</div>
          <input type="date" value={filters.date_to}
                  onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
                  data-testid="avg-filter-to"
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm">
          <div className="text-xs opacity-70 mb-1">Group by</div>
          <select value={filters.group_by}
                    onChange={(e) => setFilters((f) => ({ ...f, group_by: e.target.value }))}
                    data-testid="avg-filter-groupby"
                    className="px-3 py-2 rounded-lg text-sm"
                    style={{ background: colors.background,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }}>
            <option value="service_category">Service category</option>
            <option value="customer">Customer</option>
            <option value="both">Customer × Service</option>
          </select>
        </label>
        <label className="text-sm flex-1 min-w-[160px]">
          <div className="text-xs opacity-70 mb-1">Tech id</div>
          <input value={filters.tech_id}
                  onChange={(e) => setFilters((f) => ({ ...f, tech_id: e.target.value }))}
                  data-testid="avg-filter-tech"
                  placeholder="Optional tech id"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
      </div>

      {totals && totals.count > 0 ? (
        <div className="mb-4 text-sm opacity-80"
              data-testid="avg-totals">
          {totals.count} entries · avg {_fmtDur(totals.avg_seconds)} · total {_fmtDur(totals.total_seconds)}
        </div>
      ) : null}

      {loading ? (
        <div className="text-sm opacity-70">Loading…</div>
      ) : buckets.length === 0 ? (
        <div className="text-sm opacity-70 p-6 text-center rounded-2xl"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="avg-empty">
          No aggregate data in this range.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm" data-testid="avg-table">
            <thead>
              <tr style={{ background: colors.background }}>
                {["Group", "Entries", "Avg time", "Total time"].map((h) => (
                  <th key={h} className="text-left px-3 py-2 text-xs font-semibold opacity-70">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.key} data-testid={`avg-row-${b.key}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td className="px-3 py-2">{b.label}</td>
                  <td className="px-3 py-2">{b.count}</td>
                  <td className="px-3 py-2 font-medium">{_fmtDur(b.avg_seconds)}</td>
                  <td className="px-3 py-2 opacity-80">{_fmtDur(b.total_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ═════════════════════════════════════════════════════════════════════
// PAGE
// ═════════════════════════════════════════════════════════════════════
export default function JobTimersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("t") || "timers";
  const [me, setMe] = useState(null);
  useEffect(() => {
    api.get("/auth/me").then(setMe).catch(() => setMe({}));
  }, []);
  const isAdmin = useMemo(
    () => ["super_admin", "admin"].includes((me?.role || "").toLowerCase()),
    [me],
  );

  return (
    <div className="p-6" data-testid="job-timers-page"
          style={{ background: colors.background, minHeight: "100vh",
                      color: colors.onSurface }}>
      <h1 className="text-2xl font-bold mb-1">Job Timers</h1>
      <p className="text-sm opacity-70 mb-4">
        Retrospective view of GPS-triggered timers auto-closed on
        service-report submit. Mobile GPS geofence auto-start ships
        in Phase 2.
      </p>
      <div className="flex gap-2 mb-4">
        {[
          { key: "timers", label: "Timers" },
          { key: "avgtime", label: "Avg Time" },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => {
              const p = new URLSearchParams(searchParams);
              p.set("t", t.key);
              setSearchParams(p, { replace: true });
            }}
            data-testid={`jt-tab-${t.key}`}
            className="px-4 py-2 rounded-lg text-sm font-medium"
            style={{
              background: tab === t.key ? colors.brand : colors.surface,
              color: tab === t.key ? "#ffffff" : colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "avgtime" ? <AvgTimeTab /> : <TimersTab isAdmin={isAdmin} />}
    </div>
  );
}
