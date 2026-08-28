/**
 * Feb-2026 · Chemical Cost Report — /admin/reports/chemical-costs.
 *
 * Aggregates paid invoice line items where the linked pricebook
 * item has ``category`` matching the ``chemical`` bucket. Uses
 * ``wholesale_cost_snapshot`` (write-time capture) as the cost
 * basis so the report reflects COGS at the moment of sale.
 */
import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui-kit";


function _money(n) {
  const v = Number(n || 0);
  return v.toLocaleString(undefined, { style: "currency", currency: "USD" });
}


function _mtdRange() {
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  return {
    date_from: first.toISOString().slice(0, 10),
    date_to: now.toISOString().slice(0, 10),
  };
}


export default function ChemicalCostReportPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState(() => ({
    date_from: searchParams.get("date_from") || _mtdRange().date_from,
    date_to: searchParams.get("date_to") || _mtdRange().date_to,
    customer_id: searchParams.get("customer_id") || "",
    tech_id: searchParams.get("tech_id") || "",
    chemical_ids: searchParams.get("chemical_ids") || "",
  }));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => {
        if (v) params.set(k, v);
      });
      // Sync filters into the URL — deep-linkable.
      setSearchParams(params, { replace: true });
      const r = await api.get(`/reports/chemical-costs?${params.toString()}`);
      setData(r);
    } catch (_e) {
      toast.error("Failed to load chemical cost report");
    } finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [filters]);

  const downloadCsv = () => {
    if (!data) return;
    const header = ["chemical_name", "unit", "qty_used", "total_cost",
                      "job_count", "avg_per_job", "top_customer", "top_tech"];
    const rows = (data.by_chemical || []).map((r) => header.map((h) => {
      const v = h === "top_customer" ? (r.top_customer?.name || "")
            : h === "top_tech" ? (r.top_tech?.name || "")
            : r[h];
      return `"${String(v ?? "").replace(/"/g, '""')}"`;
    }).join(","));
    const csv = [header.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chemical-costs-${filters.date_from}-to-${filters.date_to}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6" data-testid="chemical-cost-report-page"
          style={{ background: colors.background, minHeight: "100vh",
                      color: colors.onSurface }}>
      <h1 className="text-2xl font-bold mb-1">Chemical Cost Report</h1>
      <p className="text-sm opacity-70 mb-4">
        Wholesale-cost aggregation from paid invoice line items where
        the source pricebook item is a chemical. Cost basis is the
        write-time ``wholesale_cost_snapshot`` — the report reflects
        COGS at the moment of sale, never re-priced.
      </p>
      <div className="flex flex-wrap gap-3 items-end mb-4 p-4 rounded-2xl"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
        <label className="text-sm">
          <div className="text-xs opacity-70 mb-1">From</div>
          <input type="date" value={filters.date_from}
                  onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))}
                  data-testid="cc-filter-from"
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm">
          <div className="text-xs opacity-70 mb-1">To</div>
          <input type="date" value={filters.date_to}
                  onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
                  data-testid="cc-filter-to"
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm flex-1 min-w-[160px]">
          <div className="text-xs opacity-70 mb-1">Customer id</div>
          <input value={filters.customer_id}
                  onChange={(e) => setFilters((f) => ({ ...f, customer_id: e.target.value }))}
                  data-testid="cc-filter-customer"
                  placeholder="Optional customer id"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm flex-1 min-w-[160px]">
          <div className="text-xs opacity-70 mb-1">Tech id</div>
          <input value={filters.tech_id}
                  onChange={(e) => setFilters((f) => ({ ...f, tech_id: e.target.value }))}
                  data-testid="cc-filter-tech"
                  placeholder="Optional tech id"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <label className="text-sm flex-1 min-w-[200px]">
          <div className="text-xs opacity-70 mb-1">Chemical ids (comma-sep)</div>
          <input value={filters.chemical_ids}
                  onChange={(e) => setFilters((f) => ({ ...f, chemical_ids: e.target.value }))}
                  data-testid="cc-filter-chemicals"
                  placeholder="Optional"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }} />
        </label>
        <Button onClick={downloadCsv} testid="cc-export-csv" variant="secondary">
          Export CSV
        </Button>
      </div>

      {data?.totals ? (
        <div className="flex flex-wrap gap-4 mb-4" data-testid="cc-totals">
          <div className="p-4 rounded-2xl min-w-[180px]"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="text-xs opacity-70">Total wholesale cost</div>
            <div className="text-2xl font-bold">{_money(data.totals.total_wholesale_cost)}</div>
          </div>
          <div className="p-4 rounded-2xl min-w-[180px]"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="text-xs opacity-70">Total qty</div>
            <div className="text-2xl font-bold">{data.totals.total_qty}</div>
          </div>
          <div className="p-4 rounded-2xl min-w-[180px]"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="text-xs opacity-70">Jobs touched</div>
            <div className="text-2xl font-bold">{data.totals.job_count}</div>
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="text-sm opacity-70">Loading…</div>
      ) : !data?.by_chemical?.length ? (
        <div className="text-sm opacity-70 p-6 text-center rounded-2xl"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="cc-empty">
          No chemical line items in this range.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm" data-testid="cc-table">
            <thead>
              <tr style={{ background: colors.background }}>
                {["Chemical", "Qty used", "Wholesale cost", "Avg / job",
                    "Top customer", "Top tech"].map((h) => (
                  <th key={h} className="text-left px-3 py-2 text-xs font-semibold opacity-70">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.by_chemical.map((r) => (
                <tr key={r.chemical_id} data-testid={`cc-row-${r.chemical_id}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td className="px-3 py-2">
                    <div className="font-medium">{r.chemical_name}</div>
                    {r.unit ? <div className="text-xs opacity-60">{r.unit}</div> : null}
                  </td>
                  <td className="px-3 py-2">{r.qty_used}</td>
                  <td className="px-3 py-2 font-medium">{_money(r.total_cost)}</td>
                  <td className="px-3 py-2">{_money(r.avg_per_job)}</td>
                  <td className="px-3 py-2">
                    {r.top_customer ? (
                      <span>
                        {r.top_customer.name}
                        <span className="text-xs opacity-60"> · {_money(r.top_customer.cost)}</span>
                      </span>
                    ) : <span className="opacity-60">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    {r.top_tech ? (
                      <span>
                        {r.top_tech.name}
                        <span className="text-xs opacity-60"> · {r.top_tech.jobs} jobs</span>
                      </span>
                    ) : <span className="opacity-60">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
