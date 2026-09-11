/**
 * Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Attrition Report.
 *
 * Route: ``/reports/attrition`` (AdminOnly-gated in App.js).
 * Endpoint: ``GET /api/reports/attrition?start_date&end_date``.
 *
 * Surfaces: 3 summary tiles + reason-count bar chart + sortable
 * row table + CSV export. Refetches on date-range change.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { UserMinus, Users, DollarSign } from "lucide-react";

function _n(v) {
  if (v === null || v === undefined) return "—";
  return typeof v === "number" ? v.toLocaleString() : String(v);
}
function _money(v) {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "number" ? v : parseFloat(v);
  if (Number.isNaN(num)) return "—";
  return `$${num.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
}
function _shortDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
}

function _csv(d) {
  const rows = [
    ["customer_id", "customer_name", "became_inactive_at",
     "inactive_reason", "lifetime_value", "last_service_date"],
    ...(d.rows || []).map((r) => [
      r.customer_id || "",
      r.customer_name || "",
      r.became_inactive_at || "",
      r.inactive_reason || "",
      r.lifetime_value ?? "",
      r.last_service_date || "",
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

export default function AttritionReport() {
  const { start, end } = useDateRange("this-month");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    if (!start || !end) return;
    setState({ loading: true });
    try {
      const res = await api.get(
        `/reports/attrition?start_date=${encodeURIComponent(start)}` +
        `&end_date=${encodeURIComponent(end)}`,
      );
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Attrition Report";
      setState({ loading: false, error: msg });
      try {
        toast({ title: "Attrition Report failed",
                 description: msg, variant: "destructive" });
      } catch { /* toast shim absent in some test envs */ }
    }
  }, [start, end]);

  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const s = d.summary || {};
  const rows = d.rows || [];
  const reasonCounts = (d.chart || {}).reason_counts || {};
  const isLoading = state.loading;
  const isError   = !!state.error;

  const maxCount = useMemo(
    () => Math.max(1, ...Object.values(reasonCounts).map((v) => Number(v) || 0)),
    [reasonCounts],
  );

  return (
    <div
      className="p-4 md:p-8 max-w-6xl mx-auto"
      data-testid="attrition-report-page"
    >
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1
            className="text-3xl md:text-4xl font-bold"
            style={{ color: colors.onSurface }}
            data-testid="attrition-report-title"
          >
            Attrition Report
          </h1>
          <p
            className="text-sm mt-1"
            style={{ color: colors.muted }}
            data-testid="attrition-report-subtitle"
          >
            Customers who became inactive in the selected window,
            grouped by reason. Complements the Inactive Customers
            surface (which is a full active/inactive dump).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePicker />
          <button
            type="button"
            onClick={() => _download(
              `attrition-${start || "now"}-to-${end || "now"}.csv`, _csv(d),
            )}
            disabled={isLoading || isError}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="attrition-report-csv-btn"
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
          data-testid="attrition-report-error"
        >
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div
            className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6"
            data-testid="attrition-report-tiles"
          >
            <Tile icon={UserMinus} testid="tile-total-attrited"
              label="Total Attrited"
              primary={isLoading ? "…" : _n(s.total_attrited)}
              secondary="Customers in window" />
            <Tile icon={Users} testid="tile-attrition-rate"
              label="Attrition Rate"
              primary={isLoading ? "…" : `${_n(s.attrition_rate_pct)}%`}
              secondary="vs at-risk population" />
            <Tile icon={DollarSign} testid="tile-avg-ltv"
              label="Avg LTV of Attrited"
              primary={isLoading ? "…" : _money(s.avg_ltv_of_attrited)}
              secondary="Lifetime revenue avg" />
          </div>

          <div
            className="rounded-2xl p-5 mb-6"
            style={{ background: colors.surface,
                     border: `1px solid ${colors.border}` }}
            data-testid="attrition-report-chart"
          >
            <div className="text-sm font-semibold mb-3"
                 style={{ color: colors.onSurface }}>
              By reason
            </div>
            {Object.keys(reasonCounts).length === 0 && !isLoading ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="attrition-report-chart-empty">
                No attrition in this window.
              </div>
            ) : (
              <div className="space-y-2" data-testid="attrition-report-chart-bars">
                {Object.entries(reasonCounts).map(([reason, count]) => (
                  <div key={reason} className="flex items-center gap-3"
                       data-testid={`reason-bar-${reason}`}>
                    <div className="text-xs w-40 truncate"
                         style={{ color: colors.onSurface }}
                         title={reason}>
                      {reason}
                    </div>
                    <div className="flex-1 h-4 rounded-md relative"
                         style={{ background: colors.surfaceSecondary }}>
                      <div className="h-4 rounded-md"
                           style={{
                             width: `${(count / maxCount) * 100}%`,
                             background: colors.brand || "#1B1F5C",
                           }} />
                    </div>
                    <div className="text-xs font-semibold w-8 text-right"
                         style={{ color: colors.onSurface }}>
                      {count}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div
            className="rounded-2xl overflow-hidden"
            style={{ background: colors.surface,
                     border: `1px solid ${colors.border}` }}
            data-testid="attrition-report-table"
          >
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: colors.surfaceSecondary }}>
                  <Th>Customer</Th><Th>Became Inactive</Th>
                  <Th>Reason</Th><Th>LTV</Th><Th>Last Service</Th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !isLoading ? (
                  <tr><td colSpan={5}
                          className="text-center py-6 text-xs"
                          style={{ color: colors.muted }}
                          data-testid="attrition-report-table-empty">
                    No attrition in this window.
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.customer_id}
                      data-testid={`attrition-row-${r.customer_id}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                    <Td>{r.customer_name || "—"}</Td>
                    <Td>{_shortDate(r.became_inactive_at)}</Td>
                    <Td>{r.inactive_reason || "—"}</Td>
                    <Td>{_money(r.lifetime_value)}</Td>
                    <Td>{_shortDate(r.last_service_date)}</Td>
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
