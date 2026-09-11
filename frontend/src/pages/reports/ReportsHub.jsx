import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  DollarSign,
  Users,
  MapPin,
  BarChart3,
  Activity,
  Users2,
  Target,
  Gauge,
  FileText,
  CalendarClock,
  ChevronRight,
  Lock,
  UserMinus,
  Clock,
  Wrench,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";
import { formatValue, formatNumber } from "@/components/reports/formatters";

/**
 * Phase K66 · Feb-2026 — ReportsHub quick-access tile grid.
 *
 * Landing surface at ``/reports``. Every visible report gets its
 * own tile with a live headline KPI + one-click deep-link to the
 * corresponding tab in ``/reports/suite``. R1–R7 stubs render as
 * "Coming soon" placeholders so the eventual growth of the
 * reporting suite is visible from day one.
 *
 * Constraints (K66):
 *   * Web only.
 *   * Reuses ``/api/reports/kpi/{key}`` — no new endpoints.
 *   * Preserves role gating (existing ``AdminOnly`` wrapper on the
 *     route in ``App.js``).
 *   * Ships with the current tile visual style — K70 will
 *     retheme (navy → green gradient + green-fill buttons).
 */
export default function ReportsHub() {
  const { start, end } = useDateRange("this-month");

  // Live KPI state — one per built tile.
  const [revenueTotal, setRevenueTotal]     = useState({ loading: true });
  const [revenueByCust, setRevenueByCust]   = useState({ loading: true });
  const [revenueByCity, setRevenueByCity]   = useState({ loading: true });
  // R1.b · Feb-2026 — Financial suite tile flip. Drives the R1
  // tile's live headline KPI (P&L Net Income for the window).
  const [pnlByPeriod, setPnlByPeriod]       = useState({ loading: true });

  useEffect(() => {
    let live = true;
    const qs = `?period=custom&start=${start}&end=${end}`;

    // Revenue Total — scalar metric, returns {value, format, ...}.
    (async () => {
      try {
        const r = await api.get(`/reports/kpi/revenue_total${qs}`);
        if (live) setRevenueTotal({ loading: false, data: r });
      } catch (e) {
        if (live) setRevenueTotal({ loading: false, error: e?.message || "Failed" });
      }
    })();
    // Revenue by Customer — grouped metric; headline = total.
    (async () => {
      try {
        const r = await api.get(`/reports/kpi/revenue_by_customer${qs}&limit=1&include_prior=false`);
        if (live) setRevenueByCust({ loading: false, data: r });
      } catch (e) {
        if (live) setRevenueByCust({ loading: false, error: e?.message || "Failed" });
      }
    })();
    // Revenue by City — grouped metric; headline = total.
    (async () => {
      try {
        const r = await api.get(`/reports/kpi/revenue_by_city${qs}&limit=1`);
        if (live) setRevenueByCity({ loading: false, data: r });
      } catch (e) {
        if (live) setRevenueByCity({ loading: false, error: e?.message || "Failed" });
      }
    })();
    // R1.b · Feb-2026 — P&L Net Income headline for the Financial
    // suite tile flip. Uses ``pnl_by_period`` (scalar) so we get a
    // signed delta chip for free.
    (async () => {
      try {
        const r = await api.get(`/reports/kpi/pnl_by_period${qs}`);
        if (live) setPnlByPeriod({ loading: false, data: r });
      } catch (e) {
        if (live) setPnlByPeriod({ loading: false, error: e?.message || "Failed" });
      }
    })();

    return () => { live = false; };
  }, [start, end]);

  // Suite deep-link querystring — preserve period + custom range
  // so the tabbed shell picks up the same window on landing.
  const preset = new URLSearchParams(window.location.search).get("preset") || "this-month";
  const suiteQs = `?period=custom&start=${start}&end=${end}&preset=${preset}`;

  const builtTiles = [
    {
      key: "revenue-total",
      icon: DollarSign,
      title: "Revenue Total",
      description: "All revenue for the selected window.",
      to: `/reports/suite${suiteQs}&tab=overview`,
      kpi: revenueTotal,
      renderKpi: (state) => {
        if (state.loading) return "…";
        if (state.error) return "—";
        const v = state.data?.value;
        const fmt = state.data?.format || "currency";
        return formatValue(v, fmt);
      },
      kpiSubtitle: (state) => {
        if (state.loading || state.error) return null;
        const d = state.data?.delta_pct;
        if (d === null || d === undefined) return null;
        const sign = d > 0 ? "+" : "";
        return `${sign}${Number(d).toFixed(1)}% vs prior`;
      },
    },
    {
      key: "revenue-by-customer",
      icon: Users,
      title: "Revenue by Customer",
      description: "Top-paying customers in the window, ranked.",
      to: `/reports/suite${suiteQs}&tab=financial#revenue-by-customer`,
      kpi: revenueByCust,
      renderKpi: (state) => {
        if (state.loading) return "…";
        if (state.error) return "—";
        return formatValue(state.data?.total ?? 0, "currency");
      },
      kpiSubtitle: (state) => {
        if (state.loading || state.error) return null;
        const n = state.data?.row_count ?? 0;
        return `${formatNumber(n)} customer${n === 1 ? "" : "s"}`;
      },
    },
    {
      key: "revenue-by-city",
      icon: MapPin,
      title: "Revenue by City",
      description: "Group paid invoices by customer city.",
      to: `/reports/suite${suiteQs}&tab=financial#revenue-by-city`,
      kpi: revenueByCity,
      renderKpi: (state) => {
        if (state.loading) return "…";
        if (state.error) return "—";
        return formatValue(state.data?.total ?? 0, "currency");
      },
      kpiSubtitle: (state) => {
        if (state.loading || state.error) return null;
        const n = state.data?.row_count ?? 0;
        return `${formatNumber(n)} cit${n === 1 ? "y" : "ies"}`;
      },
    },
    // R1.b · Feb-2026 — Financial suite tile flip (was
    // ``comingSoonTiles`` R1 before this phase).
    {
      key: "r1-financial",
      icon: BarChart3,
      title: "R1 · Financial Suite",
      description: "P&L, cash flow, A/R aging & unpaid invoices.",
      to: `/reports/suite${suiteQs}&tab=financial#pnl`,
      kpi: pnlByPeriod,
      renderKpi: (state) => {
        if (state.loading) return "…";
        if (state.error) return "—";
        const v = state.data?.value;
        const fmt = state.data?.format || "currency";
        return formatValue(v, fmt);
      },
      kpiSubtitle: (state) => {
        if (state.loading || state.error) return null;
        const d = state.data?.delta_pct;
        if (d === null || d === undefined) return "Net Income";
        const sign = d > 0 ? "+" : "";
        return `Net Income · ${sign}${Number(d).toFixed(1)}% vs prior`;
      },
    },
    // Feb-2026 · Reports Gap Fill Phase 5a.1 — Business Snapshot.
    // Static-KPI tile (no live cockpit fetch — the destination
    // page reads the values on mount). Section badge: "Others".
    {
      key: "business-snapshot",
      icon: Gauge,
      title: "Business Snapshot",
      description: "Service radius, team size & weekly labor capacity.",
      to: `/reports/business-snapshot`,
      sectionBadge: "Others",
      kpi: { loading: false, data: { headline: "Snapshot" } },
      renderKpi: () => "→",
      kpiSubtitle: () => "Current-state",
    },
    // Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Attrition.
    // Static tile (destination reads on mount + date range).
    // Section badge: "Others".
    {
      key: "attrition-report",
      icon: UserMinus,
      title: "Attrition Report",
      description: "Customers who became inactive in the window, by reason.",
      to: `/reports/attrition`,
      sectionBadge: "Others",
      kpi: { loading: false, data: { headline: "Attrition" } },
      renderKpi: () => "→",
      kpiSubtitle: () => "Date-ranged",
    },
    // Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Time to
    // Get Paid. Section badge: "Receivables".
    {
      key: "time-to-get-paid",
      icon: Clock,
      title: "Time to Get Paid",
      description: "Invoice cycle-time: avg, p50, p90 + trailing 12mo.",
      to: `/reports/time-to-get-paid`,
      sectionBadge: "Receivables",
      kpi: { loading: false, data: { headline: "TTGP" } },
      renderKpi: () => "→",
      kpiSubtitle: () => "Rolling view",
    },
    // Feb-2026 · Reports Gap Fill Phase 5a.2 — cockpit-mirror trio.
    {
      key: "revenue-by-service",
      icon: Wrench,
      title: "Revenue by Service",
      description: "Billed + collected pivoted by invoice service.",
      to: `/reports/revenue-by-service`,
      sectionBadge: "Financial",
      kpi: { loading: false, data: { headline: "RBS" } },
      renderKpi: () => "→",
      kpiSubtitle: () => "Service pivot",
    },
    {
      key: "recurring-vs-project",
      icon: RefreshCw,
      title: "Recurring vs. Project Revenue",
      description: "Split paid revenue using the dashboard predicate.",
      to: `/reports/recurring-vs-project-revenue`,
      sectionBadge: "Financial",
      kpi: { loading: false, data: { headline: "RvP" } },
      renderKpi: () => "→",
      kpiSubtitle: () => "Bucketed",
    },
    {
      key: "client-lifetime-value",
      icon: TrendingUp,
      title: "Client Lifetime Value",
      description: "Per-customer billed / collected + histogram.",
      to: `/reports/client-lifetime-value`,
      sectionBadge: "Others",
      kpi: { loading: false, data: { headline: "CLV" } },
      renderKpi: () => "→",
      kpiSubtitle: () => "All-time by default",
    },
  ];

  const comingSoonTiles = [
    { key: "r2", icon: Activity,       title: "R2 · Operations",          description: "Jobs completed, tech utilization, chemistry.", phase: "R2" },
    { key: "r3", icon: Users2,         title: "R3 · Customers",           description: "LTV, churn, chemistry trends.",                phase: "R3" },
    { key: "r4", icon: Target,         title: "R4 · Sales",               description: "Funnel, win rate, source attribution.",        phase: "R4" },
    { key: "r5", icon: Gauge,          title: "R5 · KPI Overview",        description: "Variance tiles + rollups.",                    phase: "R5" },
    { key: "r6", icon: FileText,       title: "R6 · Custom Report Builder", description: "Author bespoke reports from any metric.",    phase: "R6" },
    { key: "r7", icon: CalendarClock,  title: "R7 · Scheduled Reports",   description: "Email + Slack deliveries on cadence.",         phase: "R7" },
  ];

  return (
    <div
      className="p-4 md:p-8 max-w-7xl mx-auto"
      style={{ fontFamily: "inherit" }}
      data-testid="reports-hub"
    >
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1
            className="text-3xl md:text-4xl font-bold"
            style={{ color: colors.onSurface }}
            data-testid="reports-hub-title"
          >
            Reports
          </h1>
          <p
            className="text-sm mt-1"
            style={{ color: colors.muted }}
            data-testid="reports-hub-subtitle"
          >
            Quick-access tiles for every available report. Coming-soon tiles surface future phases.
          </p>
        </div>
        <DateRangePicker />
      </div>

      <div
        className="grid grid-cols-1 md:grid-cols-3 gap-4"
        data-testid="reports-hub-grid"
      >
        {builtTiles.map((t, i) => (
          <BuiltTile key={t.key} tile={t} isPrimary={i === 0} />
        ))}
        {comingSoonTiles.map((t) => (
          <ComingSoonTile key={t.key} tile={t} />
        ))}
      </div>
    </div>
  );
}

/**
 * A built (live) tile — icon, title, one-sentence description,
 * live headline KPI (formatted via the shared ``formatValue``
 * helper so tile numbers match the KpiCard component byte-for-byte),
 * and an "Open report" button.
 *
 * Phase K70.a · Feb-2026 — the tile painted the canonical K67
 * navy → green gradient (``gradients.navyToGreen.css``) as its
 * background with white text on top.
 *
 * Phase K74 · Feb-2026 — that gradient is replaced with solid
 * navy (``colors.tile.solidNavy`` == #1B1F5C). White text reads
 * at AAA (12.8:1). The "Open report" button keeps its K70.a
 * green-700 (``#15803D``) fill + 1px white outline + white text
 * (WCAG AA body: 4.9:1) so the CTA still pops off the tile.
 * ONLY the tile background changes — the page canvas is
 * untouched (per K74 spec).
 */
function BuiltTile({ tile, isPrimary = false }) {
  const { icon: Icon, title, description, to, kpi, renderKpi, kpiSubtitle,
          sectionBadge } = tile;
  const sub = kpiSubtitle ? kpiSubtitle(kpi) : null;
  const testIdRoot = `reports-tile-${tile.key}`;

  return (
    <div
      className="rounded-2xl p-5 flex flex-col gap-4 transition"
      style={{
        backgroundColor: colors.tile.solidNavy,
        border: `1px solid ${colors.border}`,
        color: "#FFFFFF",
      }}
      data-testid={isPrimary ? "k74-reports-tile-bg" : testIdRoot}
      data-tile-key={tile.key}
      data-tile-testid={testIdRoot}
      data-k74-reports-tile-bg={isPrimary ? "true" : undefined}
      data-k74-solid-navy-tile="true"
    >
      <div className="flex items-start gap-3">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            backgroundColor: "rgba(255,255,255,0.18)",
            color: "#FFFFFF",
          }}
        >
          <Icon size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div
              className="font-semibold text-sm"
              style={{ color: "#FFFFFF" }}
            >
              {title}
            </div>
            {sectionBadge ? (
              <span
                className="text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded"
                style={{
                  background: "rgba(255,255,255,0.18)",
                  color: "#FFFFFF",
                }}
                data-testid={`${testIdRoot}-section-badge`}
              >
                {sectionBadge}
              </span>
            ) : null}
          </div>
          <div
            className="text-xs mt-0.5"
            style={{ color: "rgba(255,255,255,0.82)" }}
          >
            {description}
          </div>
        </div>
      </div>

      <div>
        <div
          className="text-2xl md:text-3xl font-bold"
          style={{ color: "#FFFFFF" }}
          data-testid={`${testIdRoot}-kpi`}
        >
          {renderKpi(kpi)}
        </div>
        {sub ? (
          <div
            className="text-xs mt-1"
            style={{ color: "rgba(255,255,255,0.75)" }}
            data-testid={`${testIdRoot}-kpi-sub`}
          >
            {sub}
          </div>
        ) : null}
      </div>

      <div className="mt-auto">
        <Link
          to={to}
          className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg transition"
          style={{
            backgroundColor: "#15803D",
            border: "1px solid #FFFFFF",
            color: "#FFFFFF",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = "#166534";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = "#15803D";
          }}
          data-testid={`${testIdRoot}-open`}
          data-k70a-cta="true"
        >
          Open report
          <ChevronRight size={14} />
        </Link>
      </div>
    </div>
  );
}

/**
 * A placeholder tile for R1–R7. Muted styling, "Coming soon"
 * ribbon, deliberately not clickable — the outer element is a
 * plain ``div`` (no ``Link``) so keyboard tabbing skips it.
 */
function ComingSoonTile({ tile }) {
  const { icon: Icon, title, description, phase } = tile;
  return (
    <div
      className="rounded-2xl p-5 relative flex flex-col gap-4"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px dashed ${colors.border}`,
        opacity: 0.85,
      }}
      data-testid={`reports-tile-coming-${phase.toLowerCase()}`}
      aria-disabled="true"
    >
      <span
        className="absolute top-3 right-3 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full"
        style={{
          backgroundColor: colors.brandTertiary,
          color: colors.onBrandTertiary,
        }}
        data-testid={`reports-tile-coming-${phase.toLowerCase()}-ribbon`}
      >
        Coming soon
      </span>

      <div className="flex items-start gap-3">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            backgroundColor: colors.surfaceTertiary || colors.surface,
            color: colors.onSurfaceSecondary,
          }}
        >
          <Icon size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <div
            className="font-semibold text-sm"
            style={{ color: colors.onSurface }}
          >
            {title}
          </div>
          <div
            className="text-xs mt-0.5"
            style={{ color: colors.onSurfaceSecondary }}
          >
            {description}
          </div>
        </div>
      </div>

      <div
        className="mt-auto text-[11px] inline-flex items-center gap-1"
        style={{ color: colors.onSurfaceSecondary }}
      >
        <Lock size={11} />
        Ships in {phase}
      </div>
    </div>
  );
}
