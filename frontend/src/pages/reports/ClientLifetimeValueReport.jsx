/**
 * Feb-2026 · Reports Gap Fill Phase 5a.2 — Client Lifetime Value.
 * Route: /reports/client-lifetime-value (AdminOnly).
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { TrendingUp, Users, DollarSign, Award } from "lucide-react";
import { CustomerLink } from "@/components/customer";

const _money = (v) => {
  if (v === null || v === undefined) return "—";
  const n = typeof v === "number" ? v : parseFloat(v);
  if (Number.isNaN(n)) return "—";
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};
const _n = (v) => (v === null || v === undefined ? "—"
  : typeof v === "number" ? v.toLocaleString() : String(v));
const _shortDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
};

function _csv(d) {
  const rows = [
    ["customer_id", "customer_name", "first_service_date",
     "last_service_date", "total_billed", "total_collected",
     "is_active", "client_type"],
    ...(d.rows || []).map((r) => [
      r.customer_id || "", r.customer_name || "",
      r.first_service_date || "", r.last_service_date || "",
      r.total_billed ?? "", r.total_collected ?? "",
      r.is_active ? "true" : "false", r.client_type || "",
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

export default function ClientLifetimeValueReport() {
  // LTV is all-time by default (both undefined = null). If the URL
  // carries a range, we forward it. `useDateRange` returns preset
  // defaults, so we detect "no range in URL" via a params probe.
  const { start, end } = useDateRange("this-month");
  const [state, setState] = useState({ loading: true });
  const [allTime, setAllTime] = useState(true);

  const load = useCallback(async () => {
    setState({ loading: true });
    try {
      let qs = "";
      if (!allTime && start && end) {
        qs = `?start_date=${encodeURIComponent(start)}` +
             `&end_date=${encodeURIComponent(end)}`;
      }
      const res = await api.get(`/reports/client-lifetime-value${qs}`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load CLV report";
      setState({ loading: false, error: msg });
      try { toast({ title: "Client Lifetime Value failed",
              description: msg, variant: "destructive" }); } catch {}
    }
  }, [start, end, allTime]);
  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const buckets = (d.chart || {}).ltv_buckets || [];
  const maxBucket = useMemo(
    () => Math.max(1, ...buckets.map((b) => Number(b.count) || 0)),
    [buckets],
  );

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="clv-report-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="clv-report-title">Client Lifetime Value</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}
             data-testid="clv-report-subtitle">
            Per-customer billed / collected aggregate, LTV histogram,
            and cohort averages (recurring vs. project).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs flex items-center gap-1"
                 style={{ color: colors.onSurface }}
                 data-testid="clv-report-alltime-label">
            <input type="checkbox" checked={allTime}
                   onChange={(e) => setAllTime(e.target.checked)}
                   data-testid="clv-report-alltime-toggle" />
            All time
          </label>
          {!allTime ? <DateRangePicker /> : null}
          <button type="button"
            onClick={() => _download(
              `client-lifetime-value-${allTime ? "all-time" : `${start}-to-${end}`}.csv`,
              _csv(d))}
            disabled={state.loading || !!state.error}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="clv-report-csv-btn">Export CSV</button>
        </div>
      </div>
      {state.error ? (
        <div className="rounded-xl p-6 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                      color: "#7F1D1D" }}
             data-testid="clv-report-error">
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
               data-testid="clv-report-tiles">
            <Tile icon={TrendingUp} testid="tile-avg-recurring"
              label="Avg LTV · Recurring"
              primary={state.loading ? "…" : _money(s.avg_ltv_recurring)}
              secondary="Recurring cohort" />
            <Tile icon={DollarSign} testid="tile-avg-project"
              label="Avg LTV · Project"
              primary={state.loading ? "…" : _money(s.avg_ltv_project)}
              secondary="Project cohort" />
            <Tile icon={Award} testid="tile-top-share"
              label="Top 10% Share"
              primary={state.loading ? "…" : `${_n(s.top_10_pct_revenue_share)}%`}
              secondary="Of total collected" />
            <Tile icon={Users} testid="tile-active-count"
              label="Active Clients"
              primary={state.loading ? "…" : _n(s.active_client_count)}
              secondary="Currently active" />
          </div>
          <div className="rounded-2xl p-5 mb-6"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="clv-report-chart">
            <div className="text-sm font-semibold mb-3"
                 style={{ color: colors.onSurface }}>
              LTV distribution
            </div>
            {buckets.length === 0 && !state.loading ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="clv-report-chart-empty">
                No customers to bucket.
              </div>
            ) : (
              <div className="space-y-2" data-testid="clv-report-chart-bars">
                {buckets.map((b) => (
                  <div key={b.bucket} className="flex items-center gap-3"
                       data-testid={`clv-bucket-${b.bucket}`}>
                    <div className="text-xs w-24"
                         style={{ color: colors.onSurface }}>{b.bucket}</div>
                    <div className="flex-1 h-4 rounded-md"
                         style={{ background: colors.surfaceSecondary }}>
                      <div className="h-4 rounded-md"
                           style={{ width: `${(b.count / maxBucket) * 100}%`,
                                    background: colors.brand || "#1B1F5C" }} />
                    </div>
                    <div className="text-xs font-semibold w-10 text-right"
                         style={{ color: colors.onSurface }}>{b.count}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="clv-report-table">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Customer</Th><Th>Type</Th><Th>Active</Th>
                  <Th>First</Th><Th>Last</Th>
                  <Th>Billed</Th><Th>Collected</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !state.loading ? (
                  <tr><td colSpan={7} className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="clv-report-table-empty">
                    No customers to show.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.customer_id}
                      data-testid={`clv-row-${r.customer_id}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td><CustomerLink customerId={r.customer_id} name={r.customer_name} /></Td>
                    <Td>{r.client_type}</Td>
                    <Td>{r.is_active ? "Yes" : "No"}</Td>
                    <Td>{_shortDate(r.first_service_date)}</Td>
                    <Td>{_shortDate(r.last_service_date)}</Td>
                    <Td>{_money(r.total_billed)}</Td>
                    <Td>{_money(r.total_collected)}</Td>
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
