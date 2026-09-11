/**
 * Feb-2026 · Reports Gap Fill Phase 5b.2 — Booked Out / Capacity.
 * Route: /reports/booked-out-capacity (AdminOnly).
 * NO date range filter — forward-looking N-week rolling view.
 * Capacity line is Business Snapshot's ``bh_per_week_capacity``.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import { CalendarClock, Calendar, Activity, CheckSquare } from "lucide-react";

const _n = (v) => (v === null || v === undefined ? "—"
  : typeof v === "number" ? v.toLocaleString() : String(v));

function _csv(d) {
  const rows = [
    ["week_start", "week_end", "booked_hours", "capacity_hours",
     "utilization_pct", "jobs_count"],
    ...(d.rows || []).map((r) => [
      r.week_start || "", r.week_end || "",
      r.booked_hours ?? "", r.capacity_hours ?? "",
      r.utilization_pct ?? "", r.jobs_count ?? "",
    ]),
  ];
  return rows.map((r) => r.map((c) => {
    const s = String(c ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",")).join("\n");
}
function _download(name, text) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const _QUICK_PICKS = [4, 8, 12, 24];

export default function BookedOutCapacityReport() {
  const [weeksAhead, setWeeksAhead] = useState(8);
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/booked-out-capacity?weeks_ahead=${weeksAhead}`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Booked Out / Capacity";
      setState({ loading: false, error: msg });
      try { toast({ title: "Booked Out / Capacity failed",
              description: msg, variant: "destructive" }); } catch {}
    }
  }, [weeksAhead]);
  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const bars = (d.chart || {}).weekly_bookings || [];

  // Bar chart geometry — bars are booked hours; horizontal line
  // at ``capacity_hours`` marks capacity. Y is normalized to
  // max(capacity, max_booked) so the capacity line stays inside
  // the viewbox even when a week over-books.
  const chart = useMemo(() => {
    if (!bars.length) return null;
    const cap = Number(s.weekly_capacity_hours) || 0;
    const maxBooked = Math.max(0, ...bars.map((b) => Number(b.booked_hours) || 0));
    const maxY = Math.max(1, cap, maxBooked);
    const w = 640, h = 180, pad = 20;
    const barW = (w - pad * 2) / bars.length * 0.7;
    const step = (w - pad * 2) / bars.length;
    const capY = h - pad - ((cap / maxY) * (h - pad * 2));
    const rects = bars.map((b, i) => {
      const bh = Number(b.booked_hours) || 0;
      const barH = (bh / maxY) * (h - pad * 2);
      const x = pad + i * step + (step - barW) / 2;
      const y = h - pad - barH;
      return { x, y, w: barW, h: barH, bh, label: b.week_label };
    });
    return { w, h, capY, cap, rects };
  }, [bars, s.weekly_capacity_hours]);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="boc-report-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="boc-report-title">Booked Out / Capacity</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}
             data-testid="boc-report-subtitle">
            Rolling forward-looking view. Capacity line reuses
            Business Snapshot's ``bh_per_week_capacity`` so both
            surfaces show the same number.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1"
               data-testid="boc-weeks-picker">
            {_QUICK_PICKS.map((n) => (
              <button key={n} type="button"
                onClick={() => setWeeksAhead(n)}
                className="px-2 py-1 rounded text-xs border transition"
                style={{ background: weeksAhead === n
                             ? (colors.brand || "#1B1F5C")
                             : "#FFFFFF",
                         color:      weeksAhead === n
                             ? "#FFFFFF" : colors.onSurface,
                         borderColor: colors.border }}
                data-testid={`boc-weeks-${n}`}>{n}w</button>
            ))}
          </div>
          <button type="button"
            onClick={() => _download(
              `booked-out-capacity-${weeksAhead}w.csv`, _csv(d))}
            disabled={state.loading || !!state.error}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="boc-report-csv-btn">Export CSV</button>
        </div>
      </div>
      {state.error ? (
        <div className="rounded-xl p-6 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                      color: "#7F1D1D" }}
             data-testid="boc-report-error">
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
               data-testid="boc-report-tiles">
            <Tile icon={Calendar} testid="tile-capacity"
              label="Weekly Capacity"
              primary={state.loading ? "…" : `${_n(s.weekly_capacity_hours)}h`}
              secondary="From Biz Snapshot" />
            <Tile icon={Activity} testid="tile-booked"
              label="Total Booked"
              primary={state.loading ? "…" : `${_n(s.total_booked_hours)}h`}
              secondary={`Across ${weeksAhead} wks`} />
            <Tile icon={CalendarClock} testid="tile-util"
              label="Avg Utilization"
              primary={state.loading ? "…" : `${_n(s.avg_weekly_utilization_pct)}%`}
              secondary="Per week avg" />
            <Tile icon={CheckSquare} testid="tile-first-available"
              label="First Available"
              primary={state.loading ? "…" : (s.first_available_week || "None")}
              secondary="Below 80% util" />
          </div>
          <div className="rounded-2xl p-5 mb-6"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="boc-report-chart">
            <div className="text-sm font-semibold mb-3"
                 style={{ color: colors.onSurface }}>
              Weekly bookings vs. capacity
            </div>
            {!chart ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="boc-report-chart-empty">
                No forward-looking schedule yet.
              </div>
            ) : (
              <svg viewBox={`0 0 ${chart.w} ${chart.h}`}
                   className="w-full" role="img"
                   data-testid="boc-report-chart-svg">
                {chart.rects.map((r) => (
                  <g key={r.label} data-testid={`boc-bar-${r.label.replace(/\s+/g, "-")}`}>
                    <rect x={r.x} y={r.y} width={r.w} height={r.h}
                          fill={colors.brand || "#1B1F5C"} />
                    <title>{`${r.label}: ${r.bh}h`}</title>
                  </g>
                ))}
                <line x1="20" x2={chart.w - 20} y1={chart.capY} y2={chart.capY}
                      stroke="#DC2626" strokeWidth="2" strokeDasharray="5 3"
                      data-testid="boc-capacity-line" />
              </svg>
            )}
          </div>
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="boc-report-table">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Week Start</Th><Th>Week End</Th>
                  <Th>Booked</Th><Th>Capacity</Th>
                  <Th>Utilization</Th><Th>Jobs</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !state.loading ? (
                  <tr><td colSpan={6} className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="boc-report-table-empty">
                    No weeks in the window.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.week_start} data-testid={`boc-row-${r.week_start}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td>{r.week_start}</Td>
                    <Td>{r.week_end}</Td>
                    <Td>{_n(r.booked_hours)}h</Td>
                    <Td>{_n(r.capacity_hours)}h</Td>
                    <Td>{_n(r.utilization_pct)}%</Td>
                    <Td>{_n(r.jobs_count)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ icon: Icon, testid, label, primary, secondary }) {
  return (
    <div className="rounded-2xl p-5 flex flex-col gap-3"
         style={{ backgroundColor: colors.tile?.solidNavy || "#1B1F5C",
                  border: `1px solid ${colors.border}`, color: "#FFFFFF" }}
         data-testid={testid}>
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
             style={{ backgroundColor: "rgba(255,255,255,0.18)" }}>
          <Icon size={20} />
        </div>
        <div className="text-sm font-semibold opacity-90">{label}</div>
      </div>
      <div className="text-2xl font-bold truncate" data-testid={`${testid}-primary`}>{primary}</div>
      <div className="text-xs opacity-80" data-testid={`${testid}-secondary`}>{secondary}</div>
    </div>
  );
}
function Th({ children }) {
  return <th className="text-left px-4 py-2 text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.muted }}>{children}</th>;
}
function Td({ children }) {
  return <td className="px-4 py-2" style={{ color: colors.onSurface }}>{children}</td>;
}
