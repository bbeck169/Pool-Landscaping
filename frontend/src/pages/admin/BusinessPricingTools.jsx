/**
 * Phase T3 — Business Pricing Tools (admin only).
 *
 * Three tabs, all wired to `backend/routers/pool_calculators.py`:
 *   1. Service In-cost   — POST /calculators/service-in-cost
 *   2. Cost per Pool     — GET  /calculators/cost-per-pool
 *   3. Service Price     — POST /calculators/service-price
 *
 * RBAC on the frontend is enforced by <AdminOnly> in App.js; the backend
 * endpoints re-check via `_require_admin` (super_admin + admin only, techs
 * and customers get 403).
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, DollarSign, LineChart, TrendingDown, Copy, Download,
  CheckCircle2, AlertTriangle,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const TABS = [
  { key: "in-cost",       label: "Service In-cost",  icon: DollarSign },
  { key: "cost-per-pool", label: "Cost per Pool",    icon: LineChart },
  { key: "service-price", label: "Service Price",    icon: TrendingDown },
];

function copy(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text);
}

function Field({ label, value, onChange, unit, type = "number", testid, placeholder = "" }) {
  return (
    <label className="block">
      <span className="text-xs font-bold uppercase tracking-wider"
            style={{ color: colors.muted }}>{label}</span>
      <div className="flex items-center gap-2 mt-1 rounded-lg px-3 py-2"
           style={{ backgroundColor: colors.background,
                     border: `1px solid ${colors.border}` }}>
        <input value={value} onChange={(e) => onChange(e.target.value)}
               type={type} step="any" placeholder={placeholder}
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
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

// ── T3.1 In-cost ─────────────────────────────────────────────────────
function InCostPanel() {
  const [gal, setGal] = useState("20000");
  const [vt, setVt] = useState("weekly");
  const [chems, setChems] = useState([
    {chemical_slug: "liquid_chlorine", quantity: 1.0, unit: "gal"},
    {chemical_slug: "muriatic_acid", quantity: 0.25, unit: "gal"},
    {chemical_slug: "chlorine_tabs", quantity: 2, unit: "tab"},
  ]);
  const [mins, setMins] = useState("45");
  const [hourly, setHourly] = useState("35");
  const [overhead, setOverhead] = useState("1.25");
  const [margin, setMargin] = useState("40");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/service-in-cost", {
        pool_gallons: parseFloat(gal),
        visit_type: vt,
        chemicals_per_visit: chems.map(c => ({
          chemical_slug: c.chemical_slug, quantity: parseFloat(c.quantity), unit: c.unit
        })),
        tech_time_minutes: parseFloat(mins),
        tech_hourly_cost: parseFloat(hourly),
        overhead_multiplier: parseFloat(overhead),
        margin_target_pct: parseFloat(margin),
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  return (
    <div className="rounded-2xl p-6"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="incost-panel">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Pool volume" unit="gal" value={gal} onChange={setGal} testid="incost-gal" />
        <Select label="Visit type" value={vt} onChange={setVt}
                options={[{value:"weekly",label:"Weekly"},{value:"bi-weekly",label:"Bi-weekly"},{value:"monthly",label:"Monthly"}]}
                testid="incost-vt" />
        <Field label="Tech time" unit="min" value={mins} onChange={setMins} testid="incost-mins" />
        <Field label="Hourly cost" unit="$/hr" value={hourly} onChange={setHourly} testid="incost-hourly" />
        <Field label="Overhead mult" value={overhead} onChange={setOverhead} testid="incost-overhead" />
        <Field label="Margin target" unit="%" value={margin} onChange={setMargin} testid="incost-margin" />
      </div>

      <div className="mt-4">
        <div className="text-xs font-bold uppercase tracking-wider mb-2"
             style={{ color: colors.muted }}>Chemicals per visit</div>
        {chems.map((c, i) => (
          <div key={i} className="grid grid-cols-3 gap-2 mb-2">
            <input value={c.chemical_slug} onChange={(e) => {
              const nx = [...chems]; nx[i].chemical_slug = e.target.value; setChems(nx);
            }} placeholder="slug (e.g. liquid_chlorine)"
              className="rounded-lg px-2 py-1"
              style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
              data-testid={`incost-chem-slug-${i}`} />
            <input value={c.quantity} onChange={(e) => {
              const nx = [...chems]; nx[i].quantity = e.target.value; setChems(nx);
            }} type="number" placeholder="qty"
              className="rounded-lg px-2 py-1"
              style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
              data-testid={`incost-chem-qty-${i}`} />
            <input value={c.unit} onChange={(e) => {
              const nx = [...chems]; nx[i].unit = e.target.value; setChems(nx);
            }} placeholder="unit"
              className="rounded-lg px-2 py-1"
              style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
              data-testid={`incost-chem-unit-${i}`} />
          </div>
        ))}
        <button onClick={() => setChems([...chems, {chemical_slug: "", quantity: 0, unit: ""}])}
                className="text-xs font-semibold"
                style={{ color: colors.brand }}
                data-testid="incost-add-chem">+ Add chemical</button>
      </div>

      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="incost-compute">Compute in-cost</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <div className="mt-4 rounded-xl p-4"
             style={{ backgroundColor: `${colors.brand}10` }}
             data-testid="incost-result">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="Chem cost" value={`$${result.chemical_cost_total}`} />
            <Stat label="Labor" value={`$${result.labor_cost}`} />
            <Stat label="Overhead" value={`$${result.overhead_cost}`} />
            <Stat label="Total in-cost" value={`$${result.total_in_cost}`} bold />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-4">
            <Stat label={`Minimum price @ ${result.margin_target_pct}% margin`}
                  value={`$${result.minimum_price_per_visit}/visit`} bold accent />
            <Stat label={`Annualized (${result.visits_per_year} visits/yr)`}
                  value={`$${result.annualized_revenue.toLocaleString()}`} accent />
          </div>
          <button onClick={() => copy(
            `Total in-cost: $${result.total_in_cost} · Minimum price: $${result.minimum_price_per_visit}/visit · Annualized: $${result.annualized_revenue}`
          )} className="mt-3 text-xs font-semibold rounded-lg px-2 py-1 flex items-center gap-1"
             style={{ backgroundColor: `${colors.brand}22`, color: colors.brand }}
             data-testid="incost-copy">
            <Copy size={12} /> Copy summary
          </button>
        </div>
      ) : null}
    </div>
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

// ── T3.2 Cost per Pool ───────────────────────────────────────────────
function CostPerPoolPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    api.get("/calculators/cost-per-pool")
      .then(setData).catch((e) => setErr(e.message));
  }, []);

  const rows = (data?.rows || []).filter(r =>
    !filter || r.customer_name.toLowerCase().includes(filter.toLowerCase())
  );

  const exportCsv = () => {
    if (!rows.length) return;
    const header = ["Customer","Gallons","Frequency","Monthly in-cost","Monthly revenue","Margin $","Margin %","Flags"];
    const lines = [header.join(",")].concat(rows.map(r =>
      [r.customer_name, r.pool_gallons, r.visit_type, r.monthly_in_cost, r.monthly_revenue,
       r.margin_amount, r.margin_pct ?? "", (r.flags || []).join("|")].map(v => `"${v}"`).join(",")));
    const blob = new Blob([lines.join("\n")], {type: "text/csv"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "cost-per-pool.csv";
    a.click();
  };

  return (
    <div className="rounded-2xl p-6"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="cpp-panel">
      {err ? <div className="text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {!data ? <div style={{ color: colors.muted }}>Loading…</div> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-3">
            <Stat label="Customers" value={data.count} bold />
            <Stat label="Median margin" value={data.summary.median_margin_pct !== null ? `${data.summary.median_margin_pct}%` : "—"} bold accent />
            <Stat label="Negative" value={data.summary.negative_margin_count} />
            <Stat label="Low margin" value={data.summary.low_margin_count} />
            <Stat label="High margin" value={data.summary.high_margin_count} />
          </div>
          <div className="flex items-center gap-2 mb-3">
            <input value={filter} onChange={(e) => setFilter(e.target.value)}
                   placeholder="Filter by customer name…"
                   className="flex-1 rounded-lg px-3 py-2 text-sm"
                   style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                   data-testid="cpp-filter" />
            <button onClick={exportCsv}
                    className="flex items-center gap-1 rounded-lg px-3 py-2 text-xs font-semibold"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="cpp-export">
              <Download size={12} /> Export CSV
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="cpp-table">
              <thead>
                <tr style={{ color: colors.muted }}>
                  <th className="text-left py-2">Customer</th>
                  <th className="text-right">Gallons</th>
                  <th className="text-left">Freq</th>
                  <th className="text-right">In-cost/mo</th>
                  <th className="text-right">Revenue/mo</th>
                  <th className="text-right">Margin $</th>
                  <th className="text-right">Margin %</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const isNeg = (r.flags || []).includes("negative_margin");
                  const isLow = (r.flags || []).includes("low_margin");
                  const isHigh = (r.flags || []).includes("high_margin");
                  const bg = isNeg ? "#FEE2E2" : isLow ? "#FEF3C7" : isHigh ? "#DCFCE7" : "transparent";
                  return (
                    <tr key={r.customer_id} style={{ backgroundColor: bg }} data-testid={`cpp-row-${r.customer_id}`}>
                      <td className="py-2">{r.customer_name}</td>
                      <td className="text-right">{r.pool_gallons?.toLocaleString()}</td>
                      <td>{r.visit_type}</td>
                      <td className="text-right">${r.monthly_in_cost}</td>
                      <td className="text-right">${r.monthly_revenue}</td>
                      <td className="text-right" style={{color: r.margin_amount < 0 ? "#991B1B" : colors.onSurface}}>
                        ${r.margin_amount}
                      </td>
                      <td className="text-right font-bold">{r.margin_pct ?? "—"}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ── T3.3 Service Price ───────────────────────────────────────────────
function ServicePricePanel() {
  const [gal, setGal] = useState("20000");
  const [vt, setVt] = useState("weekly");
  const [feats, setFeats] = useState({saltwater: true, heater: true});
  const [zone, setZone] = useState("");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const toggle = (k) => setFeats(f => ({...f, [k]: !f[k]}));

  const compute = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/service-price", {
        pool_gallons: parseFloat(gal),
        visit_type: vt,
        pool_features: Object.keys(feats).filter(k => feats[k]),
        distance_zone: zone || null,
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  const FeatBtn = ({k, label}) => (
    <button onClick={() => toggle(k)}
            className="px-3 py-1 rounded-lg text-xs font-semibold"
            style={{
              backgroundColor: feats[k] ? colors.brand : colors.surface,
              color: feats[k] ? "#fff" : colors.onSurface,
              border: `1px solid ${feats[k] ? colors.brand : colors.border}`,
            }}
            data-testid={`sp-feat-${k}`}>
      {label}
    </button>
  );

  return (
    <div className="rounded-2xl p-6"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="sp-panel">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Pool volume" unit="gal" value={gal} onChange={setGal} testid="sp-gal" />
        <Select label="Visit type" value={vt} onChange={setVt}
                options={[{value:"weekly",label:"Weekly"},{value:"bi-weekly",label:"Bi-weekly"},{value:"monthly",label:"Monthly"}]}
                testid="sp-vt" />
        <Field label="Distance zone" value={zone} onChange={setZone} testid="sp-zone" placeholder="(optional)" type="text" />
      </div>
      <div className="mt-3">
        <div className="text-xs font-bold uppercase tracking-wider mb-2"
             style={{ color: colors.muted }}>Pool features</div>
        <div className="flex flex-wrap gap-2">
          <FeatBtn k="saltwater" label="Saltwater" />
          <FeatBtn k="heater" label="Heater" />
          <FeatBtn k="spa" label="Spa" />
          <FeatBtn k="automation" label="Automation" />
          <FeatBtn k="chlorine_tabs" label="Chlorine tabs" />
          <FeatBtn k="liquid_chlorine" label="Liquid chlorine" />
        </div>
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="sp-compute">Compute recommended price</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <div className="mt-4 rounded-xl p-4"
             style={{ backgroundColor: `${colors.brand}10` }}
             data-testid="sp-result">
          <Stat label={`Recommended ${result.visit_type} price`}
                value={`$${result.recommended_price}`} bold accent />
          <div className="mt-3 text-sm" style={{ color: colors.onSurface }}>
            <strong>Breakdown:</strong>
            <ul className="mt-1 space-y-1 text-xs" style={{ color: colors.muted }}>
              <li>Base: ${result.breakdown.base}</li>
              {result.breakdown.features.map((f, i) => (
                <li key={i}>+ ${f.amount} · {f.feature}</li>
              ))}
              <li>+ ${result.breakdown.gallons_adder} · gallons over baseline</li>
              <li>Zone multiplier: ×{result.breakdown.zone_multiplier}</li>
              <li>Subtotal before zone: ${result.breakdown.subtotal_before_zone}</li>
            </ul>
          </div>
          {result.peer_median_price != null ? (
            <div className="mt-3 text-xs"
                 style={{ color: result.recommended_price > result.peer_median_price ? "#92400E" : "#166534" }}
                 data-testid="sp-peer">
              Peer median ({result.peer_sample_size} similar customers): ${result.peer_median_price} ·{" "}
              {result.recommended_price > result.peer_median_price
                ? "above peer median"
                : result.recommended_price < result.peer_median_price
                ? "below peer median"
                : "at peer median"}
            </div>
          ) : (
            <div className="mt-3 text-xs" style={{ color: colors.muted }}>
              No peer sample available yet.
            </div>
          )}
          <button onClick={() => copy(
            `Recommended ${result.visit_type} price: $${result.recommended_price} (base $${result.breakdown.base}, features $${result.breakdown.features_total}, gallons $${result.breakdown.gallons_adder}, zone ×${result.breakdown.zone_multiplier})`
          )} className="mt-3 text-xs font-semibold rounded-lg px-2 py-1 flex items-center gap-1"
             style={{ backgroundColor: `${colors.brand}22`, color: colors.brand }}
             data-testid="sp-copy">
            <Copy size={12} /> Copy summary
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default function BusinessPricingTools() {
  const nav = useNavigate();
  const [tab, setTab] = useState("in-cost");
  const Panel = { "in-cost": InCostPanel, "cost-per-pool": CostPerPoolPanel, "service-price": ServicePricePanel }[tab];

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="pricing-tools-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="pricing-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <DollarSign size={22} style={{ color: colors.brand }} />
            Business Pricing Tools
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Admin-only. Service in-cost · Portfolio margin scan · New-customer price recommender.
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
                    data-testid={`pricing-tab-${t.key}`}>
              <Icon size={14} /> {t.label}
            </button>
          );
        })}
      </div>

      <Panel />
    </div>
  );
}
