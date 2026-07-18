import React, { useEffect, useMemo, useState } from "react";
import {
  BarChart, Bar, LineChart, Line, Area, AreaChart, ComposedChart, ReferenceDot,
  XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend,
} from "recharts";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

/* ─── shared bits ────────────────────────────────────────────────── */
const H = ({ title, sub, right }) => (
  <div className="flex items-start justify-between mb-6">
    <div>
      <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
      {sub && <p className="text-sm mt-1" style={{ color: colors.muted }}>{sub}</p>}
    </div>
    {right}
  </div>
);
const Card = ({ children, className = "", testId }) => (
  <div className={"rounded-2xl " + className}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);
const Tile = ({ label, value, sub, testId, tone }) => (
  <Card className="p-4" testId={testId}>
    <div className="text-xs uppercase tracking-wide" style={{ color: colors.muted }}>{label}</div>
    <div className="text-3xl font-bold mt-1" style={{ color: tone || colors.onSurface }}>{value}</div>
    {sub && <div className="text-xs mt-1" style={{ color: colors.muted }}>{sub}</div>}
  </Card>
);
const money = (n) => `$${Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const TIER_COLOR = { platinum: "#7C3AED", gold: "#D97706", silver: "#64748B", bronze: "#92400E" };
const BAND_COLOR = { high: "#DC2626", medium: "#D97706", low: "#16A34A" };

const TABS = [
  { k: "overview", label: "Overview" },
  { k: "ltv", label: "Customer LTV" },
  { k: "churn", label: "Churn Prediction" },
  { k: "productivity", label: "Tech Productivity" },
  { k: "anomalies", label: "Revenue Anomalies" },
  { k: "forecast", label: "Forecast v2" },
];

/* ─── /analytics ──────────────────────────────────────────────── */
export default function AnalyticsPage() {
  const [tab, setTab] = useState("overview");
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid="analytics-page">
      <H title="Advanced Analytics"
         sub="Real-time insights, predictions, and revenue diagnostics — computed from live seed data."
      />
      <div className="flex gap-2 flex-wrap mb-6" data-testid="analytics-tabs">
        {TABS.map((t) => (
          <button key={t.k} onClick={() => setTab(t.k)}
                  className="px-4 py-2 rounded-xl text-sm font-semibold transition"
                  style={{
                    background: tab === t.k ? brandGradientCss : colors.surface,
                    color: tab === t.k ? "#fff" : colors.onSurface,
                    border: `1px solid ${tab === t.k ? "transparent" : colors.border}`,
                  }}
                  data-testid={`analytics-tab-${t.k}`}>{t.label}</button>
        ))}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "ltv" && <CustomerLTV />}
      {tab === "churn" && <ChurnRisk />}
      {tab === "productivity" && <TechProductivity />}
      {tab === "anomalies" && <RevenueAnomalies />}
      {tab === "forecast" && <ForecastV2 />}
    </div>
  );
}

/* ─── Overview ─────────────────────────────────────────────── */
function Overview() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/analytics/overview").then(setData).catch(() => {}); }, []);
  if (!data) return <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>;
  const positive = data.mom_change_pct >= 0;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="overview-tiles">
      <Tile testId="tile-this-month" label="This-month revenue" value={money(data.this_month_revenue)}
            sub={`vs ${money(data.last_month_revenue)} last month`} />
      <Tile testId="tile-mom" label="MoM change"
            value={`${positive ? "+" : ""}${data.mom_change_pct}%`}
            tone={positive ? "#16A34A" : "#DC2626"}
            sub={positive ? "Trending up" : "Trending down"} />
      <Tile testId="tile-cac" label="CAC (placeholder)" value={money(data.cac)}
            sub={`${data.new_customers_this_month} new customers`} />
      <Tile testId="tile-ltv" label="Avg LTV" value={money(data.avg_ltv)}
            sub={`${data.active_customers} active`} />
    </div>
  );
}

/* ─── Customer LTV ─────────────────────────────────────────── */
function CustomerLTV() {
  const [data, setData] = useState(null);
  const [sort, setSort] = useState("revenue");
  useEffect(() => { api.get("/analytics/customer-ltv").then(setData).catch(() => {}); }, []);
  const rows = useMemo(() => {
    if (!data) return [];
    const list = [...data.rows];
    if (sort === "name") list.sort((a, b) => (a.customer_name || "").localeCompare(b.customer_name || ""));
    if (sort === "tier") list.sort((a, b) => (b.revenue || 0) - (a.revenue || 0));
    return list;
  }, [data, sort]);
  if (!data) return <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4" data-testid="ltv-tier-summary">
        {Object.entries(data.tier_counts).map(([tier, n]) => (
          <Tile key={tier} testId={`tile-tier-${tier}`}
                label={tier.toUpperCase()} value={n} tone={TIER_COLOR[tier]} />
        ))}
      </div>
      <Card className="overflow-hidden" testId="ltv-table">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wide"
             style={{ color: colors.muted, backgroundColor: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-4 cursor-pointer" onClick={() => setSort("name")}>Customer</div>
          <div className="col-span-2 text-right cursor-pointer" onClick={() => setSort("revenue")}>Revenue</div>
          <div className="col-span-2 text-right">Invoices</div>
          <div className="col-span-2">Last paid</div>
          <div className="col-span-2 cursor-pointer" onClick={() => setSort("tier")}>Tier</div>
        </div>
        {rows.map((r) => (
          <div key={r.customer_id} className="grid grid-cols-12 gap-2 px-4 py-3 text-sm"
               style={{ borderBottom: `1px solid ${colors.border}`, color: colors.onSurface }}
               data-testid={`ltv-row-${r.customer_id}`}>
            <div className="col-span-4 font-semibold truncate">
              <a href={`/customers/${r.customer_id}`} style={{ color: colors.onSurface }}>{r.customer_name}</a>
              {r.vip && <span className="ml-2 text-[10px] font-bold text-white px-1.5 py-0.5 rounded" style={{ background: brandGradientCss }}>VIP</span>}
            </div>
            <div className="col-span-2 text-right font-mono">{money(r.revenue)}</div>
            <div className="col-span-2 text-right">{r.invoice_count}</div>
            <div className="col-span-2 text-xs" style={{ color: colors.muted }}>{r.last_paid || "—"}</div>
            <div className="col-span-2 text-xs font-bold uppercase" style={{ color: TIER_COLOR[r.tier] }}>{r.tier}</div>
          </div>
        ))}
        {rows.length === 0 && <div className="p-8 text-center text-sm" style={{ color: colors.muted }}>No customers.</div>}
      </Card>
    </>
  );
}

/* ─── Churn Risk ───────────────────────────────────────────── */
function ChurnRisk() {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  useEffect(() => { api.get("/analytics/churn-risk").then(setData).catch(() => {}); }, []);
  if (!data) return <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <>
      <div className="grid grid-cols-3 gap-3 mb-4" data-testid="churn-summary">
        {Object.entries(data.band_counts).map(([b, n]) => (
          <Tile key={b} testId={`tile-band-${b}`} label={`${b.toUpperCase()} RISK`}
                value={n} tone={BAND_COLOR[b]} />
        ))}
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div className="md:col-span-2">
          <Card className="overflow-hidden" testId="churn-table">
            <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wide"
                 style={{ color: colors.muted, backgroundColor: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
              <div className="col-span-4">Customer</div>
              <div className="col-span-2 text-right">Risk</div>
              <div className="col-span-2 text-right">Last visit</div>
              <div className="col-span-2 text-right">Lag (d)</div>
              <div className="col-span-2">Band</div>
            </div>
            {data.rows.map((r) => (
              <div key={r.customer_id} onClick={() => setSelected(r)}
                   className="grid grid-cols-12 gap-2 px-4 py-3 text-sm cursor-pointer hover:brightness-95 transition"
                   style={{ borderBottom: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid={`churn-row-${r.customer_id}`}>
                <div className="col-span-4 font-semibold truncate">{r.customer_name}</div>
                <div className="col-span-2 text-right font-mono font-bold" style={{ color: BAND_COLOR[r.band] }}>{r.risk_score}</div>
                <div className="col-span-2 text-right text-xs" style={{ color: colors.muted }}>{r.days_since_last_visit}d</div>
                <div className="col-span-2 text-right text-xs" style={{ color: colors.muted }}>{r.avg_payment_lag_days}</div>
                <div className="col-span-2 text-xs font-bold uppercase" style={{ color: BAND_COLOR[r.band] }}>{r.band}</div>
              </div>
            ))}
          </Card>
        </div>
        <div>
          <Card className="p-5" testId="churn-drill">
            {selected ? <>
              <div className="text-xs uppercase tracking-wide mb-1" style={{ color: colors.muted }}>Feature contribution</div>
              <div className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>{selected.customer_name}</div>
              <div className="mb-3">
                <div className="text-4xl font-bold" style={{ color: BAND_COLOR[selected.band] }}>{selected.risk_score}</div>
                <div className="text-xs" style={{ color: colors.muted }}>Risk score</div>
              </div>
              {Object.entries(selected.factors).map(([k, v]) => (
                <div key={k} className="mb-2">
                  <div className="flex justify-between text-xs mb-1">
                    <span style={{ color: colors.onSurface }}>{k.replace(/_/g, " ")}</span>
                    <span className="font-mono" style={{ color: colors.muted }}>{Math.round(v)}</span>
                  </div>
                  <div className="h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: colors.surfaceSecondary }}>
                    <div className="h-full" style={{ width: `${Math.min(100, v * 2.5)}%`, background: brandGradientCss }} />
                  </div>
                </div>
              ))}
            </> : <div className="text-sm text-center py-8" style={{ color: colors.muted }}>Click a row to drill in.</div>}
          </Card>
        </div>
      </div>
    </>
  );
}

/* ─── Tech Productivity ─────────────────────────────────────── */
function TechProductivity() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/analytics/tech-productivity").then(setData).catch(() => {}); }, []);
  if (!data) return <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>;
  const heat = (n) => {
    if (!n) return colors.surfaceSecondary;
    if (n >= 5) return "#0284C7";
    if (n >= 3) return "#38BDF8";
    if (n >= 1) return "#BAE6FD";
    return colors.surfaceSecondary;
  };
  return (
    <Card className="p-5 overflow-x-auto" testId="tech-productivity-table">
      <div className="text-xs mb-3" style={{ color: colors.muted }}>
        {data.start} → {data.end} · color = jobs completed
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr style={{ color: colors.muted }}>
            <th className="text-left px-2 py-1 font-bold uppercase text-xs">Technician</th>
            {data.weekdays.map((d) => <th key={d} className="px-2 py-1 font-bold uppercase text-xs">{d}</th>)}
            <th className="text-right px-2 py-1 font-bold uppercase text-xs">Total</th>
          </tr>
        </thead>
        <tbody>
          {data.matrix.map((row) => (
            <tr key={row.technician_id} data-testid={`prod-row-${row.technician_id}`}>
              <td className="px-2 py-2 font-semibold" style={{ color: colors.onSurface }}>{row.technician_name}</td>
              {row.cells.map((c, i) => (
                <td key={i} className="px-1 py-1">
                  <div title={`${c.jobs} jobs · avg ${c.avg_duration_min}min · ${c.on_time_pct}% on-time`}
                       className="rounded-lg text-center py-2"
                       style={{ backgroundColor: heat(c.jobs), color: c.jobs >= 3 ? "#fff" : colors.onSurface }}>
                    <div className="font-bold">{c.jobs}</div>
                    <div className="text-[9px] opacity-80">{c.on_time_pct}% ot</div>
                  </div>
                </td>
              ))}
              <td className="px-2 py-2 text-right font-bold" style={{ color: colors.onSurface }}>{row.total_jobs}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.matrix.length === 0 && <div className="p-6 text-center text-sm" style={{ color: colors.muted }}>No technicians.</div>}
    </Card>
  );
}

/* ─── Revenue Anomalies ─────────────────────────────────────── */
function RevenueAnomalies() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/analytics/revenue-anomalies?days=120").then(setData).catch(() => {}); }, []);
  if (!data) return <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
        <Tile testId="tile-anomaly-count" label="Anomalies flagged (120d)"
              value={data.anomaly_count} tone={data.anomaly_count > 0 ? "#DC2626" : "#16A34A"} />
        <Tile testId="tile-series-days" label="Days tracked" value={data.series.length} />
        <Tile testId="tile-threshold" label="Threshold" value="±2σ" sub="30-day rolling window" />
      </div>
      <Card className="p-5" testId="anomaly-chart">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data.series}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Bar dataKey="revenue" fill="#0284C7" opacity={0.75} />
            {data.series.filter((s) => s.anomaly).map((s) => (
              <ReferenceDot key={s.date} x={s.date} y={s.revenue} r={5} fill="#DC2626" stroke="#fff" />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </Card>
      {data.anomalies.length > 0 && (
        <Card className="mt-4" testId="anomaly-list">
          <div className="px-4 py-2 text-xs font-bold uppercase tracking-wide"
               style={{ color: colors.muted, backgroundColor: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
            Recent anomalies
          </div>
          {data.anomalies.map((a) => (
            <div key={a.date} className="grid grid-cols-4 gap-2 px-4 py-2 text-sm"
                 style={{ borderBottom: `1px solid ${colors.border}`, color: colors.onSurface }}>
              <div className="font-mono">{a.date}</div>
              <div className="text-right">{money(a.revenue)}</div>
              <div className="text-right text-xs" style={{ color: colors.muted }}>
                mean {money(a.mean)} ± {money(a.stdev)}
              </div>
              <div className="text-right font-mono font-bold" style={{ color: a.score > 0 ? "#16A34A" : "#DC2626" }}>
                {a.score > 0 ? "+" : ""}{a.score}σ
              </div>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}

/* ─── Forecast v2 ──────────────────────────────────────────── */
function ForecastV2() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/analytics/forecast-v2?days=90").then(setData).catch(() => {}); }, []);
  if (!data) return <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Tile testId="tile-baseline" label="Baseline daily" value={money(data.baseline_daily)}
              sub={`vol ${money(data.volatility)}`} />
        <Tile testId="tile-p50" label="90-day P50" value={money(data.totals.p50)} tone="#0284C7" />
        <Tile testId="tile-p10" label="P10 (bear)" value={money(data.totals.p10)} tone="#DC2626" />
        <Tile testId="tile-p90" label="P90 (bull)" value={money(data.totals.p90)} tone="#16A34A" />
      </div>
      <Card className="p-5" testId="forecast-chart">
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={data.series}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Legend />
            <Area type="monotone" dataKey="p90" stroke="#16A34A" fill="#DCFCE7" name="P90" />
            <Area type="monotone" dataKey="p50" stroke="#0284C7" fill="#DBEAFE" name="P50" />
            <Area type="monotone" dataKey="p10" stroke="#DC2626" fill="#FEE2E2" name="P10" />
          </AreaChart>
        </ResponsiveContainer>
        <div className="text-xs mt-3" style={{ color: colors.muted }}>
          Includes April-October seasonality boost and a {Math.round((1 - data.weather_adjustment) * 100)}% weather drag.
        </div>
      </Card>
    </>
  );
}
