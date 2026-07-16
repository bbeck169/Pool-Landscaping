/**
 * Phase 47.1 — Budget Setup page (web).
 * Admin/super_admin only. Edits a 12-month × 6-category table for a given year.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Save, Copy, Wand2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";

const CATEGORIES = [
  { key: "revenue",    label: "Revenue",    type: "revenue" },
  { key: "labor",      label: "Labor" },
  { key: "equipment",  label: "Equipment" },
  { key: "materials",  label: "Materials" },
  { key: "overhead",   label: "Overhead" },
  { key: "insurance",  label: "Insurance" },
  { key: "fuel",       label: "Fuel" },
  { key: "target_net_profit_pct", label: "Target Net %", type: "pct" },
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function currency(cents) {
  const v = (cents || 0) / 100;
  return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function centsFromInput(str) {
  const cleaned = String(str).replace(/[^0-9.-]/g, "");
  const n = Number(cleaned);
  if (!isFinite(n)) return 0;
  return Math.round(n * 100);
}

function emptyMonth() {
  return {
    revenue_cents: 0, labor_cents: 0, equipment_cents: 0, materials_cents: 0,
    overhead_cents: 0, insurance_cents: 0, fuel_cents: 0,
    target_net_profit_pct: 15.0,
  };
}

export default function BudgetSetup() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [prevYear, setPrevYear] = useState(new Date().getFullYear() - 1);
  const [copyScale, setCopyScale] = useState(1.1);

  const monthKeys = useMemo(
    () => Array.from({ length: 12 }, (_, i) => `${year}-${String(i + 1).padStart(2, "0")}`),
    [year],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setMsg(null);
    try {
      const res = await api.get(`/budgets/${year}`);
      setDoc(res);
    } catch (e) {
      if (/no_budget_for_year|404/.test(e.message)) {
        // Fresh doc for editing.
        const fresh = {
          year,
          currency: "USD",
          monthly_targets: Object.fromEntries(monthKeys.map((m) => [m, emptyMonth()])),
          labor_burden_pct: 25.0,
          equipment_hourly_cents: 0,
          computed: null,
        };
        setDoc(fresh);
      } else {
        setMsg({ type: "error", text: e.message });
      }
    } finally { setLoading(false); }
  }, [year, monthKeys]);

  useEffect(() => { load(); }, [load]);

  const updateCell = (month, key, value) => {
    setDoc((prev) => ({
      ...prev,
      monthly_targets: {
        ...prev.monthly_targets,
        [month]: { ...(prev.monthly_targets?.[month] || emptyMonth()), [key]: value },
      },
    }));
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const res = await api.put(`/budgets/${year}`, {
        monthly_targets: doc.monthly_targets,
        labor_burden_pct: Number(doc.labor_burden_pct || 25),
        equipment_hourly_cents: Number(doc.equipment_hourly_cents || 0),
      });
      setDoc(res);
      setMsg({ type: "ok", text: "Budget saved. Open estimates re-flagged with new markup." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally { setSaving(false); }
  };

  const clone = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const res = await api.post(`/budgets/${year}/copy-from/${prevYear}?scale=${copyScale}`);
      setDoc(res);
      setMsg({ type: "ok", text: `Cloned ${prevYear} × ${copyScale} into ${year}.` });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally { setSaving(false); }
  };

  const totals = useMemo(() => {
    const t = { revenue: 0, labor: 0, equipment: 0, materials: 0, overhead: 0, insurance: 0, fuel: 0 };
    if (!doc?.monthly_targets) return t;
    for (const row of Object.values(doc.monthly_targets)) {
      for (const c of ["revenue", "labor", "equipment", "materials", "overhead", "insurance", "fuel"]) {
        t[c] += Number(row?.[`${c}_cents`] || 0);
      }
    }
    return t;
  }, [doc]);

  const computed = doc?.computed || {};

  return (
    <div className="p-4 md:p-8 max-w-[1400px] mx-auto" data-testid="budget-setup">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Budget Setup</h1>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            Annual revenue + expense targets, split across 12 months. Amounts in USD.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <label className="text-xs font-semibold" style={{ color: colors.muted }}>Year</label>
          <input
            type="number" min="2020" max="2100" value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="text-sm px-2 py-1.5 rounded-md w-24"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="budget-setup-year"
          />
          <Link to="/admin/budget/dashboard" className="text-xs font-semibold underline"
                style={{ color: colors.brand }} data-testid="budget-setup-dashboard-link">
            Dashboard →
          </Link>
          <Link to="/admin/budget/wizard" className="text-xs font-semibold px-2 py-1.5 rounded-md inline-flex items-center gap-1"
                style={{ border: `1px solid ${colors.border}`, color: colors.brand, background: colors.surface }}
                data-testid="budget-setup-wizard-link">
            <Wand2 size={12} /> Wizard
          </Link>
          <button onClick={load} className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
                  style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                  data-testid="budget-setup-refresh">
            <RefreshCw size={12} /> Refresh
          </button>
          <button onClick={save} disabled={saving || loading}
                  className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
                  style={{ background: colors.brand, color: "#fff", border: 0, cursor: saving ? "wait" : "pointer" }}
                  data-testid="budget-setup-save">
            <Save size={12} /> {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {msg ? (
        <div className={`rounded-md p-3 text-sm mb-4`}
             style={{
               background: msg.type === "ok" ? "#ECFDF5" : "#FEF2F2",
               border: `1px solid ${msg.type === "ok" ? "#A7F3D0" : "#FECACA"}`,
               color: msg.type === "ok" ? "#166534" : "#B91C1C",
             }}
             data-testid="budget-setup-msg">
          {msg.text}
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div className="lg:col-span-2 rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="budget-setup-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.border}`, background: colors.surfaceSecondary }}>
                  <th className="text-left px-3 py-2 font-semibold uppercase" style={{ color: colors.muted, minWidth: 60 }}>Month</th>
                  {CATEGORIES.map((c) => (
                    <th key={c.key} className="text-right px-3 py-2 font-semibold uppercase" style={{ color: colors.muted }}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {monthKeys.map((m, i) => {
                  const row = doc?.monthly_targets?.[m] || emptyMonth();
                  return (
                    <tr key={m} data-testid={`budget-setup-row-${m}`}
                        style={{ borderBottom: `1px solid ${colors.border}` }}>
                      <td className="px-3 py-1.5 font-semibold" style={{ color: colors.onSurface }}>{MONTHS[i]}</td>
                      {CATEGORIES.map((c) => {
                        const cellKey = c.type === "pct" ? "target_net_profit_pct" : `${c.key}_cents`;
                        const displayValue = c.type === "pct"
                          ? String(row?.target_net_profit_pct ?? "")
                          : (Number(row?.[cellKey] || 0) / 100).toString();
                        return (
                          <td key={c.key} className="px-2 py-1">
                            <input
                              type="text"
                              value={displayValue}
                              onChange={(e) => {
                                if (c.type === "pct") {
                                  updateCell(m, cellKey, Number(e.target.value) || 0);
                                } else {
                                  updateCell(m, cellKey, centsFromInput(e.target.value));
                                }
                              }}
                              className="w-full text-right px-1.5 py-1 rounded"
                              style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                              data-testid={`budget-setup-input-${m}-${c.key}`}
                            />
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
                <tr style={{ background: colors.surfaceSecondary, borderTop: `2px solid ${colors.border}` }}>
                  <td className="px-3 py-2 font-bold uppercase text-[10px]" style={{ color: colors.muted }}>Total</td>
                  {CATEGORIES.map((c) => (
                    <td key={c.key} className="px-3 py-2 text-right font-bold" style={{ color: colors.onSurface }}
                        data-testid={`budget-setup-total-${c.key}`}>
                      {c.type === "pct" ? "—" : currency(totals[c.key])}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <aside className="rounded-2xl p-4 h-fit"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid="budget-setup-summary">
          <div className="text-xs font-bold uppercase mb-3" style={{ color: colors.muted }}>Summary</div>
          <SummaryRow label="Annual revenue target" value={currency(totals.revenue)} testid="budget-summary-revenue" />
          <SummaryRow label="Annual total costs" value={currency(computed.total_costs_cents || 0)} testid="budget-summary-costs" />
          <SummaryRow label="Break-even" value={currency(computed.break_even_cents || 0)} testid="budget-summary-breakeven" />
          <SummaryRow label="Target profit %" value={`${computed.target_profit_pct ?? "—"}%`} testid="budget-summary-margin" />
          <SummaryRow label="Billable hourly" value={currency(computed.billable_hourly_cents || 0) + "/hr"} testid="budget-summary-hourly" />
          <SummaryRow label="Markup %" value={`${computed.markup_pct ?? "—"}%`} testid="budget-summary-markup" />
          <div className="my-3 h-px" style={{ background: colors.border }} />
          <div className="text-xs font-bold uppercase mb-2" style={{ color: colors.muted }}>Labor burden</div>
          <input
            type="number" value={doc?.labor_burden_pct ?? 25} min="0" max="200"
            onChange={(e) => setDoc((d) => ({ ...d, labor_burden_pct: Number(e.target.value) }))}
            className="w-full text-sm px-2 py-1.5 rounded-md mb-3"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="budget-setup-labor-burden"
          />
          <div className="text-xs font-bold uppercase mb-2" style={{ color: colors.muted }}>Copy from prior year</div>
          <div className="flex gap-1">
            <input
              type="number" value={prevYear} onChange={(e) => setPrevYear(Number(e.target.value))}
              className="text-sm px-2 py-1.5 rounded-md w-20"
              style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
              data-testid="budget-setup-copy-year"
            />
            <input
              type="number" step="0.05" value={copyScale} onChange={(e) => setCopyScale(Number(e.target.value))}
              className="text-sm px-2 py-1.5 rounded-md w-16"
              style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
              data-testid="budget-setup-copy-scale"
            />
            <button onClick={clone} disabled={saving}
                    className="text-xs font-bold px-2 py-1.5 rounded-md inline-flex items-center gap-1"
                    style={{ background: colors.brand, color: "#fff", border: 0 }}
                    data-testid="budget-setup-copy-btn">
              <Copy size={12} /> Copy
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function SummaryRow({ label, value, testid }) {
  return (
    <div className="flex justify-between text-sm mb-1.5" data-testid={testid}>
      <span style={{ color: colors.muted }}>{label}</span>
      <span className="font-semibold" style={{ color: colors.onSurface }}>{value}</span>
    </div>
  );
}
