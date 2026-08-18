import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import {
  Briefcase,
  Hourglass,
  Users,
  Wrench,
  TrendingUp,
  Clock,
  AlertCircle,
  Bell,
  CheckCircle2,
  ChevronRight,
  Waves,
  Droplet,
} from "lucide-react";
import { api } from "@/api";
import { brandGradientCss, colors, money } from "@/theme";
import LiveWeatherWidget from "@/components/Weather/WeatherWidget";
import MassMessagingCard from "@/components/mass-messaging/MassMessagingCard";
import TeamCpoReadinessWidget from "@/components/admin/TeamCpoReadinessWidget";
import RecommendationsQueueWidget from "@/components/admin/RecommendationsQueueWidget";
import RevenueDateRangeFilter from "@/components/dashboard/RevenueDateRangeFilter";
import RevenueByCategoryTile from "@/components/dashboard/RevenueByCategoryTile";
import RevenueForecastTile from "@/components/dashboard/RevenueForecastTile";
import IncomeByServiceCategoryTile from "@/components/dashboard/IncomeByServiceCategoryTile";
import EbitTile from "@/components/dashboard/EbitTile";
import { useAuth } from "@/auth";

function Skeleton({ className = "", style = {} }) {
  return (
    <div
      className={`animate-pulse rounded-xl ${className}`}
      style={{ backgroundColor: colors.surfaceTertiary, ...style }}
    />
  );
}

function KpiCard({ icon: Icon, label, value, onClick, testId }) {
  return (
    <button
      onClick={onClick}
      className="text-left rounded-2xl p-5 transition hover:brightness-95 active:scale-[0.99]"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testId}
    >
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center mb-3"
        style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
      >
        <Icon size={20} />
      </div>
      <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>
        {value}
      </div>
      <div className="text-xs mt-1" style={{ color: colors.muted }}>
        {label}
      </div>
    </button>
  );
}

/** Phase 20B module B — Referral Revenue tile. */
function ReferralRevenueTile() {
  const navigate = useNavigate();
  const [data, setData] = React.useState(null);
  React.useEffect(() => {
    api.get("/referrals/admin/analytics/v2")
      .then(setData)
      .catch(() => setData(null));
  }, []);
  if (!data) return null;
  const rev = data?.revenue_attribution?.total_usd || 0;
  const converted = data?.funnel?.converted || 0;
  return (
    <button
      onClick={() => navigate("/admin/referrals/analytics")}
      className="w-full text-left mb-6 rounded-2xl p-5 flex items-center gap-4 transition hover:brightness-95 active:scale-[0.99]"
      style={{
        background: `linear-gradient(135deg, ${colors.brand} 0%, ${colors.brandSecondary || colors.brand} 100%)`,
      }}
      data-testid="tile-referral-revenue"
    >
      <div className="w-14 h-14 rounded-xl flex items-center justify-center"
           style={{ backgroundColor: "rgba(255,255,255,0.2)", color: "#fff" }}>
        <TrendingUp size={26} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-bold uppercase tracking-wider"
             style={{ color: "rgba(255,255,255,0.85)" }}>
          Referral Revenue
        </div>
        <div className="text-3xl font-bold mt-1" style={{ color: "#fff" }}>
          ${rev.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </div>
        <div className="text-xs mt-0.5" style={{ color: "rgba(255,255,255,0.8)" }}>
          {converted} referral{converted === 1 ? "" : "s"} converted · view analytics
        </div>
      </div>
      <ChevronRight size={20} color="#fff" />
    </button>
  );
}

function StatusChip({ status }) {
  const meta = {
    requested: { bg: "#FFEDD5", fg: "#C2410C", label: "Requested" },
    pending: { bg: "#FEF9C3", fg: "#A16207", label: "Pending" },
    active: { bg: colors.brandTertiary, fg: colors.onBrandTertiary, label: "Active" },
    completed: { bg: "#DCFCE7", fg: colors.success, label: "Completed" },
    cancelled: { bg: "#FEE2E2", fg: colors.error, label: "Cancelled" },
    scheduled: { bg: "#E0E7FF", fg: "#4338CA", label: "Scheduled" },
  }[status] || { bg: colors.surfaceTertiary, fg: colors.muted, label: status || "—" };
  return (
    <span
      className="text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap"
      style={{ backgroundColor: meta.bg, color: meta.fg }}
    >
      {meta.label}
    </span>
  );
}

function RevenueChart({ series, outstanding }) {
  const last = series.length - 1;
  const data = series.map((s, i) => ({ ...s, isLast: i === last }));
  return (
    <div
      className="rounded-2xl p-6"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="revenue-chart"
    >
      <div className="flex items-start justify-between mb-6">
        <div>
          <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Revenue Trend
          </h3>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            Last 6 months
          </p>
        </div>
        <div
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full"
          style={{ backgroundColor: "#FEF9C3", color: "#A16207" }}
        >
          <AlertCircle size={14} />
          <span className="text-xs font-semibold">{money(outstanding)} due</span>
        </div>
      </div>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.divider} vertical={false} />
            <XAxis
              dataKey="label"
              stroke={colors.muted}
              tickLine={false}
              axisLine={false}
              style={{ fontSize: 12, fontFamily: "inherit" }}
            />
            <YAxis
              stroke={colors.muted}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v)}
              style={{ fontSize: 11 }}
              width={40}
            />
            <Tooltip
              cursor={{ fill: colors.brandTertiary + "80" }}
              contentStyle={{
                borderRadius: 12,
                border: `1px solid ${colors.border}`,
                fontSize: 13,
              }}
              formatter={(v) => [money(v), "Revenue"]}
            />
            <Bar dataKey="value" radius={[8, 8, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.isLast ? colors.brand : colors.brandTertiary} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PaymentsWidget({ onOpenInvoice, onViewAll }) {
  const [summary, setSummary] = useState(null);
  useEffect(() => {
    api.get("/payments/summary").then(setSummary).catch(() => setSummary(null));
  }, []);
  if (!summary) return null;
  const overdue = (summary.overdue || []).slice(0, 4);
  return (
    <div
      className="rounded-2xl p-6"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="payments-widget"
    >
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Payments
          </h3>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            {summary.month_label}
          </p>
        </div>
        <button
          onClick={onViewAll}
          className="text-sm font-semibold"
          style={{ color: colors.brand }}
          data-testid="payments-view-all"
        >
          View all
        </button>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div
          className="rounded-xl p-4"
          style={{ backgroundColor: colors.success + "12" }}
        >
          <div className="flex items-center gap-1.5" style={{ color: colors.success }}>
            <TrendingUp size={14} />
            <span className="text-xs font-semibold">Collected</span>
          </div>
          <div className="text-xl font-bold mt-1" style={{ color: colors.onSurface }} data-testid="widget-collected">
            {money(summary.collected_this_month)}
          </div>
        </div>
        <div className="rounded-xl p-4" style={{ backgroundColor: "#FEF9C3" }}>
          <div className="flex items-center gap-1.5" style={{ color: "#A16207" }}>
            <Clock size={14} />
            <span className="text-xs font-semibold">Outstanding</span>
          </div>
          <div className="text-xl font-bold mt-1" style={{ color: colors.onSurface }} data-testid="widget-outstanding">
            {money(summary.outstanding_total)}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
            {summary.outstanding_count} invoice{summary.outstanding_count === 1 ? "" : "s"}
          </div>
        </div>
      </div>
      {overdue.length ? (
        <>
          <div
            className="text-xs uppercase tracking-wide font-semibold mt-5 mb-1"
            style={{ color: colors.muted }}
          >
            Awaiting payment
          </div>
          {overdue.map((o) => (
            <button
              key={o.id}
              onClick={() => onOpenInvoice(o.id)}
              className="w-full flex items-center gap-3 py-3 text-left"
              style={{ borderTop: `1px solid ${colors.divider}` }}
              data-testid={`overdue-${o.id}`}
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                  {o.customer_name}
                </div>
                <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                  {money(o.total)} · {o.days === 0 ? "today" : `${o.days}d`}
                </div>
              </div>
              <ChevronRight size={16} color={colors.muted} />
            </button>
          ))}
        </>
      ) : (
        <div className="flex items-center gap-2 mt-4">
          <CheckCircle2 size={16} color={colors.success} />
          <span className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
            No outstanding invoices
          </span>
        </div>
      )}
    </div>
  );
}

function RecentJobs({ jobs, onOpen }) {
  if (!jobs?.length) return null;
  return (
    <div className="mt-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
          Recent Jobs
        </h3>
      </div>
      <div className="space-y-2">
        {jobs.map((j) => (
          <button
            key={j.id}
            onClick={() => onOpen(j.id)}
            className="w-full flex items-center gap-3 p-4 rounded-xl transition hover:brightness-95 text-left"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`recent-job-${j.id}`}
          >
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
            >
              <Droplet size={18} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                {j.title}
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {j.customer_name}
              </div>
            </div>
            <StatusChip status={j.status} />
          </button>
        ))}
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  // Feb-2026 · Revenue tiles — shared date range across both tiles.
  const [revenueRange, setRevenueRange] = useState(null);
  // Feb-2026 · Income-category enforcement — banner data.
  const [uncategorized, setUncategorized] = useState(null);
  useEffect(() => {
    api.get("/reports/uncategorized-count")
      .then(setUncategorized)
      .catch(() => setUncategorized(null));
  }, []);

  useEffect(() => {
    api
      .get("/dashboard")
      .then(setData)
      .catch((e) => setError(e.message || "Failed to load dashboard"));
  }, []);

  const firstName = user?.name?.split(" ")[0] || "";

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-dashboard">
      <header className="mb-6">
        <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
          Dashboard
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          Hi{firstName ? `, ${firstName}` : ""} — here&apos;s your business at a glance.
        </p>
      </header>

      {error ? (
        <div
          className="rounded-xl p-4 text-sm"
          style={{ backgroundColor: "#FEE2E2", color: colors.error }}
          data-testid="dashboard-error"
        >
          {error}
        </div>
      ) : null}

      {/* Phase 15 · Feb-2026 — Mass Messaging top card. Self-guards on
          role (admin / super_admin only). Renders above the weather
          widget so it's the first CTA an admin sees on the Dashboard. */}
      <MassMessagingCard />

      {/* Feb-2026 follow-up — 5-day forecast panel unmounted per user
          request. The live now-condition widget stays; the 5-day panel
          added noise to the admin dashboard.  `<WeatherWidget5Day>`
          still lives at `/pages/aitools/WeatherWidget5Day.jsx` and is
          reachable from AI Tools when needed. */}
      {(user?.role === "admin" || user?.role === "super_admin") && (
        <div className="mb-6">
          <LiveWeatherWidget user={user} />
        </div>
      )}

      {/* Hero KPI card */}
      <div
        className="rounded-2xl p-6 md:p-8 mb-6 relative overflow-hidden"
        style={{
          background: brandGradientCss,
          minHeight: 180,
        }}
        data-testid="dashboard-hero"
      >
        <div
          className="absolute inset-0 opacity-25"
          style={{
            backgroundImage:
              "url(https://images.pexels.com/photos/8974468/pexels-photo-8974468.jpeg?auto=compress&cs=tinysrgb&w=1200)",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        <div className="relative">
          <p className="text-white/85 text-sm font-medium">Total Revenue</p>
          {data ? (
            <p className="text-white text-4xl md:text-5xl font-bold mt-1" data-testid="dashboard-revenue">
              {money(data.revenue)}
            </p>
          ) : (
            <Skeleton className="mt-2" style={{ height: 44, width: 220, backgroundColor: "rgba(255,255,255,0.25)" }} />
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {data && (
              <>
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-white text-xs font-medium bg-white/20 backdrop-blur">
                  <Briefcase size={12} />
                  {data.active_jobs} active jobs
                </span>
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-white text-xs font-medium bg-white/20 backdrop-blur">
                  <Clock size={12} />
                  {money(data.outstanding)} due
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Requested jobs banner */}
      {data?.requested_jobs > 0 ? (
        <button
          onClick={() => navigate("/jobs")}
          className="w-full flex items-center gap-3 rounded-xl p-3 mb-6 transition hover:brightness-95"
          style={{
            backgroundColor: "#FFEDD5",
            border: `1px solid #FED7AA`,
          }}
          data-testid="requested-jobs-banner"
        >
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: "#FED7AA", color: "#C2410C" }}
          >
            <Bell size={16} />
          </div>
          <span className="flex-1 text-sm font-semibold text-left" style={{ color: "#C2410C" }}>
            {data.requested_jobs} new service request{data.requested_jobs > 1 ? "s" : ""} awaiting
            review
          </span>
          <ChevronRight size={16} color="#C2410C" />
        </button>
      ) : null}

      {/* Phase 53e · Feb-2026 — EBIT exec-summary tile. Restricted
          to super_admin + admin (manager sees the full report page
          but NOT this dashboard tile, per Phase 53e scope). */}
      {(user?.role === "super_admin" || user?.role === "admin") && (
        <div className="mb-6" data-testid="dashboard-ebit-tile-slot">
          <EbitTile />
        </div>
      )}

      {/* Feb-2026 · Revenue tiles — donut + forecast with a shared
          date-range filter.  Both tiles refetch when the range changes. */}
      <div className="mb-6" data-testid="revenue-tiles-section">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold"
              style={{ color: colors.onSurface }}>Revenue insights</h2>
          <RevenueDateRangeFilter onChange={setRevenueRange} />
        </div>
        {uncategorized && uncategorized.count > 0 ? (
          <button
            onClick={() => navigate("/reports/uncategorized-items")}
            className="w-full flex items-center gap-3 rounded-xl p-3 mb-3 transition hover:brightness-95 text-left"
            style={{ background: "#FEF3C7", color: "#78350F",
                      border: "1px solid #FCD34D" }}
            data-testid="uncategorized-banner"
          >
            <span className="text-lg" aria-hidden="true">⚠️</span>
            <span className="flex-1 text-sm font-semibold">
              {uncategorized.count} line item
              {uncategorized.count === 1 ? "" : "s"} are uncategorized.
            </span>
            <span className="text-xs font-bold underline">Review →</span>
          </button>
        ) : null}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <RevenueByCategoryTile range={revenueRange} />
          <IncomeByServiceCategoryTile range={revenueRange} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
          <RevenueForecastTile range={revenueRange} />
        </div>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {data ? (
          <>
            <KpiCard
              icon={Briefcase}
              label="Active Jobs"
              value={data.active_jobs}
              onClick={() => navigate("/jobs")}
              testId="kpi-active-jobs"
            />
            <KpiCard
              icon={Hourglass}
              label="Pending"
              value={data.pending_jobs}
              onClick={() => navigate("/jobs")}
              testId="kpi-pending"
            />
            <KpiCard
              icon={Users}
              label="Customers"
              value={data.total_customers}
              onClick={() => navigate("/customers")}
              testId="kpi-customers"
            />
            <KpiCard
              icon={Wrench}
              label="Technicians"
              value={data.total_technicians}
              onClick={() => navigate("/more")}
              testId="kpi-technicians"
            />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} style={{ height: 120 }} />)
        )}
      </div>

      {/* Referral Revenue tile — Phase 20B module B */}
      <ReferralRevenueTile />

      {/* Revenue chart + payments */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        {data ? (
          <RevenueChart series={data.revenue_series || []} outstanding={data.outstanding} />
        ) : (
          <Skeleton style={{ height: 320 }} />
        )}
        <PaymentsWidget
          onOpenInvoice={(id) => navigate(`/quotes/${id}`)}
          onViewAll={() => navigate("/quotes")}
        />
      </div>

      {/* Phase 56.13c — Team CPO Readiness widget */}
      <TeamCpoReadinessWidget />
      <RecommendationsQueueWidget />

      {/* Revenue by service (progress bars) */}
      {data?.revenue_by_service?.length ? (
        <div
          className="rounded-2xl p-6 mb-6"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="revenue-by-service"
        >
          <div className="flex items-center gap-2 mb-4">
            <Waves size={18} color={colors.brand} />
            <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              Revenue by Service
            </h3>
          </div>
          {(() => {
            const max = Math.max(...data.revenue_by_service.map((x) => x.value), 1);
            return data.revenue_by_service.map((s) => (
              <div key={s.label} className="flex items-center gap-3 mb-2">
                <div className="w-32 truncate text-sm font-medium" style={{ color: colors.onSurfaceSecondary }}>
                  {s.label}
                </div>
                <div
                  className="flex-1 h-2.5 rounded-full overflow-hidden"
                  style={{ backgroundColor: colors.surfaceTertiary }}
                >
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${Math.max(4, (s.value / max) * 100)}%`,
                      background: brandGradientCss,
                    }}
                  />
                </div>
                <div className="w-20 text-right text-sm font-semibold" style={{ color: colors.onSurface }}>
                  {money(s.value)}
                </div>
              </div>
            ));
          })()}
        </div>
      ) : null}

      {/* Recent jobs */}
      {data?.recent_jobs?.length ? (
        <RecentJobs jobs={data.recent_jobs.slice(0, 5)} onOpen={(id) => navigate(`/jobs/${id}`)} />
      ) : null}
    </div>
  );
}
