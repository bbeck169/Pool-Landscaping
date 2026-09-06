import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { KpiCard } from "./KpiCard";
import { downloadCsv } from "./downloadCsv";
import { formatCurrency, formatPercent } from "./formatters";

/**
 * Phase R1.b · Feb-2026 — P&L panel for the Financial tab.
 *
 * Two-column layout on md+:
 *   Left  — big KPI (net income, ``pnl_by_period``) w/ sparkline
 *   Right — line-items table (``pnl_line_items``)
 *
 * Rows in the line-items table: Revenue → COGS → Gross Profit →
 * OpEx → Depreciation → EBIT → EBIT margin. The backend metric
 * ships whichever labels its bookkeeping backend emits — we
 * render them in the order returned and let the metric layer own
 * ordering. Percent rows (``EBIT margin``) are recognised by their
 * ``format=='percent'`` per-row hint and rendered accordingly.
 */
function buildQuery(f) {
  const p = new URLSearchParams();
  p.set("period", f.period || "mtd");
  if (f.period === "custom" && f.start && f.end) {
    p.set("start", f.start);
    p.set("end", f.end);
  }
  if (f.service_type) p.set("service_type", f.service_type);
  if (f.tech_id) p.set("tech_id", f.tech_id);
  return p.toString();
}

export function PnlPanel({ filters, testid = "pnl-panel" }) {
  const [scalar, setScalar] = React.useState({ loading: true });
  const [rows, setRows] = React.useState({ loading: true });

  const qs = buildQuery(filters);

  React.useEffect(() => {
    let live = true;
    setScalar({ loading: true });
    setRows({ loading: true });
    (async () => {
      const [s, r] = await Promise.all([
        api.get(`/reports/kpi/pnl_by_period?${qs}`).catch((e) => ({ __err: e?.message })),
        api.get(`/reports/kpi/pnl_line_items?${qs}`).catch((e) => ({ __err: e?.message })),
      ]);
      if (!live) return;
      setScalar({ loading: false, ...(s || {}) });
      setRows({ loading: false, ...(r || {}) });
    })();
    return () => { live = false; };
  }, [qs]);

  const exportCsv = () => {
    const body = (rows.rows || []).map((r) => [
      r.label,
      Number(r.value ?? 0).toFixed(2),
      r.format || "currency",
    ]);
    downloadCsv(`pnl-${filters.period || "mtd"}.csv`, ["Label", "Value", "Format"], body);
  };

  return (
    <section className="space-y-4" data-testid={testid}>
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Profit &amp; Loss
          </h2>
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            Net income for the selected period, plus the standard
            revenue → EBIT line-item breakdown.
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={exportCsv}
          disabled={rows.loading || !(rows.rows && rows.rows.length)}
          data-testid={`${testid}-export`}
        >
          Export CSV
        </Button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-1">
          <KpiCard
            testid={`${testid}-kpi`}
            label={scalar.label || "Net Income"}
            value={scalar.value}
            priorValue={scalar.prior_value}
            deltaPct={scalar.delta_pct}
            sparkline={scalar.sparkline}
            format={scalar.format || "currency"}
            direction={scalar.direction || "up_is_good"}
            loading={scalar.loading}
            error={scalar.__err}
          />
        </div>

        <div
          className="md:col-span-2 rounded-xl border overflow-hidden"
          style={{ backgroundColor: colors.surface, borderColor: colors.border }}
        >
          <table className="w-full text-sm" data-testid={`${testid}-table`}>
            <thead style={{ backgroundColor: colors.surfaceSecondary }}>
              <tr>
                <th className="text-left px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>
                  Line item
                </th>
                <th className="text-right px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.loading ? (
                <tr><td colSpan={2} className="px-3 py-6 text-center text-xs"
                        style={{ color: colors.onSurfaceSecondary }}>Loading…</td></tr>
              ) : rows.__err ? (
                <tr><td colSpan={2} className="px-3 py-6 text-center text-xs"
                        style={{ color: colors.error }}>{rows.__err}</td></tr>
              ) : (rows.rows || []).length === 0 ? (
                <tr><td colSpan={2} className="px-3 py-6 text-center text-xs"
                        style={{ color: colors.onSurfaceSecondary }}
                        data-testid={`${testid}-empty`}>No line items for this period</td></tr>
              ) : rows.rows.map((r, i) => {
                const isPct = r.format === "percent";
                const emphasize = /net income|ebit\b/i.test(String(r.label || ""));
                return (
                  <tr key={`${r.label}-${i}`}
                      style={{ borderTop: `1px solid ${colors.border}` }}
                      data-testid={`${testid}-row-${r.label?.toString().toLowerCase().replace(/[^a-z0-9]+/g,'-')}`}>
                    <td className="px-3 py-2"
                        style={{ color: emphasize ? colors.brand : colors.onSurface,
                                  fontWeight: emphasize ? 700 : 400 }}>
                      {r.label}
                    </td>
                    <td className="text-right px-3 py-2 font-semibold"
                        style={{ color: emphasize ? colors.brand : colors.onSurface }}>
                      {isPct ? formatPercent(r.value) : formatCurrency(r.value)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

export default PnlPanel;
