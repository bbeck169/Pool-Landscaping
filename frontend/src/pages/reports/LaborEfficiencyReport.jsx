/**
 * Feb-2026 · Reports Gap Fill Phase 5b.2 — Labor Efficiency.
 * Route: /reports/labor-efficiency (AdminOnly).
 * Rows sorted asc (worst-first, actionable ops view).
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { Gauge, TrendingUp, Activity, FileText } from "lucide-react";

const _n = (v) => (v === null || v === undefined ? "—"
  : typeof v === "number" ? v.toLocaleString() : String(v));
const _shortDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
};

function _csv(d) {
  const rows = [
    ["job_id", "customer_id", "customer_name", "service_date",
     "budgeted_hours", "actual_hours", "efficiency_pct",
     "technician_id", "technician_name"],
    ...(d.rows || []).map((r) => [
      r.job_id || "", r.customer_id || "", r.customer_name || "",
      r.service_date || "", r.budgeted_hours ?? "",
      r.actual_hours ?? "", r.efficiency_pct ?? "",
      r.technician_id || "", r.technician_name || "",
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

export default function LaborEfficiencyReport() {
  const { start, end } = useDateRange("this-month");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    if (!start || !end) return;
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/labor-efficiency?start_date=${encodeURIComponent(start)}` +
        `&end_date=${encodeURIComponent(end)}`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Labor Efficiency";
      setState({ loading: false, error: msg });
      try { toast({ title: "Labor Efficiency failed",
              description: msg, variant: "destructive" }); } catch {}
    }
  }, [start, end]);
  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const chartData = (d.chart || {}).monthly_efficiency || [];
  const chart = useMemo(() => {
    if (!chartData.length) return null;
    const maxY = Math.max(100, ...chartData.map((r) => Number(r.efficiency_pct) || 0));
    const w = 640, h = 140, pad = 16;
    const step = chartData.length > 1 ? (w - pad * 2) / (chartData.length - 1) : 0;
    const pts = chartData.map((r, i) => {
      const v = Number(r.efficiency_pct) || 0;
      const y = h - pad - ((v / maxY) * (h - pad * 2));
      return { x: pad + i * step, y, v, month: r.month };
    });
    return { w, h, pts, polyline: pts.map((p) => `${p.x},${p.y}`).join(" ") };
  }, [chartData]);
  const insufficient = !state.loading && rows.length === 0;

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="le-report-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="le-report-title">Labor Efficiency</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}
             data-testid="le-report-subtitle">
            Budgeted vs. actual hours per job. Rows are sorted
            worst-first — the top of the table is where ops
            attention pays off.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePicker />
          <button type="button"
            onClick={() => _download(
              `labor-efficiency-${start}-to-${end}.csv`, _csv(d))}
            disabled={state.loading || !!state.error}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="le-report-csv-btn">Export CSV</button>
        </div>
      </div>
      {state.error ? (
        <div className="rounded-xl p-6 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                      color: "#7F1D1D" }}
             data-testid="le-report-error">
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
               data-testid="le-report-tiles">
            <Tile icon={Gauge} testid="tile-eff-pct"
              label="Efficiency" primary={state.loading ? "…" : `${_n(s.labor_efficiency_pct)}%`}
              secondary="Budget / Actual" />
            <Tile icon={TrendingUp} testid="tile-budgeted"
              label="Budgeted" primary={state.loading ? "…" : `${_n(s.budgeted_hours)}h`}
              secondary="Total in window" />
            <Tile icon={Activity} testid="tile-actual"
              label="Actual" primary={state.loading ? "…" : `${_n(s.actual_hours)}h`}
              secondary="Time logged" />
            <Tile icon={FileText} testid="tile-jobs"
              label="Jobs" primary={state.loading ? "…" : _n(s.jobs_counted)}
              secondary="Counted rows" />
          </div>
          {insufficient ? (
            <div className="rounded-2xl p-6 mb-6 text-sm"
                 style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.muted }}
                 data-testid="le-report-insufficient">
              Insufficient data: jobs in this window don't carry
              both budgeted and actual hours. Log time on completed
              jobs and re-run the report.
            </div>
          ) : (
            <>
              <div className="rounded-2xl p-5 mb-6"
                   style={{ background: colors.surface,
                            border: `1px solid ${colors.border}` }}
                   data-testid="le-report-chart">
                <div className="text-sm font-semibold mb-3"
                     style={{ color: colors.onSurface }}>
                  Monthly efficiency
                </div>
                {!chart ? (
                  <div className="text-xs" style={{ color: colors.muted }}
                       data-testid="le-report-chart-empty">
                    No monthly data.
                  </div>
                ) : (
                  <svg viewBox={`0 0 ${chart.w} ${chart.h}`}
                       className="w-full" role="img"
                       data-testid="le-report-chart-svg">
                    <polyline points={chart.polyline} fill="none"
                              stroke={colors.brand || "#1B1F5C"} strokeWidth="2" />
                    {chart.pts.map((p) => (
                      <g key={p.month} data-testid={`le-chart-point-${p.month}`}>
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
                   data-testid="le-report-table">
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ background: colors.surfaceSecondary }}>
                      <Th>Job</Th><Th>Customer</Th><Th>Date</Th>
                      <Th>Bgt</Th><Th>Act</Th><Th>Eff</Th><Th>Tech</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.job_id} data-testid={`le-row-${r.job_id}`}
                          style={{ borderTop: `1px solid ${colors.border}` }}>
                        <Td>{(r.job_id || "").slice(0, 8)}…</Td>
                        <Td>{r.customer_name}</Td>
                        <Td>{_shortDate(r.service_date)}</Td>
                        <Td>{_n(r.budgeted_hours)}h</Td>
                        <Td>{_n(r.actual_hours)}h</Td>
                        <Td>{_n(r.efficiency_pct)}%</Td>
                        <Td>{r.technician_name}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
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
