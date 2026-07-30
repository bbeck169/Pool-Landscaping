// MR3 · Feb-2026 — Widget Analytics admin page.
//
// Renders three panels for the current tenant's public check-in widget:
//   1. KPI cards — Impressions, Clicks, CTR (with 7d/30d/90d toggle).
//   2. Recharts line chart — daily impressions vs clicks.
//   3. Top 10 check-ins table — clicks / impressions / CTR.
//
// Uses the two authed endpoints introduced by MR3:
//   GET /api/widget/analytics/summary?range=7d|30d|90d
//   GET /api/widget/analytics/timeseries?range=…&granularity=day
import React from "react";
import { toast } from "sonner";
import { Eye, MousePointerClick, Percent, BarChart3 } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";

import { api } from "@/api";
import { colors } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

const RANGES = [
  { key: "7d",  label: "7 days"  },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
];

function KpiCard({ icon: Icon, label, value, hint, testId }) {
  return (
    <div
      data-testid={testId}
      style={{
        background: colors.surface || "#FFFFFF",
        border: `1px solid ${colors.border || "#E2E8F0"}`,
        borderRadius: 14,
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, color: colors.muted }}>
        <Icon size={16} />
        <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: 0.4, textTransform: "uppercase" }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 34, fontWeight: 700, color: colors.text || "#0F172A" }}>
        {value}
      </div>
      {hint && (
        <div style={{ fontSize: 12, color: colors.muted }}>{hint}</div>
      )}
    </div>
  );
}

function formatPct(f) {
  if (f == null || Number.isNaN(f)) return "0.0%";
  return `${(f * 100).toFixed(1)}%`;
}

export default function WidgetAnalyticsPage() {
  const [range, setRange] = React.useState("7d");
  const [summary, setSummary] = React.useState(null);
  const [series, setSeries] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState(null);

  const load = React.useCallback(async (r) => {
    setLoading(true);
    setErr(null);
    try {
      const [s, t] = await Promise.all([
        api.get(`/widget/analytics/summary?range=${encodeURIComponent(r)}`),
        api.get(`/widget/analytics/timeseries?range=${encodeURIComponent(r)}&granularity=day`),
      ]);
      setSummary(s);
      setSeries(t?.series || []);
    } catch (e) {
      const msg = e?.message || "Failed to load widget analytics";
      setErr(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(range); }, [range, load]);

  const impressions = summary?.impressions ?? 0;
  const clicks      = summary?.clicks ?? 0;
  const ctr         = summary?.ctr ?? 0;
  const top         = summary?.top_checkins || [];

  const isEmpty = !loading && !err && impressions === 0 && clicks === 0;

  return (
    <SafeScrollContainer>
      <div data-testid="widget-analytics-page" style={{ padding: 24, maxWidth: 1240, margin: "0 auto" }}>
        {/* Header + range toggle */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 24, gap: 16, flexWrap: "wrap",
        }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <BarChart3 size={22} color={colors.text || "#0F172A"} />
              <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: colors.text || "#0F172A" }}>
                Widget Analytics
              </h1>
            </div>
            <div style={{ fontSize: 13, color: colors.muted, marginTop: 4 }}>
              Impressions, clicks, and top-performing check-ins from your public widget.
            </div>
          </div>
          <div
            data-testid="widget-analytics-range-toggle"
            role="tablist"
            style={{ display: "inline-flex", background: colors.surfaceMuted || "#F1F5F9",
                      border: `1px solid ${colors.border || "#E2E8F0"}`, borderRadius: 999, padding: 4 }}
          >
            {RANGES.map((r) => (
              <button
                key={r.key}
                role="tab"
                aria-selected={range === r.key}
                data-testid={`widget-analytics-range-${r.key}`}
                onClick={() => setRange(r.key)}
                style={{
                  padding: "8px 16px", fontSize: 13, fontWeight: 600,
                  background: range === r.key ? (colors.brand || "#0284C7") : "transparent",
                  color: range === r.key ? "#FFFFFF" : (colors.muted || "#64748B"),
                  border: "none", borderRadius: 999, cursor: "pointer",
                  transition: "background 120ms, color 120ms",
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {/* KPI cards */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 16, marginBottom: 24,
        }}>
          <KpiCard testId="widget-kpi-impressions" icon={Eye}
                    label="Impressions"
                    value={loading ? "…" : impressions.toLocaleString()}
                    hint="Widget loads in this window" />
          <KpiCard testId="widget-kpi-clicks" icon={MousePointerClick}
                    label="Clicks"
                    value={loading ? "…" : clicks.toLocaleString()}
                    hint="Card interactions" />
          <KpiCard testId="widget-kpi-ctr" icon={Percent}
                    label="CTR"
                    value={loading ? "…" : formatPct(ctr)}
                    hint="Clicks ÷ Impressions" />
        </div>

        {/* Empty state */}
        {isEmpty && (
          <div data-testid="widget-analytics-empty"
                style={{ padding: 32, textAlign: "center",
                          background: colors.surfaceMuted || "#F1F5F9",
                          border: `1px dashed ${colors.border || "#E2E8F0"}`,
                          borderRadius: 14, marginBottom: 24 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: colors.text || "#0F172A" }}>
              No widget activity yet
            </div>
            <div style={{ fontSize: 13, color: colors.muted, marginTop: 6, maxWidth: 480, margin: "6px auto 0" }}>
              Once your public widget is embedded on a page and loads for a visitor,
              impressions and clicks will begin showing here. Visit the
              <b> Widget Embed </b> page to grab your snippet.
            </div>
          </div>
        )}

        {/* Chart */}
        <div style={{
          background: colors.surface || "#FFFFFF",
          border: `1px solid ${colors.border || "#E2E8F0"}`,
          borderRadius: 14, padding: 20, marginBottom: 24,
        }}>
          <div style={{ marginBottom: 12, fontSize: 14, fontWeight: 600, color: colors.text || "#0F172A" }}>
            Daily impressions &amp; clicks
          </div>
          <div data-testid="widget-analytics-chart" style={{ width: "100%", height: 280 }}>
            <ResponsiveContainer>
              <LineChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={colors.border || "#E2E8F0"} strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip contentStyle={{ borderRadius: 8, borderColor: colors.border || "#E2E8F0" }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="impressions" name="Impressions"
                       stroke="#0284C7" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="clicks"      name="Clicks"
                       stroke="#16A34A" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top 10 table */}
        <div style={{
          background: colors.surface || "#FFFFFF",
          border: `1px solid ${colors.border || "#E2E8F0"}`,
          borderRadius: 14, overflow: "hidden",
        }}>
          <div style={{ padding: "16px 20px", borderBottom: `1px solid ${colors.border || "#E2E8F0"}`,
                          fontSize: 14, fontWeight: 600, color: colors.text || "#0F172A" }}>
            Top 10 check-ins
          </div>
          <div style={{ overflowX: "auto" }}>
            <table
              data-testid="widget-analytics-top-table"
              style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
            >
              <thead>
                <tr style={{ background: colors.surfaceMuted || "#F8FAFC", color: colors.muted }}>
                  <th style={{ textAlign: "left",  padding: "10px 20px", fontWeight: 600 }}>Check-in</th>
                  <th style={{ textAlign: "right", padding: "10px 20px", fontWeight: 600, width: 120 }}>Impressions</th>
                  <th style={{ textAlign: "right", padding: "10px 20px", fontWeight: 600, width: 100 }}>Clicks</th>
                  <th style={{ textAlign: "right", padding: "10px 20px", fontWeight: 600, width: 80  }}>CTR</th>
                </tr>
              </thead>
              <tbody>
                {top.length === 0 && (
                  <tr>
                    <td colSpan={4} data-testid="widget-analytics-top-empty"
                         style={{ padding: 24, textAlign: "center", color: colors.muted }}>
                      No clicks yet in this window.
                    </td>
                  </tr>
                )}
                {top.map((row, i) => (
                  <tr key={row.checkin_id}
                       data-testid={`widget-analytics-top-row-${i}`}
                       style={{ borderTop: `1px solid ${colors.border || "#E2E8F0"}` }}>
                    <td style={{ padding: "12px 20px", color: colors.text || "#0F172A" }}>
                      <div style={{ fontWeight: 600 }}>{row.title || row.checkin_id}</div>
                      <div style={{ fontSize: 11, color: colors.muted }}>{row.checkin_id}</div>
                    </td>
                    <td style={{ padding: "12px 20px", textAlign: "right" }}>{row.impressions.toLocaleString()}</td>
                    <td style={{ padding: "12px 20px", textAlign: "right", fontWeight: 600 }}>{row.clicks.toLocaleString()}</td>
                    <td style={{ padding: "12px 20px", textAlign: "right" }}>{formatPct(row.ctr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {err && (
          <div data-testid="widget-analytics-error"
                style={{ marginTop: 16, padding: 12, background: "#FEF2F2",
                          border: "1px solid #FECACA", borderRadius: 10, color: "#B91C1C", fontSize: 13 }}>
            {err}
          </div>
        )}
      </div>
    </SafeScrollContainer>
  );
}
