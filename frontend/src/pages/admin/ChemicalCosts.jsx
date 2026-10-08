/**
 * Phase 50.A — Admin: Chemical Costs CRUD.
 *
 * Editable table of 9 default chemicals. Admin+super_admin only.
 * Wires to:
 *   GET  /api/admin/chemical-costs
 *   PUT  /api/admin/chemical-costs/{slug}
 *   POST /api/admin/chemical-costs/reseed
 */
import React, { useEffect, useState } from "react";
import { FlaskConical, RefreshCw, Save, RotateCcw, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function centsToDollars(c) {
  return (Number(c || 0) / 100).toFixed(2);
}
function dollarsToCents(v) {
  const n = Math.round(Number(v || 0) * 100);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

const UNIT_OPTIONS = ["gal", "lbs", "oz", "tab", "bag", "kg"];

export default function ChemicalCosts() {
  const [rows, setRows] = useState([]);
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reseeding, setReseeding] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState("");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get("/admin/chemical-costs");
      setRows(res.items || []);
      // Reset draft to canonical values.
      const d = {};
      for (const r of res.items || []) {
        d[r.chemical_slug] = {
          name: r.name || "",
          unit_kind: r.unit_kind || "",
          dollars: centsToDollars(r.cost_per_unit_cents),
        };
      }
      setDraft(d);
    } catch (e) {
      setError(e?.message || "Failed to load chemical costs.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const editRow = (slug, patch) => {
    setDraft((d) => ({ ...d, [slug]: { ...(d[slug] || {}), ...patch } }));
  };

  const saveRow = async (slug) => {
    const d = draft[slug];
    if (!d) return;
    setSaving(slug);
    setError(null);
    try {
      await api.put(`/admin/chemical-costs/${slug}`, {
        cost_per_unit_cents: dollarsToCents(d.dollars),
        unit_kind: d.unit_kind,
        name: d.name,
      });
      setToast(`Saved ${d.name}`);
      setTimeout(() => setToast(""), 2000);
      await load();
    } catch (e) {
      setError(e?.message || "Save failed.");
    } finally {
      setSaving(null);
    }
  };

  const reseed = async () => {
    setReseeding(true);
    setError(null);
    try {
      const res = await api.post("/admin/chemical-costs/reseed", {});
      setToast(`Restored ${res?.inserted || 0} default rows.`);
      setTimeout(() => setToast(""), 2500);
      await load();
    } catch (e) {
      setError(e?.message || "Reseed failed.");
    } finally {
      setReseeding(false);
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="chemical-costs-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
          >
            <FlaskConical size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              Chemical Costs
            </h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Per-unit material cost the Job Costing view uses when computing margin.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface, background: colors.surface }}
            data-testid="chemical-costs-refresh"
          >
            <RefreshCw size={12} /> Refresh
          </button>
          <button
            type="button"
            onClick={reseed}
            disabled={reseeding}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
            style={{
              background: colors.surface, color: colors.brand,
              border: `1px solid ${colors.brand}`,
              cursor: reseeding ? "wait" : "pointer",
            }}
            data-testid="chemical-costs-reseed"
          >
            <RotateCcw size={12} /> Restore missing defaults
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl p-3 mb-4 text-sm inline-flex items-center gap-2"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="chemical-costs-error">
          <AlertTriangle size={14} /> {error}
        </div>
      ) : null}

      {toast ? (
        <div className="rounded-md p-2 mb-4 text-xs font-semibold"
             style={{ background: "#DCFCE7", border: "1px solid #86EFAC", color: "#166534" }}
             data-testid="chemical-costs-toast">
          {toast}
        </div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
          Loading…
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="chemical-costs-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <th className="text-left px-4 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>
                    Chemical
                  </th>
                  <th className="text-left px-4 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>
                    Unit
                  </th>
                  <th className="text-right px-4 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>
                    Cost per unit ($)
                  </th>
                  <th className="text-right px-4 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>
                    Updated
                  </th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-sm"
                        style={{ color: colors.muted }}
                        data-testid="chemical-costs-empty">
                      No chemicals yet — click "Restore missing defaults" above.
                    </td>
                  </tr>
                ) : (
                  rows.map((r) => {
                    const d = draft[r.chemical_slug] || {};
                    return (
                      <tr key={r.chemical_slug}
                          data-testid={`chemical-cost-row-${r.chemical_slug}`}
                          style={{ borderBottom: `1px solid ${colors.border}` }}>
                        <td className="px-4 py-2.5 font-semibold" style={{ color: colors.onSurface }}>
                          <input
                            type="text"
                            value={d.name || ""}
                            onChange={(e) => editRow(r.chemical_slug, { name: e.target.value })}
                            className="w-full px-2 py-1 rounded text-sm"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`chemical-cost-name-${r.chemical_slug}`}
                          />
                          <div className="text-[10px] mt-0.5 font-mono" style={{ color: colors.muted }}>
                            {r.chemical_slug}
                          </div>
                        </td>
                        <td className="px-4 py-2.5">
                          <select
                            value={d.unit_kind || ""}
                            onChange={(e) => editRow(r.chemical_slug, { unit_kind: e.target.value })}
                            className="px-2 py-1 rounded text-sm"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`chemical-cost-unit-${r.chemical_slug}`}
                          >
                            {UNIT_OPTIONS.map((u) => <option key={u} value={u}>{u}</option>)}
                            {d.unit_kind && !UNIT_OPTIONS.includes(d.unit_kind) ? (
                              <option value={d.unit_kind}>{d.unit_kind}</option>
                            ) : null}
                          </select>
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <div className="inline-flex items-center gap-1">
                            <span className="text-xs" style={{ color: colors.muted }}>$</span>
                            {/* PRICING-DECIMAL-INPUT-PARITY ·
                                Feb-2026 — see commit ``0f5e7886f``
                                for the full rationale.  Save button
                                in this row reads ``d.dollars`` LIVE
                                (``editRow`` writes on every
                                keystroke), so a shared
                                ``<DecimalInput>`` with its blur-
                                only onChange would race the Save
                                button and ship stale values. */}
                            <input
                              type="text"
                              inputMode="decimal"
                              pattern="[0-9]*[.,]?[0-9]*"
                              value={d.dollars || ""}
                              onChange={(e) => {
                                const v = e.target.value;
                                if (v !== "" && !/^\d*\.?\d*$/.test(v)) return;
                                editRow(r.chemical_slug, { dollars: v });
                              }}
                              className="w-24 px-2 py-1 rounded text-sm text-right"
                              style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                              data-testid={`chemical-cost-dollars-${r.chemical_slug}`}
                            />
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-right text-[11px]" style={{ color: colors.muted }}>
                          {r.updated_at ? new Date(r.updated_at).toLocaleDateString() : "—"}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <button
                            type="button"
                            onClick={() => saveRow(r.chemical_slug)}
                            disabled={saving === r.chemical_slug}
                            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-bold"
                            style={{
                              background: colors.brand, color: "#fff", border: 0,
                              cursor: saving === r.chemical_slug ? "wait" : "pointer",
                              opacity: saving === r.chemical_slug ? 0.6 : 1,
                            }}
                            data-testid={`chemical-cost-save-${r.chemical_slug}`}
                          >
                            <Save size={12} />
                            {saving === r.chemical_slug ? "Saving…" : "Save"}
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
