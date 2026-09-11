/**
 * Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Time to Get Paid.
 *
 * Route: ``/reports/time-to-get-paid`` (AdminOnly-gated in App.js).
 * Endpoint: ``GET /api/reports/time-to-get-paid?start_date&end_date``.
 *
 * Surfaces: 4 summary tiles + trailing-12-month monthly avg line
 * chart (independent of the filter) + rows table sorted by
 * ``days_to_paid`` desc + CSV export. Refetches on date-range
 * change.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { Clock, BarChart3, Activity, FileText } from "lucide-react";

function _n(v) {
  if (v === null || v === undefined) return "—";
  return typeof v === "number" ? v.toLocaleString() : String(v);
}
function _shortDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
}

function _csv(d) {
  const rows = [
    ["invoice_id", "customer_id", "customer_name",
     "sent_at", "paid_at", "days_to_paid"],
    ...(d.rows || []).map((r) => [
      r.invoice_id || "",
      r.customer_id || "",
      r.customer_name || "",
      r.sent_at || "",
      r.paid_at || "",
      r.days_to_paid ?? "",
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

export default function TimeToGetPaidReport() {
  const { start, end } = useDateRange("last-90-days");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    if (!start || !end) return;
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/time-to-get-paid?start_date=${encodeURIComponent(start)}` +
        `&end_date=${encodeURIComponent(end)}`,
      );
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Time to Get Paid";
      setState({ loading: false, error: msg });
      try {
        toast({ title: "Time to Get Paid failed",
                 description: msg, variant: "destructive" });
      } catch { /* toast shim absent in some test envs */ }
    }
  }, [start, end]);

  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const chartRows = (d.chart || {}).monthly_avg_days || [];
  const isLoading = state.loading;
  const isError   = !!state.error;

  // Line-chart geometry — SVG polyline over the trailing-12-month
  // series. Y is normalized to the max avg_days in the series so
  // the shape is legible even when the absolute values are small.
  const chart = useMemo(() => {
    if (!chartRows.length) return null;
    const maxY = Math.max(1, ...chartRows.map((r) => Number(r.avg_days) || 0));
    const w = 640, h = 140, pad = 16;
    const n = chartRows.length;
    const stepX = n > 1 ? (w - pad * 2) / (n - 1) : 0;
    const points = chartRows.map((r, i) => {
      const x = pad + i * stepX;
      const v = Number(r.avg_days) || 0;
      const y = h - pad - ((v / maxY) * (h - pad * 2));
      return { x, y, v, month: r.month };
    });
    const polyline = points.map((p) => `${p.x},${p.y}`).join(" ");
    return { w, h, points, polyline, maxY };
  }, [chartRows]);

  return (
    <div
      className="p-4 md:p-8 max-w-6xl mx-auto"
      data-testid="ttgp-report-page"
    >
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1
            className="text-3xl md:text-4xl font-bold"
            style={{ color: colors.onSurface }}
            data-testid="ttgp-report-title"
          >
            Time to Get Paid
          </h1>
          <p
            className="text-sm mt-1"
            style={{ color: colors.muted }}
            data-testid="ttgp-report-subtitle"
          >
            Cycle-time from invoice sent to paid. Summary tiles
            reflect the selected window; the line chart is a rolling
            trailing-12-month view independent of the filter.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePicker defaultPreset="last-90-days" />
          <button
            type="button"
            onClick={() => _download(
              `time-to-get-paid-${start || "now"}-to-${end || "now"}.csv`,
              _csv(d),
            )}
            disabled={isLoading || isError}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="ttgp-report-csv-btn"
          >
            Export CSV
          </button>
        </div>
      </div>

      {isError ? (
        <div
          className="rounded-xl p-6 text-sm"
          style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                   color: "#7F1D1D" }}
          data-testid="ttgp-report-error"
        >
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div
            className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
            data-testid="ttgp-report-tiles"
          >
            <Tile icon={Clock}    testid="tile-avg-days"
              label="Avg Days" primary={isLoading ? "…" : _n(s.avg_days_to_paid)}
              secondary="Days to paid" />
            <Tile icon={Activity} testid="tile-p50-days"
              label="Median (p50)" primary={isLoading ? "…" : _n(s.p50_days)}
              secondary="50th percentile" />
            <Tile icon={BarChart3} testid="tile-p90-days"
              label="p90" primary={isLoading ? "…" : _n(s.p90_days)}
              secondary="90th percentile" />
            <Tile icon={FileText} testid="tile-invoice-count"
              label="Invoices" primary={isLoading ? "…" : _n(s.invoices_counted)}
              secondary="Counted in window" />
          </div>

          <div
            className="rounded-2xl p-5 mb-6"
            style={{ background: colors.surface,
                     border: `1px solid ${colors.border}` }}
            data-testid="ttgp-report-chart"
          >
            <div className="text-sm font-semibold mb-3"
                 style={{ color: colors.onSurface }}>
              Trailing 12 months · monthly avg days to paid
            </div>
            {!chart ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="ttgp-report-chart-empty">
                No paid invoices in the trailing 12-month window.
              </div>
            ) : (
              <svg viewBox={`0 0 ${chart.w} ${chart.h}`}
                   role="img" aria-label="Monthly avg days to paid"
                   className="w-full"
                   data-testid="ttgp-report-chart-svg">
                <polyline points={chart.polyline} fill="none"
                          stroke={colors.brand || "#1B1F5C"}
                          strokeWidth="2" />
                {chart.points.map((p) => (
                  <g key={p.month} data-testid={`ttgp-chart-point-${p.month}`}>
                    <circle cx={p.x} cy={p.y} r="3"
                            fill={colors.brand || "#1B1F5C"} />
                    <title>{`${p.month} · avg ${p.v}d`}</title>
                  </g>
                ))}
              </svg>
            )}
          </div>

          <div
            className="rounded-2xl overflow-hidden"
            style={{ background: colors.surface,
                     border: `1px solid ${colors.border}` }}
            data-testid="ttgp-report-table"
          >
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Invoice</Th><Th>Customer</Th>
                  <Th>Sent</Th><Th>Paid</Th><Th>Days</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !isLoading ? (
                  <tr><td colSpan={5}
                          className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="ttgp-report-table-empty">
                    No paid invoices in this window.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.invoice_id}
                      data-testid={`ttgp-row-${r.invoice_id}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td>{(r.invoice_id || "").slice(0, 8)}…</Td>
                    <Td>{r.customer_name || "—"}</Td>
                    <Td>{_shortDate(r.sent_at)}</Td>
                    <Td>{_shortDate(r.paid_at)}</Td>
                    <Td>{_n(r.days_to_paid)}</Td>
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
                  border: `1px solid ${colors.border || "#E5E7EB"}`,
                  color: "#FFFFFF" }}
         data-testid={testid}>
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
             style={{ backgroundColor: "rgba(255,255,255,0.18)" }}>
          <Icon size={20} />
        </div>
        <div className="text-sm font-semibold opacity-90">{label}</div>
      </div>
      <div className="text-3xl font-bold" data-testid={`${testid}-primary`}>
        {primary}
      </div>
      <div className="text-xs opacity-80" data-testid={`${testid}-secondary`}>
        {secondary}
      </div>
    </div>
  );
}
function Th({ children }) {
  return (
    <th className="text-left px-4 py-2 text-xs font-semibold uppercase tracking-wide"
        style={{ color: colors.muted }}>
      {children}
    </th>
  );
}
function Td({ children }) {
  return <td className="px-4 py-2" style={{ color: colors.onSurface }}>{children}</td>;
}
