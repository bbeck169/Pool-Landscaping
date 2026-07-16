/**
 * Phase 52.A — Pricing Insights admin page.
 *
 * Wires:
 *   GET  /api/reports/least-profitable-services?month=YYYY-MM&limit=3
 *   POST /api/cfo/price-increase-suggestions {month}
 *   GET  /api/reports/pricing-insights/email-history?limit=10
 */
import React, { useEffect, useState } from "react";
import { LineChart, Wand2, RefreshCw, TrendingDown, MessageSquare } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function fmtMoney(cents) { return `$${(Number(cents || 0) / 100).toFixed(2)}`; }
function previousMonth() {
  const d = new Date();
  d.setDate(1); d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 7);
}

export default function PricingInsights() {
  const [month, setMonth] = useState(previousMonth());
  const [ranked, setRanked] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [history, setHistory] = useState([]);
  const [weeklyCash, setWeeklyCash] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [cached, setCached] = useState(false);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [r, h, s] = await Promise.all([
        api.get(`/reports/least-profitable-services?month=${month}&limit=3`),
        api.get("/reports/pricing-insights/email-history?limit=10").catch(() => ({ items: [] })),
        api.get(`/cfo/stripe-cash-weekly?month=${month}`).catch(() => ({ weeks: [] })),
      ]);
      setRanked(r);
      setHistory(h?.items || []);
      setWeeklyCash(s?.weeks || []);
    } catch (e) { setError(e?.message || "Load failed"); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); setSuggestions([]); setCached(false); }, [month]);

  const generate = async () => {
    setGenerating(true); setError(null);
    try {
      const res = await api.post("/cfo/price-increase-suggestions", { month });
      setSuggestions(res?.suggestions || []);
      setCached(!!res?.cached);
      if (!res?.suggestions?.length && res?.raw_error) {
        setError(`No suggestions returned. ${res.raw_error}`);
      }
    } catch (e) { setError(e?.message || "Suggestions failed"); }
    finally { setGenerating(false); }
  };

  const services = ranked?.services || [];

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="pricing-insights-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center"
               style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
            <LineChart size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              Pricing Insights
            </h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Least-profitable service types + AI-drafted price-increase suggestions.
              Auto-digest emails go out on the 1st of every month.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
                 className="text-sm px-2 py-1.5 rounded-md"
                 style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                 data-testid="pricing-insights-month" />
          <button type="button" onClick={load}
                  className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
                  style={{ border: `1px solid ${colors.border}`, color: colors.onSurface, background: colors.surface }}
                  data-testid="pricing-insights-refresh">
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl p-3 mb-4 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="pricing-insights-error">{error}</div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>Loading…</div>
      ) : (
        <>
          {weeklyCash.length > 0 ? (() => {
            const totalNet = weeklyCash.reduce((a, w) => a + (w.net_cents || 0), 0);
            const maxNet = Math.max(1, ...weeklyCash.map((w) => Math.abs(w.net_cents || 0)));
            return (
              <div className="rounded-2xl overflow-hidden mb-6"
                   style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                   data-testid="pricing-insights-cash-card">
                <div className="px-4 py-3 flex items-center justify-between"
                     style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
                  <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
                    Cash collected via Stripe · {month}
                  </div>
                  <div className="text-sm font-bold" style={{ color: colors.onSurface }}
                       data-testid="pricing-insights-cash-net-total">
                    Net ${(totalNet / 100).toFixed(2)}
                  </div>
                </div>
                <div className="p-4 grid grid-cols-1 md:grid-cols-4 gap-3">
                  {weeklyCash.map((w) => (
                    <div key={w.week_starting}
                         className="rounded-xl p-3"
                         style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                         data-testid={`cash-week-${w.week_starting}`}>
                      <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.muted }}>
                        Week of {w.week_starting}
                      </div>
                      <div className="text-lg font-bold mt-0.5" style={{ color: colors.onSurface }}>
                        ${(w.net_cents / 100).toFixed(2)}
                      </div>
                      <div className="text-[11px] mt-0.5" style={{ color: colors.muted }}>
                        gross ${(w.cash_collected_cents / 100).toFixed(2)} · refunds ${(w.refunds_cents / 100).toFixed(2)}
                      </div>
                      <div className="mt-2 h-1.5 rounded-full overflow-hidden"
                           style={{ background: "#E5E7EB" }}>
                        <div style={{
                          width: `${Math.max(2, Math.round(100 * Math.abs(w.net_cents || 0) / maxNet))}%`,
                          background: (w.net_cents || 0) < 0 ? "#DC2626" : colors.brand,
                          height: "100%",
                        }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })() : null}

          <div className="rounded-2xl overflow-hidden mb-6"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid="pricing-insights-ranked-card">
            <div className="px-4 py-3 flex items-center gap-2 justify-between" style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
              <div className="flex items-center gap-2">
                <TrendingDown size={14} style={{ color: "#B91C1C" }} />
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
                  Least-profitable service types · {month}
                </span>
              </div>
              <button type="button" onClick={generate}
                      disabled={generating || services.length === 0}
                      className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
                      style={{ background: colors.brand, color: "#fff", border: 0,
                                cursor: generating ? "wait" : "pointer",
                                opacity: (generating || services.length === 0) ? 0.5 : 1 }}
                      data-testid="pricing-insights-generate">
                <Wand2 size={12} /> {generating ? "Asking CFO…" : "Generate suggestions"}
              </button>
            </div>
            <table className="w-full text-sm" data-testid="pricing-insights-ranked-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <th className="text-left px-3 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Service</th>
                  <th className="text-right px-3 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Jobs</th>
                  <th className="text-right px-3 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Revenue</th>
                  <th className="text-right px-3 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Cost</th>
                  <th className="text-right px-3 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Margin ($)</th>
                  <th className="text-right px-3 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Margin %</th>
                  <th className="text-right px-3 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Avg hrs</th>
                </tr>
              </thead>
              <tbody>
                {services.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-sm"
                         style={{ color: colors.muted }}
                         data-testid="pricing-insights-empty">
                    No completed jobs with cost data in {month}.
                  </td></tr>
                ) : services.map((s) => (
                  <tr key={s.service_type} data-testid={`pricing-insights-row-${s.service_type.replace(/\s+/g,'-')}`}
                      style={{ borderBottom: `1px solid ${colors.border}` }}>
                    <td className="px-3 py-2 font-semibold" style={{ color: colors.onSurface }}>{s.service_type}</td>
                    <td className="px-3 py-2 text-right" style={{ color: colors.muted }}>{s.job_count}</td>
                    <td className="px-3 py-2 text-right" style={{ color: colors.onSurface }}>{fmtMoney(s.revenue_cents)}</td>
                    <td className="px-3 py-2 text-right" style={{ color: colors.onSurface }}>{fmtMoney(s.cost_cents)}</td>
                    <td className="px-3 py-2 text-right font-semibold"
                        style={{ color: (s.margin_cents ?? 0) < 0 ? "#B91C1C" : colors.onSurface }}
                        data-testid={`pricing-insights-margin-dollars-${s.service_type.replace(/\s+/g,'-')}`}>
                      {fmtMoney(s.margin_cents)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                            style={{ background: s.margin_pct >= 40 ? "#DCFCE7" : s.margin_pct >= 20 ? "#FEF3C7" : "#FEE2E2",
                                       color: s.margin_pct >= 40 ? "#166534" : s.margin_pct >= 20 ? "#92400E" : "#991B1B" }}>
                        {Number(s.margin_pct || 0).toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right" style={{ color: colors.muted }}>{s.avg_hours_per_job}h</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {suggestions.length > 0 ? (
            <div className="grid md:grid-cols-3 gap-4 mb-6" data-testid="pricing-insights-suggestions">
              {cached ? (
                <div className="md:col-span-3 rounded-md p-2 text-xs font-semibold"
                     style={{ background: "#EFF6FF", border: "1px solid #BFDBFE", color: "#1E40AF" }}
                     data-testid="pricing-insights-cached-note">
                  Cached suggestions from the last 24h.
                </div>
              ) : null}
              {suggestions.map((s, i) => (
                <div key={i} className="rounded-2xl overflow-hidden"
                     style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                     data-testid={`pricing-insights-suggestion-${i}`}>
                  <div className="px-4 py-3" style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
                    <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
                      {s.service_type}
                    </div>
                  </div>
                  <div className="p-4 space-y-3">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs" style={{ color: colors.muted }}>Now</span>
                      <span className="text-base font-semibold" style={{ color: colors.onSurface }}>
                        {fmtMoney(s.current_avg_price_cents)}
                      </span>
                      <span className="text-xs" style={{ color: colors.muted }}>→</span>
                      <span className="text-base font-bold" style={{ color: colors.brand }}>
                        {fmtMoney(s.recommended_price_cents)}
                      </span>
                    </div>
                    <div className="text-xs font-bold" style={{ color: "#166534" }}>
                      +{Number(s.expected_margin_lift_pct || 0).toFixed(1)}% expected margin lift
                    </div>
                    <div className="text-xs" style={{ color: colors.onSurface }}>
                      {s.rationale}
                    </div>
                    <div className="space-y-1 text-xs" style={{ color: colors.muted }}>
                      <div className="inline-flex items-center gap-1 font-semibold" style={{ color: colors.onSurface }}>
                        <MessageSquare size={12} /> Talking points
                      </div>
                      <ul className="space-y-1 pl-3" style={{ listStyle: "disc" }}>
                        {(s.customer_talking_points || []).map((tp, idx) => (
                          <li key={idx}>{tp}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid="pricing-insights-history">
            <div className="px-4 py-3 flex items-center justify-between"
                 style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
              <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
                Auto-digest deliveries (last 10)
              </span>
              <span className="text-xs" style={{ color: colors.muted, fontStyle: "italic" }}>
                Cron: 1st @ 09:00 UTC
              </span>
            </div>
            {history.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm" style={{ color: colors.muted }}
                   data-testid="pricing-insights-history-empty">
                No deliveries yet — the first monthly digest will appear here.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                    <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Sent</th>
                    <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Month</th>
                    <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Services / suggestions</th>
                    <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id} data-testid={`pricing-insights-history-row-${h.id}`}
                        style={{ borderBottom: `1px solid ${colors.border}` }}>
                      <td className="px-4 py-2" style={{ color: colors.onSurface }}>
                        {h.sent_at ? new Date(h.sent_at).toLocaleString() : "—"}
                      </td>
                      <td className="px-4 py-2 text-xs" style={{ color: colors.muted }}>{h.month}</td>
                      <td className="px-4 py-2 text-xs" style={{ color: colors.muted }}>
                        {h.service_count || 0} / {h.suggestion_count || 0}
                      </td>
                      <td className="px-4 py-2">
                        {h.mocked ? (
                          <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                                style={{ background: "#FEF3C7", color: "#92400E" }}
                                title={h.reason || "mocked"}>
                            MOCKED · {h.reason || "no reason"}
                          </span>
                        ) : (
                          <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                                style={{ background: "#DCFCE7", color: "#166534" }}>
                            Sent
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
