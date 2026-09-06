import React from "react";
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
 * Phase R0.1 · Feb-2026 — Revenue by City panel.
 *
 * Same UX contract as ``RevenueByCustomerPanel`` but grouped by
 * customer service-address city (with "(unknown)" fallback).
 *
 * City rows are NOT clickable — the app does not yet expose a
 * ``/customers?city=...`` filtered listing, so R0.1 deliberately
 * leaves the row non-interactive rather than inventing a URL
 * pattern that isn't wired to the customer list yet.
 */
export function RevenueByCityPanel({ filters, params, setParams }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);
  const [page, setPage] = React.useState(0);

  const showAll = params.get("show_all_cities") === "1";

  const fetchRows = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = buildQuery(filters);
      const r = await api.get(`/reports/kpi/revenue_by_city?${q}`);
      setData(r);
      setPage(0);
    } catch (e) {
      setError(e?.message || "Failed to load revenue by city");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.period, filters.start, filters.end, filters.lens, filters.service_type, filters.tech_id]);

  React.useEffect(() => { fetchRows(); }, [fetchRows]);

  const rows = data?.rows || [];
  const chartRows = rows.slice(0, TOP_N_DEFAULT).map((r) => ({
    label: r.city,
    value: r.revenue,
  }));

  const pageRows = showAll
    ? rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
    : rows.slice(0, TOP_N_DEFAULT);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));

  const toggleShowAll = () => {
    const next = new URLSearchParams(params);
    if (showAll) next.delete("show_all_cities"); else next.set("show_all_cities", "1");
    setParams(next, { replace: true });
    setPage(0);
  };

  const exportCsv = () => {
    downloadCsv(
      `revenue-by-city-${filters.period || "mtd"}-${filters.lens || "invoiced"}.csv`,
      ["City", "Customer count", "Revenue (USD)"],
      rows.map((r) => [r.city, r.customer_count, r.revenue.toFixed(2)]),
    );
  };

  return (
    <section
      className="space-y-4"
      data-testid="revenue-by-city-panel"
    >
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Revenue by City
          </h2>
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {loading ? "Loading…" : error ? "Error" : (
              <>
                {formatCurrency(data?.total)} total · {data?.row_count || 0} cit{data?.row_count === 1 ? "y" : "ies"}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={toggleShowAll}
            disabled={!data || (data.row_count || 0) <= TOP_N_DEFAULT}
            data-testid="revenue-by-city-show-all"
          >
            {showAll ? `Show top ${TOP_N_DEFAULT}` : "Show all"}
          </Button>
          <Button
            variant="ghost"
            onClick={exportCsv}
            disabled={!data || rows.length === 0}
            data-testid="revenue-by-city-export"
          >
            Export CSV
          </Button>
        </div>
      </header>

      <HorizontalBarChart
        data={chartRows}
        format="currency"
        height={Math.max(200, chartRows.length * 30)}
        testid="revenue-by-city-chart"
      />

      <div
        className="rounded-xl border overflow-hidden"
        style={{ backgroundColor: colors.surface, borderColor: colors.border }}
      >
        <table className="w-full text-sm" data-testid="revenue-by-city-table">
          <thead style={{ backgroundColor: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                City
              </th>
              <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                Customers
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
                       data-testid="revenue-by-city-empty">
                No matching cities for the current filter set
              </td></tr>
            ) : pageRows.map((r) => (
              <tr
                key={r.city}
                data-testid={`revenue-by-city-row-${r.city}`}
                style={{ borderTop: `1px solid ${colors.border}` }}
              >
                <td className="px-3 py-2" style={{ color: colors.onSurface }}>
                  {r.city}
                </td>
                <td className="text-right px-3 py-2" style={{ color: colors.onSurfaceSecondary }}>
                  {r.customer_count}
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
            data-testid="revenue-by-city-paginator"
          >
            <span style={{ color: colors.onSurfaceSecondary }}>
              Page {page + 1} of {totalPages}
            </span>
            <div className="flex gap-2">
              <Button variant="ghost" disabled={page === 0}
                        onClick={() => setPage((p) => Math.max(0, p - 1))}
                        data-testid="revenue-by-city-prev">Prev</Button>
              <Button variant="ghost" disabled={page >= totalPages - 1}
                        onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                        data-testid="revenue-by-city-next">Next</Button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default RevenueByCityPanel;
