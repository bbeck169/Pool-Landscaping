import React from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/auth";
import { api } from "@/api";
import { colors } from "@/theme";
import { KpiCard } from "@/components/reports/KpiCard";
import { PeriodPicker } from "@/components/reports/PeriodPicker";
import FinancialTab from "@/pages/reports/FinancialTab";

/**
 * Phase R0 · Feb-2026 — Reporting suite shell.
 *
 * Owns the tabbed nav layout that R1–R7 phases will hang new
 * content off. R0 ships only the "Overview" tab with a single
 * live KPI (``revenue_total``) as the end-to-end proof. Every
 * other tab renders a "Coming in R{n}" empty state so the shell
 * shape is visible from day one.
 */
const TABS = [
  { key: "overview",   label: "Overview",   phase: "R5" },
  { key: "financial",  label: "Financial",  phase: "R1" },
  { key: "operations", label: "Operations", phase: "R2" },
  { key: "customers",  label: "Customers",  phase: "R3" },
  { key: "sales",      label: "Sales",      phase: "R4" },
  { key: "custom",     label: "Custom",     phase: "R6" },
  { key: "scheduled",  label: "Scheduled",  phase: "R7" },
];

const READER_ROLES = ["super_admin", "admin", "owner", "manager"];

export default function ReportsSuite() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = React.useState("overview");

  React.useEffect(() => {
    if (authLoading) return;
    const role = user?.role || "";
    if (!READER_ROLES.includes(role)) {
      toast.error("Reporting is restricted to admin roles");
      navigate("/", { replace: true });
    }
  }, [authLoading, user, navigate]);

  if (authLoading) return null;

  return (
    <div
      className="p-6"
      style={{ backgroundColor: colors.surfaceSecondary, minHeight: "100vh" }}
      data-testid="reports-suite"
    >
      <header className="mb-6">
        <h1
          className="text-3xl font-bold"
          style={{ color: colors.onSurface }}
          data-testid="reports-suite-title"
        >
          Reports
        </h1>
        <p
          className="text-sm mt-1"
          style={{ color: colors.onSurfaceSecondary }}
        >
          Phase R0 foundation — R1–R7 dashboards will land in this shell.
        </p>
      </header>

      <nav
        className="flex flex-wrap gap-2 mb-6 border-b"
        style={{ borderColor: colors.border }}
        data-testid="reports-suite-tabs"
      >
        {TABS.map((t) => {
          const isActive = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className="text-sm font-semibold px-4 py-2 -mb-px transition"
              style={{
                color: isActive ? colors.brand : colors.onSurfaceSecondary,
                borderBottom: `2px solid ${isActive ? colors.brand : "transparent"}`,
              }}
              data-testid={`reports-tab-${t.key}`}
              aria-pressed={isActive}
            >
              {t.label}
            </button>
          );
        })}
      </nav>

      {tab === "overview" ? (
        <OverviewTab />
      ) : tab === "financial" ? (
        <FinancialTab />
      ) : (
        <ComingSoonTab phase={TABS.find((t) => t.key === tab)?.phase} />
      )}
    </div>
  );
}

function OverviewTab() {
  const [period, setPeriod] = React.useState({ period: "mtd" });
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  const fetchKpi = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ period: period.period });
      if (period.period === "custom") {
        if (!period.start || !period.end) {
          setLoading(false);
          return;
        }
        params.set("start", period.start);
        params.set("end", period.end);
      }
      const r = await api.get(`/reports/kpi/revenue_total?${params.toString()}`);
      setData(r);
    } catch (e) {
      setError(e?.message || "Failed to load KPI");
    } finally {
      setLoading(false);
    }
  }, [period.period, period.start, period.end]);

  React.useEffect(() => { fetchKpi(); }, [fetchKpi]);

  return (
    <div className="space-y-6" data-testid="reports-overview">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <div
            className="text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.onSurfaceSecondary }}
          >
            Period
          </div>
          <div className="mt-2">
            <PeriodPicker value={period} onChange={setPeriod} />
          </div>
        </div>
        {data?.cached ? (
          <span
            className="text-xs px-2 py-1 rounded-full"
            style={{
              backgroundColor: colors.brandTertiary,
              color: colors.onBrandTertiary,
            }}
            data-testid="reports-overview-cached-chip"
          >
            Cached · &lt;60s
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <KpiCard
          testid="kpi-revenue-total"
          label={data?.label || "Total Revenue"}
          value={data?.value}
          priorValue={data?.prior_value}
          deltaPct={data?.delta_pct}
          sparkline={data?.sparkline}
          format={data?.format || "currency"}
          direction={data?.direction || "up_is_good"}
          loading={loading}
          error={error}
        />
        <ComingSoonKpiSlot phase="R1" title="Gross margin" />
        <ComingSoonKpiSlot phase="R1" title="A/R aging" />
      </div>
    </div>
  );
}

function ComingSoonKpiSlot({ phase, title }) {
  return (
    <div
      className="rounded-xl border p-5 flex items-center justify-center text-center"
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        borderStyle: "dashed",
        minHeight: 160,
      }}
      data-testid={`reports-overview-placeholder-${phase.toLowerCase()}`}
    >
      <div>
        <div
          className="text-sm font-semibold"
          style={{ color: colors.onSurface }}
        >
          {title}
        </div>
        <div
          className="text-xs mt-1"
          style={{ color: colors.onSurfaceSecondary }}
        >
          Coming in {phase}
        </div>
      </div>
    </div>
  );
}

function ComingSoonTab({ phase }) {
  return (
    <div
      className="rounded-xl border p-16 flex flex-col items-center justify-center text-center"
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        borderStyle: "dashed",
      }}
      data-testid="reports-coming-soon"
    >
      <div
        className="text-lg font-semibold"
        style={{ color: colors.onSurface }}
      >
        Coming in {phase || "a future phase"}
      </div>
      <div
        className="text-sm mt-2 max-w-md"
        style={{ color: colors.onSurfaceSecondary }}
      >
        R0 shipped the foundation — aggregation engine, cache
        layer, metric registry, and the KPI pipeline you see on
        the Overview tab. This tab will fill in as R1–R7 land.
      </div>
    </div>
  );
}
