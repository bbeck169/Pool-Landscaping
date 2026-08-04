/**
 * Phase 47.5 — "Know Your Numbers" 4-step budget wizard.
 * Admin/super_admin only. On apply → PUTs a fresh 12-month budget doc.
 */
import React, { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Wand2, Check } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function money(cents) {
  const v = (cents || 0) / 100;
  return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

const STEPS = ["Net Profit", "Operating Expenses", "Preview", "Apply"];

export default function BudgetWizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [year, setYear] = useState(new Date().getFullYear());
  const [profitMode, setProfitMode] = useState("pct"); // "pct" | "cents"
  const [profitPct, setProfitPct] = useState(15);
  const [profitDollars, setProfitDollars] = useState(50000);
  const [opex, setOpex] = useState(400000);
  const [seasonal, setSeasonal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState(null);

  const opexCents = Math.round(Number(opex) * 100);
  const profitDollarsCents = Math.round(Number(profitDollars) * 100);

  const derived = useMemo(() => {
    // Simple math preview — server does the authoritative version.
    let targetProfit = 0;
    if (profitMode === "cents") targetProfit = profitDollarsCents;
    else {
      const p = Math.max(0, Math.min(90, Number(profitPct))) / 100;
      targetProfit = Math.round(opexCents * (p / Math.max(1e-6, 1 - p)));
    }
    const requiredRevenue = opexCents + targetProfit;
    const grossProfit = targetProfit;
    return {
      target_profit_cents: targetProfit,
      required_revenue_cents: requiredRevenue,
      break_even_cents: opexCents,
      gross_profit_cents: grossProfit,
      margin_pct: requiredRevenue > 0 ? Math.round((targetProfit / requiredRevenue) * 1000) / 10 : 0,
    };
  }, [profitMode, profitPct, profitDollars, opex, opexCents, profitDollarsCents]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: memoized deps are stable by value; wrapping the source in its own useMemo would obscure the read

  const apply = async () => {
    setSubmitting(true); setErr(null);
    try {
      const body = {
        annual_operating_expenses_cents: opexCents,
        seasonal_weighting: seasonal,
      };
      if (profitMode === "cents") body.annual_net_profit_cents = profitDollarsCents;
      else body.annual_net_profit_pct = Number(profitPct);
      await api.post(`/budgets/${year}/wizard/apply`, body);
      navigate("/admin/budget");
    } catch (e) {
      setErr(e.message);
    } finally { setSubmitting(false); }
  };

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="budget-wizard">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center"
             style={{ background: colors.brandTertiary, color: colors.onBrandTertiary }}>
          <Wand2 size={20} />
        </div>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Know Your Numbers</h1>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            4 steps → pre-fills a 12-month budget for the year you choose.
          </p>
        </div>
        <Link to="/admin/budget" className="text-xs font-semibold underline" style={{ color: colors.brand }}
              data-testid="budget-wizard-back-to-setup">
          Skip to setup
        </Link>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-2 mb-6" data-testid="budget-wizard-stepper">
        {STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-2 flex-1">
            <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                 style={{
                   background: i <= step ? colors.brand : colors.surfaceSecondary,
                   color: i <= step ? "#fff" : colors.muted,
                   border: `1px solid ${i <= step ? colors.brand : colors.border}`,
                 }}>
              {i < step ? <Check size={14} /> : i + 1}
            </div>
            <div className="text-xs font-semibold" style={{ color: i <= step ? colors.onSurface : colors.muted }}>{s}</div>
            {i < STEPS.length - 1 ? <div className="h-px flex-1" style={{ background: colors.border }} /> : null}
          </div>
        ))}
      </div>

      <div className="rounded-2xl p-6"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid={`budget-wizard-step-${step}`}>

        {step === 0 && (
          <>
            <div className="text-lg font-bold mb-1" style={{ color: colors.onSurface }}>What net profit do you want?</div>
            <div className="text-sm mb-4" style={{ color: colors.muted }}>Either a dollar amount or a percentage of revenue.</div>
            <div className="flex gap-2 mb-3">
              <button onClick={() => setProfitMode("pct")}
                      className="text-xs font-bold px-3 py-1.5 rounded-md"
                      style={{ background: profitMode === "pct" ? colors.brand : colors.surface,
                               color: profitMode === "pct" ? "#fff" : colors.onSurface,
                               border: `1px solid ${profitMode === "pct" ? colors.brand : colors.border}` }}
                      data-testid="budget-wizard-profit-mode-pct">Percent</button>
              <button onClick={() => setProfitMode("cents")}
                      className="text-xs font-bold px-3 py-1.5 rounded-md"
                      style={{ background: profitMode === "cents" ? colors.brand : colors.surface,
                               color: profitMode === "cents" ? "#fff" : colors.onSurface,
                               border: `1px solid ${profitMode === "cents" ? colors.brand : colors.border}` }}
                      data-testid="budget-wizard-profit-mode-cents">Dollars</button>
            </div>
            {profitMode === "pct" ? (
              <input type="number" value={profitPct} onChange={(e) => setProfitPct(e.target.value)}
                     step="0.5" min="0" max="90"
                     className="w-full text-lg px-3 py-2 rounded-md"
                     style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                     data-testid="budget-wizard-profit-pct" />
            ) : (
              <input type="number" value={profitDollars} onChange={(e) => setProfitDollars(e.target.value)}
                     className="w-full text-lg px-3 py-2 rounded-md"
                     style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                     data-testid="budget-wizard-profit-dollars" />
            )}
            <div className="mt-4 flex items-center gap-2">
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Year</label>
              <input type="number" min="2020" max="2100" value={year}
                     onChange={(e) => setYear(Number(e.target.value))}
                     className="text-sm px-2 py-1.5 rounded-md w-24"
                     style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                     data-testid="budget-wizard-year" />
            </div>
          </>
        )}
        {step === 1 && (
          <>
            <div className="text-lg font-bold mb-1" style={{ color: colors.onSurface }}>Estimated annual operating expenses?</div>
            <div className="text-sm mb-4" style={{ color: colors.muted }}>Everything you'll spend in the year to run the business.</div>
            <input type="number" value={opex} onChange={(e) => setOpex(e.target.value)}
                   className="w-full text-lg px-3 py-2 rounded-md"
                   style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                   data-testid="budget-wizard-opex" />
            <label className="mt-4 flex items-center gap-2 text-sm" style={{ color: colors.onSurface }}>
              <input type="checkbox" checked={seasonal} onChange={(e) => setSeasonal(e.target.checked)}
                     data-testid="budget-wizard-seasonal" />
              Apply seasonal weighting (summer bump)
            </label>
          </>
        )}
        {step === 2 && (
          <>
            <div className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>Preview</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Preview label="Required revenue"   value={money(derived.required_revenue_cents)} testid="budget-wizard-preview-revenue" />
              <Preview label="Break-even"         value={money(derived.break_even_cents)} testid="budget-wizard-preview-breakeven" />
              <Preview label="Gross profit"       value={money(derived.gross_profit_cents)} testid="budget-wizard-preview-gross" />
              <Preview label="Target net margin"  value={`${derived.margin_pct}%`} testid="budget-wizard-preview-margin" />
            </div>
            <div className="mt-4 text-xs" style={{ color: colors.muted }}>
              Applying will overwrite the {year} budget with an even {seasonal ? "seasonal " : ""}split across 12 months.
              You can fine-tune the numbers in <Link to="/admin/budget" className="underline">Budget Setup</Link>.
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <div className="text-lg font-bold mb-1" style={{ color: colors.onSurface }}>Apply to {year}?</div>
            <div className="text-sm mb-4" style={{ color: colors.muted }}>Overwrites any existing {year} budget.</div>
            {err ? (
              <div className="rounded-md p-3 text-sm mb-3"
                   style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
                   data-testid="budget-wizard-error">{err}</div>
            ) : null}
            <button onClick={apply} disabled={submitting}
                    className="text-sm font-bold px-4 py-2 rounded-md inline-flex items-center gap-2"
                    style={{ background: colors.brand, color: "#fff", border: 0, cursor: submitting ? "wait" : "pointer" }}
                    data-testid="budget-wizard-apply">
              <Check size={14} /> {submitting ? "Applying…" : `Apply to ${year} budget`}
            </button>
          </>
        )}
      </div>

      <div className="flex justify-between mt-4">
        <button onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}
                className="text-sm font-semibold inline-flex items-center gap-1 px-3 py-1.5 rounded-md"
                style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface,
                         opacity: step === 0 ? 0.4 : 1, cursor: step === 0 ? "not-allowed" : "pointer" }}
                data-testid="budget-wizard-back">
          <ChevronLeft size={14} /> Back
        </button>
        {step < STEPS.length - 1 ? (
          <button onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
                  className="text-sm font-bold inline-flex items-center gap-1 px-3 py-1.5 rounded-md"
                  style={{ background: colors.brand, color: "#fff", border: 0 }}
                  data-testid="budget-wizard-next">
            Next <ChevronRight size={14} />
          </button>
        ) : null}
      </div>
    </div>
  );
}

function Preview({ label, value, testid }) {
  return (
    <div className="rounded-lg p-3"
         style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
         data-testid={testid}>
      <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>{label}</div>
      <div className="text-lg font-bold mt-1" style={{ color: colors.onSurface }}>{value}</div>
    </div>
  );
}
