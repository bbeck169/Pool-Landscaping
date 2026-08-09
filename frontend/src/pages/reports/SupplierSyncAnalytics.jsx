/**
 * Phase 54g · Feb-2026 — Supplier sync analytics dashboard.
 *
 * Aggregate view over `supplier_sync_jobs`. Read-only for everyone
 * (super_admin + admin get the range picker; manager sees the same
 * data with the picker disabled). Route: /reports/supplier-syncs.
 */
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, MinusCircle, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import { SUPPLIER_METADATA } from "@/pages/settings/supplier_metadata";

const SIGNAL_PALETTE = {
  healthy:  { bg: "#DCFCE7", fg: "#166534", label: "Healthy",  Icon: CheckCircle2 },
  warning:  { bg: "#FEF3C7", fg: "#92400E", label: "Warning",  Icon: AlertTriangle },
  critical: { bg: "#FEE2E2", fg: "#991B1B", label: "Critical", Icon: MinusCircle },
};

function fmtDT(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function Sparkline({ data, testid }) {
  // Compact inline SVG — no external chart dep. Renders daily success
  // (green) + error (red) stacked-ish over the last N buckets.
  const w = 120, h = 32, pad = 2;
  if (!data || data.length === 0) {
    return <svg width={w} height={h} data-testid={testid}><rect width={w} height={h} fill="transparent" /></svg>;
  }
  const maxRuns = Math.max(...data.map((d) => d.runs || 0), 1);
  const bw = Math.max(1, (w - pad * 2) / data.length - 1);
  return (
    <svg width={w} height={h} data-testid={testid}>
      {data.map((d, i) => {
        const x = pad + i * (bw + 1);
        const totalH = (h - pad * 2) * ((d.runs || 0) / maxRuns);
        const errH = totalH * ((d.error || 0) / Math.max(d.runs || 1, 1));
        const sucH = totalH - errH;
        return (
          <g key={d.date}>
            <rect x={x} y={h - pad - sucH} width={bw} height={sucH} fill="#16A34A" />
            <rect x={x} y={h - pad - totalH} width={bw} height={errH} fill="#DC2626" />
          </g>
        );
      })}
    </svg>
  );
}

function SupplierCard({ row, expanded, onToggleExpand }) {
  const meta = SUPPLIER_METADATA[row.slug] || {};
  const palette = SIGNAL_PALETTE[row.health_signal] || SIGNAL_PALETTE.healthy;
  const { Icon } = palette;
  return (
    <div
      className="rounded-xl p-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={`analytics-card-${row.slug}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            {meta.display_name || row.display_name}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
            {row.total_runs} run{row.total_runs === 1 ? "" : "s"}
            &middot; success {Math.round(row.success_rate * 100)}%
          </div>
        </div>
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold"
          style={{ backgroundColor: palette.bg, color: palette.fg }}
          data-testid={`analytics-signal-${row.slug}`}
        >
          <Icon size={12} /> {palette.label}
        </span>
      </div>

      <div className="text-xs mt-2" style={{ color: colors.muted }}
           data-testid={`analytics-rationale-${row.slug}`}>
        {row.health_rationale}
      </div>

      <div className="mt-3"><Sparkline data={row.trend_daily}
                             testid={`analytics-sparkline-${row.slug}`} /></div>

      <div className="grid grid-cols-2 gap-x-2 gap-y-1 mt-3 text-xs"
           style={{ color: colors.muted }}>
        <div>Last success</div>
        <div className="text-right" style={{ color: colors.onSurface }}>
          {fmtDT(row.last_success_at)}
        </div>
        <div>Last error</div>
        <div className="text-right" style={{ color: colors.onSurface }}>
          {fmtDT(row.last_error_at)}
        </div>
        <div>Items / run</div>
        <div className="text-right" style={{ color: colors.onSurface }}>
          +{row.avg_items_added} · ~{row.avg_items_updated} · -{row.avg_items_removed}
        </div>
      </div>

      {row.last_error_message ? (
        <div className="mt-2">
          <button
            onClick={onToggleExpand}
            className="text-xs underline"
            style={{ color: colors.brandPrimary }}
            data-testid={`analytics-expand-error-${row.slug}`}
          >
            {expanded ? "Hide error" : "Show last error"}
          </button>
          {expanded && (
            <pre
              className="text-[10px] mt-1 p-2 rounded whitespace-pre-wrap"
              style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D" }}
              data-testid={`analytics-error-body-${row.slug}`}
            >{row.last_error_message}</pre>
          )}
        </div>
      ) : null}
    </div>
  );
}

export default function SupplierSyncAnalytics() {
  const { user } = useAuth();
  const role = user?.role || "";
  const isEditor = role === "super_admin" || role === "admin";
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState({});

  const load = useCallback((d) => {
    setError("");
    api.get(`/suppliers/analytics?days=${d || days}`)
      .then((body) => setData(body))
      .catch((e) => setError(e.message || "Failed to load analytics"));
  }, [days]);

  useEffect(() => { load(days); }, [load, days]);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="supplier-sync-analytics-page">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <div className="text-xl font-semibold" style={{ color: colors.onSurface }}>
            Supplier sync analytics · last {days} days
          </div>
          <div className="text-sm" style={{ color: colors.muted }}>
            Aggregated across every recorded sync job. Critical + warning
            suppliers surface first.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            disabled={!isEditor}
            className="px-2 py-1 rounded-md text-sm disabled:opacity-60"
            style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}
            data-testid="analytics-range-picker"
          >
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={60}>60 days</option>
            <option value={90}>90 days</option>
          </select>
          <button
            onClick={() => load(days)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-sm"
            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid="analytics-refresh-btn"
          >
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {error && (
        <div
          className="p-3 rounded-lg text-sm mb-4"
          style={{ backgroundColor: "#FEE2E2", color: colors.error }}
          data-testid="analytics-error"
        >
          {error}
        </div>
      )}

      {!data ? (
        <div className="text-sm" style={{ color: colors.muted }}
             data-testid="analytics-loading">
          Loading…
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {data.suppliers.map((row) => (
              <SupplierCard
                key={row.slug}
                row={row}
                expanded={!!expanded[row.slug]}
                onToggleExpand={() => setExpanded((s) => ({ ...s, [row.slug]: !s[row.slug] }))}
              />
            ))}
          </div>

          <div className="mt-6">
            <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>
              Per-day summary
            </div>
            <div
              className="rounded-lg overflow-hidden"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="analytics-daily-table"
            >
              <table className="w-full text-xs">
                <thead style={{ backgroundColor: colors.surfaceSecondary }}>
                  <tr>
                    <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Date</th>
                    <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Supplier</th>
                    <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Runs</th>
                    <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Success</th>
                    <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Error</th>
                    <th className="text-right px-3 py-2" style={{ color: colors.muted }}>+Items</th>
                    <th className="text-right px-3 py-2" style={{ color: colors.muted }}>~Items</th>
                  </tr>
                </thead>
                <tbody>
                  {data.suppliers.flatMap((s) =>
                    s.trend_daily.map((d) => (
                      <tr key={`${s.slug}-${d.date}`}
                          style={{ borderTop: `1px solid ${colors.border}` }}>
                        <td className="px-3 py-1.5">{d.date}</td>
                        <td className="px-3 py-1.5">
                          {(SUPPLIER_METADATA[s.slug] || {}).display_name || s.slug}
                        </td>
                        <td className="px-3 py-1.5 text-right">{d.runs}</td>
                        <td className="px-3 py-1.5 text-right" style={{ color: "#16A34A" }}>
                          {d.success}
                        </td>
                        <td className="px-3 py-1.5 text-right" style={{ color: "#DC2626" }}>
                          {d.error}
                        </td>
                        <td className="px-3 py-1.5 text-right">{d.items_added}</td>
                        <td className="px-3 py-1.5 text-right">{d.items_updated}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
