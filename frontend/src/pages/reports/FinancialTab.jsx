import React from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { PeriodPicker } from "@/components/reports/PeriodPicker";
import { LensToggle } from "@/components/reports/LensToggle";
import { RevenueByCustomerPanel } from "@/components/reports/RevenueByCustomerPanel";
import { RevenueByCityPanel } from "@/components/reports/RevenueByCityPanel";

/**
 * Phase R0.1 · Feb-2026 — Financial tab.
 *
 * Owns the shared filter toolbar (period + lens + service_type +
 * tech_id) that drives both revenue panels below. Filter state
 * lives in the URL querystring so a customer drill-down + back
 * navigation preserves the report state.
 *
 * URL contract:
 *   ?period=mtd|qtd|ytd|last_30d|custom
 *   &start=YYYY-MM-DD&end=YYYY-MM-DD   (custom only)
 *   &lens=invoiced|collected
 *   &service_type=<value>
 *   &tech_id=<value>
 *   &show_all_customers=1
 *   &show_all_cities=1
 */
export default function FinancialTab() {
  const [params, setParams] = useSearchParams();

  const period = params.get("period") || "mtd";
  const start = params.get("start") || "";
  const end = params.get("end") || "";
  const lens = params.get("lens") || "invoiced";
  const serviceType = params.get("service_type") || "";
  const techId = params.get("tech_id") || "";

  const [techOptions, setTechOptions] = React.useState([]);
  const [serviceTypes, setServiceTypes] = React.useState([]);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [techs, custs] = await Promise.all([
          api.get("/users?role=technician").catch(() => []),
          api.get("/customers?limit=1000&fields=service_type").catch(() => []),
        ]);
        if (cancelled) return;
        setTechOptions(Array.isArray(techs) ? techs : (techs?.items || []));
        const set = new Set();
        const items = Array.isArray(custs) ? custs : (custs?.items || []);
        items.forEach((c) => c.service_type && set.add(c.service_type));
        setServiceTypes(Array.from(set).sort());
      } catch {
        /* non-fatal — dropdowns just render empty */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value === "" || value === null || value === undefined) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const onPeriodChange = (nextP) => {
    const next = new URLSearchParams(params);
    next.set("period", nextP.period);
    if (nextP.period === "custom") {
      if (nextP.start) next.set("start", nextP.start); else next.delete("start");
      if (nextP.end) next.set("end", nextP.end); else next.delete("end");
    } else {
      next.delete("start"); next.delete("end");
    }
    setParams(next, { replace: true });
  };

  const filters = { period, start, end, lens, service_type: serviceType, tech_id: techId };

  return (
    <div className="space-y-6" data-testid="financial-tab">
      <div
        className="rounded-xl border p-4 flex flex-wrap items-end gap-4"
        style={{ backgroundColor: colors.surface, borderColor: colors.border }}
        data-testid="financial-tab-toolbar"
      >
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide mb-1"
                 style={{ color: colors.onSurfaceSecondary }}>
            Period
          </div>
          <PeriodPicker value={{ period, start, end }} onChange={onPeriodChange} />
        </div>

        <div>
          <div className="text-xs font-semibold uppercase tracking-wide mb-1"
                 style={{ color: colors.onSurfaceSecondary }}>
            Lens
          </div>
          <LensToggle value={lens} onChange={(v) => setParam("lens", v)} />
        </div>

        <div>
          <div className="text-xs font-semibold uppercase tracking-wide mb-1"
                 style={{ color: colors.onSurfaceSecondary }}>
            Service type
          </div>
          <select
            value={serviceType}
            onChange={(e) => setParam("service_type", e.target.value)}
            className="text-sm px-2 py-1.5 rounded border"
            style={{ borderColor: colors.border, color: colors.onSurface, backgroundColor: colors.surface }}
            data-testid="financial-tab-service-type"
          >
            <option value="">All</option>
            {serviceTypes.map((s) => (<option key={s} value={s}>{s}</option>))}
          </select>
        </div>

        <div>
          <div className="text-xs font-semibold uppercase tracking-wide mb-1"
                 style={{ color: colors.onSurfaceSecondary }}>
            Technician
          </div>
          <select
            value={techId}
            onChange={(e) => setParam("tech_id", e.target.value)}
            className="text-sm px-2 py-1.5 rounded border"
            style={{ borderColor: colors.border, color: colors.onSurface, backgroundColor: colors.surface }}
            data-testid="financial-tab-tech"
          >
            <option value="">All</option>
            {techOptions.map((t) => (
              <option key={t.id} value={t.id}>{t.name || t.email || t.id}</option>
            ))}
          </select>
        </div>

        {(serviceType || techId) ? (
          <Button
            variant="ghost"
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("service_type");
              next.delete("tech_id");
              setParams(next, { replace: true });
            }}
            data-testid="financial-tab-clear-filters"
          >
            Clear filters
          </Button>
        ) : null}
      </div>

      <div id="revenue-by-customer">
        <RevenueByCustomerPanel filters={filters} params={params} setParams={setParams} />
      </div>
      <div id="revenue-by-city">
        <RevenueByCityPanel filters={filters} params={params} setParams={setParams} />
      </div>
    </div>
  );
}
