// Phase 10 · sub-item F · Feb-2026 — Cumulative weekly savings KPI strip
// for the Dispatch Board top bar. Shown only on md+ breakpoints.
//
// Reads /api/dispatch/route/savings/weekly (7d default, 30d toggle in the
// details modal). Sparkline via recharts. Big number is `total_savings_km`.
import React from "react";
import { X, TrendingUp, BarChart3 } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "@/api";
import { colors } from "@/theme";


export default function DispatchSavingsStrip() {
  const [data, setData] = React.useState(null);
  const [range, setRange] = React.useState("7d");
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await api.get(`/dispatch/route/savings/weekly?range=${range}`);
        if (alive) setData(r);
      } catch { if (alive) setData(null); }
    })();
    return () => { alive = false; };
  }, [range]);

  if (!data) {
    return (
      <div className="hidden md:block" data-testid="dispatch-savings-strip-loading" />
    );
  }

  const km = Number(data.total_savings_km || 0);
  const perDay = data.per_day || [];
  const label = range === "7d" ? "this week" : "this month";

  return (
    <>
      <div className="hidden md:flex items-center gap-3 rounded-xl px-3 py-2"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="dispatch-savings-strip">
        <div className="flex flex-col">
          <div className="text-[10px] font-semibold uppercase tracking-wide flex items-center gap-1"
                style={{ color: colors.muted }}>
            <TrendingUp size={11} /> Team saved
          </div>
          <div className="text-lg font-bold leading-tight"
                style={{ color: km > 0 ? "#059669" : colors.onSurface }}
                data-testid="dispatch-savings-total">
            {km.toFixed(1)} km <span className="text-xs font-medium"
                                                     style={{ color: colors.muted }}>
              {label}
            </span>
          </div>
        </div>
        <div className="w-[120px] h-[42px]" data-testid="dispatch-savings-sparkline">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={perDay} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
              <defs>
                <linearGradient id="savingsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10B981" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#10B981" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <Tooltip cursor={false} contentStyle={{ fontSize: 11, padding: 6 }}
                        formatter={(v) => [`${v} km`, "Saved"]}
                        labelFormatter={(l) => l} />
              <Area type="monotone" dataKey="savings_km" stroke="#10B981"
                    strokeWidth={1.5} fill="url(#savingsGrad)" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <button type="button" onClick={() => setOpen(true)}
                 className="text-[11px] font-semibold underline"
                 style={{ color: colors.brand }}
                 data-testid="dispatch-savings-view-report">
          View report
        </button>
      </div>

      {open ? (
        <div style={{ position: "fixed", inset: 0, zIndex: 5000,
                        background: "rgba(15,23,42,0.6)", display: "flex",
                        alignItems: "center", justifyContent: "center" }}
              onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
              data-testid="dispatch-savings-modal">
          <div style={{ background: colors.surface, borderRadius: 14,
                          width: "min(560px, 96vw)", padding: 20,
                          boxShadow: "0 20px 48px rgba(15,23,42,0.24)",
                          maxHeight: "90vh", overflow: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "center", marginBottom: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <BarChart3 size={16} color={colors.brand} />
                <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700,
                               color: colors.onSurface }}>
                  Route savings — {range === "7d" ? "last 7 days" : "last 30 days"}
                </h2>
              </div>
              <button onClick={() => setOpen(false)}
                       style={{ background: "transparent", border: "none",
                                 cursor: "pointer", color: colors.muted }}
                       aria-label="Close"><X size={16} /></button>
            </div>
            <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
              {["7d", "30d"].map((k) => (
                <button key={k} type="button"
                         onClick={() => setRange(k)}
                         className="px-3 py-1 rounded-md text-xs font-semibold"
                         style={{
                           backgroundColor: range === k ? colors.brand : colors.surfaceSecondary,
                           color: range === k ? "#fff" : colors.onSurface,
                           border: `1px solid ${range === k ? colors.brand : colors.border}`,
                         }}
                         data-testid={`dispatch-savings-range-${k}`}>
                  {k === "7d" ? "Last 7 days" : "Last 30 days"}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-3 gap-2 mb-3">
              <KpiCard label="Total saved" value={`${Number(data.total_savings_km).toFixed(1)} km`} tone="ok" />
              <KpiCard label="Optimize events" value={data.total_optimize_events} />
              <KpiCard label="Insert events" value={data.total_insert_events} />
            </div>
            <div style={{ width: "100%", height: 180, marginBottom: 12 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={perDay} margin={{ top: 6, right: 8, left: 8, bottom: 8 }}>
                  <defs>
                    <linearGradient id="savingsGrad2" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#10B981" stopOpacity={0.6} />
                      <stop offset="100%" stopColor="#10B981" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <Tooltip contentStyle={{ fontSize: 12 }} formatter={(v) => [`${v} km`, "Saved"]} />
                  <Area type="monotone" dataKey="savings_km" stroke="#10B981"
                        strokeWidth={2} fill="url(#savingsGrad2)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide font-semibold mb-1"
                    style={{ color: colors.muted }}>Top techs by savings</div>
              {(data.top_techs || []).length === 0 ? (
                <div className="text-xs" style={{ color: colors.muted }}>
                  No optimize/insert events yet in this window.
                </div>
              ) : (
                <table className="w-full text-xs" data-testid="dispatch-savings-top-techs">
                  <thead>
                    <tr style={{ color: colors.muted }}>
                      <th className="text-left py-1">Tech</th>
                      <th className="text-right py-1">Saved</th>
                      <th className="text-right py-1">Events</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_techs.map((t) => (
                      <tr key={t.tech_user_id} style={{ borderTop: `1px solid ${colors.border}` }}>
                        <td className="py-1" style={{ color: colors.onSurface }}>{t.name}</td>
                        <td className="py-1 text-right font-mono">{t.savings_km.toFixed(1)} km</td>
                        <td className="py-1 text-right font-mono">{t.event_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}


function KpiCard({ label, value, tone }) {
  const color = tone === "ok" ? "#059669" : colors.onSurface;
  return (
    <div className="rounded-lg p-2"
          style={{ backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}` }}>
      <div className="text-[10px] uppercase tracking-wide font-semibold"
            style={{ color: colors.muted }}>{label}</div>
      <div className="text-base font-bold" style={{ color }}>{value}</div>
    </div>
  );
}
