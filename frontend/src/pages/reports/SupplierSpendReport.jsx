/**
 * Phase 56-d · Aug-2026 — Supplier Spend / Margin report.
 *
 * Read-only view over ``GET /api/reports/supplier-spend``. Shows
 * aggregated spend + margin by resolved primary supplier for
 * pricebook-linked line items in the selected date range.
 *
 * Legacy line items without a ``pricebook_item_id`` bucket into an
 * "Uncategorized" row so historical revenue is still visible.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, TrendingUp, Download } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { PageHeader } from "@/components/ui-kit";


function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
function isoToday() {
  return new Date().toISOString().slice(0, 10);
}


// Margin% tier colour palette (locked in scope §4):
//   ≥30%  green · 10-30% neutral · <10% red.
function marginTier(pct) {
  const p = Number(pct) || 0;
  if (p >= 30) return { bg: "#DCFCE7", fg: "#166534" };
  if (p >= 10) return { bg: "#F1F5F9", fg: "#475569" };
  return { bg: "#FEE2E2", fg: "#991B1B" };
}


export default function SupplierSpendReport() {
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [incomeCats, setIncomeCats] = useState([]);

  const [dateFrom, setDateFrom] = useState(() => isoDaysAgo(90));
  const [dateTo, setDateTo] = useState(() => isoToday());
  const [categoryFilter, setCategoryFilter] = useState("");
  const [sort, setSort] = useState("spend_desc");
  const [includeUncategorized, setIncludeUncategorized] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/income-categories");
        const items = Array.isArray(r) ? r : (r?.items || []);
        setIncomeCats(items.filter((c) => !c.is_archived));
      } catch { setIncomeCats([]); }
    })();
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const qs = new URLSearchParams();
      qs.set("date_from", dateFrom);
      qs.set("date_to", dateTo);
      if (categoryFilter) qs.set("income_category_id", categoryFilter);
      qs.set("include_uncategorized", String(includeUncategorized));
      qs.set("sort", sort);
      const r = await api.get(`/reports/supplier-spend?${qs.toString()}`);
      setRows(Array.isArray(r?.rows) ? r.rows : []);
      setTotals(r?.totals || null);
    } catch (e) {
      setError(e?.message || "Failed to load supplier spend.");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, categoryFilter, sort, includeUncategorized]);

  useEffect(() => { load(); }, [load]);

  const exportCsv = () => {
    const header = [
      "Supplier", "Category", "Line items", "Quantity",
      "Spend ($)", "Revenue ($)", "Margin ($)", "Margin (%)",
    ];
    const body = rows.map((r) => [
      r.display_name,
      r.income_category_name,
      r.line_item_count,
      r.quantity_sum,
      ((r.spend_cents || 0) / 100).toFixed(2),
      ((r.revenue_cents || 0) / 100).toFixed(2),
      ((r.margin_cents || 0) / 100).toFixed(2),
      Number(r.margin_pct || 0).toFixed(2),
    ]);
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [header, ...body]
      .map((row) => row.map(esc).join(",")).join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `supplier-spend-${dateFrom}_to_${dateTo}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  };

  const hasRows = rows.length > 0;
  const isFiltered = useMemo(
    () => Boolean(categoryFilter || !includeUncategorized),
    [categoryFilter, includeUncategorized],
  );

  return (
    <div className="max-w-6xl mx-auto py-6 px-4 space-y-4"
          data-testid="supplier-spend-page">
      <Link to="/reports"
            className="inline-flex items-center gap-1 text-xs font-bold"
            style={{ color: colors.brand, textDecoration: "none" }}>
        <ArrowLeft size={12} /> Reports Hub
      </Link>

      <PageHeader
        icon={TrendingUp}
        title="Supplier Spend & Margin"
        subtitle="Aggregates cost + revenue per primary supplier for pricebook-linked line items. Legacy line items without a pricebook FK bucket into 'Uncategorized'."
      />

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Date from</div>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="text-sm px-2 py-2 rounded-md"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="ssp-date-from"
          />
        </div>
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Date to</div>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="text-sm px-2 py-2 rounded-md"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="ssp-date-to"
          />
        </div>
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Category</div>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[160px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="ssp-filter-category"
          >
            <option value="">All categories</option>
            {incomeCats.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Sort</div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="text-sm px-2 py-2 rounded-md"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="ssp-filter-sort"
          >
            <option value="spend_desc">Spend (highest first)</option>
            <option value="margin_desc">Margin % (highest first)</option>
            <option value="name">Supplier name (A–Z)</option>
          </select>
        </div>
        <label className="inline-flex items-center gap-2 text-xs font-semibold cursor-pointer pb-2"
                style={{ color: colors.onSurface }}
                data-testid="ssp-uncategorized-label">
          <input
            type="checkbox"
            checked={includeUncategorized}
            onChange={(e) => setIncludeUncategorized(e.target.checked)}
            data-testid="ssp-uncategorized-toggle"
            className="cursor-pointer"
          />
          Include uncategorized
        </label>
        <div className="flex-1" />
        <button
          type="button"
          onClick={exportCsv}
          disabled={!hasRows}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md"
          style={{ background: colors.brand, color: "#fff", border: 0,
                   opacity: hasRows ? 1 : 0.5,
                   cursor: hasRows ? "pointer" : "not-allowed" }}
          data-testid="ssp-csv-export"
        >
          <Download size={12} /> Export CSV
        </button>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="ssp-loading">Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}
              data-testid="ssp-error">{error}</div>
      ) : !hasRows ? (
        <div className="rounded-lg p-6 text-sm text-center"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.muted }}
              data-testid="ssp-empty">
          {isFiltered
            ? "No supplier-linked line items match this filter. Try widening the date range or clearing the category filter."
            : "No supplier-linked line items in this range. Ensure new invoices pick items from the Price Book."}
        </div>
      ) : (
        <div className="rounded-lg overflow-hidden"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="ssp-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Supplier</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Category</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Lines</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Qty</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Spend</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Revenue</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Margin</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Margin %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const tier = marginTier(r.margin_pct);
                const isUncat = !r.supplier_slug;
                const key = r.supplier_slug || "__uncategorized__";
                return (
                  <tr key={key}
                       data-testid={`ssp-row-${key}`}
                       style={{ opacity: isUncat ? 0.7 : 1 }}>
                    <td className="px-3 py-2 font-semibold"
                        style={{ color: colors.onSurface }}
                        data-testid={`ssp-row-name-${key}`}>
                      {r.display_name}
                    </td>
                    <td className="px-3 py-2"
                        style={{ color: colors.muted }}>
                      {r.income_category_name}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {r.line_item_count}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {Number(r.quantity_sum || 0).toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono"
                        style={{ color: "#991B1B" }}
                        data-testid={`ssp-row-spend-${key}`}>
                      {money((r.spend_cents || 0) / 100)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono"
                        style={{ color: "#166534" }}
                        data-testid={`ssp-row-revenue-${key}`}>
                      {money((r.revenue_cents || 0) / 100)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono"
                        style={{ color: colors.onSurface }}>
                      {money((r.margin_cents || 0) / 100)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span
                        className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold"
                        style={{ backgroundColor: tier.bg, color: tier.fg }}
                        data-testid={`ssp-row-margin-pill-${key}`}
                      >
                        {Number(r.margin_pct || 0).toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                );
              })}
              {totals ? (
                <tr data-testid="ssp-totals-row"
                     style={{ borderTop: `2px solid ${colors.border}`,
                              background: colors.surfaceAlt }}>
                  <td className="px-3 py-2 font-bold"
                      style={{ color: colors.onSurface }}>
                    Totals
                  </td>
                  <td></td>
                  <td className="px-3 py-2 text-right font-mono font-bold">
                    {totals.line_item_count}
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-bold">
                    {Number(totals.quantity_sum || 0).toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-bold"
                      style={{ color: "#991B1B" }}
                      data-testid="ssp-totals-spend">
                    {money((totals.spend_cents || 0) / 100)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-bold"
                      style={{ color: "#166534" }}
                      data-testid="ssp-totals-revenue">
                    {money((totals.revenue_cents || 0) / 100)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-bold">
                    {money((totals.margin_cents || 0) / 100)}
                  </td>
                  <td className="px-3 py-2 text-right font-bold"
                      style={{ color: colors.onSurface }}
                      data-testid="ssp-totals-margin-pct">
                    {Number(totals.margin_pct || 0).toFixed(1)}%
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
