/**
 * P2 #6 · Feb-2026 · ServiceCategoryTileRow
 *
 * Admin Dashboard tile row: 4 KpiCards keyed on the customer-level
 * ``service_category`` enum.  Fetches
 * ``GET /api/dashboard/service-category-breakdown`` on mount and
 * renders Pool / Landscaping / Both as full tiles (customers +
 * active_jobs + MTD revenue) plus a "Not set" tile with only the
 * customer count (ops signal — if this count is high, the backfill
 * script needs to run).  Each tile deep-links the customers list
 * via the P2 #6 ``?service_category=`` filter chip.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Waves, TreePine, Grid2x2, HelpCircle } from "lucide-react";
import { api } from "@/api";
import { money } from "@/theme";


function _StatLine({ label, value, "data-testid": testId }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs"
            data-testid={testId}>
      <span className="font-semibold uppercase tracking-wide opacity-70">
        {label}
      </span>
      <span className="font-mono">{value}</span>
    </div>
  );
}


function Tile({
  icon: Icon, title, bucket, extraStats, bgTone, borderTone, iconBg,
  onClick, testId,
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left rounded-2xl p-5 transition hover:brightness-95 active:scale-[0.99]"
      style={{
        backgroundColor: bgTone,
        border: `1px solid ${borderTone}`,
        borderLeft: `4px solid ${borderTone}`,
      }}
      data-testid={testId}
    >
      <div className="flex items-start gap-3 mb-3">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center"
          style={{ backgroundColor: iconBg, color: "#FFFFFF" }}
        >
          <Icon size={20} />
        </div>
        <div className="flex-1">
          <div className="text-xs font-bold uppercase tracking-wide opacity-75">
            {title}
          </div>
          <div className="text-2xl font-bold mt-0.5"
                data-testid={`${testId}-customers`}>
            {Number(bucket.customers || 0).toLocaleString()}
          </div>
          <div className="text-[11px] opacity-60">customers</div>
        </div>
      </div>
      {extraStats ? (
        <div className="space-y-1 mt-2">{extraStats}</div>
      ) : null}
    </button>
  );
}


export default function ServiceCategoryTileRow() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    api.get("/dashboard/service-category-breakdown")
      .then((d) => { if (mounted) setData(d); })
      .catch(() => { if (mounted) setError(true); });
    return () => { mounted = false; };
  }, []);

  if (error) return null;

  return (
    <div
      className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6"
      data-testid="dashboard-service-category-row"
    >
      {data ? (
        <>
          <Tile
            icon={Waves}
            title="Pool"
            bucket={data.pool || { customers: 0 }}
            bgTone="#ECFEFF"
            borderTone="#06B6D4"
            iconBg="#0891B2"
            onClick={() => navigate("/customers?service_category=pool")}
            testId="kpi-service-category-pool"
            extraStats={<>
              <_StatLine label="Active jobs"
                           value={Number(data.pool?.active_jobs || 0).toLocaleString()}
                           data-testid="kpi-service-category-pool-active-jobs" />
              <_StatLine label="MTD revenue"
                           value={money(data.pool?.mtd_revenue || 0)}
                           data-testid="kpi-service-category-pool-mtd" />
            </>}
          />
          <Tile
            icon={TreePine}
            title="Landscaping"
            bucket={data.landscaping || { customers: 0 }}
            bgTone="#ECFDF5"
            borderTone="#10B981"
            iconBg="#047857"
            onClick={() => navigate("/customers?service_category=landscaping")}
            testId="kpi-service-category-landscaping"
            extraStats={<>
              <_StatLine label="Active jobs"
                           value={Number(data.landscaping?.active_jobs || 0).toLocaleString()}
                           data-testid="kpi-service-category-landscaping-active-jobs" />
              <_StatLine label="MTD revenue"
                           value={money(data.landscaping?.mtd_revenue || 0)}
                           data-testid="kpi-service-category-landscaping-mtd" />
            </>}
          />
          <Tile
            icon={Grid2x2}
            title="Both"
            bucket={data.both || { customers: 0 }}
            bgTone="#FEF3C7"
            borderTone="#D97706"
            iconBg="#B45309"
            onClick={() => navigate("/customers?service_category=both")}
            testId="kpi-service-category-both"
            extraStats={<>
              <_StatLine label="Active jobs"
                           value={Number(data.both?.active_jobs || 0).toLocaleString()}
                           data-testid="kpi-service-category-both-active-jobs" />
              <_StatLine label="MTD revenue"
                           value={money(data.both?.mtd_revenue || 0)}
                           data-testid="kpi-service-category-both-mtd" />
            </>}
          />
          <Tile
            icon={HelpCircle}
            title="Not set"
            bucket={data.unset || { customers: 0 }}
            bgTone="#F3F4F6"
            borderTone="#64748B"
            iconBg="#475569"
            onClick={() => navigate("/customers?service_category=unset")}
            testId="kpi-service-category-unset"
          />
        </>
      ) : (
        [0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="rounded-2xl p-5 animate-pulse"
            style={{
              backgroundColor: "#F3F4F6",
              border: "1px solid #E5E7EB",
              height: 150,
            }}
            data-testid={`service-category-skeleton-${i}`}
          />
        ))
      )}
    </div>
  );
}
