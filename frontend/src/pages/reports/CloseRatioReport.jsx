/**
 * Feb-2026 · Reports Gap Fill Phase 5b.1 — Close Ratio.
 * Route: /reports/close-ratio (AdminOnly).
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { Target, TrendingUp, CheckCircle2, XCircle } from "lucide-react";

const _n = (v) => (v === null || v === undefined ? "—"
  : typeof v === "number" ? v.toLocaleString() : String(v));

function _csv(d) {
  const rows = [
    ["month", "leads_created", "closed_won", "closed_lost", "close_ratio_pct"],
    ...(d.rows || []).map((r) => [
      r.month || "", r.leads_created ?? "",
      r.closed_won ?? "", r.closed_lost ?? "", r.close_ratio_pct ?? "",
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

export default function CloseRatioReport() {
  const { start, end } = useDateRange("last-90-days");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    if (!start || !end) return;
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/close-ratio?start_date=${encodeURIComponent(start)}` +
        `&end_date=${encodeURIComponent(end)}`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Close Ratio";
      setState({ loading: false, error: msg });
      try { toast({ title: "Close Ratio failed", description: msg,
                      variant: "destructive" }); } catch {}
    }
  }, [start, end]);
  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const chartData = (d.chart || {}).monthly_close_ratio || [];
  const chart = useMemo(() => {
    if (!chartData.length) return null;
    const w = 640, h = 140, pad = 16;
    const step = chartData.length > 1 ? (w - pad * 2) / (chartData.length - 1) : 0;
    const pts = chartData.map((r, i) => {
      const v = Number(r.close_ratio_pct) || 0;
      const y = h - pad - ((v / 100) * (h - pad * 2));
      return { x: pad + i * step, y, v, month: r.month };
    });
    return { w, h, pts, polyline: pts.map((p) => `${p.x},${p.y}`).join(" ") };
  }, [chartData]);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="cr-report-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="cr-report-title">Close Ratio</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}
             data-testid="cr-report-subtitle">
            Won / (Won + Lost) for leads created in the window. Open
            leads are excluded from the denominator.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePicker defaultPreset="last-90-days" />
          <button type="button"
            onClick={() => _download(
              `close-ratio-${start}-to-${end}.csv`, _csv(d))}
            disabled={state.loading || !!state.error}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="cr-report-csv-btn">Export CSV</button>
        </div>
      </div>
      {state.error ? (
        <div className="rounded-xl p-6 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                      color: "#7F1D1D" }}
             data-testid="cr-report-error">
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
               data-testid="cr-report-tiles">
            <Tile icon={Target} testid="tile-close-ratio"
              label="Close Ratio" primary={state.loading ? "…" : `${_n(s.close_ratio_pct)}%`}
              secondary="Won / (Won + Lost)" />
            <Tile icon={TrendingUp} testid="tile-leads-created"
              label="Leads Created" primary={state.loading ? "…" : _n(s.leads_created)}
              secondary="In window" />
            <Tile icon={CheckCircle2} testid="tile-won"
              label="Won" primary={state.loading ? "…" : _n(s.leads_closed_won)}
              secondary="Closed won" />
            <Tile icon={XCircle} testid="tile-lost"
              label="Lost" primary={state.loading ? "…" : _n(s.leads_closed_lost)}
              secondary="Closed lost" />
          </div>
          <div className="rounded-2xl p-5 mb-6"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="cr-report-chart">
            <div className="text-sm font-semibold mb-3"
                 style={{ color: colors.onSurface }}>
              Monthly close ratio
            </div>
            {!chart ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="cr-report-chart-empty">
                No leads in this window.
              </div>
            ) : (
              <svg viewBox={`0 0 ${chart.w} ${chart.h}`}
                   className="w-full" role="img"
                   data-testid="cr-report-chart-svg">
                <polyline points={chart.polyline} fill="none"
                          stroke={colors.brand || "#1B1F5C"} strokeWidth="2" />
                {chart.pts.map((p) => (
                  <g key={p.month} data-testid={`cr-chart-point-${p.month}`}>
                    <circle cx={p.x} cy={p.y} r="3"
                            fill={colors.brand || "#1B1F5C"} />
                    <title>{`${p.month} · ${p.v}%`}</title>
                  </g>
                ))}
              </svg>
            )}
          </div>
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="cr-report-table">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Month</Th><Th>Leads</Th><Th>Won</Th><Th>Lost</Th><Th>Ratio</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !state.loading ? (
                  <tr><td colSpan={5} className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="cr-report-table-empty">
                    No leads in this window.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.month} data-testid={`cr-row-${r.month}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td>{r.month}</Td>
                    <Td>{_n(r.leads_created)}</Td>
                    <Td>{_n(r.closed_won)}</Td>
                    <Td>{_n(r.closed_lost)}</Td>
                    <Td>{_n(r.close_ratio_pct)}%</Td>
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
