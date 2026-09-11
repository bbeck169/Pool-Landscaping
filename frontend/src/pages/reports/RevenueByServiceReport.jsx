/**
 * Feb-2026 · Reports Gap Fill Phase 5a.2 — Revenue by Service.
 * Route: /reports/revenue-by-service (AdminOnly).
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { Wrench, DollarSign, Package } from "lucide-react";

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
    ["service_name", "service_id", "billed_amount",
     "collected_amount", "job_count", "avg_ticket"],
    ...(d.rows || []).map((r) => [
      r.service_name || "", r.service_id || "",
      r.billed_amount ?? "", r.collected_amount ?? "",
      r.job_count ?? "", r.avg_ticket ?? "",
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

export default function RevenueByServiceReport() {
  const { start, end } = useDateRange("this-month");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    if (!start || !end) return;
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/revenue-by-service?start_date=${encodeURIComponent(start)}` +
        `&end_date=${encodeURIComponent(end)}`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Revenue by Service";
      setState({ loading: false, error: msg });
      try { toast({ title: "Revenue by Service failed",
              description: msg, variant: "destructive" }); } catch {}
    }
  }, [start, end]);
  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const top = (d.chart || {}).top_services || [];
  const total = top.reduce((a, r) => a + (Number(r.billed_amount) || 0), 0) || 1;

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="rbs-report-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="rbs-report-title">Revenue by Service</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}
             data-testid="rbs-report-subtitle">
            Billed and collected revenue pivoted by invoice service
            (title). Mirrors the Revenue by Customer join pattern.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePicker />
          <button type="button"
            onClick={() => _download(
              `revenue-by-service-${start}-to-${end}.csv`, _csv(d))}
            disabled={state.loading || !!state.error}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="rbs-report-csv-btn">Export CSV</button>
        </div>
      </div>
      {state.error ? (
        <div className="rounded-xl p-6 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                      color: "#7F1D1D" }}
             data-testid="rbs-report-error">
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6"
               data-testid="rbs-report-tiles">
            <Tile icon={DollarSign} testid="tile-total-billed"
              label="Total Billed"
              primary={state.loading ? "…" : _money(s.total_billed)}
              secondary="All invoices in window" />
            <Tile icon={Package} testid="tile-total-collected"
              label="Total Collected"
              primary={state.loading ? "…" : _money(s.total_collected)}
              secondary="Paid only" />
            <Tile icon={Wrench} testid="tile-top-service"
              label="Top Service"
              primary={state.loading ? "…" : (s.top_service_by_revenue?.name || "—")}
              secondary={_money(s.top_service_by_revenue?.amount)} />
          </div>
          <div className="rounded-2xl p-5 mb-6"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="rbs-report-chart">
            <div className="text-sm font-semibold mb-3"
                 style={{ color: colors.onSurface }}>
              Top services (by billed)
            </div>
            {top.length === 0 && !state.loading ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="rbs-report-chart-empty">
                No revenue in this window.
              </div>
            ) : (
              <div className="space-y-2" data-testid="rbs-report-chart-bars">
                {top.map((r) => (
                  <div key={r.service_name} className="flex items-center gap-3"
                       data-testid={`rbs-bar-${r.service_name}`}>
                    <div className="text-xs w-48 truncate"
                         style={{ color: colors.onSurface }}
                         title={r.service_name}>{r.service_name}</div>
                    <div className="flex-1 h-4 rounded-md"
                         style={{ background: colors.surfaceSecondary }}>
                      <div className="h-4 rounded-md"
                           style={{ width: `${(r.billed_amount / total) * 100}%`,
                                    background: colors.brand || "#1B1F5C" }} />
                    </div>
                    <div className="text-xs font-semibold w-24 text-right"
                         style={{ color: colors.onSurface }}>
                      {_money(r.billed_amount)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="rbs-report-table">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Service</Th><Th>Billed</Th><Th>Collected</Th>
                  <Th>Jobs</Th><Th>Avg Ticket</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !state.loading ? (
                  <tr><td colSpan={5} className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="rbs-report-table-empty">
                    No services in this window.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.service_id}
                      data-testid={`rbs-row-${r.service_id}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td>{r.service_name}</Td>
                    <Td>{_money(r.billed_amount)}</Td>
                    <Td>{_money(r.collected_amount)}</Td>
                    <Td>{_n(r.job_count)}</Td>
                    <Td>{_money(r.avg_ticket)}</Td>
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
      <div className="text-2xl font-bold truncate" data-testid={`${testid}-primary`}
           title={typeof primary === "string" ? primary : ""}>{primary}</div>
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
