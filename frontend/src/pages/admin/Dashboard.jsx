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
  UserCheck,
  UserX,
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
import { colors, gradients, money } from "@/theme";
import { KPI_TONE_ROTATION, getAccentTone } from "@/utils/serviceLineTheme";
import LiveWeatherWidget from "@/components/Weather/WeatherWidget";
import MassMessagingCard from "@/components/mass-messaging/MassMessagingCard";
import TeamCpoReadinessWidget from "@/components/admin/TeamCpoReadinessWidget";
import RecommendationsQueueWidget from "@/components/admin/RecommendationsQueueWidget";
import RevenueDateRangeFilter from "@/components/dashboard/RevenueDateRangeFilter";
import RevenueByCategoryTile from "@/components/dashboard/RevenueByCategoryTile";
import RevenueForecastTile from "@/components/dashboard/RevenueForecastTile";
import IncomeByServiceCategoryTile from "@/components/dashboard/IncomeByServiceCategoryTile";
import EbitTile from "@/components/dashboard/EbitTile";
import GlobalSearchBar from "@/components/dashboard/GlobalSearchBar";
// Phase L1.5 · Feb-2026 — 7-card action row (Today's Routes · Approve
// Check-ins · Unpaid · Overdue · New Leads · Alerts · Missed Services).
// Batched via `GET /api/dashboard/action-cards`; auto-hides cards
// with count 0 (except Open Intelligence Alerts). Manager/admin/
// super_admin only — parent handles the role gate.
import DashboardActionCards from "@/components/dashboard/DashboardActionCards";
import DataIntegrityTile from "@/components/admin/DataIntegrityTile";
import BulkOpsAuditTile from "@/components/admin/BulkOpsAuditTile";
// Phase F3 · Feb-2026 — Soshie Publishing Dashboard Tile.
import SoshiePublishingTile from "@/components/admin/SoshiePublishingTile";
// Phase H5 · Feb-2026 — Crew Productivity tile (weekly revenue-per-crew).
import CrewProductivityTile from "@/components/admin/CrewProductivityTile";
// Feb-2026 · UX Polish Batch B — Routing Cost telemetry tile.
import RoutingCostTile from "@/components/admin/RoutingCostTile";
// Feb-2026 · Polish bundle Item 3 — Warranties nearing expiration tile.
import WarrantiesExpiringTile from "@/components/admin/WarrantiesExpiringTile";
import { useAuth } from "@/auth";
// Feb-2026 · N5-T1 · PageHeader adoption sweep (Option A: replace).
import PageHeader from "@/components/layout/PageHeader";

function Skeleton({ className = "", style = {} }) {
  return (
    <div
      className={`animate-pulse rounded-xl ${className}`}
      style={{ backgroundColor: colors.surfaceTertiary, ...style }}
    />
  );
}


// ═══════════════════════════════════════════════════════════════
// Feb 2026 · Color pass fix 1 — RevenueChart current-month
// detection. Pure logic, exported so
// ``feb2026-revenue-chart-current-month.test.jsx`` can drive it
// with a mocked ``Date`` without needing to mount the full
// dashboard (recharts SVGs don't lay out in jsdom).
// ═══════════════════════════════════════════════════════════════
export const REVENUE_MONTH_ABBR = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

export function computeRevenueBarFills(series, now = new Date()) {
  const currentMonthLabel = REVENUE_MONTH_ABBR[now.getMonth()];
  const data = (series || []).map((s) => ({
    ...s,
    isCurrent: String(s.label || "").trim() === currentMonthLabel,
  }));
  // The current-month bar might be present in the series but with
  // ``value === 0`` (tenant hasn't invoiced yet this month) — in
  // which case recharts renders no visible path for it. Detect
  // that case and re-anchor the highlight on the most recent
  // NON-ZERO bar so the chart never looks flat / uncoloured.
  const currentIdx = data.findIndex((d) => d.isCurrent);
  const currentIsEmpty = currentIdx >= 0
    && !(Number(data[currentIdx].value) > 0);
  if (currentIsEmpty || currentIdx < 0) {
    for (let i = data.length - 1; i >= 0; i -= 1) {
      if (Number(data[i].value) > 0) {
        data.forEach((d) => { d.isCurrent = false; });
        data[i].isCurrent = true;
        break;
      }
    }
    // Series is all-zero → fallback to the last row so at least
    // one bar carries the label (no visible path either way).
    if (!data.some((d) => d.isCurrent) && data.length > 0) {
      data[data.length - 1].isCurrent = true;
    }
  }
  return data.map((d, i) => {
    const palette = getAccentTone(
      KPI_TONE_ROTATION[i % KPI_TONE_ROTATION.length]);
    return {
      ...d,
      fill: d.isCurrent ? colors.pool[500] : palette[500],
    };
  });
}

function KpiCard({ icon: Icon, label, value, onClick, testId, tone }) {
  // Feb 2026 · Color pass — each KPI tile picks up a distinct
  // accent tone (violet / amber / sky / emerald / rose) so the
  // dashboard headline row visually pops.  ``tone`` maps to a
  // family under ``colors.accent`` — the icon gets the 500 shade,
  // the soft background sits on the 50 shade, and a 4-pixel left
  // border on the 500 shade ties them together.  White text on
  // 500+ / dark text on 50 both pass WCAG AA (spot-checked in
  // ``feb2026-color-contrast.test.js``).
  //
  // Phase K70.a · Feb-2026 — the icon chip carried a navy → green
  // gradient across every tile as the shared brand cue.
  //
  // Phase K74 · Feb-2026 — that gradient is swapped for solid
  // navy (``colors.tile.solidNavy`` == #1B1F5C, same value as
  // ``colors.nav.bg``). The pastel tone-driven background +
  // colored left-border are preserved so tiles remain visually
  // distinct at a glance; the solid navy chip is the shared
  // brand cue on top. White icon reads at AAA on ``#1B1F5C``
  // (12.8:1) — see colors.tile.solidNavy contrast note in theme.js.
  const palette = getAccentTone(tone);
  return (
    <button
      onClick={onClick}
      className="text-left rounded-2xl p-5 transition hover:brightness-95 active:scale-[0.99]"
      style={{
        backgroundColor: palette[50],
        border: `1px solid ${colors.border}`,
        borderLeft: `4px solid ${palette[500]}`,
      }}
      data-testid={testId}
      data-tone={tone || "sky"}
    >
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center mb-3"
        style={{
          backgroundColor: colors.tile.solidNavy,
          color: "#FFFFFF",
        }}
        data-testid="k74-kpi-identity-chip"
        data-tile-key={testId || ""}
        data-k74-solid-navy-chip="true"
      >
        <Icon size={20} />
      </div>
      <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>
        {value}
      </div>
      <div
        className="text-xs mt-1 font-semibold uppercase tracking-wide"
        style={{ color: palette[700] }}
      >
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
  // Feb 2026 · Color pass — the current-month detection lives in
  // the pure exported ``computeRevenueBarFills`` helper above so
  // it can be date-mocked in unit tests without needing to mount
  // the recharts SVG (which doesn't lay out under jsdom).
  const data = computeRevenueBarFills(series);
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
                <Cell key={i} fill={d.fill} />
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

  // Phase P15 · Feb-2026 — re-hydrate the dashboard when the tenant
  // timezone (or any other tenant-scoped setting) changes.  Fired by
  // BusinessSettings.jsx's TimezoneSelect ``onChange`` handler.  We
  // refetch ``/dashboard`` (whose numeric counts don't depend on tz
  // yet) AND bump the ``DashboardActionCards`` remount key so its
  // tenant-tz-anchored "today" endpoints refetch under the new zone.
  const [tenantSettingsVersion, setTenantSettingsVersion] = useState(0);
  useEffect(() => {
    function onTenantSettingsUpdated() {
      setTenantSettingsVersion((v) => v + 1);
      api
        .get("/dashboard")
        .then(setData)
        .catch(() => {});
    }
    window.addEventListener(
      "tenant:settings-updated", onTenantSettingsUpdated,
    );
    return () => window.removeEventListener(
      "tenant:settings-updated", onTenantSettingsUpdated,
    );
  }, []);

  const firstName = user?.name?.split(" ")[0] || "";

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-dashboard">
      {/* Feb-2026 · N5-T1 · PageHeader adoption. Replaces the
          inline <h1>Dashboard</h1> block with the shared
          <PageHeader/>. Subtitle keeps the greeting copy verbatim
          so no visible behavior changes for the operator. */}
      <PageHeader
        title="Dashboard"
        subtitle={`Hi${firstName ? `, ${firstName}` : ""} — here's your business at a glance.`}
      />

      {/* Feb-2026 · Dashboard reorg — Mass Messaging is the first
          CTA on the Dashboard. Self-guards on role internally
          (admin / super_admin only). */}
      <MassMessagingCard />

      {/* Feb 2026 · Dashboard quick-find — grouped search across
          customers / jobs / invoices / leads. Reuses the shared
          /api/search endpoint (admin | super_admin | manager). */}
      <GlobalSearchBar />

      {/* Feb-2026 · Revenue tiles — donut + forecast with a shared
          date-range filter.  Both tiles refetch when the range changes.
          Phase K5 · Feb-2026 — RevenueForecastTile was pulled OUT of
          this section and promoted to the topline row below.  The
          shared ``revenueRange`` state still drives the top tile so
          the filter here controls both surfaces. */}
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
              {/* Feb-2026 · Grammar hotfix — backlog (ii) fixed the
                  noun pluralization but the verb ``are`` was left
                  hardcoded; count=1 rendered "1 line item are
                  uncategorized." Now: is/are pivots on the count
                  too. */}
              {uncategorized.count} line item{uncategorized.count === 1 ? "" : "s"}{" "}
              {uncategorized.count === 1 ? "is" : "are"} uncategorized.
            </span>
            <span className="text-xs font-bold underline">Review →</span>
          </button>
        ) : null}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <RevenueByCategoryTile range={revenueRange} />
          <IncomeByServiceCategoryTile range={revenueRange} />
        </div>
      </div>

      {/* Feb-2026 · Dashboard reorg — action-cards row (Today's
          Routes, AI Alerts, ...) now sits under the Revenue-insights
          section. Manager+ only. Remounts via ``tenantSettingsVersion``
          so a tenant timezone change refetches the tz-anchored
          "today" counts immediately (no page reload). */}
      {(user?.role === "admin" || user?.role === "super_admin"
         || user?.role === "manager") ? (
        <DashboardActionCards key={tenantSettingsVersion} />
      ) : null}

      {error ? (
        <div
          className="rounded-xl p-4 text-sm"
          style={{ backgroundColor: "#FEE2E2", color: colors.error }}
          data-testid="dashboard-error"
        >
          {error}
        </div>
      ) : null}

      {/* Feb-2026 · Revenue Forecast + EBIT topline tiles. Sit below
          the Mass Messaging card, Global Search Bar, Revenue-insights
          section, and action-cards row per the Feb-2026 Dashboard
          reorg. RevenueForecastTile shares ``revenueRange`` state
          with the donut tiles above. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6"
              data-testid="dashboard-topline-tiles">
        <RevenueForecastTile range={revenueRange} />
        {(user?.role === "super_admin" || user?.role === "admin") && (
          <div data-testid="dashboard-ebit-tile-slot">
            <EbitTile />
          </div>
        )}
      </div>

      {/* Phase F3 · Feb-2026 — Soshie Publishing tile. Admin+ (super_admin
          / admin / owner) since moderation queue is admin-gated. */}
      {["super_admin", "admin", "owner"].includes(user?.role) ? (
        <div className="mb-6">
          <SoshiePublishingTile />
        </div>
      ) : null}

      {/* Feb-2026 follow-up — 5-day forecast panel unmounted per user
          request. The live now-condition widget stays; the 5-day panel
          added noise to the admin dashboard.  `<WeatherWidget5Day>`
          still lives at `/pages/aitools/WeatherWidget5Day.jsx` and is
          reachable from AI Tools when needed. */}
      {(user?.role === "admin" || user?.role === "super_admin") && (
        <div className="mb-6">
          {/* Feb 2026 · Task B — dashboard is report-focused, so pass
              ``collapsible`` so the widget renders today-only by
              default with Hourly / 7-Day / Radar expand chips. Tech
              /schedule keeps the always-expanded rendering (no prop). */}
          <LiveWeatherWidget user={user} collapsible />
        </div>
      )}

      {/* Feb 2026 · Priority 2 — the emerald "Total Paid Revenue"
          hero tile was removed per operator feedback: the number
          duplicated the split chip below and the giant gradient
          crowded out the KPI grid. The Pool vs Landscape split
          chip immediately below carries the same lifetime paid
          revenue plus the mix breakdown, so no data is lost.
          Locked-in-place by ``priority2-emerald-hero-removed.test.jsx``. */}

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

      {/* Phase K5 · Feb-2026 — Data Integrity + Crew Productivity
          were previously stacked above the Mass Messaging card.
          Both are now rendered directly below the Revenue-insights
          (a.k.a. Revenue Trend) section so the topline stays focused
          on money forecasts and the operational-health tiles sit
          adjacent to the KPI grid.  Role gates are unchanged
          (DataIntegrity → super_admin only; CrewProductivity →
          admin+). */}
      {user?.role === "super_admin" ? (
        <DataIntegrityTile userRole={user?.role} />
      ) : null}
      {/* Phase K41d · Feb-2026 — Bulk Operations audit tile.
          Renders below DataIntegrityTile because both tiles share
          the "admin drilldown activity" mental model. Role gate is
          admin+/super_admin (same as the bulk-resolve/undo endpoints
          the tile summarizes). The tile self-hides when the backend
          hasn't shipped K41d yet — safe under mixed-version rolls. */}
      {["super_admin", "admin", "owner"].includes(user?.role) ? (
        <BulkOpsAuditTile data={data} />
      ) : null}
      {["super_admin", "admin", "owner"].includes(user?.role) ? (
        <div className="mb-6">
          <CrewProductivityTile />
        </div>
      ) : null}
      {/* Feb-2026 · UX Polish Batch B — Routing Cost telemetry tile
          (admin-visible only). Reads the in-memory ring buffer
          maintained by the traffic-aware routing feature. */}
      {["super_admin", "admin", "owner"].includes(user?.role) ? (
        <div className="mb-6">
          <RoutingCostTile />
        </div>
      ) : null}

      {/* Feb-2026 · Polish bundle Item 3 — Warranties nearing expiration.
          Admin+/super_admin only; hides itself when zero contracts
          are within the 30-day window. */}
      {["super_admin", "admin", "owner"].includes(user?.role) ? (
        <div className="mb-6">
          <WarrantiesExpiringTile />
        </div>
      ) : null}

      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {data ? (
          <>
            <KpiCard
              icon={Briefcase}
              label="Active Jobs"
              value={data.active_jobs}
              onClick={() => navigate("/admin/jobs?status=active")}
              testId="kpi-active-jobs"
              tone="sky"
            />
            <KpiCard
              icon={Hourglass}
              label="Pending"
              value={data.pending_jobs}
              onClick={() => navigate("/admin/jobs?status=pending")}
              testId="kpi-pending"
              tone="amber"
            />
            {/* Feb-2026 · Active/Inactive Customers tile swap.
                Bottom row of the KPI grid replaces the legacy
                Customers total + Technicians tiles with a pair
                keyed to the recurring-service-contract signal.
                See ``routers/dashboard.py`` for the
                ``active_customers_count`` /
                ``inactive_customers_count`` fields; sum invariant
                (active + inactive == total_customers) preserved. */}
            <KpiCard
              icon={UserCheck}
              label="Active Customers"
              value={data.active_customers_count}
              onClick={() => navigate("/customers?status=active")}
              testId="kpi-active-customers"
              tone="violet"
            />
            <KpiCard
              icon={UserX}
              label="Inactive Customers"
              value={data.inactive_customers_count}
              onClick={() => navigate("/customers?status=inactive")}
              testId="kpi-inactive-customers"
              tone="emerald"
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
                      background: gradients.navyToGreen.css,
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
