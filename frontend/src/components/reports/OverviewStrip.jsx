import React from "react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import { formatCurrency } from "./formatters";

/**
 * Phase R1.b · Feb-2026 — Financial tab overview strip.
 *
 * Four side-by-side KPI cards that anchor the top of the
 * Financial tab:
 *
 *   1. MTD Revenue         (from ``revenue_total`` — scalar)
 *   2. MTD Collected       (from ``cashflow_by_period`` — sum of
 *                           ``collected`` across rows)
 *   3. AR Balance          (from ``ar_aging.total``)
 *   4. Top 3 aging buckets (from ``ar_aging.rows`` — mini bars)
 *
 * The strip owns its own fetch cycle so it does NOT need to be
 * threaded through the parent's ``filters`` object. It re-fetches
 * whenever the ``filters`` prop changes.
 *
 * Each tile paints the canonical K67 navy→green gradient with
 * white text on top, matching the K70.a-themed ``<KpiCard>`` used
 * elsewhere in the suite.
 */
export function OverviewStrip({ filters, testid = "financial-overview-strip" }) {
  const [state, setState] = React.useState({ loading: true });

  const qs = React.useMemo(() => {
    const p = new URLSearchParams();
    p.set("period", filters.period || "mtd");
    if (filters.period === "custom" && filters.start && filters.end) {
      p.set("start", filters.start);
      p.set("end", filters.end);
    }
    if (filters.service_type) p.set("service_type", filters.service_type);
    if (filters.tech_id) p.set("tech_id", filters.tech_id);
    return p.toString();
  }, [filters.period, filters.start, filters.end,
      filters.service_type, filters.tech_id]);

  React.useEffect(() => {
    let live = true;
    setState({ loading: true });
    (async () => {
      const [rev, cash, ar] = await Promise.all([
        api.get(`/reports/kpi/revenue_total?${qs}`).catch(() => null),
        api.get(`/reports/kpi/cashflow_by_period?${qs}`).catch(() => null),
        api.get(`/reports/kpi/ar_aging?${qs}`).catch(() => null),
      ]);
      if (!live) return;
      setState({ loading: false, rev, cash, ar });
    })();
    return () => { live = false; };
  }, [qs]);

  const collected = React.useMemo(() => {
    const s = state.cash?.summary?.collected_total;
    if (typeof s === "number") return s;
    return (state.cash?.rows || []).reduce(
      (acc, r) => acc + Number(r.collected || 0), 0,
    );
  }, [state.cash]);

  const arRows = state.ar?.rows || [];
  const top3 = arRows.slice(0, 3);
  const arMax = Math.max(1, ...arRows.map((r) => Number(r.amount || 0)));

  return (
    <div
      className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4"
      data-testid={testid}
    >
      <MiniTile
        testid={`${testid}-revenue`}
        label={`${(filters.period || "mtd").toUpperCase()} Revenue`}
        value={state.rev?.value}
        deltaPct={state.rev?.delta_pct}
        loading={state.loading}
      />
      <MiniTile
        testid={`${testid}-collected`}
        label={`${(filters.period || "mtd").toUpperCase()} Collected`}
        value={collected}
        loading={state.loading}
      />
      <MiniTile
        testid={`${testid}-ar-balance`}
        label="AR Balance"
        value={state.ar?.total}
        loading={state.loading}
        direction="down_is_good"
        subtitle={state.ar?.net_terms_days ? `Net ${state.ar.net_terms_days}` : null}
      />
      <BucketMiniTile
        testid={`${testid}-buckets`}
        buckets={top3}
        max={arMax}
        loading={state.loading}
      />
    </div>
  );
}

function MiniTile({ testid, label, value, deltaPct, subtitle, direction = "up_is_good", loading }) {
  const chip = React.useMemo(() => {
    if (typeof deltaPct !== "number") return null;
    const good = direction === "down_is_good" ? deltaPct < 0 : deltaPct > 0;
    const bad = direction === "down_is_good" ? deltaPct > 0 : deltaPct < 0;
    const bg = good ? "#DCFCE7" : bad ? "#FEE2E2" : "rgba(255,255,255,0.15)";
    const fg = good ? colors.success : bad ? colors.error : "#FFFFFF";
    const sign = deltaPct > 0 ? "+" : "";
    return { bg, fg, text: `${sign}${deltaPct.toFixed(1)}%` };
  }, [deltaPct, direction]);

  return (
    <div
      className="rounded-xl p-5 flex flex-col gap-2"
      style={{
        background: gradients.navyToGreen.css,
        border: `1px solid ${colors.border}`,
        color: "#FFFFFF",
      }}
      data-testid={testid}
      data-k70a-gradient-tile="true"
    >
      <div className="flex items-center justify-between">
        <span
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: "rgba(255,255,255,0.85)" }}
          data-testid={`${testid}-label`}
        >
          {label}
        </span>
        {chip ? (
          <span
            className="text-xs font-semibold px-2 py-0.5 rounded-full"
            style={{ backgroundColor: chip.bg, color: chip.fg }}
            data-testid={`${testid}-delta`}
          >
            {chip.text}
          </span>
        ) : null}
      </div>
      <div
        className="text-2xl md:text-3xl font-bold leading-none"
        style={{ color: "#FFFFFF" }}
        data-testid={`${testid}-value`}
      >
        {loading ? <span className="opacity-60">…</span> : formatCurrency(value)}
      </div>
      {subtitle ? (
        <div
          className="text-xs"
          style={{ color: "rgba(255,255,255,0.75)" }}
          data-testid={`${testid}-subtitle`}
        >
          {subtitle}
        </div>
      ) : null}
    </div>
  );
}

function BucketMiniTile({ testid, buckets, max, loading }) {
  return (
    <div
      className="rounded-xl p-5 flex flex-col gap-2"
      style={{
        background: gradients.navyToGreen.css,
        border: `1px solid ${colors.border}`,
        color: "#FFFFFF",
      }}
      data-testid={testid}
      data-k70a-gradient-tile="true"
    >
      <span
        className="text-xs font-semibold uppercase tracking-wide"
        style={{ color: "rgba(255,255,255,0.85)" }}
        data-testid={`${testid}-label`}
      >
        AR Aging (top 3 buckets)
      </span>
      {loading ? (
        <div className="text-sm opacity-60">Loading…</div>
      ) : buckets.length === 0 ? (
        <div className="text-sm" data-testid={`${testid}-empty`}>
          No outstanding balances
        </div>
      ) : (
        <div className="flex flex-col gap-2 mt-1" data-testid={`${testid}-list`}>
          {buckets.map((b) => {
            const pct = Math.max(4, Math.round((Number(b.amount || 0) / max) * 100));
            return (
              <div key={b.bucket} data-testid={`${testid}-row-${b.bucket}`}>
                <div className="flex items-baseline justify-between text-xs mb-1">
                  <span style={{ color: "#FFFFFF" }}>{b.bucket} days</span>
                  <span
                    className="font-semibold"
                    style={{ color: "#FFFFFF" }}
                    data-testid={`${testid}-row-${b.bucket}-amount`}
                  >
                    {formatCurrency(b.amount, { compact: true })}
                  </span>
                </div>
                <div
                  className="h-1.5 rounded-full overflow-hidden"
                  style={{ backgroundColor: "rgba(255,255,255,0.2)" }}
                >
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${pct}%`, backgroundColor: "#FFFFFF" }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default OverviewStrip;
