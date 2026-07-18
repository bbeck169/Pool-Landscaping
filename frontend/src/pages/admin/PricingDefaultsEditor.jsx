/**
 * Ship 1 · T3-followup — Pricing Defaults editor (admin only).
 *
 * Edits `tenants.settings.{pricing_defaults, route_valuation_defaults,
 * pay_model_defaults}` via `GET/PUT /api/settings/pricing-defaults`. Three
 * collapsible sections group the 30+ constants. Each numeric field has:
 *   * label + numeric input
 *   * tooltip explaining what it drives
 *   * "Reset to app default" button (sends null → server drops the override)
 * Per-section "Reset section" button clears all overrides in that section.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Settings, RotateCcw, Save, ChevronDown, ChevronRight, Info } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

// Field metadata: order + tooltip for every editable key. Anything not in
// this map falls back to a generic tooltip (still editable).
const FIELDS = {
  pricing_defaults: {
    label: "Service Pricing",
    subtitle: "Constants used by Service In-cost, Cost per Pool, and Service Price recommender.",
    rows: [
      ["tech_hourly_cost",        "$", "Cost the tenant pays a tech per hour (used in labor calc)."],
      ["tech_time_minutes",       "min", "Minutes an average visit takes."],
      ["overhead_multiplier",     "×", "Multiplier applied to (chem+labor) to include overhead."],
      ["margin_target_pct",       "%", "Target gross margin for new-customer price recommendations."],
      ["base_weekly",             "$", "Base weekly service price before adders."],
      ["base_bi_weekly",          "$", "Base bi-weekly service price before adders."],
      ["base_monthly",            "$", "Base monthly service price before adders."],
      ["gallons_baseline",        "gal", "Pool size at which no gallons-adder applies."],
      ["gallons_step",            "gal", "Gallons above baseline per each step-price adder."],
      ["gallons_step_price",      "$", "Dollars added per step of extra gallons."],
      ["adder_saltwater",         "$", "Extra $ for saltwater pools."],
      ["adder_heater",            "$", "Extra $ for pools with a heater."],
      ["adder_spa",               "$", "Extra $ for attached spa."],
      ["adder_automation",        "$", "Extra $ for automation/smart-control equipment."],
      ["adder_chlorine_tabs",     "$", "Extra $ if primary sanitizer is chlorine tabs."],
      ["adder_liquid_chlorine",   "$", "Extra $ if primary sanitizer is liquid chlorine."],
      ["zone_default_multiplier", "×", "Zone multiplier applied when no per-zone override exists."],
    ],
  },
  route_valuation_defaults: {
    label: "Route Valuation",
    subtitle: "Constants used by /admin/tools/analysis · Route Valuation tab.",
    rows: [
      ["churn_rate_pct",             "%", "Default churn rate (annual %) when no input provided."],
      ["tech_cost_percentage",       "%", "Tech cost as % of revenue (used in gross-profit calc)."],
      ["chemical_cost_percentage",   "%", "Chemical cost as % of revenue."],
      ["overhead_percentage",        "%", "Overhead cost as % of revenue."],
      ["contract_length_avg_months", "mo", "Default avg contract length when no input provided."],
      ["multiple_min",               "x", "Lowest possible route multiple (worst-case mix)."],
      ["multiple_max",               "x", "Highest possible route multiple (best-case mix)."],
      ["churn_low_pct",              "%", "Churn ≤ this = ideal (factor 1.0)."],
      ["churn_high_pct",             "%", "Churn ≥ this = worst-case (factor 0.0)."],
      ["contract_short_months",      "mo", "Contract length ≤ this = worst-case (factor 0.0)."],
      ["contract_long_months",       "mo", "Contract length ≥ this = ideal (factor 1.0)."],
      ["industry_per_customer_low",  "$", "Industry per-customer valuation lower bound (benchmark)."],
      ["industry_per_customer_high", "$", "Industry per-customer valuation upper bound (benchmark)."],
    ],
  },
  pay_model_defaults: {
    label: "Pay Model",
    subtitle: "Constants used by /admin/tools/analysis · Pay Model Compare tab.",
    rows: [
      ["hourly_rate",              "$", "Hourly rate paid to tech under hourly model."],
      ["per_pool_rate",            "$", "$ paid per pool under per-pool model."],
      ["route_buy_pct",            "%", "% of route revenue tech keeps under route-buy model."],
      ["chemical_cost_percentage", "%", "Chemical cost as % of revenue (for company margin math)."],
      ["overhead_percentage",      "%", "Overhead cost as % of revenue."],
    ],
  },
};

function Row({ section, sectionData, k, unit, tooltip, spec, overrideVal, onChange, onReset }) {
  const [showTip, setShowTip] = useState(false);
  const specVal = spec[k];
  const isOverridden = overrideVal !== undefined;
  const displayed = isOverridden ? overrideVal : specVal;
  return (
    <div className="flex items-center gap-2 py-2" style={{ borderBottom: `1px solid ${colors.border}` }}>
      <div className="flex-1">
        <div className="flex items-center gap-1">
          <label className="text-sm font-semibold" style={{ color: colors.onSurface }}
                 htmlFor={`pd-${section}-${k}`}>
            {k}
          </label>
          <button onClick={() => setShowTip(!showTip)}
                  data-testid={`pd-tip-${section}-${k}`}>
            <Info size={12} color={colors.muted} />
          </button>
          {isOverridden ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full ml-1"
                  style={{ backgroundColor: `${colors.brand}22`, color: colors.brand }}>
              overridden
            </span>
          ) : null}
        </div>
        {showTip ? (
          <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
            {tooltip}. App default: <b>{String(specVal)}</b>.
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-2 rounded-lg px-2 py-1 w-32"
           style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}` }}>
        {unit === "$" ? <span style={{ color: colors.muted }} className="text-xs">$</span> : null}
        <input id={`pd-${section}-${k}`}
               type="number" step="any" value={String(displayed)}
               onChange={(e) => onChange(k, e.target.value)}
               className="w-full bg-transparent focus:outline-none text-sm text-right"
               style={{ color: colors.onSurface }}
               data-testid={`pd-input-${section}-${k}`} />
        {unit !== "$" ? <span style={{ color: colors.muted }} className="text-xs">{unit}</span> : null}
      </div>
      <button onClick={() => onReset(k)}
              className="text-xs font-semibold rounded-lg px-2 py-1 inline-flex items-center gap-1"
              style={{
                backgroundColor: isOverridden ? colors.brand : colors.surface,
                color: isOverridden ? "#fff" : colors.muted,
                border: `1px solid ${isOverridden ? colors.brand : colors.border}`,
                opacity: isOverridden ? 1 : 0.5,
              }}
              disabled={!isOverridden}
              data-testid={`pd-reset-${section}-${k}`}>
        <RotateCcw size={11} /> reset
      </button>
    </div>
  );
}

function Section({ section, spec, overrides, onPatch, onResetSection }) {
  const meta = FIELDS[section];
  const [open, setOpen] = useState(true);
  const overrideKeys = Object.keys(overrides || {});
  return (
    <div className="rounded-2xl mb-4"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid={`pd-section-${section}`}>
      <button onClick={() => setOpen(!open)}
              className="w-full flex items-center gap-2 p-4"
              data-testid={`pd-section-toggle-${section}`}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <div className="flex-1 text-left">
          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
            {meta.label}
            {overrideKeys.length ? (
              <span className="text-xs font-normal ml-2" style={{ color: colors.brand }}>
                ({overrideKeys.length} override{overrideKeys.length === 1 ? "" : "s"})
              </span>
            ) : null}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>{meta.subtitle}</div>
        </div>
        {overrideKeys.length ? (
          <button onClick={(e) => { e.stopPropagation(); onResetSection(); }}
                  className="text-xs font-semibold rounded-lg px-2 py-1 inline-flex items-center gap-1"
                  style={{ backgroundColor: `${colors.brand}22`, color: colors.brand }}
                  data-testid={`pd-reset-section-${section}`}>
            <RotateCcw size={11} /> Reset section
          </button>
        ) : null}
      </button>
      {open ? (
        <div className="px-4 pb-4">
          {meta.rows.map(([k, unit, tooltip]) => (
            <Row key={k} section={section} sectionData={spec} k={k} unit={unit} tooltip={tooltip}
                 spec={spec} overrideVal={overrides?.[k]}
                 onChange={onPatch}
                 onReset={(kk) => onPatch(kk, null)} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function PricingDefaultsEditor() {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [pending, setPending] = useState({ pricing_defaults: {}, route_valuation_defaults: {}, pay_model_defaults: {} });
  const [err, setErr] = useState(null);
  const [flash, setFlash] = useState(null);

  const load = () => api.get("/settings/pricing-defaults").then(setData).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  // pending stores unsaved edits keyed by section → field → value.
  const patch = (section, key, value) => {
    setPending({ ...pending, [section]: { ...pending[section], [key]: value === "" ? null : value } });
    setFlash(null);
  };
  const resetSection = (section) => {
    // Send explicit-nulls for every currently-overridden key in that section.
    const overrides = data.tenant_overrides[section] || {};
    const patches = Object.fromEntries(Object.keys(overrides).map(k => [k, null]));
    setPending({ ...pending, [section]: { ...pending[section], ...patches } });
  };

  const save = async () => {
    setErr(null); setFlash(null);
    // Coerce numeric strings → floats where appropriate.
    const cleaned = {};
    for (const section of Object.keys(pending)) {
      const patchObj = pending[section];
      if (!Object.keys(patchObj).length) continue;
      cleaned[section] = {};
      for (const [k, v] of Object.entries(patchObj)) {
        if (v === null) { cleaned[section][k] = null; continue; }
        const n = Number(v);
        cleaned[section][k] = Number.isFinite(n) ? n : v;
      }
    }
    if (!Object.keys(cleaned).length) {
      setFlash({ ok: true, msg: "Nothing to save." });
      setTimeout(() => setFlash(null), 2500);
      return;
    }
    try {
      await api.put("/settings/pricing-defaults", cleaned);
      setPending({ pricing_defaults: {}, route_valuation_defaults: {}, pay_model_defaults: {} });
      await load();
      setFlash({ ok: true, msg: "Saved ✓" });
    } catch (e) { setErr(e.message); }
    setTimeout(() => setFlash(null), 3500);
  };

  if (!data) {
    return <div className="p-6" data-testid="pd-loading" style={{ color: colors.muted }}>Loading…</div>;
  }

  // Effective view = tenant_overrides merged with pending edits (unsaved).
  const effOverride = (section) => ({ ...(data.tenant_overrides[section] || {}), ...(pending[section] || {}) });
  const pendingCount = Object.values(pending).reduce((n, o) => n + Object.keys(o).length, 0);

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="pricing-defaults-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="pd-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
            <Settings size={22} style={{ color: colors.brand }} />
            Pricing Defaults
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Tune the constants used by every T3/T5 calculator. Leave a field on app default
            and it comes from the shipped spec; set an override and it applies tenant-wide.
          </p>
        </div>
        <button onClick={save}
                className="text-sm font-bold rounded-lg px-4 py-2 inline-flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="pd-save">
          <Save size={14} /> Save
          {pendingCount ? <span className="ml-1 text-xs px-1.5 py-0.5 rounded-full"
                                style={{ backgroundColor: "rgba(255,255,255,0.25)" }}>{pendingCount}</span> : null}
        </button>
      </div>
      {err ? <div className="mb-3 text-sm rounded-lg p-2"
                   style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                   data-testid="pd-err">{err}</div> : null}
      {flash ? <div className="mb-3 text-sm rounded-lg p-2"
                     style={{ backgroundColor: flash.ok ? "#DCFCE7" : "#FEE2E2",
                              color: flash.ok ? "#166534" : "#991B1B" }}
                     data-testid="pd-flash">{flash.msg}</div> : null}

      {["pricing_defaults", "route_valuation_defaults", "pay_model_defaults"].map((section) => (
        <Section key={section} section={section}
                 spec={data.spec_defaults[section]}
                 overrides={effOverride(section)}
                 onPatch={(k, v) => patch(section, k, v)}
                 onResetSection={() => resetSection(section)} />
      ))}
    </div>
  );
}
