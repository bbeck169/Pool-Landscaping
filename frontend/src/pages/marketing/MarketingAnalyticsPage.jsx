/**
 * Feb-2026 · Marketing Slice M7 — Campaign Analytics dashboard.
 *
 * Read-only view over /api/marketing/analytics/*.  Renders KPIs, a
 * daily-trend Recharts line, top-5 sequences + campaigns tables and
 * a review-request funnel bar.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend,
  BarChart, Bar, CartesianGrid,
} from "recharts";
import {
  Sparkles, Star, MousePointerClick, Mail, RefreshCw, Bot,
} from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

const WINDOWS = [
  { value: "7d",  label: "Last 7 days"  },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "all", label: "All time"     },
];

export default function MarketingAnalyticsPage() {
  const [window, setWindow] = useState("30d");
  const [overview, setOverview] = useState(null);
  const [rrFunnel, setRrFunnel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [aiOutput, setAiOutput] = useState("");
  const [aiBusy, setAiBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [o, rr] = await Promise.all([
        api.get(`/marketing/analytics/overview?window=${window}`),
        api.get(`/marketing/analytics/review-requests?window=${window}`),
      ]);
      setOverview(o); setRrFunnel(rr);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [window]);

  const refresh = async () => {
    try { await api.post("/marketing/analytics/_cache/clear", {}); } catch {}
    await load();
  };

  const askBuddy = async () => {
    setAiBusy(true); setAiOutput("");
    try {
      // Try to reuse an existing Buddy conversation; if none, create one.
      let cid;
      try {
        const list = await api.get("/ai-employees/buddy/conversations?limit=1");
        cid = list?.conversations?.[0]?.id;
      } catch {}
      if (!cid) {
        const c = await api.post("/ai-employees/buddy/conversations",
                                   { title: "Marketing recap" });
        cid = c.id;
      }
      const r = await api.post(
        `/ai-employees/buddy/conversations/${cid}/messages`,
        { text: "Give me this week's marketing recap.",
          action: "buddy.marketing_weekly_recap" },
      );
      setAiOutput(r?.assistant_message?.text || r?.text
                   || "(Buddy did not return a recap.)");
    } catch (e) {
      setAiOutput(`Buddy is unavailable: ${e?.message || "unknown error"}`);
    } finally { setAiBusy(false); }
  };

  const kpis = useMemo(() => {
    if (!overview) return null;
    const c = overview.campaigns || {};
    const rr = overview.review_requests || {};
    const totalDeliveries = (c.delivered || 0)
      + (rr.sent || 0) + (rr.opened || 0) + (rr.reviewed || 0)
      + (rr.expired || 0);
    return {
      totalDeliveries,
      openRatePct: c.delivered ? Math.round(100 * c.opened / c.delivered) : null,
      clickRatePct: c.delivered ? Math.round(100 * c.clicked / c.delivered) : null,
      reviewRatePct: rr.review_rate_pct,
      avgRating: rr.avg_rating,
    };
  }, [overview]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="analytics-page">
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Marketing Analytics
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Read-only rollup across campaigns, sequences and review requests.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select value={window} onChange={(e) => setWindow(e.target.value)}
                  className="px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={selectStyle}
                  data-testid="analytics-window-select">
            {WINDOWS.map((w) =>
              <option key={w.value} value={w.value}>{w.label}</option>
            )}
          </select>
          <button onClick={refresh}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary,
                           color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}>
            <RefreshCw size={13} /> Refresh
          </button>
          <button onClick={askBuddy} disabled={aiBusy}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-bold text-white disabled:opacity-50"
                  style={{ background: brandGradientCss }}
                  data-testid="analytics-ask-buddy-btn">
            <Bot size={13} /> {aiBusy ? "Asking Buddy…" : "Ask Buddy for a recap"}
          </button>
        </div>
      </div>

      {aiOutput ? (
        <div className="rounded-2xl p-4 mb-4"
             style={{ backgroundColor: colors.brandTertiary,
                      color: colors.brand,
                      border: `1px solid ${colors.brand}` }}
             data-testid="analytics-ai-output">
          <div className="text-[10px] font-bold uppercase tracking-wider mb-1">
            <Bot size={11} className="inline mr-1" />Buddy · recap
          </div>
          <pre className="whitespace-pre-wrap text-sm"
               style={{ fontFamily: "inherit", color: colors.onSurface }}>
            {aiOutput}
          </pre>
        </div>
      ) : null}

      {loading ? (
        <div className="text-sm py-6" style={{ color: colors.muted }}>Loading…</div>
      ) : !overview ? (
        <div className="text-sm py-6" style={{ color: colors.muted }}>No data.</div>
      ) : (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
            <Kpi label="Total deliveries" value={kpis.totalDeliveries}
                  icon={<Mail size={14} />} testid="kpi-total-deliveries" />
            <Kpi label="Open rate" value={fmtPct(kpis.openRatePct)}
                  icon={<MousePointerClick size={14} />} testid="kpi-open-rate" />
            <Kpi label="Click rate" value={fmtPct(kpis.clickRatePct)}
                  icon={<MousePointerClick size={14} />} testid="kpi-click-rate" />
            <Kpi label="Review rate" value={fmtPct(kpis.reviewRatePct)}
                  icon={<Star size={14} />} testid="kpi-review-rate" />
            <Kpi label="Avg rating" value={kpis.avgRating ?? "—"}
                  icon={<Star size={14} />} testid="kpi-avg-rating" />
          </div>

          {/* Trend chart */}
          <div className="rounded-2xl p-4 mb-6"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="analytics-trend-chart">
            <h3 className="text-base font-bold mb-3"
                style={{ color: colors.onSurface }}>Daily trend</h3>
            <div style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer>
                <LineChart data={(overview.trend || []).map((t) => ({
                  date: t.date.slice(5),
                  Deliveries: t.deliveries,
                  Opens: t.opens,
                  Conversions: t.conversions,
                }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.divider} />
                  <XAxis dataKey="date" fontSize={10} stroke={colors.muted} />
                  <YAxis fontSize={10} stroke={colors.muted} allowDecimals={false} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="Deliveries"
                        stroke={colors.brand} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="Opens"
                        stroke="#F59E0B" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="Conversions"
                        stroke="#16A34A" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top tables */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <TopTable title="Top sequences"
                       testid="analytics-top-sequences-table"
                       rows={overview.top_sequences}
                       cols={[
                         { key: "name", label: "Sequence" },
                         { key: "enrolments", label: "Enrolments" },
                         { key: "completion_rate", label: "Completion", fmt: fmtPct },
                       ]} />
            <TopTable title="Top campaigns"
                       testid="analytics-top-campaigns-table"
                       rows={overview.top_campaigns}
                       cols={[
                         { key: "name", label: "Campaign" },
                         { key: "delivered", label: "Delivered" },
                         { key: "open_rate_pct", label: "Open rate", fmt: fmtPct },
                       ]} />
          </div>

          {/* Review-request funnel */}
          <div className="rounded-2xl p-4 mb-6"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="analytics-review-funnel">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
                Review request funnel
              </h3>
              <span className="text-xs" style={{ color: colors.muted }}>
                Avg rating: {rrFunnel?.avg_rating ?? "—"}
              </span>
            </div>
            <div style={{ width: "100%", height: 220 }}>
              <ResponsiveContainer>
                <BarChart data={(rrFunnel?.funnel || []).map((f) => ({
                  stage: f.stage, count: f.count,
                }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.divider} />
                  <XAxis dataKey="stage" fontSize={11} stroke={colors.muted} />
                  <YAxis fontSize={11} stroke={colors.muted} allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="count" fill={colors.brand} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-4 gap-2 mt-3">
              {(rrFunnel?.funnel || []).map((f) => (
                <div key={f.stage}
                     className="rounded-lg p-2 text-center"
                     style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.divider}` }}>
                  <div className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.muted }}>{f.stage}</div>
                  <div className="text-lg font-bold"
                       style={{ color: colors.onSurface }}>{f.count}</div>
                  <div className="text-[10px]" style={{ color: colors.muted }}>
                    {fmtPct(f.rate_pct)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {overview?.review_requests?.ab_variants ? (
            <AbTestCard ab={overview.review_requests.ab_variants} />
          ) : null}
        </>
      )}
    </div>
  );
}


function AbTestCard({ ab }) {
  const lift = ab?.lift_pct;
  const liftColor =
    lift === null || lift === undefined ? colors.muted
      : lift >= 5 ? "#16A34A"
      : lift <= -5 ? colors.error
      : colors.muted;
  return (
    <div className="rounded-2xl p-4 mb-6"
         style={{ backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}` }}
         data-testid="analytics-ab-test-card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
          A/B Test Results
        </h3>
        {lift !== null && lift !== undefined ? (
          <span className="px-2 py-1 rounded-full text-xs font-bold"
                style={{ backgroundColor: liftColor + "22", color: liftColor }}
                data-testid="analytics-ab-lift">
            Lift {lift > 0 ? "+" : ""}{lift}%
          </span>
        ) : (
          <span className="text-xs" style={{ color: colors.muted }}
                data-testid="analytics-ab-lift">
            Lift — (need more A data)
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <VariantColumn label="A" testid="analytics-ab-variant-a" data={ab?.A} />
        <VariantColumn label="B" testid="analytics-ab-variant-b" data={ab?.B} />
      </div>
    </div>
  );
}


function VariantColumn({ label, data, testid }) {
  return (
    <div className="rounded-xl p-3"
         style={{ backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.divider}` }}
         data-testid={testid}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-lg font-bold" style={{ color: colors.onSurface }}>
          Variant {label}
        </span>
        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
              style={{ backgroundColor: label === "A" ? "#E0E7FF" : "#DBEAFE",
                       color: label === "A" ? "#4338CA" : "#1E3A8A" }}>
          {label}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <span style={{ color: colors.muted }}>Sent</span>
        <span className="text-right font-semibold"
              style={{ color: colors.onSurface }}>{data?.sent ?? 0}</span>
        <span style={{ color: colors.muted }}>Opened</span>
        <span className="text-right font-semibold"
              style={{ color: colors.onSurface }}>{data?.opened ?? 0}</span>
        <span style={{ color: colors.muted }}>Reviewed</span>
        <span className="text-right font-semibold"
              style={{ color: colors.onSurface }}>{data?.reviewed ?? 0}</span>
        <span style={{ color: colors.muted }}>Review rate</span>
        <span className="text-right font-semibold"
              style={{ color: colors.onSurface }}>
          {fmtPct(data?.review_rate_pct)}
        </span>
        <span style={{ color: colors.muted }}>Avg rating</span>
        <span className="text-right font-semibold"
              style={{ color: colors.onSurface }}>
          {data?.avg_rating ?? "—"}
        </span>
      </div>
    </div>
  );
}


const selectStyle = {
  backgroundColor: colors.surface,
  color: colors.onSurface,
  border: `1px solid ${colors.border}`,
};


function Kpi({ label, value, icon, testid }) {
  return (
    <div className="rounded-2xl p-4"
         style={{ backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}` }}
         data-testid={testid}>
      <div className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider mb-1"
           style={{ color: colors.muted }}>
        {icon} {label}
      </div>
      <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>
        {value ?? "—"}
      </div>
    </div>
  );
}


function TopTable({ title, rows, cols, testid }) {
  return (
    <div className="rounded-2xl overflow-hidden"
         style={{ backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}` }}
         data-testid={testid}>
      <div className="p-3" style={{ borderBottom: `1px solid ${colors.divider}` }}>
        <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
          {title}
        </h3>
      </div>
      {(!rows || rows.length === 0) ? (
        <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>
          No data for this window.
        </div>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${colors.divider}` }}>
                {cols.map((c, i) => (
                  <td key={c.key}
                      className="py-2 px-3"
                      style={{ color: i === 0 ? colors.onSurface : colors.muted }}>
                    {c.fmt ? c.fmt(r[c.key]) : (r[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}


function fmtPct(v) {
  if (v === null || v === undefined) return "—";
  return `${v}%`;
}
