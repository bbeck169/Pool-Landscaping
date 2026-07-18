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
  ArrowLeft, BarChart3, Users, TrendingUp, Copy, Download, Sparkles,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api, api_base } from "@/api";
import { colors } from "@/theme";

const TABS = [
  { key: "route",    label: "Route Valuation",  icon: BarChart3 },
  { key: "pay",      label: "Pay Model Compare", icon: Users },
  { key: "playbook", label: "Growth Playbook",   icon: Sparkles },
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

// ── Ship 2 · Growth Playbook ─────────────────────────────────────────
function PlaybookPanel() {
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  const compute = async () => {
    setErr(null); setLoading(true);
    try {
      const r = await api.post("/analysis/growth-playbook", {});
      setResult(r);
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  useEffect(() => { compute(); }, []);

  if (loading) {
    return <div className="rounded-2xl p-6" data-testid="playbook-panel"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
      Computing playbook…
    </div>;
  }
  if (err) {
    return <div className="rounded-2xl p-6" data-testid="playbook-panel"
                style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}>
      Error: {err}
    </div>;
  }
  if (!result) return null;

  const t = result.today;
  const m = result.market_median_scenario;
  const be = result.churn_breakeven;
  const skip = be.flavor === "skip_playbook";
  const flavorColor = {
    healthy:        "#166534",
    very_generous:  "#166534",
    thin:           "#92400E",
    skip_playbook:  "#991B1B",
  }[be.flavor] || colors.brand;

  return (
    <div className="rounded-2xl p-6 space-y-4" data-testid="playbook-panel"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
      {result.state_fallback_used ? (
        <div className="rounded-lg p-3 flex items-center gap-2"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
             data-testid="playbook-state-fallback">
          <span className="text-sm font-semibold">Set your state:</span>
          <span className="text-xs">We fell back to Arizona ({result.state_code}) because your tenant profile has no state code. Update it via</span>
          <Link to="/settings/tenant" className="text-xs font-semibold underline" style={{ color: colors.brand }}>
            Tenant Settings
          </Link>
        </div>
      ) : null}

      {/* 3 stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-2xl p-4" data-testid="playbook-card-today"
             style={{ backgroundColor: `${colors.brand}10`, border: `1px solid ${colors.brand}22` }}>
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            Today's route value
          </div>
          <div className="text-3xl font-bold mt-2" style={{ color: colors.onSurface }}>
            ${t.route_valuation.toLocaleString()}
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            {result.active_customers} active customers · ${t.total_monthly_revenue.toLocaleString()}/mo · {t.route_multiple}x multiple
          </div>
        </div>
        <div className="rounded-2xl p-4" data-testid="playbook-card-market"
             style={{ backgroundColor: skip ? "#FEE2E210" : `${flavorColor}12`,
                      border: `1px solid ${skip ? "#FCA5A555" : `${flavorColor}44`}` }}>
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            Market-median scenario ({result.state_code})
          </div>
          <div className="text-3xl font-bold mt-2" style={{ color: skip ? "#991B1B" : colors.onSurface }}>
            ${m.route_valuation.toLocaleString()}
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            ${m.market_median_per_visit}/visit market median · {m.market_position.replace(/_/g, " ")}
          </div>
          <div className="text-sm font-bold mt-2" style={{ color: m.delta_valuation >= 0 ? "#166534" : "#991B1B" }}>
            {m.delta_valuation >= 0 ? "+" : ""}${m.delta_valuation.toLocaleString()} valuation
          </div>
        </div>
        <div className="rounded-2xl p-4" data-testid="playbook-card-breakeven"
             style={{ backgroundColor: skip ? "#F4F4F5" : `${flavorColor}12`,
                      border: `1px solid ${skip ? colors.border : `${flavorColor}44`}` }}>
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            Churn breakeven tolerance
          </div>
          {skip ? (
            <div className="mt-2">
              <div className="text-xl font-bold" style={{ color: "#991B1B" }}>Skip playbook</div>
              <div className="text-xs mt-1" style={{ color: colors.muted }}>
                Repricing would REDUCE your valuation — you're already at or above the market median.
              </div>
            </div>
          ) : (
            <>
              <div className="text-3xl font-bold mt-2" style={{ color: flavorColor }}>
                {be.additional_churn_tolerated_pct > 0 ? "+" : ""}{be.additional_churn_tolerated_pct}%
              </div>
              <div className="text-xs mt-1" style={{ color: colors.muted }}>
                Additional annual churn tolerated
              </div>
              <div className="text-xs mt-2 font-semibold" style={{ color: flavorColor }}>
                {be.flavor.replace(/_/g, " ")}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Narrative paragraph */}
      <div className="rounded-2xl p-4 leading-relaxed" data-testid="playbook-narrative"
           style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}>
        {skip ? (
          <>
            Your {result.active_customers} active customers currently generate a route worth
            {" "}<b>${t.route_valuation.toLocaleString()}</b>.
            You're already <b>{m.market_position.replace(/_/g, " ")}</b> the {result.state_name} median
            of ${m.market_median_per_visit}/visit — repricing to the state median would
            <b> reduce </b> revenue by ${Math.abs(m.delta_monthly_revenue).toLocaleString()}/mo
            and valuation by ${Math.abs(m.delta_valuation).toLocaleString()}. Skip this playbook.
          </>
        ) : (
          <>
            Your <b>{result.active_customers}</b> active customers currently generate a route worth
            {" "}<b>${t.route_valuation.toLocaleString()}</b>. Repricing to
            {" "}<b>{result.state_name}'s ${m.market_median_per_visit}</b> median
            {result.dominant_frequency === "weekly" ? " weekly" : result.dominant_frequency === "biweekly" ? " biweekly" : " monthly"} rate
            would grow monthly revenue by <b>+${m.delta_monthly_revenue.toLocaleString()}</b>
            {" "}(+${m.delta_annual_revenue.toLocaleString()} annual) → valuation
            {" "}<b>+${m.delta_valuation.toLocaleString()}</b>.
            {be.flavor === "very_generous" ? (
              <> You could tolerate up to <b>{be.additional_churn_tolerated_pct}%</b> additional
                 annual churn from the increase (pinned to the churn scale max — market gap is enormous)
                 and still come out ahead.</>
            ) : be.flavor === "thin" ? (
              <> Warning: you could tolerate only <b>{be.additional_churn_tolerated_pct}%</b> additional
                 churn before erasing the gain — consider a phased price increase to test elasticity.</>
            ) : (
              <> You could tolerate up to <b>{be.additional_churn_tolerated_pct}%</b> additional annual
                 churn from the increase and still come out ahead.</>
            )}
          </>
        )}
      </div>

      {/* Assumptions */}
      <div className="rounded-2xl p-4" data-testid="playbook-assumptions"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            Assumptions used
          </div>
          <Link to="/admin/settings/pricing-defaults" className="text-xs font-semibold"
                style={{ color: colors.brand }}
                data-testid="playbook-tune-link">
            Tune defaults →
          </Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div>
            <div style={{ color: colors.muted }}>Density</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{result.assumptions.density}</div>
          </div>
          <div>
            <div style={{ color: colors.muted }}>Churn (today)</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{result.assumptions.churn_pct}%</div>
          </div>
          <div>
            <div style={{ color: colors.muted }}>Contract length</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{result.assumptions.contract_length_avg_months} mo</div>
          </div>
          <div>
            <div style={{ color: colors.muted }}>Multiple range</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>
              {result.assumptions.multiple_min}x – {result.assumptions.multiple_max}x
            </div>
          </div>
          <div>
            <div style={{ color: colors.muted }}>Dominant frequency</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{result.dominant_frequency}</div>
          </div>
          <div>
            <div style={{ color: colors.muted }}>Market service type</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{result.service_type}</div>
          </div>
          <div>
            <div style={{ color: colors.muted }}>State</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{result.state_name} ({result.state_code})</div>
          </div>
          <div>
            <div style={{ color: colors.muted }}>Target margin</div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{result.assumptions.target_margin_pct}%</div>
          </div>
        </div>
      </div>

      {/* CTA */}
      {!skip ? (
        <Link to="/admin/tools/pricing"
              className="block rounded-xl px-4 py-3 text-center text-sm font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="playbook-draft-emails-link">
          Draft rate-increase emails for low-margin customers →
        </Link>
      ) : null}
    </div>
  );
}

export default function BusinessAnalysisTools() {
  const nav = useNavigate();
  const [tab, setTab] = useState("route");
  const Panel = { route: RoutePanel, pay: PayPanel, playbook: PlaybookPanel }[tab];

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
