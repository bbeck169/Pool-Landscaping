/**
 * Phase T5 — Business Analysis Tools (admin only).
 *
 * Two tabs wired to `backend/routers/pool_calculators.py`:
 *   1. Route Valuation      — POST /calculators/route-valuation
 *   2. Pay Model Comparator — POST /calculators/pay-model-compare
 *
 * RBAC: <AdminOnly> route wrapper + backend `_require_admin`.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, BarChart3, Users, TrendingUp, Copy, Download,
} from "lucide-react";
import { api, api_base } from "@/api";
import { colors } from "@/theme";

const TABS = [
  { key: "route",  label: "Route Valuation",  icon: BarChart3 },
  { key: "pay",    label: "Pay Model Compare", icon: Users },
];

function copy(text) { if (navigator.clipboard) navigator.clipboard.writeText(text); }

function Field({ label, value, onChange, unit, testid, placeholder = "" }) {
  return (
    <label className="block">
      <span className="text-xs font-bold uppercase tracking-wider"
            style={{ color: colors.muted }}>{label}</span>
      <div className="flex items-center gap-2 mt-1 rounded-lg px-3 py-2"
           style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}` }}>
        <input value={value ?? ""} onChange={(e) => onChange(e.target.value)}
               type="number" step="any" placeholder={placeholder}
               className="w-full bg-transparent focus:outline-none text-base"
               style={{ color: colors.onSurface }}
               data-testid={testid} />
        {unit ? <span className="text-xs font-semibold" style={{ color: colors.muted }}>{unit}</span> : null}
      </div>
    </label>
  );
}

function Select({ label, value, onChange, options, testid }) {
  return (
    <label className="block">
      <span className="text-xs font-bold uppercase tracking-wider"
            style={{ color: colors.muted }}>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
              className="mt-1 w-full rounded-lg px-3 py-2 text-base"
              style={{ backgroundColor: colors.background,
                       border: `1px solid ${colors.border}`, color: colors.onSurface }}
              data-testid={testid}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

function Stat({ label, value, bold, accent }) {
  return (
    <div>
      <div className="text-xs font-bold uppercase tracking-wider"
           style={{ color: accent ? colors.brand : colors.muted }}>{label}</div>
      <div className={bold ? "text-2xl font-bold mt-1" : "text-lg font-semibold mt-1"}
           style={{ color: accent ? colors.brand : colors.onSurface }}>{value}</div>
    </div>
  );
}

// ── T5.1 Route Valuation ─────────────────────────────────────────────
function RoutePanel() {
  const [customers, setCustomers] = useState("");
  const [avgRev, setAvgRev] = useState("");
  const [totalRev, setTotalRev] = useState("");
  const [churn, setChurn] = useState("8");
  const [density, setDensity] = useState("dense");
  const [contractLen, setContractLen] = useState("24");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const body = {
        active_customers: customers === "" ? null : parseFloat(customers),
        avg_monthly_revenue_per_customer: avgRev === "" ? null : parseFloat(avgRev),
        total_monthly_revenue: totalRev === "" ? null : parseFloat(totalRev),
        churn_rate_pct: parseFloat(churn),
        route_density: density,
        contract_length_avg_months: parseFloat(contractLen),
      };
      const r = await api.post("/calculators/route-valuation", body);
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  // Benchmark bar — position between industry low ($1500) and high ($3500).
  const benchBar = (val, lo, hi) => {
    const clamped = Math.max(lo * 0.5, Math.min(hi * 1.3, val));
    const span = hi * 1.3 - lo * 0.5;
    const pos = ((clamped - lo * 0.5) / span) * 100;
    return { pos, lo, hi };
  };

  return (
    <div className="rounded-2xl p-6"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="route-panel">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Field label="Active customers (blank = auto)" value={customers} onChange={setCustomers} testid="route-customers" placeholder="auto" />
        <Field label="Avg monthly rev/customer (blank = auto)" unit="$" value={avgRev} onChange={setAvgRev} testid="route-avgrev" placeholder="auto" />
        <Field label="Total monthly revenue (blank = computed)" unit="$" value={totalRev} onChange={setTotalRev} testid="route-totalrev" placeholder="computed" />
        <Field label="Churn rate" unit="%" value={churn} onChange={setChurn} testid="route-churn" />
        <Select label="Route density" value={density} onChange={setDensity}
                options={[{value:"dense",label:"Dense"},{value:"medium",label:"Medium"},{value:"spread",label:"Spread"}]}
                testid="route-density" />
        <Field label="Contract length" unit="months" value={contractLen} onChange={setContractLen} testid="route-contract" />
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="route-compute">Value this route</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <div className="mt-4 space-y-3" data-testid="route-result">
          <div className="rounded-xl p-4" style={{ backgroundColor: `${colors.brand}10` }}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat label="Active customers" value={result.active_customers.toLocaleString()} />
              <Stat label="Monthly revenue" value={`$${result.total_monthly_revenue.toLocaleString()}`} />
              <Stat label="Annual gross profit" value={`$${result.annual_gross_profit.toLocaleString()}`} />
              <Stat label="Route multiple" value={`${result.route_multiple}x`} bold accent />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-4">
              <Stat label="Route valuation" value={`$${result.route_valuation.toLocaleString()}`} bold accent />
              <Stat label="Valuation per customer" value={`$${result.valuation_per_customer.toLocaleString()}`} bold />
            </div>
          </div>
          {/* Industry benchmark bar */}
          <div className="rounded-xl p-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="text-xs font-bold uppercase tracking-wider mb-2"
                 style={{ color: colors.muted }}>Industry benchmark — per-customer valuation</div>
            {(() => {
              const bench = benchBar(result.valuation_per_customer,
                                       result.benchmarks.industry_per_customer_low,
                                       result.benchmarks.industry_per_customer_high);
              const posColor = result.benchmarks.position === "below_industry" ? "#991B1B"
                : result.benchmarks.position === "above_industry" ? "#166534"
                : colors.brand;
              return (
                <>
                  <div className="relative h-6 rounded-full"
                       style={{ backgroundColor: `${colors.muted}22` }}>
                    <div className="absolute h-full rounded-full"
                         style={{ left: `${(bench.lo * 0.5 / (bench.hi * 1.3)) * 100}%`,
                                  width: `${((bench.hi - bench.lo) / (bench.hi * 1.3)) * 100}%`,
                                  backgroundColor: `${colors.brand}55` }} />
                    <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-6 rounded"
                         style={{ left: `${bench.pos}%`, backgroundColor: posColor }} />
                  </div>
                  <div className="flex justify-between text-xs mt-1"
                       style={{ color: colors.muted }}>
                    <span>${bench.lo}</span>
                    <span style={{ color: posColor, fontWeight: 700 }}>
                      ${result.valuation_per_customer.toLocaleString()}
                      ({result.benchmarks.position.replace(/_/g, " ")})
                    </span>
                    <span>${bench.hi}</span>
                  </div>
                </>
              );
            })()}
          </div>
          {/* Breakdown */}
          <div className="rounded-xl p-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="text-xs font-bold uppercase tracking-wider mb-2"
                 style={{ color: colors.muted }}>Multiple breakdown</div>
            <ul className="text-xs space-y-1" style={{ color: colors.onSurface }}>
              <li>Density <b>{result.breakdown.density}</b> → factor {result.breakdown.density_factor}</li>
              <li>Churn <b>{result.breakdown.churn_rate_pct}%</b> → factor {result.breakdown.churn_factor}</li>
              <li>Contract length <b>{result.breakdown.contract_length_avg_months} mo</b> → factor {result.breakdown.contract_factor}</li>
              <li>Combined factor <b>{result.breakdown.combined_factor}</b> → multiple lerped between {result.breakdown.multiple_min}x and {result.breakdown.multiple_max}x</li>
            </ul>
          </div>
          <div className="flex items-center gap-2">
          <button onClick={() => copy(
            `Route valuation: $${result.route_valuation.toLocaleString()} · Multiple ${result.route_multiple}x · Per-customer $${result.valuation_per_customer}`
          )} className="text-xs font-semibold rounded-lg px-2 py-1 flex items-center gap-1"
             style={{ backgroundColor: `${colors.brand}22`, color: colors.brand }}
             data-testid="route-copy">
            <Copy size={12} /> Copy summary
          </button>
          <button onClick={async () => {
            try {
              const token = localStorage.getItem("token");
              const r = await fetch(`${api_base()}/documents/route-valuation-pdf`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify({ ...result, generated_by: (JSON.parse(localStorage.getItem("user") || "{}").email || "") }),
              });
              if (!r.ok) throw new Error(`HTTP ${r.status}`);
              const blob = await r.blob();
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = "route-valuation.pdf";
              a.click();
            } catch (e) { setErr(e.message); }
          }} className="ml-2 text-xs font-semibold rounded-lg px-2 py-1 flex items-center gap-1"
             style={{ backgroundColor: colors.brand, color: "#fff" }}
             data-testid="route-download-pdf">
            <Download size={12} /> Download PDF
          </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── T5.2 Pay Model Compare ───────────────────────────────────────────
function PayPanel() {
  const [n, setN] = useState("40");
  const [visitMins, setVisitMins] = useState("45");
  const [revPerCust, setRevPerCust] = useState("135");
  const [visitsPerMonth, setVisitsPerMonth] = useState("4.33");
  const [hourly, setHourly] = useState("22");
  const [perPool, setPerPool] = useState("18");
  const [routePct, setRoutePct] = useState("65");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/pay-model-compare", {
        tech_route_customers: parseFloat(n),
        avg_visit_time_minutes: parseFloat(visitMins),
        avg_revenue_per_customer_month: parseFloat(revPerCust),
        visits_per_customer_per_month: parseFloat(visitsPerMonth),
        hourly_rate: parseFloat(hourly),
        per_pool_rate: parseFloat(perPool),
        route_buy_pct: parseFloat(routePct),
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  const modelLabel = (k) => k === "hourly" ? "Hourly" : k === "per_pool" ? "Per pool" : "Route buy";

  return (
    <div className="rounded-2xl p-6"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="pay-panel">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Route customers" value={n} onChange={setN} testid="pay-n" />
        <Field label="Avg visit time" unit="min" value={visitMins} onChange={setVisitMins} testid="pay-mins" />
        <Field label="Avg rev/customer/mo" unit="$" value={revPerCust} onChange={setRevPerCust} testid="pay-rev" />
        <Field label="Visits/cust/mo" value={visitsPerMonth} onChange={setVisitsPerMonth} testid="pay-vpm" />
        <Field label="Hourly rate" unit="$" value={hourly} onChange={setHourly} testid="pay-hourly" />
        <Field label="Per-pool rate" unit="$" value={perPool} onChange={setPerPool} testid="pay-perpool" />
        <Field label="Route buy %" unit="%" value={routePct} onChange={setRoutePct} testid="pay-routepct" />
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="pay-compute">Compare pay models</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <div className="mt-4 space-y-3" data-testid="pay-result">
          <div className="rounded-xl p-3 text-sm"
               style={{ backgroundColor: `${colors.brand}10`, color: colors.brand }}
               data-testid="pay-recommendation">
            {result.recommendation}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="pay-table">
              <thead>
                <tr style={{ color: colors.muted }}>
                  <th className="text-left py-2">Model</th>
                  <th className="text-right">Weekly tech pay</th>
                  <th className="text-right">Monthly tech pay</th>
                  <th className="text-right">Annualized tech pay</th>
                  <th className="text-right">Company margin</th>
                  <th className="text-right">Company profit/mo</th>
                </tr>
              </thead>
              <tbody>
                {["hourly","per_pool","route_buy"].map((k) => {
                  const m = result.models[k];
                  const isBestMargin = result.best_company_margin === k;
                  const isBestTech = result.best_tech_pay === k;
                  return (
                    <tr key={k} data-testid={`pay-row-${k}`}>
                      <td className="py-2 font-semibold">{modelLabel(k)}</td>
                      <td className="text-right" style={{color: isBestTech ? "#166534" : colors.onSurface, fontWeight: isBestTech ? 700 : 400}}>
                        ${m.weekly_tech_pay.toLocaleString()}
                      </td>
                      <td className="text-right" style={{color: isBestTech ? "#166534" : colors.onSurface, fontWeight: isBestTech ? 700 : 400}}>
                        ${m.monthly_tech_pay.toLocaleString()}
                      </td>
                      <td className="text-right">${m.annualized_tech_pay.toLocaleString()}</td>
                      <td className="text-right" style={{color: isBestMargin ? "#166534" : colors.onSurface, fontWeight: isBestMargin ? 700 : 400}}>
                        {m.company_gross_margin_pct}%
                      </td>
                      <td className="text-right" style={{color: isBestMargin ? "#166534" : colors.onSurface, fontWeight: isBestMargin ? 700 : 400}}>
                        ${m.company_monthly_profit.toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Inputs: {result.inputs_echo.monthly_hours} monthly hours · ${result.inputs_echo.monthly_revenue.toLocaleString()} monthly revenue · {result.inputs_echo.other_costs_pct}% other costs.
          </div>
          <div className="text-xs italic" style={{ color: colors.muted }} data-testid="pay-breakeven">
            {result.breakeven_hint}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function BusinessAnalysisTools() {
  const nav = useNavigate();
  const [tab, setTab] = useState("route");
  const Panel = { route: RoutePanel, pay: PayPanel }[tab];

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="analysis-tools-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="analysis-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <TrendingUp size={22} style={{ color: colors.brand }} />
            Business Analysis Tools
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Admin-only. Route valuation for buy/sell decisions · Tech pay model side-by-side comparator.
          </p>
        </div>
      </div>

      <div className="flex gap-2 mb-4 overflow-x-auto pb-1">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold whitespace-nowrap"
                    style={{
                      backgroundColor: active ? colors.brand : colors.surface,
                      color: active ? "#fff" : colors.onSurface,
                      border: `1px solid ${active ? colors.brand : colors.border}`,
                    }}
                    data-testid={`analysis-tab-${t.key}`}>
              <Icon size={14} /> {t.label}
            </button>
          );
        })}
      </div>

      <Panel />
    </div>
  );
}
