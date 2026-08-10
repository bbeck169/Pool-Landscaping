/**
 * Phase 56-c · Aug-2026 — Pricebook Cost Comparison report.
 *
 * Read-only view over ``GET /api/reports/pricebook-cost-comparison``.
 * Surfaces items where suppliers disagree on cost — the bigger the
 * spread%, the more actionable the sourcing opportunity.
 *
 * Filters: income_category, min_spread_pct, sort, limit.
 * Actions: expand a row for per-supplier breakdown · Export CSV.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Scale, ChevronDown, ChevronRight, Download } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { PageHeader } from "@/components/ui-kit";


// Spread% tier colour palette (locked in scope §2):
//   0–10%  → neutral · 10–30% → amber · ≥30% → red.
function spreadTier(pct) {
  const p = Number(pct) || 0;
  if (p >= 30) return { bg: "#FEE2E2", fg: "#991B1B", label: "high" };
  if (p >= 10) return { bg: "#FEF3C7", fg: "#92400E", label: "med" };
  return { bg: "#F1F5F9", fg: "#475569", label: "low" };
}

function CategoryPill({ name }) {
  const palette = name === "Pool"
    ? { bg: "#DBEAFE", fg: "#1E40AF" }
    : name === "Landscaping"
      ? { bg: "#DCFCE7", fg: "#166534" }
      : { bg: "#F1F5F9", fg: "#475569" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
      style={{ backgroundColor: palette.bg, color: palette.fg }}
    >
      {name || "—"}
    </span>
  );
}


export default function PricebookCostComparison() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [incomeCats, setIncomeCats] = useState([]);
  const [expanded, setExpanded] = useState(() => new Set());

  const [categoryFilter, setCategoryFilter] = useState("");
  const [minSpread, setMinSpread] = useState(0);
  const [sort, setSort] = useState("spread_desc");
  const [limit, setLimit] = useState(100);

  // Load income categories once — dropdown filter.
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
      if (categoryFilter) qs.set("income_category_id", categoryFilter);
      if (minSpread) qs.set("min_spread_pct", String(minSpread));
      qs.set("sort", sort);
      qs.set("limit", String(limit));
      const r = await api.get(
        `/reports/pricebook-cost-comparison?${qs.toString()}`,
      );
      setRows(Array.isArray(r?.rows) ? r.rows : []);
      setTotal(Number(r?.total) || 0);
    } catch (e) {
      setError(e?.message || "Failed to load cost comparison.");
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, minSpread, sort, limit]);

  useEffect(() => { load(); }, [load]);

  const toggleExpanded = (id) => setExpanded((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // ── CSV export — Blob + createObjectURL, same pattern as
  // AutobillingRuns.jsx#exportCsv. Columns mirror the table columns.
  const exportCsv = () => {
    const header = [
      "Item name", "Income category", "Suppliers",
      "Min ($)", "Max ($)", "Spread ($)", "Spread (%)",
    ];
    const body = rows.map((r) => [
      r.item_name,
      r.income_category_name,
      r.supplier_count,
      ((r.min_cost_cents || 0) / 100).toFixed(2),
      ((r.max_cost_cents || 0) / 100).toFixed(2),
      ((r.spread_cents || 0) / 100).toFixed(2),
      Number(r.spread_pct || 0).toFixed(2),
    ]);
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [header, ...body]
      .map((row) => row.map(esc).join(",")).join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `pricebook-cost-comparison-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  };

  const hasRows = rows.length > 0;
  const isFiltered = useMemo(
    () => Boolean(categoryFilter || Number(minSpread) > 0),
    [categoryFilter, minSpread],
  );

  return (
    <div className="max-w-6xl mx-auto py-6 px-4 space-y-4"
          data-testid="pricebook-cost-comparison-page">
      <Link to="/reports"
            className="inline-flex items-center gap-1 text-xs font-bold"
            style={{ color: colors.brand, textDecoration: "none" }}>
        <ArrowLeft size={12} /> Reports Hub
      </Link>

      <PageHeader
        icon={Scale}
        title="Pricebook Cost Comparison"
        subtitle="Per-item supplier price spread — surfaces items where one supplier is significantly cheaper than another. Sort by spread% to prioritise sourcing conversations."
      />

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Category</div>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[160px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="pcc-filter-category"
          >
            <option value="">All categories</option>
            {incomeCats.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Min spread %</div>
          <input
            type="number"
            step="1"
            min="0"
            max="1000"
            value={minSpread}
            onChange={(e) => setMinSpread(Number(e.target.value) || 0)}
            className="text-sm px-2 py-2 rounded-md w-24"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="pcc-filter-min-spread"
          />
        </div>
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Sort</div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="text-sm px-2 py-2 rounded-md"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="pcc-filter-sort"
          >
            <option value="spread_desc">Biggest spread first</option>
            <option value="spread_asc">Smallest spread first</option>
            <option value="name">Item name (A–Z)</option>
          </select>
        </div>
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted, letterSpacing: 0.4 }}>Limit</div>
          <input
            type="number"
            step="10"
            min="1"
            max="500"
            value={limit}
            onChange={(e) => setLimit(Math.min(500, Math.max(1, Number(e.target.value) || 100)))}
            className="text-sm px-2 py-2 rounded-md w-24"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="pcc-filter-limit"
          />
        </div>
        <div className="flex-1" />
        <button
          type="button"
          onClick={exportCsv}
          disabled={!hasRows}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md"
          style={{ background: colors.brand, color: "#fff", border: 0,
                   opacity: hasRows ? 1 : 0.5,
                   cursor: hasRows ? "pointer" : "not-allowed" }}
          data-testid="pcc-csv-export"
        >
          <Download size={12} /> Export CSV
        </button>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="pcc-loading">Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}
              data-testid="pcc-error">{error}</div>
      ) : !hasRows ? (
        <div className="rounded-lg p-6 text-sm text-center"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.muted }}
              data-testid="pcc-empty">
          {isFiltered
            ? "No items match this filter. Try lowering the min spread or clearing the category filter."
            : "No items have supplier prices set. Set prices in Ops Hub → Price Book."}
        </div>
      ) : (
        <div className="rounded-lg overflow-hidden"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="pcc-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="px-3 py-2 w-8">&nbsp;</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Item</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Category</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Suppliers</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Min</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Max</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Spread</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Spread %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const tier = spreadTier(r.spread_pct);
                const isOpen = expanded.has(r.item_id);
                return (
                  <React.Fragment key={r.item_id}>
                    <tr
                      data-testid={`pcc-row-${r.item_id}`}
                      onClick={() => toggleExpanded(r.item_id)}
                      style={{ cursor: "pointer" }}
                      className="hover:bg-slate-50"
                    >
                      <td className="px-3 py-2 text-slate-400">
                        {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      </td>
                      <td className="px-3 py-2 font-semibold"
                          style={{ color: colors.onSurface }}
                          data-testid={`pcc-row-name-${r.item_id}`}>
                        {r.item_name}
                      </td>
                      <td className="px-3 py-2">
                        <CategoryPill name={r.income_category_name} />
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {r.supplier_count}
                      </td>
                      <td className="px-3 py-2 text-right font-mono"
                          style={{ color: "#166534" }}
                          data-testid={`pcc-row-min-${r.item_id}`}>
                        {money((r.min_cost_cents || 0) / 100)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono"
                          style={{ color: "#991B1B" }}
                          data-testid={`pcc-row-max-${r.item_id}`}>
                        {money((r.max_cost_cents || 0) / 100)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono"
                          style={{ color: colors.onSurface }}>
                        {money((r.spread_cents || 0) / 100)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold"
                          style={{ backgroundColor: tier.bg, color: tier.fg }}
                          data-testid={`pcc-row-spread-pill-${r.item_id}`}
                        >
                          {Number(r.spread_pct || 0).toFixed(1)}%
                        </span>
                      </td>
                    </tr>
                    {isOpen ? (
                      <tr data-testid={`pcc-row-detail-${r.item_id}`}
                          style={{ background: colors.surface }}>
                        <td></td>
                        <td colSpan={7} className="px-3 py-3">
                          <div className="text-[10px] uppercase font-bold mb-2"
                                style={{ color: colors.muted,
                                          letterSpacing: 0.4 }}>
                            Supplier breakdown
                          </div>
                          <table className="w-full text-xs">
                            <tbody>
                              {r.supplier_prices.map((p) => (
                                <tr key={p.supplier_slug}
                                     style={{ opacity: p.is_deleted ? 0.55 : 1 }}
                                     data-testid={`pcc-detail-row-${r.item_id}-${p.supplier_slug}`}>
                                  <td className="py-1">
                                    {p.display_name}
                                    {p.is_deleted ? (
                                      <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase"
                                            style={{ backgroundColor: "#E5E7EB",
                                                      color: "#6B7280" }}
                                            data-testid={`pcc-detail-deleted-${r.item_id}-${p.supplier_slug}`}>
                                        Deleted
                                      </span>
                                    ) : null}
                                  </td>
                                  <td className="py-1 text-right font-mono"
                                      style={{ color: colors.onSurface }}>
                                    {money((p.cost_cents || 0) / 100)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    ) : null}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          {total > rows.length ? (
            <div className="p-2 text-[11px] text-center"
                  style={{ color: colors.muted }}
                  data-testid="pcc-truncated">
              Showing top {rows.length} of {total} matching items.
              Raise the Limit filter to see more.
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
