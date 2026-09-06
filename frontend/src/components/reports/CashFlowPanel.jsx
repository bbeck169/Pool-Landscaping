import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { TrendChart } from "./TrendChart";
import { downloadCsv } from "./downloadCsv";
import { formatCurrency } from "./formatters";

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

/**
 * Phase R1.b · Feb-2026 — Cash Flow panel.
 *
 * Backed by ``/reports/kpi/cashflow_by_period``. Renders:
 *   * Two-series area chart (Invoiced vs Collected) over time.
 *   * A running-balance line series overlayed (secondary y).
 *   * Summary row (invoiced_total / collected_total / net_total).
 *   * CSV export.
 */
export function CashFlowPanel({ filters, testid = "cash-flow-panel" }) {
  const [state, setState] = React.useState({ loading: true });
  const qs = buildQuery(filters);

  React.useEffect(() => {
    let live = true;
    setState({ loading: true });
    (async () => {
      try {
        const r = await api.get(`/reports/kpi/cashflow_by_period?${qs}`);
        if (live) setState({ loading: false, data: r });
      } catch (e) {
        if (live) setState({ loading: false, error: e?.message || "Failed" });
      }
    })();
    return () => { live = false; };
  }, [qs]);

  const rows = state.data?.rows || [];
  const xLabels = rows.map((r) => r.bucket);
  const series = [
    { name: "Invoiced",  data: rows.map((r) => Number(r.invoiced || 0)) },
    { name: "Collected", data: rows.map((r) => Number(r.collected || 0)) },
    { name: "Running Balance", data: rows.map((r) => Number(r.running_balance || 0)) },
  ];

  const summary = state.data?.summary || {};

  const exportCsv = () => {
    const body = rows.map((r) => [
      r.bucket,
      Number(r.invoiced || 0).toFixed(2),
      Number(r.collected || 0).toFixed(2),
      Number(r.net || 0).toFixed(2),
      Number(r.running_balance || 0).toFixed(2),
    ]);
    downloadCsv(
      `cash-flow-${filters.period || "mtd"}.csv`,
      ["Bucket", "Invoiced", "Collected", "Net", "Running Balance"],
      body,
    );
  };

  return (
    <section className="space-y-4" data-testid={testid}>
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Cash Flow
          </h2>
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {state.loading ? "Loading…" : state.error ? "Error" : (
              <>
                Invoiced <b>{formatCurrency(summary.invoiced_total)}</b>
                {" · "}
                Collected <b>{formatCurrency(summary.collected_total)}</b>
                {" · "}
                Net <b>{formatCurrency(summary.net_total)}</b>
              </>
            )}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={exportCsv}
          disabled={state.loading || rows.length === 0}
          data-testid={`${testid}-export`}
        >
          Export CSV
        </Button>
      </header>

      {state.loading ? (
        <div className="rounded-xl border p-8 text-center text-sm"
             style={{ borderColor: colors.border, color: colors.onSurfaceSecondary }}>
          Loading cash flow…
        </div>
      ) : state.error ? (
        <div className="rounded-xl border p-8 text-center text-sm"
             style={{ borderColor: colors.border, color: colors.error }}>
          {state.error}
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border p-8 text-center text-sm"
             style={{ borderColor: colors.border, color: colors.onSurfaceSecondary }}
             data-testid={`${testid}-empty`}>
          No cash-flow activity for this period
        </div>
      ) : (
        <TrendChart
          testid={`${testid}-chart`}
          series={series}
          xLabels={xLabels}
          type="area"
          height={280}
          valueFormat="currency"
        />
      )}
    </section>
  );
}

export default CashFlowPanel;
