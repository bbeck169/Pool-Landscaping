import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, BarChart, Bar,
} from "recharts";
import { ArrowLeft, DollarSign, Clock, ListChecks, TrendingUp, Users } from "lucide-react";
import { api } from "@/api";
import { colors, money, brandGradient } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";

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

function Skeleton({ h = 24, w = "100%" }) {
  return (
    <div
      className="animate-pulse rounded-lg"
      style={{ backgroundColor: colors.surfaceTertiary, height: h, width: w }}
    />
  );
}

function KpiCard({ icon: Icon, label, value, testId }) {
  return (
    <Card testId={testId}>
      <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-3"
           style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
        <Icon size={18} />
      </div>
      <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>{value}</div>
      <div className="text-xs mt-1" style={{ color: colors.muted }}>{label}</div>
    </Card>
  );
}

export default function BusinessSummary() {
  const nav = useNavigate();
  const { start, end } = useDateRange("this-month");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.get(`/reports/business-summary?date_from=${start}&date_to=${end}`)
      .then((r) => { if (live) { setData(r); setLoading(false); } })
      .catch(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [start, end]);

  const k = data?.kpis || {};

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid="business-summary-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav("/reports")}
                  className="p-2 rounded-lg hover:brightness-95"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                  data-testid="back-to-reports">
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Business Summary</h1>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>KPIs + trend for {start} → {end}</p>
          </div>
        </div>
        <DateRangePicker />
      </div>

      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} h={110} />)}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <KpiCard icon={DollarSign} label="Revenue" value={money(k.revenue)} testId="kpi-revenue" />
            <KpiCard icon={Clock} label="Outstanding" value={money(k.outstanding)} testId="kpi-outstanding" />
            <KpiCard icon={ListChecks} label="Jobs" value={k.total_jobs || 0} testId="kpi-jobs" />
            <KpiCard icon={TrendingUp} label="Avg ticket" value={money(k.avg_ticket)} testId="kpi-avg-ticket" />
          </div>

          <Card className="mb-6" testId="revenue-trend-card">
            <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>
              Revenue trend (6 mo)
            </div>
            <div style={{ height: 260 }}>
              <ResponsiveContainer>
                <LineChart data={data?.revenue_series || []}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                  <XAxis dataKey="label" stroke={colors.muted} fontSize={12} />
                  <YAxis stroke={colors.muted} fontSize={12} />
                  <Tooltip formatter={(v) => money(v)} />
                  <Line type="monotone" dataKey="value" stroke={brandGradient[0]} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card testId="top-customers-card">
              <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>
                Top customers
              </div>
              <table className="w-full text-sm">
                <tbody>
                  {(data?.top_customers || []).map((r, i) => (
                    <tr key={i}>
                      <td className="py-1.5" style={{ color: colors.onSurface }}>{r.label}</td>
                      <td className="py-1.5 text-right font-semibold" style={{ color: colors.brand }}>
                        {money(r.value)}
                      </td>
                    </tr>
                  ))}
                  {(!data?.top_customers || data.top_customers.length === 0) && (
                    <tr><td colSpan={2} className="py-6 text-center text-sm" style={{ color: colors.muted }}>
                      No paid customers in this window
                    </td></tr>
                  )}
                </tbody>
              </table>
            </Card>
            <Card testId="revenue-by-service-card">
              <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>
                Revenue by service
              </div>
              <div style={{ height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={data?.revenue_by_service || []}>
                    <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                    <XAxis dataKey="label" stroke={colors.muted} fontSize={11} />
                    <YAxis stroke={colors.muted} fontSize={11} />
                    <Tooltip formatter={(v) => money(v)} />
                    <Bar dataKey="value" fill={brandGradient[1]} radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
