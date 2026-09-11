/**
 * Feb-2026 · Reports Gap Fill Phase 5a.2 — Recurring vs. Project Revenue.
 * Route: /reports/recurring-vs-project-revenue (AdminOnly).
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { RefreshCw, PieChart, DollarSign, Activity } from "lucide-react";

const _money = (v) => {
  if (v === null || v === undefined) return "—";
  const n = typeof v === "number" ? v : parseFloat(v);
  if (Number.isNaN(n)) return "—";
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};
const _n = (v) => (v === null || v === undefined ? "—"
  : typeof v === "number" ? v.toLocaleString() : String(v));
function _csv(d) {
  const rows = [
    ["month", "recurring_amount", "project_amount", "total"],
    ...(d.rows || []).map((r) => [
      r.month || "", r.recurring_amount ?? "",
      r.project_amount ?? "", r.total ?? "",
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

export default function RecurringVsProjectReport() {
  const { start, end } = useDateRange("this-month");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    if (!start || !end) return;
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/recurring-vs-project-revenue?start_date=${encodeURIComponent(start)}` +
        `&end_date=${encodeURIComponent(end)}`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load report";
      setState({ loading: false, error: msg });
      try { toast({ title: "Recurring vs Project failed",
              description: msg, variant: "destructive" }); } catch {}
    }
  }, [start, end]);
  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const donut = (d.chart || {}).donut || { recurring: 0, project: 0 };
  const trailing = (d.chart || {}).trailing_12mo || [];
  const chart = useMemo(() => {
    if (!trailing.length) return null;
    const maxY = Math.max(1, ...trailing.map(
      (r) => (Number(r.recurring_amount) || 0) + (Number(r.project_amount) || 0)));
    const w = 640, h = 140, pad = 16;
    const step = trailing.length > 1 ? (w - pad * 2) / (trailing.length - 1) : 0;
    const rec = trailing.map((r, i) => {
      const y = h - pad - ((Number(r.recurring_amount) || 0) / maxY) * (h - pad * 2);
      return `${pad + i * step},${y}`;
    }).join(" ");
    const proj = trailing.map((r, i) => {
      const y = h - pad - ((Number(r.project_amount) || 0) / maxY) * (h - pad * 2);
      return `${pad + i * step},${y}`;
    }).join(" ");
    return { w, h, rec, proj, months: trailing.map((r) => r.month) };
  }, [trailing]);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="rvp-report-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="rvp-report-title">Recurring vs. Project Revenue</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}
             data-testid="rvp-report-subtitle">
            Splits paid revenue using the same predicate as the admin
            dashboard: title keywords (weekly / monthly / recurring).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePicker />
          <button type="button"
            onClick={() => _download(
              `recurring-vs-project-${start}-to-${end}.csv`, _csv(d))}
            disabled={state.loading || !!state.error}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="rvp-report-csv-btn">Export CSV</button>
        </div>
      </div>
      {state.error ? (
        <div className="rounded-xl p-6 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                      color: "#7F1D1D" }}
             data-testid="rvp-report-error">
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
               data-testid="rvp-report-tiles">
            <Tile icon={DollarSign} testid="tile-total-revenue"
              label="Total" primary={state.loading ? "…" : _money(s.total_revenue)}
              secondary="Paid in window" />
            <Tile icon={RefreshCw} testid="tile-recurring"
              label="Recurring" primary={state.loading ? "…" : _money(s.recurring_amount)}
              secondary={`${_n(s.recurring_pct)}% of total`} />
            <Tile icon={PieChart} testid="tile-project"
              label="Project" primary={state.loading ? "…" : _money(s.project_amount)}
              secondary="Everything else" />
            <Tile icon={Activity} testid="tile-recurring-pct"
              label="Recurring %" primary={state.loading ? "…" : `${_n(s.recurring_pct)}%`}
              secondary="Of paid revenue" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div className="rounded-2xl p-5"
                 style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                 data-testid="rvp-report-donut">
              <div className="text-sm font-semibold mb-3"
                   style={{ color: colors.onSurface }}>In-window split</div>
              <DonutLite recurring={donut.recurring} project={donut.project} />
            </div>
            <div className="rounded-2xl p-5"
                 style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                 data-testid="rvp-report-trailing">
              <div className="text-sm font-semibold mb-3"
                   style={{ color: colors.onSurface }}>
                Trailing 12 months
              </div>
              {!chart ? (
                <div className="text-xs" style={{ color: colors.muted }}
                     data-testid="rvp-report-trailing-empty">
                  No paid invoices in the trailing 12mo.
                </div>
              ) : (
                <svg viewBox={`0 0 ${chart.w} ${chart.h}`}
                     className="w-full" role="img"
                     data-testid="rvp-report-trailing-svg">
                  <polyline points={chart.rec} fill="none"
                            stroke={colors.brand || "#1B1F5C"} strokeWidth="2" />
                  <polyline points={chart.proj} fill="none"
                            stroke="#15803D" strokeWidth="2" strokeDasharray="4 3" />
                </svg>
              )}
            </div>
          </div>
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="rvp-report-table">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Month</Th><Th>Recurring</Th><Th>Project</Th><Th>Total</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !state.loading ? (
                  <tr><td colSpan={4} className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="rvp-report-table-empty">
                    No data in this window.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.month} data-testid={`rvp-row-${r.month}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td>{r.month}</Td>
                    <Td>{_money(r.recurring_amount)}</Td>
                    <Td>{_money(r.project_amount)}</Td>
                    <Td>{_money(r.total)}</Td>
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

function DonutLite({ recurring = 0, project = 0 }) {
  const total = (Number(recurring) || 0) + (Number(project) || 0);
  const pct = total > 0 ? (Number(recurring) / total) * 100 : 0;
  const c = 2 * Math.PI * 40;  // circumference for r=40
  const rec = (pct / 100) * c;
  return (
    <div className="flex items-center gap-4">
      <svg width="120" height="120" viewBox="0 0 120 120"
           data-testid="rvp-donut-svg">
        <circle cx="60" cy="60" r="40" fill="none"
                stroke={colors.surfaceSecondary || "#E5E7EB"} strokeWidth="16" />
        <circle cx="60" cy="60" r="40" fill="none"
                stroke={colors.brand || "#1B1F5C"} strokeWidth="16"
                strokeDasharray={`${rec} ${c - rec}`}
                strokeDashoffset={c / 4} />
      </svg>
      <div className="text-xs">
        <div style={{ color: colors.onSurface }}>
          <b>Recurring:</b> ${Number(recurring).toLocaleString()}
        </div>
        <div style={{ color: colors.onSurface }} className="mt-1">
          <b>Project:</b> ${Number(project).toLocaleString()}
        </div>
      </div>
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
