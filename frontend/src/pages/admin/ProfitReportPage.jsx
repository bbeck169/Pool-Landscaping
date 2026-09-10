/**
 * PB1 · Feb-2026 — Profit Report page.
 *
 * Admin-only surface at ``/admin/reports/profit``. Consumes the
 * ``GET /api/reports/profit`` endpoint.  Renders:
 *
 *   * A date-range picker (radio pills: This Month / Last Month /
 *     QTD / YTD / Custom). The Custom option surfaces two date
 *     inputs; every other option hides them.
 *   * A dimension toggle: Service Category ↔ Income Category.
 *     Changing it re-fetches with the new dimension.
 *   * Summary tiles across the top: Revenue · COGS · Labor · Gross
 *     Profit · Margin %.
 *   * Sortable breakdown table (Category, Revenue, COGS, Labor,
 *     Profit, Margin %, Line Count).
 *   * Export CSV button — hits the ``.csv`` sibling endpoint and
 *     triggers a browser download.
 *
 * Wholesale + labor cost numbers rendered here are STRICTLY
 * internal. This page must never be linked from a customer-facing
 * surface.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Download, TrendingUp, ShieldCheck, DollarSign, Package,
  Wrench, PiggyBank, Percent, Wrench as FixIcon, X as CloseIcon, Loader2,
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { Skeleton } from "@/components/ui-kit";
import { useAuth } from "@/auth";
import EbitPanel from "@/components/admin/EbitPanel";

const RANGE_OPTIONS = [
  { key: "this_month", label: "This Month" },
  { key: "last_month", label: "Last Month" },
  { key: "qtd", label: "Quarter to Date" },
  { key: "ytd", label: "Year to Date" },
  { key: "custom", label: "Custom" },
];

function fmtPct(n) {
  return `${Number(n || 0).toFixed(1)}%`;
}

function SummaryTile({ icon: Icon, label, value, hint, colorHex, testid }) {
  return (
    <div
      className="rounded-xl p-4 flex-1 min-w-[160px]"
      style={{
        background: `${colorHex}14`,
        border: `1px solid ${colorHex}30`,
      }}
      data-testid={testid}
    >
      <div className="flex items-center gap-1.5 text-xs uppercase font-bold tracking-wide"
            style={{ color: colorHex }}>
        <Icon size={12} /> {label}
      </div>
      <div className="text-2xl font-black mt-1"
            style={{ color: colors.onSurface }}>
        {value}
      </div>
      {hint ? (
        <div className="text-[11px]" style={{ color: colors.muted }}>
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export default function ProfitReportPage() {
  const nav = useNavigate();
  const { user } = useAuth() || {};
  const isAdmin = user?.role === "admin" || user?.role === "super_admin" ||
                    user?.role === "owner";

  // Phase 53f · Feb-2026 — drill-down entry point. When the URL
  // carries ``?from=YYYY-MM-DD&to=YYYY-MM-DD`` (Phase 53f EBIT-tile
  // click), read once on mount and pre-select the custom range so
  // the report renders scoped to the tapped month.
  const _urlFrom = typeof window !== "undefined"
    ? new URLSearchParams(window.location.search).get("from") : null;
  const _urlTo = typeof window !== "undefined"
    ? new URLSearchParams(window.location.search).get("to") : null;
  const _dateRe = /^\d{4}-\d{2}-\d{2}$/;
  const _initialFrom = _urlFrom && _dateRe.test(_urlFrom) ? _urlFrom : "";
  const _initialTo = _urlTo && _dateRe.test(_urlTo) ? _urlTo : "";
  const _hasDeepLink = Boolean(_initialFrom && _initialTo);

  const [rangeKey, setRangeKey] = useState(_hasDeepLink ? "custom" : "this_month");
  const [customFrom, setCustomFrom] = useState(_initialFrom);
  const [customTo, setCustomTo] = useState(_initialTo);
  const [dimension, setDimension] = useState("service_category");
  const [sort, setSort] = useState({ col: "revenue", dir: "desc" });
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  // Feb-2026 · Phase 3 — snapshot coverage tile. Cheap 60s-cached
  // GET; loaded once per session and refreshed only on manual
  // reload. Failure is non-fatal — tile silently hides.
  const [health, setHealth] = useState(null);

  const buildQuery = () => {
    const params = new URLSearchParams();
    params.set("dimension", dimension);
    params.set("range", rangeKey);
    if (rangeKey === "custom") {
      if (!customFrom || !customTo) return null;
      params.set("from", customFrom);
      params.set("to", customTo);
    }
    return params.toString();
  };

  const load = async () => {
    const qs = buildQuery();
    if (!qs) return;
    setBusy(true); setErr("");
    try {
      const res = await api.get(`/reports/profit?${qs}`);
      setData(res);
    } catch (e) {
      setErr(e?.message || "Failed to load profit report.");
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!isAdmin) return;
    // Auto-fetch on preset ranges; wait for both dates on Custom.
    if (rangeKey === "custom" && (!customFrom || !customTo)) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dimension, rangeKey, customFrom, customTo]);

  // Feb-2026 · Phase 3 — pull snapshot coverage once on mount.
  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    api.get("/reports/pricebook-health?window_days=90")
      .then((h) => { if (!cancelled) setHealth(h); })
      .catch(() => { if (!cancelled) setHealth(null); });
    return () => { cancelled = true; };
  }, [isAdmin]);

  const sorted = useMemo(() => {
    const rows = (data?.breakdown || []).slice();
    rows.sort((a, b) => {
      const av = a[sort.col];
      const bv = b[sort.col];
      const an = typeof av === "number" ? av : String(av || "").toLowerCase();
      const bn = typeof bv === "number" ? bv : String(bv || "").toLowerCase();
      if (an < bn) return sort.dir === "asc" ? -1 : 1;
      if (an > bn) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });
    return rows;
  }, [data, sort]);

  const bump = (col) => setSort((s) =>
    s.col === col ? { col, dir: s.dir === "asc" ? "desc" : "asc" }
                    : { col, dir: "desc" });

  // ── PB1-QoL · Uncategorized "Fix" modal state. ──────────────
  const [fixModalOpen, setFixModalOpen] = useState(false);
  const [fixBusy, setFixBusy] = useState(false);
  const [fixItems, setFixItems] = useState([]);
  const [fixErr, setFixErr] = useState("");

  const openFixModal = async (row) => {
    const ids = row.uncategorized_item_ids || [];
    setFixModalOpen(true);
    setFixItems([]);
    setFixErr("");
    if (ids.length === 0) return;
    setFixBusy(true);
    // Fetch item names in parallel (capped at 100 ids by backend).
    try {
      const rows = await Promise.all(
        ids.map((id) =>
          api.get(`/items/${id}`)
            .then((it) => ({ id, name: it?.name || `Item ${id.slice(0, 8)}` }))
            .catch(() => ({ id, name: `Item ${id.slice(0, 8)} (not found)` })),
        ),
      );
      setFixItems(rows);
    } catch (e) {
      setFixErr(e?.message || "Failed to load item names.");
    } finally {
      setFixBusy(false);
    }
  };
  const closeFixModal = () => { if (!fixBusy) setFixModalOpen(false); };

  const exportCsv = () => {
    const qs = buildQuery();
    if (!qs) return;
    // Use fetch directly so we can hand the blob to the download flow.
    // ``api.get`` is JSON-only; the CSV route returns text/csv.
    const url = `${process.env.REACT_APP_BACKEND_URL}/api/reports/profit.csv?${qs}`;
    const token = localStorage.getItem("access_token") ||
                    localStorage.getItem("token") || "";
    fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.blob())
      .then((blob) => {
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = `profit-${dimension}-${data?.range?.from || "range"}_to_${data?.range?.to || "range"}.csv`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
      });
  };

  if (!isAdmin) {
    return (
      <div className="p-8 max-w-2xl mx-auto"
             data-testid="profit-report-forbidden">
        <div className="rounded-xl p-4 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}>
          <b>Admin only.</b> This report shows internal wholesale +
          labor cost data.
        </div>
      </div>
    );
  }

  const totals = data?.totals || {};

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-5"
           data-testid="profit-report-page">
      <button
        onClick={() => nav(-1)}
        className="flex items-center gap-1 text-sm font-semibold"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> Back
      </button>

      <div className="flex items-center gap-2 flex-wrap">
        <TrendingUp size={22} color="#0891B2" />
        <h1 className="text-2xl font-bold"
             style={{ color: colors.onSurface }}>
          Profit Report
        </h1>
        <span className="text-xs px-2 py-0.5 rounded-full inline-flex items-center gap-1"
               style={{ background: "#FEF3C7", color: "#92400E" }}>
          <ShieldCheck size={11} /> Internal — not shown to customers
        </span>
      </div>

      {/* Feb-2026 · Phase 3 — Snapshot coverage tile. Explains
          how much of the profit report is muddled by legacy
          Uncategorized lines. Silently hidden if the endpoint
          errors or returns zero lines. */}
      {health && health.lines_total > 0 ? (
        <div
          className="rounded-2xl p-4 flex items-center gap-3 flex-wrap"
          style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="profit-report-health-tile"
          title={`Trailing ${health.window_days} days · ${health.lines_with_any_snapshot} of ${health.lines_total} lines have cost snapshots. Low coverage inflates the Uncategorized bucket.`}
        >
          <div className="text-xs uppercase font-bold tracking-wide"
               style={{ color: colors.muted }}>
            Snapshot coverage (trailing {health.window_days}d)
          </div>
          <div className="flex items-baseline gap-1">
            <span
              className="text-2xl font-bold"
              style={{ color: health.coverage_pct.any >= 80
                ? "#0891B2"
                : health.coverage_pct.any >= 50 ? "#92400E" : "#DC2626" }}
              data-testid="profit-report-health-coverage-pct"
            >
              {health.coverage_pct.any}%
            </span>
            <span className="text-xs" style={{ color: colors.muted }}>
              ({health.lines_with_any_snapshot} / {health.lines_total} lines)
            </span>
          </div>
          <div className="text-[11px] max-w-md" style={{ color: colors.muted }}>
            Legacy lines missing cost snapshots inflate the Uncategorized
            bucket. Set overrides on future docs to reduce this.
          </div>
        </div>
      ) : null}

      {/* ── Filters ── */}
      <div className="rounded-2xl p-4 space-y-3"
             style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="profit-report-filters">
        <div className="flex flex-wrap gap-1.5">
          {RANGE_OPTIONS.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => setRangeKey(r.key)}
              data-testid={`profit-report-range-${r.key}`}
              aria-pressed={rangeKey === r.key}
              className="text-xs px-2.5 py-1 rounded-full font-semibold transition-colors"
              style={rangeKey === r.key
                ? { background: "#0891B2", color: "#fff",
                    border: "1px solid #0891B2" }
                : { background: colors.surface, color: colors.muted,
                    border: `1px solid ${colors.border}` }}
            >
              {r.label}
            </button>
          ))}
        </div>

        {rangeKey === "custom" ? (
          <div className="flex gap-2 items-end pt-2"
                data-testid="profit-report-custom-picker">
            <div className="flex flex-col">
              <label className="text-[10px] uppercase font-bold mb-1"
                      style={{ color: colors.muted }}>From</label>
              <input
                type="date"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="text-sm px-2 py-1.5 rounded-md"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid="profit-report-custom-from"
              />
            </div>
            <div className="flex flex-col">
              <label className="text-[10px] uppercase font-bold mb-1"
                      style={{ color: colors.muted }}>To</label>
              <input
                type="date"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="text-sm px-2 py-1.5 rounded-md"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid="profit-report-custom-to"
              />
            </div>
          </div>
        ) : null}

        <div className="flex items-center gap-2 pt-2 border-t"
              style={{ borderColor: colors.border }}>
          <span className="text-xs uppercase font-bold"
                 style={{ color: colors.muted }}>Group by:</span>
          <div className="inline-flex rounded-lg overflow-hidden"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid="profit-report-dimension-toggle">
            <button
              type="button"
              onClick={() => setDimension("service_category")}
              className="text-xs px-3 py-1 font-semibold"
              style={dimension === "service_category"
                ? { background: "#0891B2", color: "#fff" }
                : { background: colors.surface, color: colors.muted }}
              data-testid="profit-report-dim-service"
              aria-pressed={dimension === "service_category"}
            >
              Service Category
            </button>
            <button
              type="button"
              onClick={() => setDimension("income_category")}
              className="text-xs px-3 py-1 font-semibold"
              style={dimension === "income_category"
                ? { background: "#0891B2", color: "#fff" }
                : { background: colors.surface, color: colors.muted }}
              data-testid="profit-report-dim-income"
              aria-pressed={dimension === "income_category"}
            >
              Income Category
            </button>
          </div>

          <div className="flex-1" />

          <button
            type="button"
            onClick={exportCsv}
            disabled={!data || busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white"
            style={{ background: "#0891B2",
                      opacity: (!data || busy) ? 0.5 : 1 }}
            data-testid="profit-report-export-csv"
          >
            <Download size={12} /> Export CSV
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      {err ? (
        <div className="text-sm p-3 rounded-xl"
              style={{ background: "#FEE2E2", color: "#7F1D1D" }}
              data-testid="profit-report-error">
          {err}
        </div>
      ) : busy && !data ? (
        <Skeleton className="h-32 rounded-xl"
                    data-testid="profit-report-loading" />
      ) : data ? (
        <>
          <div className="flex flex-wrap gap-3">
            <SummaryTile icon={DollarSign} label="Revenue"
                          value={money(totals.revenue || 0)}
                          hint={`${totals.line_count || 0} lines`}
                          colorHex="#0891B2"
                          testid="profit-report-tile-revenue" />
            <SummaryTile icon={Package} label="COGS"
                          value={money(totals.cogs || 0)}
                          colorHex="#B45309"
                          testid="profit-report-tile-cogs" />
            <SummaryTile icon={Wrench} label="Labor"
                          value={money(totals.labor || 0)}
                          colorHex="#7C3AED"
                          testid="profit-report-tile-labor" />
            <SummaryTile icon={PiggyBank} label="Gross Profit"
                          value={money(totals.gross_profit || 0)}
                          colorHex="#166534"
                          testid="profit-report-tile-profit" />
            <SummaryTile icon={Percent} label="Margin"
                          value={fmtPct(totals.margin_pct || 0)}
                          colorHex="#065F46"
                          testid="profit-report-tile-margin" />
          </div>

          <div className="rounded-2xl overflow-hidden"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="profit-report-breakdown">
            <table className="w-full text-sm"
                    data-testid="profit-report-table">
              <thead style={{ background: colors.surfaceAlt || colors.surface }}>
                <tr>
                  {[
                    { k: "category_name", label: "Category" },
                    { k: "revenue", label: "Revenue", right: true },
                    { k: "cogs", label: "COGS", right: true },
                    { k: "labor", label: "Labor", right: true },
                    { k: "profit", label: "Profit", right: true },
                    { k: "margin_pct", label: "Margin %", right: true },
                    { k: "line_count", label: "Lines", right: true },
                  ].map((c) => (
                    <th key={c.k}
                         onClick={() => bump(c.k)}
                         className={`px-3 py-2 select-none cursor-pointer ${c.right ? "text-right" : "text-left"}`}
                         style={{ color: colors.muted,
                                   fontSize: "11px",
                                   fontWeight: 700,
                                   textTransform: "uppercase" }}
                         data-testid={`profit-report-col-${c.k}`}>
                      {c.label}
                      {sort.col === c.k ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.length === 0 ? (
                  <tr>
                    <td colSpan={7}
                         className="text-center py-6 text-sm"
                         style={{ color: colors.muted }}
                         data-testid="profit-report-empty">
                      No invoices in the selected range.
                    </td>
                  </tr>
                ) : sorted.map((row) => (
                  <tr key={row.category_id}
                       className="border-t"
                       style={{ borderColor: colors.border }}
                       data-testid={`profit-report-row-${row.category_id}`}>
                    <td className="px-3 py-2 font-semibold"
                         style={{ color: colors.onSurface }}>
                      <span>{row.category_name}</span>
                      {row.category_id === "__uncategorized__" ? (
                        <button
                          type="button"
                          onClick={() => openFixModal(row)}
                          className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold text-white"
                          style={{ background: "#B45309" }}
                          data-testid="profit-report-uncategorized-fix-btn"
                          title="See which items are feeding this bucket"
                        >
                          <FixIcon size={10} /> Fix
                        </button>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {money(row.revenue)}
                    </td>
                    <td className="px-3 py-2 text-right"
                         style={{ color: "#B45309" }}>
                      {money(row.cogs)}
                    </td>
                    <td className="px-3 py-2 text-right"
                         style={{ color: "#7C3AED" }}>
                      {money(row.labor)}
                    </td>
                    <td className="px-3 py-2 text-right font-semibold"
                         style={{ color: row.profit >= 0 ? "#166534" : "#991B1B" }}>
                      {money(row.profit)}
                    </td>
                    <td className="px-3 py-2 text-right"
                         style={{ color: colors.muted }}>
                      {fmtPct(row.margin_pct)}
                    </td>
                    <td className="px-3 py-2 text-right"
                         style={{ color: colors.muted }}>
                      {row.line_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {/* ── Phase 53b · Editable EBIT panel (super_admin/admin/manager) ── */}
      <EbitPanel />

      {/* ── PB1-QoL · Uncategorized "Fix" modal ── */}
      {fixModalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeFixModal(); }}
          data-testid="profit-report-uncategorized-fix-modal"
        >
          <div
            className="w-full max-w-lg rounded-2xl overflow-hidden shadow-2xl"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <header
              className="px-5 py-3 flex items-center justify-between"
              style={{ borderBottom: `1px solid ${colors.border}` }}
            >
              <div className="flex items-center gap-2">
                <FixIcon size={14} color="#B45309" />
                <div className="font-bold" style={{ color: colors.onSurface }}>
                  Items missing a{" "}
                  {dimension === "service_category" ? "service" : "income"} category
                </div>
              </div>
              <button
                type="button"
                onClick={closeFixModal}
                className="p-1"
                style={{ color: colors.muted }}
                aria-label="Close"
                data-testid="profit-report-uncategorized-fix-close"
              >
                <CloseIcon size={16} />
              </button>
            </header>
            <div className="px-5 py-3 max-h-[60vh] overflow-y-auto">
              {fixBusy ? (
                <div className="flex items-center gap-2 py-4 text-sm"
                      style={{ color: colors.muted }}
                      data-testid="profit-report-uncategorized-fix-loading">
                  <Loader2 size={14} className="animate-spin" />
                  Loading item names…
                </div>
              ) : fixErr ? (
                <div className="rounded-md p-3 text-sm"
                      style={{ background: "#FEE2E2", color: "#7F1D1D" }}>
                  {fixErr}
                </div>
              ) : fixItems.length === 0 ? (
                <div className="py-4 text-sm"
                      style={{ color: colors.muted }}
                      data-testid="profit-report-uncategorized-fix-empty">
                  All Uncategorized lines came from ad-hoc entries with no
                  linked pricebook item — nothing to fix here.
                </div>
              ) : (
                <ul className="divide-y" style={{ borderColor: colors.border }}
                     data-testid="profit-report-uncategorized-fix-list">
                  {fixItems.map((it) => (
                    <li key={it.id}
                         className="flex items-center justify-between py-2"
                         data-testid={`profit-report-fix-item-${it.id}`}>
                      <div>
                        <div className="text-sm font-semibold"
                              style={{ color: colors.onSurface }}>
                          {it.name}
                        </div>
                        <div className="text-[11px] font-mono"
                              style={{ color: colors.muted }}>
                          {it.id}
                        </div>
                      </div>
                      <a
                        href={`/pricebook?highlight=${encodeURIComponent(it.id)}`}
                        className="text-xs font-semibold px-2 py-1 rounded-md"
                        style={{ background: "#0891B2", color: "#fff" }}
                        data-testid={`profit-report-fix-item-link-${it.id}`}
                      >
                        Set category
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <footer
              className="px-5 py-3 flex justify-end"
              style={{ borderTop: `1px solid ${colors.border}`,
                        background: colors.surfaceSecondary || "#fafafa" }}
            >
              <button
                type="button"
                onClick={closeFixModal}
                className="px-3 py-1.5 text-sm font-semibold rounded-lg"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="profit-report-uncategorized-fix-done"
              >
                Done
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
