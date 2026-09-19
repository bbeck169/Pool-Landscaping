/**
 * Feb-2026 · Proposal Analytics — admin dashboard tab.
 *
 * Lives inside SettingsHub at ``/settings/proposal-analytics``.
 * Admin/super_admin only (route wrapper enforces).
 *
 * Landing view: filterable table of estimates that have received at
 * least one analytics event. Columns = Estimate # · Customer · Sent ·
 * Opens · Clicks · Avg pages · Avg session · [Details].
 *
 * Drill-down modal: opens per estimate. Summary tiles + recharts bar
 * chart of page views + event timeline.
 *
 * Backend endpoints consumed:
 *   GET /api/analytics/proposals/overview?date_range={7d|30d|90d|all}
 *   GET /api/analytics/proposal/{eid}/summary
 *   GET /api/analytics/proposal/{eid}/events?limit=100
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  BarChart3, Eye, MousePointerClick, LineChart as LineIcon,
  X as XIcon, Clock,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer,
} from "recharts";

import { api } from "@/api";
import { colors } from "@/theme";


const _DATE_RANGES = [
  { key: "7d",  label: "Last 7 days"  },
  { key: "30d", label: "Last 30 days" },
  { key: "90d", label: "Last 90 days" },
  { key: "all", label: "All time"      },
];


function _fmtMs(ms) {
  if (!ms || ms < 1) return "—";
  const s = Math.round(ms / 100) / 10;      // one decimal
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return r ? `${m}m ${r}s` : `${m}m`;
}


function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  } catch {
    return String(iso).slice(0, 16);
  }
}


export default function ProposalAnalyticsPage() {
  const [rangeKey, setRangeKey] = useState("30d");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [drill, setDrill] = useState(null);   // estimate_id | null

  // Sort state.
  const [sortKey, setSortKey] = useState("last_event_at");
  const [sortDir, setSortDir] = useState("desc");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const r = await api.get(
        `/analytics/proposals/overview?date_range=${rangeKey}`,
      );
      setRows(Array.isArray(r?.estimates) ? r.estimates : []);
    } catch (e) {
      setErr(e?.message || "Failed to load analytics.");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [rangeKey]);

  useEffect(() => { load(); }, [load]);

  const sortedRows = useMemo(() => {
    const cp = [...rows];
    cp.sort((a, b) => {
      const av = _sortVal(a, sortKey);
      const bv = _sortVal(b, sortKey);
      if (av === bv) return 0;
      const cmp = av < bv ? -1 : 1;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return cp;
  }, [rows, sortKey, sortDir]);

  return (
    <div className="rounded-2xl p-5 space-y-4"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="proposal-analytics-page">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2"
               style={{ color: colors.onSurface }}>
            <BarChart3 size={18} style={{ color: colors.brand }} />
            Proposal Analytics
          </h2>
          <p className="text-xs mt-1 max-w-xl"
             style={{ color: colors.muted }}>
            Anonymized viewer engagement for interactive-flipbook
            estimates. Session ids are per-tab. Client IPs are hashed
            with a per-tenant salt — no personal information is
            stored.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-semibold"
                  style={{ color: colors.muted }}>
            Range
          </label>
          <select
            value={rangeKey}
            onChange={(e) => setRangeKey(e.target.value)}
            className="text-sm rounded px-2 py-1"
            style={{ background: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface }}
            data-testid="proposal-analytics-range-select"
          >
            {_DATE_RANGES.map((d) => (
              <option key={d.key} value={d.key}>{d.label}</option>
            ))}
          </select>
        </div>
      </div>

      {err ? (
        <div className="text-sm rounded p-2"
              style={{ background: "#FEE2E2", color: "#991B1B" }}
              data-testid="proposal-analytics-error">
          {err}
        </div>
      ) : null}

      {loading ? (
        <div className="text-sm py-6 text-center"
              style={{ color: colors.muted }}
              data-testid="proposal-analytics-loading">
          Loading…
        </div>
      ) : sortedRows.length === 0 ? (
        <div className="text-sm py-8 text-center"
              style={{ color: colors.muted }}
              data-testid="proposal-analytics-empty">
          No flipbook views tracked in this window yet. When a
          customer opens a flipbook estimate, engagement data will
          appear here.
        </div>
      ) : (
        <div className="overflow-x-auto"
              data-testid="proposal-analytics-table-wrap">
          <table className="w-full text-sm"
                 style={{ borderCollapse: "separate", borderSpacing: 0 }}>
            <thead>
              <tr style={{ background: colors.surfaceSecondary }}>
                <_Th col="estimate_number" sortKey={sortKey} sortDir={sortDir}
                     onSort={_pickSorter(setSortKey, setSortDir, sortKey, sortDir)}>
                  Estimate #
                </_Th>
                <_Th col="title" sortKey={sortKey} sortDir={sortDir}
                     onSort={_pickSorter(setSortKey, setSortDir, sortKey, sortDir)}>
                  Title
                </_Th>
                <_Th col="opens" sortKey={sortKey} sortDir={sortDir}
                     onSort={_pickSorter(setSortKey, setSortDir, sortKey, sortDir)}
                     align="right">
                  Opens
                </_Th>
                <_Th col="clicks" sortKey={sortKey} sortDir={sortDir}
                     onSort={_pickSorter(setSortKey, setSortDir, sortKey, sortDir)}
                     align="right">
                  Clicks
                </_Th>
                <_Th col="avg_pages_viewed" sortKey={sortKey} sortDir={sortDir}
                     onSort={_pickSorter(setSortKey, setSortDir, sortKey, sortDir)}
                     align="right">
                  Avg pages
                </_Th>
                <_Th col="avg_session_duration_ms" sortKey={sortKey}
                     sortDir={sortDir}
                     onSort={_pickSorter(setSortKey, setSortDir, sortKey, sortDir)}
                     align="right">
                  Avg session
                </_Th>
                <_Th col="last_event_at" sortKey={sortKey} sortDir={sortDir}
                     onSort={_pickSorter(setSortKey, setSortDir, sortKey, sortDir)}
                     align="right">
                  Last activity
                </_Th>
                <th className="p-2 text-right"
                    style={{ borderBottom: `1px solid ${colors.border}` }} />
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r) => {
                const est = r.estimate || {};
                return (
                  <tr key={r.estimate_id}
                       data-testid={`proposal-analytics-row-${r.estimate_id}`}>
                    <td className="p-2" style={_td()}>
                      <span className="font-semibold">
                        {est.estimate_number || r.estimate_id.slice(0, 8).toUpperCase()}
                      </span>
                    </td>
                    <td className="p-2" style={_td()}>
                      {est.title || "—"}
                    </td>
                    <td className="p-2 text-right" style={_td()}>
                      {r.opens}
                    </td>
                    <td className="p-2 text-right" style={_td()}>
                      {r.clicks}
                    </td>
                    <td className="p-2 text-right" style={_td()}>
                      {(r.avg_pages_viewed ?? 0).toFixed(1)}
                    </td>
                    <td className="p-2 text-right" style={_td()}>
                      {_fmtMs(r.avg_session_duration_ms)}
                    </td>
                    <td className="p-2 text-right text-xs" style={_td()}>
                      {_fmtDate(r.last_event_at)}
                    </td>
                    <td className="p-2 text-right" style={_td()}>
                      <button
                        type="button"
                        onClick={() => setDrill(r.estimate_id)}
                        className="text-xs font-semibold rounded px-2 py-1"
                        style={{ background: colors.brandTertiary,
                                  color: colors.brand,
                                  border: `1px solid ${colors.brand}` }}
                        data-testid={`proposal-analytics-drill-${r.estimate_id}`}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {drill ? (
        <DrillDownModal
          estimateId={drill}
          onClose={() => setDrill(null)}
        />
      ) : null}
    </div>
  );
}


function _td() {
  return { borderBottom: `1px solid #eef2f7`, verticalAlign: "middle" };
}


function _sortVal(row, key) {
  if (key === "estimate_number") return (row.estimate?.estimate_number || "").toString();
  if (key === "title") return (row.estimate?.title || "").toString();
  if (key === "last_event_at") return String(row.last_event_at || "");
  const v = row[key];
  return typeof v === "number" ? v : Number(v || 0);
}


function _pickSorter(setKey, setDir, curKey, curDir) {
  return (nextKey) => {
    if (nextKey === curKey) {
      setDir(curDir === "asc" ? "desc" : "asc");
    } else {
      setKey(nextKey);
      setDir("desc");
    }
  };
}


function _Th({ children, col, sortKey, sortDir, onSort, align }) {
  const isActive = sortKey === col;
  return (
    <th
      className={`p-2 font-semibold cursor-pointer select-none ${align === "right" ? "text-right" : "text-left"}`}
      onClick={() => onSort(col)}
      style={{
        color: colors.onSurface,
        borderBottom: `1px solid ${colors.border}`,
        textTransform: "uppercase",
        fontSize: 11,
        letterSpacing: "0.03em",
      }}
    >
      {children}{" "}
      {isActive ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </th>
  );
}


// ─── Drill-down modal ─────────────────────────────────────────────
function DrillDownModal({ estimateId, onClose }) {
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setErr("");
      try {
        const [s, ev] = await Promise.all([
          api.get(`/analytics/proposal/${encodeURIComponent(estimateId)}/summary`),
          api.get(`/analytics/proposal/${encodeURIComponent(estimateId)}/events?limit=100`),
        ]);
        if (!alive) return;
        setSummary(s || null);
        setEvents(Array.isArray(ev?.events) ? ev.events : []);
      } catch (e) {
        if (!alive) return;
        setErr(e?.message || "Failed to load details.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [estimateId]);

  const pvBarData = useMemo(() => {
    if (!summary?.page_views_by_key) return [];
    return Object.entries(summary.page_views_by_key)
      .map(([k, v]) => ({ page: k, views: v }))
      .sort((a, b) => b.views - a.views);
  }, [summary]);

  const clickBarData = useMemo(() => {
    if (!summary?.clicks_by_button) return [];
    return Object.entries(summary.clicks_by_button)
      .map(([k, v]) => ({ button: k, clicks: v }))
      .sort((a, b) => b.clicks - a.clicks);
  }, [summary]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      data-testid="proposal-analytics-drilldown-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="bg-white rounded-2xl w-full max-w-3xl overflow-hidden shadow-2xl"
        style={{ maxHeight: "90vh", display: "flex", flexDirection: "column" }}
      >
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
              {summary?.estimate?.estimate_number
                || summary?.estimate?.title
                || estimateId.slice(0, 8).toUpperCase()}
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {summary?.estimate?.title || "Estimate analytics"}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1 hover:bg-slate-100"
            aria-label="Close"
            data-testid="proposal-analytics-drilldown-close"
          >
            <XIcon size={18} />
          </button>
        </div>

        <div className="p-4 overflow-y-auto space-y-4 flex-1">
          {loading ? (
            <div className="text-sm text-center py-6"
                  style={{ color: colors.muted }}
                  data-testid="proposal-analytics-drilldown-loading">
              Loading…
            </div>
          ) : err ? (
            <div className="text-sm p-2 rounded"
                  style={{ background: "#FEE2E2", color: "#991B1B" }}
                  data-testid="proposal-analytics-drilldown-error">
              {err}
            </div>
          ) : summary ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Tile testId="tile-opens" Icon={Eye}
                       label="Opens (sessions)"
                       value={`${summary.opens} · ${summary.unique_sessions}`} />
                <Tile testId="tile-clicks" Icon={MousePointerClick}
                       label="Clicks" value={String(summary.clicks)} />
                <Tile testId="tile-pages" Icon={LineIcon}
                       label="Avg pages"
                       value={(summary.avg_pages_viewed ?? 0).toFixed(1)} />
                <Tile testId="tile-time" Icon={Clock}
                       label="Avg session"
                       value={_fmtMs(summary.avg_session_duration_ms)} />
              </div>

              {pvBarData.length > 0 ? (
                <div className="rounded-lg border p-2"
                      style={{ borderColor: colors.border }}
                      data-testid="proposal-analytics-pv-chart">
                  <div className="text-xs font-semibold mb-1"
                        style={{ color: colors.muted }}>
                    Views per page
                  </div>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={pvBarData}>
                      <XAxis dataKey="page"
                             tick={{ fontSize: 10 }} />
                      <YAxis allowDecimals={false}
                             tick={{ fontSize: 10 }} width={30} />
                      <RTooltip />
                      <Bar dataKey="views" fill={colors.brand} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : null}

              {clickBarData.length > 0 ? (
                <div className="rounded-lg border p-2"
                      style={{ borderColor: colors.border }}
                      data-testid="proposal-analytics-click-chart">
                  <div className="text-xs font-semibold mb-1"
                        style={{ color: colors.muted }}>
                    Clicks by button
                  </div>
                  <ResponsiveContainer width="100%" height={140}>
                    <BarChart data={clickBarData}>
                      <XAxis dataKey="button"
                             tick={{ fontSize: 10 }} />
                      <YAxis allowDecimals={false}
                             tick={{ fontSize: 10 }} width={30} />
                      <RTooltip />
                      <Bar dataKey="clicks" fill="#16a34a" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : null}

              <div>
                <div className="text-xs font-semibold mb-1"
                      style={{ color: colors.muted }}>
                  Last {events.length} events
                </div>
                <div className="text-xs rounded border max-h-64 overflow-y-auto"
                      style={{ borderColor: colors.border }}
                      data-testid="proposal-analytics-events-timeline">
                  {events.length === 0 ? (
                    <div className="p-2" style={{ color: colors.muted }}>
                      No events yet.
                    </div>
                  ) : events.map((ev) => (
                    <div key={ev.id}
                          className="p-1.5 border-b last:border-b-0 flex items-center gap-2"
                          style={{ borderColor: "#eef2f7" }}>
                      <span className="text-[10px] px-1 rounded"
                            style={{
                              background: _colorForEvent(ev.event_type),
                              color: "#fff",
                              minWidth: 60, textAlign: "center",
                            }}>
                        {ev.event_type}
                      </span>
                      <span className="flex-1">
                        {ev.button_id
                          ? `button: ${ev.button_id}`
                          : ev.page_key
                            ? `page: ${ev.page_key}${
                              ev.duration_ms ? ` · ${_fmtMs(ev.duration_ms)}` : ""
                            }`
                            : ""}
                      </span>
                      <span className="text-[10px]"
                            style={{ color: colors.muted, minWidth: 90,
                                      textAlign: "right" }}>
                        {_fmtDate(ev.created_at)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}


function Tile({ Icon, label, value, testId }) {
  return (
    <div className="rounded-lg border p-2"
          style={{ borderColor: colors.border,
                    background: colors.surfaceSecondary }}
          data-testid={`proposal-analytics-${testId}`}>
      <div className="flex items-center gap-1"
            style={{ color: colors.muted }}>
        <Icon size={12} />
        <span className="text-[10px] uppercase tracking-wide font-semibold">
          {label}
        </span>
      </div>
      <div className="text-lg font-bold mt-0.5"
            style={{ color: colors.onSurface }}>
        {value}
      </div>
    </div>
  );
}


function _colorForEvent(type) {
  switch (type) {
    case "open":      return "#0891B2";
    case "page_view": return "#0f172a";
    case "click":     return "#16a34a";
    case "close":     return "#94a3b8";
    default:          return "#64748b";
  }
}
