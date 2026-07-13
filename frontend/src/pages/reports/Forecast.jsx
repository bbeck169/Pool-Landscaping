import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { ArrowLeft, TrendingUp, Layers, RefreshCw, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors, money, brandGradient } from "@/theme";

function Card({ children, className = "", testId }) {
  return (
    <div
      className={`rounded-2xl p-5 ${className}`}
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={testId}
    >
      {children}
    </div>
  );
}

export default function Forecast() {
  const nav = useNavigate();
  const [series, setSeries] = useState([]);
  const [cards, setCards] = useState(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(90);

  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([
      api.get(`/reports/forecast?days=${days}`),
      api.get(`/reports/forecast-cards`),
    ]).then(([f, c]) => {
      if (!live) return;
      setSeries(f.series || []);
      setTotal(f.total || 0);
      setCards(c);
      setLoading(false);
    }).catch(() => live && setLoading(false));
    return () => { live = false; };
  }, [days]);

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid="forecast-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav("/reports")}
                  className="p-2 rounded-lg hover:brightness-95"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                  data-testid="back-to-reports">
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Revenue Forecast</h1>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
              Projected revenue from active recurring plans + probability-weighted open quotes
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {[30, 60, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold transition"
                    style={{
                      backgroundColor: days === d ? colors.brand : colors.surface,
                      color: days === d ? "#fff" : colors.onSurface,
                      border: `1px solid ${days === d ? colors.brand : colors.border}`,
                    }}
                    data-testid={`forecast-days-${d}`}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Card testId="fc-pipeline">
          <Layers size={18} style={{ color: colors.brand }} />
          <div className="text-2xl font-bold mt-3" style={{ color: colors.onSurface }}>
            {cards ? money(cards.pipeline_value) : "—"}
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>Open pipeline (quotes)</div>
        </Card>
        <Card testId="fc-weighted">
          <TrendingUp size={18} style={{ color: colors.brand }} />
          <div className="text-2xl font-bold mt-3" style={{ color: colors.onSurface }}>
            {cards ? money(cards.weighted_forecast) : "—"}
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>Weighted forecast</div>
        </Card>
        <Card testId="fc-recurring">
          <RefreshCw size={18} style={{ color: colors.brand }} />
          <div className="text-2xl font-bold mt-3" style={{ color: colors.onSurface }}>
            {cards ? money(cards.monthly_recurring) : "—"}
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>Secured recurring / mo · {cards?.active_plan_count ?? 0} plans</div>
        </Card>
        <Card testId="fc-atrisk">
          <AlertTriangle size={18} style={{ color: colors.error }} />
          <div className="text-2xl font-bold mt-3" style={{ color: colors.error }}>
            {cards ? money(cards.at_risk) : "—"}
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>At risk (past-due 30d+)</div>
        </Card>
      </div>

      <Card testId="forecast-chart-card">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            Projected revenue · next {days} days (weekly)
          </div>
          <div className="text-sm font-bold" style={{ color: colors.brand }} data-testid="forecast-total">
            {money(total)}
          </div>
        </div>
        {loading ? (
          <div className="animate-pulse rounded-xl h-72" style={{ backgroundColor: colors.surfaceTertiary }} />
        ) : (
          <div style={{ height: 300 }}>
            <ResponsiveContainer>
              <AreaChart data={series}>
                <defs>
                  <linearGradient id="fcGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={brandGradient[0]} stopOpacity={0.4} />
                    <stop offset="100%" stopColor={brandGradient[0]} stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                <XAxis dataKey="week" stroke={colors.muted} fontSize={11}
                       tickFormatter={(v) => v.slice(5)} />
                <YAxis stroke={colors.muted} fontSize={11} />
                <Tooltip formatter={(v) => money(v)} labelFormatter={(l) => `Week of ${l}`} />
                <Area type="monotone" dataKey="amount" stroke={brandGradient[0]}
                      strokeWidth={2} fill="url(#fcGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
    </div>
  );
}
