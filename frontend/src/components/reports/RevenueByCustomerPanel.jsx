import React from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { HorizontalBarChart } from "./HorizontalBarChart";
import { downloadCsv } from "./downloadCsv";
import { formatCurrency } from "./formatters";

const PAGE_SIZE = 25;
const TOP_N_DEFAULT = 20;

function buildQuery(filters) {
  const params = new URLSearchParams();
  params.set("period", filters.period || "mtd");
  if (filters.period === "custom" && filters.start && filters.end) {
    params.set("start", filters.start);
    params.set("end", filters.end);
  }
  params.set("lens", filters.lens || "invoiced");
  if (filters.service_type) params.set("service_type", filters.service_type);
  if (filters.tech_id) params.set("tech_id", filters.tech_id);
  return params.toString();
}

/**
 * Phase R0.1 · Feb-2026 — Revenue by Customer panel.
 *
 * Fetches the grouped metric, renders a horizontal bar chart of
 * the top N, and a paginated table below. Row click drills down
 * to /customers/{id}; back navigation preserves the URL filters
 * because the parent tab writes them to querystring.
 */
export function RevenueByCustomerPanel({ filters, params, setParams }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);
  const [page, setPage] = React.useState(0);
  const navigate = useNavigate();

  const showAll = params.get("show_all_customers") === "1";

  const fetchRows = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = buildQuery(filters);
      // Ask backend for as many rows as we could possibly need.
      const r = await api.get(`/reports/kpi/revenue_by_customer?${q}&limit=1000`);
      setData(r);
      setPage(0);
    } catch (e) {
      setError(e?.message || "Failed to load revenue by customer");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.period, filters.start, filters.end, filters.lens, filters.service_type, filters.tech_id]);

  React.useEffect(() => { fetchRows(); }, [fetchRows]);

  const rows = data?.rows || [];
  const chartRows = rows.slice(0, TOP_N_DEFAULT).map((r) => ({
    label: r.customer_name || "(unnamed)",
    value: r.revenue,
    id: r.customer_id,
  }));

  const pageRows = showAll
    ? rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
    : rows.slice(0, TOP_N_DEFAULT);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));

  const toggleShowAll = () => {
    const next = new URLSearchParams(params);
    if (showAll) next.delete("show_all_customers"); else next.set("show_all_customers", "1");
    setParams(next, { replace: true });
    setPage(0);
  };

  const exportCsv = () => {
    downloadCsv(
      `revenue-by-customer-${filters.period || "mtd"}-${filters.lens || "invoiced"}.csv`,
      ["Customer", "Customer ID", "Revenue (USD)", "Invoices in period"],
      rows.map((r) => [r.customer_name, r.customer_id, r.revenue.toFixed(2), r.invoice_count]),
    );
  };

  return (
    <section
      className="space-y-4"
      data-testid="revenue-by-customer-panel"
    >
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Revenue by Customer
          </h2>
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {loading ? "Loading…" : error ? "Error" : (
              <>
                {formatCurrency(data?.total)} total · {data?.row_count || 0} customer{data?.row_count === 1 ? "" : "s"}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={toggleShowAll}
            disabled={!data || (data.row_count || 0) <= TOP_N_DEFAULT}
            data-testid="revenue-by-customer-show-all"
          >
            {showAll ? `Show top ${TOP_N_DEFAULT}` : "Show all"}
          </Button>
          <Button
            variant="ghost"
            onClick={exportCsv}
            disabled={!data || rows.length === 0}
            data-testid="revenue-by-customer-export"
          >
            Export CSV
          </Button>
        </div>
      </header>

      <HorizontalBarChart
        data={chartRows}
        format="currency"
        height={Math.max(200, chartRows.length * 24)}
        onBarClick={(row) => row.id && navigate(`/customers/${row.id}`)}
        testid="revenue-by-customer-chart"
      />

      <div
        className="rounded-xl border overflow-hidden"
        style={{ backgroundColor: colors.surface, borderColor: colors.border }}
      >
        <table className="w-full text-sm" data-testid="revenue-by-customer-table">
          <thead style={{ backgroundColor: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                Customer
              </th>
              <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                Invoices
              </th>
              <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                Revenue
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={3} className="px-3 py-6 text-center text-xs" style={{ color: colors.onSurfaceSecondary }}>Loading…</td></tr>
            ) : error ? (
              <tr><td colSpan={3} className="px-3 py-6 text-center text-xs" style={{ color: colors.error }}>{error}</td></tr>
            ) : pageRows.length === 0 ? (
              <tr><td colSpan={3} className="px-3 py-6 text-center text-xs" style={{ color: colors.onSurfaceSecondary }}
                       data-testid="revenue-by-customer-empty">
                No matching customers for the current filter set
              </td></tr>
            ) : pageRows.map((r) => (
              <tr
                key={r.customer_id || r.customer_name}
                onClick={() => r.customer_id && navigate(`/customers/${r.customer_id}`)}
                className="cursor-pointer hover:opacity-80"
                data-testid={`revenue-by-customer-row-${r.customer_id}`}
                style={{ borderTop: `1px solid ${colors.border}` }}
              >
                <td className="px-3 py-2" style={{ color: colors.onSurface }}>
                  {r.customer_name || "(unnamed)"}
                </td>
                <td className="text-right px-3 py-2" style={{ color: colors.onSurfaceSecondary }}>
                  {r.invoice_count}
                </td>
                <td className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurface }}>
                  {formatCurrency(r.revenue)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {showAll && totalPages > 1 ? (
          <div
            className="flex items-center justify-between px-3 py-2 border-t text-xs"
            style={{ borderColor: colors.border, backgroundColor: colors.surfaceSecondary }}
            data-testid="revenue-by-customer-paginator"
          >
            <span style={{ color: colors.onSurfaceSecondary }}>
              Page {page + 1} of {totalPages}
            </span>
            <div className="flex gap-2">
              <Button variant="ghost" disabled={page === 0}
                        onClick={() => setPage((p) => Math.max(0, p - 1))}
                        data-testid="revenue-by-customer-prev">Prev</Button>
              <Button variant="ghost" disabled={page >= totalPages - 1}
                        onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                        data-testid="revenue-by-customer-next">Next</Button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default RevenueByCustomerPanel;
