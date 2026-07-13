import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarChart3,
  TrendingUp,
  MapPin,
  Users2,
  DollarSign,
  ListChecks,
  PieChart as PieIcon,
  Clock,
  Timer,
  History,
  Users,
  ChevronRight,
} from "lucide-react";
import { api } from "@/api";
import { colors, money, brandGradientCss } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";

function Tile({ icon: Icon, label, to, sub, testId }) {
  return (
    <Link
      to={to}
      className="rounded-2xl p-5 transition hover:brightness-95 active:scale-[0.99] flex items-start gap-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testId}
    >
      <div
        className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
      >
        <Icon size={20} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>
          {label}
        </div>
        <div className="text-xs mt-0.5 truncate" style={{ color: colors.muted }}>
          {sub}
        </div>
      </div>
      <ChevronRight size={16} style={{ color: colors.muted }} />
    </Link>
  );
}

export default function ReportsHub() {
  const { start, end } = useDateRange("this-month");
  const [summary, setSummary] = useState(null);
  const [fcards, setFcards] = useState(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await api.get(`/reports/business-summary?date_from=${start}&date_to=${end}`);
        if (live) setSummary(r);
      } catch {}
      try {
        const f = await api.get(`/reports/forecast-cards`);
        if (live) setFcards(f);
      } catch {}
    })();
    return () => { live = false; };
  }, [start, end]);

  const qs = `?start=${start}&end=${end}&preset=${new URLSearchParams(window.location.search).get("preset") || "this-month"}`;
  const revenue = summary?.kpis?.revenue ?? 0;
  const outstanding = summary?.kpis?.outstanding ?? 0;
  const jobs = summary?.kpis?.total_jobs ?? 0;
  const forecast = fcards?.weighted_forecast ?? 0;

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" style={{ fontFamily: "inherit" }} data-testid="reports-hub">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold" style={{ color: colors.onSurface }}>
            Reports
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            All finance + operations reports for the selected window
          </p>
        </div>
        <DateRangePicker />
      </div>

      {/* Preview KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          { label: "Revenue", value: money(revenue), icon: DollarSign },
          { label: "Outstanding", value: money(outstanding), icon: Clock },
          { label: "Jobs in window", value: jobs, icon: ListChecks },
          { label: "Weighted forecast (90d)", value: money(forecast), icon: TrendingUp },
        ].map((k) => {
          const Ic = k.icon;
          return (
            <div
              key={k.label}
              className="rounded-2xl p-4"
              style={{
                background: brandGradientCss,
                color: "#fff",
              }}
              data-testid={`kpi-${k.label.toLowerCase().replace(/\s+/g, "-")}`}
            >
              <Ic size={18} style={{ opacity: 0.9 }} />
              <div className="text-xs mt-2 opacity-90">{k.label}</div>
              <div className="text-xl md:text-2xl font-bold mt-0.5">{k.value}</div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <Tile icon={BarChart3} label="Business Summary" to={`/reports/business-summary${qs}`}
              sub="KPIs · trend · top customers · services" testId="tile-business-summary" />
        <Tile icon={TrendingUp} label="Revenue Forecast" to={`/reports/forecast${qs}`}
              sub="90-day projected income (weighted)" testId="tile-forecast" />
        <Tile icon={MapPin} label="Revenue by City" to={`/reports/revenue-by-city${qs}`}
              sub="Group paid invoices by customer city" testId="tile-revenue-by-city" />
        <Tile icon={Users2} label="Revenue by Crew" to={`/reports/revenue-by-crew${qs}`}
              sub="Solo tech + assigned crews" testId="tile-revenue-by-crew" />
        <Tile icon={Users} label="Revenue by Customer" to={`/reports/revenue-by-customer${qs}`}
              sub="Top payers in window" testId="tile-revenue-by-customer" />
        <Tile icon={DollarSign} label="Gross Sales" to={`/reports/gross-sales${qs}`}
              sub="All invoices issued in window" testId="tile-gross-sales" />
        <Tile icon={ListChecks} label="Invoiced Items" to={`/reports/invoiced-items${qs}`}
              sub="Line-item aggregation" testId="tile-invoiced-items" />
        <Tile icon={PieIcon} label="Income by Category" to={`/income-by-category${qs}`}
              sub="Category donut breakdown" testId="tile-income-by-category" />
        <Tile icon={Timer} label="Avg Job Time" to={`/avg-job-time`}
              sub="Per-tech average duration" testId="tile-avg-job-time" />
        <Tile icon={Clock} label="Job Timers" to={`/job-timers`}
              sub="Currently running timers" testId="tile-job-timers" />
        <Tile icon={History} label="Log History" to={`/log-history`}
              sub="Audit trail" testId="tile-log-history" />
      </div>
    </div>
  );
}
