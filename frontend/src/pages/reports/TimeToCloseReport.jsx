/**
 * Feb-2026 · Reports Gap Fill Phase 5b.1 — Time to Close.
 * Route: /reports/time-to-close (AdminOnly).
 * Uses ``Hourglass`` icon to visually distinguish from Time to
 * Get Paid (``Clock``) in the reports hub.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { Hourglass, BarChart3, Activity, FileText } from "lucide-react";

const _n = (v) => (v === null || v === undefined ? "—"
  : typeof v === "number" ? v.toLocaleString() : String(v));
const _shortDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
};

function _csv(d) {
  const rows = [
    ["lead_id", "customer_id", "customer_name",
     "created_at", "closed_at", "days_to_close", "outcome"],
    ...(d.rows || []).map((r) => [
      r.lead_id || "", r.customer_id || "", r.customer_name || "",
      r.created_at || "", r.closed_at || "",
      r.days_to_close ?? "", r.outcome || "",
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

export default function TimeToCloseReport() {
  const { start, end } = useDateRange("last-90-days");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    if (!start || !end) return;
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/time-to-close?start_date=${encodeURIComponent(start)}` +
        `&end_date=${encodeURIComponent(end)}`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Time to Close";
      setState({ loading: false, error: msg });
      try { toast({ title: "Time to Close failed", description: msg,
                      variant: "destructive" }); } catch {}
    }
  }, [start, end]);
  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const chartData = (d.chart || {}).monthly_avg_days || [];
  const chart = useMemo(() => {
    if (!chartData.length) return null;
    const maxY = Math.max(1, ...chartData.map((r) => Number(r.avg_days) || 0));
    const w = 640, h = 140, pad = 16;
    const step = chartData.length > 1 ? (w - pad * 2) / (chartData.length - 1) : 0;
    const pts = chartData.map((r, i) => {
      const v = Number(r.avg_days) || 0;
      const y = h - pad - ((v / maxY) * (h - pad * 2));
      return { x: pad + i * step, y, v, month: r.month };
    });
    return { w, h, pts, polyline: pts.map((p) => `${p.x},${p.y}`).join(" ") };
  }, [chartData]);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="ttc-report-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="ttc-report-title">Time to Close</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}
             data-testid="ttc-report-subtitle">
            Days from lead created to close outcome (won or lost).
            Summary reflects the window; chart is a rolling
            trailing-12-month view.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePicker defaultPreset="last-90-days" />
          <button type="button"
            onClick={() => _download(
              `time-to-close-${start}-to-${end}.csv`, _csv(d))}
            disabled={state.loading || !!state.error}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="ttc-report-csv-btn">Export CSV</button>
        </div>
      </div>
      {state.error ? (
        <div className="rounded-xl p-6 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                      color: "#7F1D1D" }}
             data-testid="ttc-report-error">
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
               data-testid="ttc-report-tiles">
            <Tile icon={Hourglass} testid="tile-avg-days"
              label="Avg Days" primary={state.loading ? "…" : _n(s.avg_days_to_close)}
              secondary="To close" />
            <Tile icon={Activity} testid="tile-p50"
              label="Median (p50)" primary={state.loading ? "…" : _n(s.p50_days)}
              secondary="50th percentile" />
            <Tile icon={BarChart3} testid="tile-p90"
              label="p90" primary={state.loading ? "…" : _n(s.p90_days)}
              secondary="90th percentile" />
            <Tile icon={FileText} testid="tile-lead-count"
              label="Leads" primary={state.loading ? "…" : _n(s.leads_counted)}
              secondary="Counted in window" />
          </div>
          <div className="rounded-2xl p-5 mb-6"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="ttc-report-chart">
            <div className="text-sm font-semibold mb-3"
                 style={{ color: colors.onSurface }}>
              Trailing 12 months · monthly avg days to close
            </div>
            {!chart ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="ttc-report-chart-empty">
                No closed leads in the trailing 12-month window.
              </div>
            ) : (
              <svg viewBox={`0 0 ${chart.w} ${chart.h}`}
                   className="w-full" role="img"
                   data-testid="ttc-report-chart-svg">
                <polyline points={chart.polyline} fill="none"
                          stroke={colors.brand || "#1B1F5C"} strokeWidth="2" />
                {chart.pts.map((p) => (
                  <g key={p.month} data-testid={`ttc-chart-point-${p.month}`}>
                    <circle cx={p.x} cy={p.y} r="3"
                            fill={colors.brand || "#1B1F5C"} />
                    <title>{`${p.month} · avg ${p.v}d`}</title>
                  </g>
                ))}
              </svg>
            )}
          </div>
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="ttc-report-table">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Lead</Th><Th>Customer</Th>
                  <Th>Created</Th><Th>Closed</Th>
                  <Th>Days</Th><Th>Outcome</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !state.loading ? (
                  <tr><td colSpan={6} className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="ttc-report-table-empty">
                    No closed leads in this window.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.lead_id} data-testid={`ttc-row-${r.lead_id}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td>{(r.lead_id || "").slice(0, 8)}…</Td>
                    <Td>{r.customer_name || "—"}</Td>
                    <Td>{_shortDate(r.created_at)}</Td>
                    <Td>{_shortDate(r.closed_at)}</Td>
                    <Td>{_n(r.days_to_close)}</Td>
                    <Td>{r.outcome || "—"}</Td>
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
