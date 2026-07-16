/**
 * Phase 47.4 — Revenue Target Dashboard.
 * Admin/super_admin only. Consumes GET /budgets/{year}/dashboard.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, TrendingUp, Target, Percent, Activity } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, ReferenceLine, CartesianGrid, Tooltip, Legend } from "recharts";
import { api } from "@/api";
import { colors } from "@/theme";

function money(cents) {
  const v = (cents || 0) / 100;
  return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

const paceColor = { on_track: "#16A34A", ahead: "#2563EB", behind: "#DC2626", no_target: colors.muted };
const paceLabel = { on_track: "On track", ahead: "Ahead", behind: "Behind", no_target: "No target set" };

function Card({ icon: Icon, label, value, sub, tone, testid }) {
  return (
    <div className="rounded-2xl p-4"
         style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid={testid}>
      <div className="flex items-center gap-2 text-xs font-bold uppercase" style={{ color: colors.muted }}>
        <Icon size={13} /> {label}
      </div>
      <div className="text-2xl font-bold mt-2" style={{ color: tone || colors.onSurface }}>
        {value}
      </div>
      {sub ? <div className="text-xs mt-1" style={{ color: colors.muted }}>{sub}</div> : null}
    </div>
  );
}

export default function BudgetDashboard() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const load = async () => {
    setLoading(true); setErr(null);
    try {
      const res = await api.get(`/budgets/${year}/dashboard`);
      setData(res);
    } catch (e) { setErr(e.message); setData(null); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [year]);

  const chartData = useMemo(() => {
    if (!data?.months) return [];
    return data.months.map((m) => ({
      month: m.month.slice(-2),
      Target: (m.target_cents || 0) / 100,
      Actual: (m.actual_cents || 0) / 100,
    }));
  }, [data]);

  const thisMonthPct = useMemo(() => {
    if (!data?.this_month?.target_cents) return 0;
    return Math.min(200, Math.round(data.this_month.actual_cents / data.this_month.target_cents * 100));
  }, [data]);

  const ytdPct = useMemo(() => {
    if (!data?.ytd?.target_cents) return 0;
    return Math.min(200, Math.round(data.ytd.actual_cents / data.ytd.target_cents * 100));
  }, [data]);

  const paceKey = data?.ytd?.pace || "no_target";

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="budget-dashboard">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Revenue Target Dashboard</h1>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            Actuals from paid invoices vs. the budget target for {year}.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input type="number" min="2020" max="2100" value={year}
                 onChange={(e) => setYear(Number(e.target.value))}
                 className="text-sm px-2 py-1.5 rounded-md w-24"
                 style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                 data-testid="budget-dashboard-year" />
          <Link to="/admin/budget" className="text-xs font-semibold underline"
                style={{ color: colors.brand }} data-testid="budget-dashboard-setup-link">Edit budget →</Link>
          <button onClick={load} className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
                  style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                  data-testid="budget-dashboard-refresh">
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {!data?.has_budget && !loading ? (
        <div className="rounded-2xl p-4 mb-4"
             style={{ background: "#FEF9C3", border: "1px solid #FDE68A", color: "#854D0E" }}
             data-testid="budget-dashboard-no-budget">
          No budget set for {year}. <Link to="/admin/budget" className="underline font-bold">Set one now</Link>.
        </div>
      ) : null}
      {err ? (
        <div className="rounded-2xl p-4 mb-4"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="budget-dashboard-error">{err}</div>
      ) : null}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Card
          icon={Target}
          label="This month revenue"
          value={money(data?.this_month?.actual_cents)}
          sub={`of ${money(data?.this_month?.target_cents)} target · ${thisMonthPct}%`}
          testid="budget-card-this-month"
        />
        <Card
          icon={TrendingUp}
          label="YTD revenue"
          value={money(data?.ytd?.actual_cents)}
          sub={`of ${money(data?.ytd?.target_cents)} · ${ytdPct}%`}
          testid="budget-card-ytd"
        />
        <Card
          icon={Percent}
          label="YTD net margin"
          value={`${data?.ytd?.net_profit_pct ?? 0}%`}
          sub="Actual revenue − YTD target costs"
          testid="budget-card-net-profit"
        />
        <Card
          icon={Activity}
          label="Pace to annual target"
          value={paceLabel[paceKey]}
          tone={paceColor[paceKey]}
          sub={`${money(data?.annual?.actual_cents)} / ${money(data?.annual?.target_cents)}`}
          testid="budget-card-pace"
        />
      </div>

      <div className="rounded-2xl p-4"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="budget-dashboard-chart">
        <div className="text-xs font-bold uppercase mb-3" style={{ color: colors.muted }}>
          Monthly actual vs target
        </div>
        <div style={{ width: "100%", height: 320 }}>
          <ResponsiveContainer>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
              <XAxis dataKey="month" stroke={colors.muted} />
              <YAxis stroke={colors.muted} tickFormatter={(v) => v >= 1000 ? `$${Math.round(v / 1000)}k` : `$${v}`} />
              <Tooltip formatter={(v) => `$${Math.round(v).toLocaleString()}`} />
              <Legend />
              <Bar dataKey="Actual" fill={colors.brand} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Target" fill="#94A3B8" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
