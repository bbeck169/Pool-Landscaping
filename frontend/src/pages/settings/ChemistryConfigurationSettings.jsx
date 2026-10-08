/**
 * Sprint 3b · Feb-2026 · Chemistry Configuration settings tab.
 *
 * Admin-only sidebar tab in SettingsHub. Two sections:
 *   1. Target Ranges — 6 chemicals, min/max editable, unit rendered
 *      from the API's ``targets[key].unit``.
 *   2. Gate Mode — strict / warn_only / off radio.
 *   3. Dosing Formulas — collapsible; per-formula editor +
 *      "Test formula" button that hits /chemistry/dose/preview.
 *
 * Backend:
 *   GET/PATCH /api/tenants/mine/settings/chemistry
 *   GET/PATCH /api/tenants/mine/settings/chemistry/dosing-formulas
 *   POST      /api/chemistry/dose/preview
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Beaker, ShieldAlert, ShieldCheck, ShieldOff, ChevronRight, ChevronDown,
  Play, Save,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";

const CHEMICAL_ROWS = [
  // Phase P17.2 · Feb-2026 — display-label unification.
  { key: "chlorine",         label: "Chlorine",         step: 0.1 },
  { key: "ph",               label: "pH",               step: 0.1 },
  { key: "alkalinity",       label: "Alkalinity",       step: 5   },
  { key: "cyanuric_acid",    label: "Cyanuric Acid",    step: 5   },
  { key: "calcium_hardness", label: "Calcium Hardness", step: 25  },
  { key: "salt",             label: "Salt",             step: 50  },
];

const FORMULA_ROWS = [
  // Phase P17.2 · Feb-2026 — display-label unification.
  { key: "chlorine",            label: "Chlorine (liquid)" },
  { key: "ph_up",               label: "pH Up (Soda Ash)" },
  { key: "ph_down",             label: "pH Down (Muriatic Acid)" },
  { key: "alkalinity_up",       label: "Alkalinity Up (Sodium Bicarb)" },
  { key: "cyanuric_acid_up",    label: "Cyanuric Acid Up" },
  { key: "calcium_hardness_up", label: "Calcium Hardness Up" },
  { key: "salt_up",             label: "Salt Up" },
];

const GATE_MODES = [
  { value: "strict",
    label: "Strict",
    hint: "Block submit if any Required Four reading is missing (current default).",
    Icon: ShieldCheck,
    color: "#10B981" },
  { value: "warn_only",
    label: "Warn only",
    hint: "Allow submit even with missing readings; log a warning + attach warnings[] on the response.",
    Icon: ShieldAlert,
    color: "#F59E0B" },
  { value: "off",
    label: "Off",
    hint: "Skip the chemistry gate entirely on submit.",
    Icon: ShieldOff,
    color: "#EF4444" },
];


export default function ChemistryConfigurationSettings() {
  const { user } = useAuth() || {};
  const isAdmin = ["admin", "super_admin"].includes(
    (user?.role || "").toLowerCase(),
  );
  const [cfg, setCfg] = useState(null);
  const [drafts, setDrafts] = useState({});  // {key: {min, max}}
  const [busy, setBusy] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const [formulasOpen, setFormulasOpen] = useState(false);
  const [formulaCfg, setFormulaCfg] = useState(null);
  const [formulaDrafts, setFormulaDrafts] = useState({});
  const [formulaErr, setFormulaErr] = useState({});
  const [previewResults, setPreviewResults] = useState({});

  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/mine/settings/chemistry");
      setCfg(r || {});
      const nextDrafts = {};
      for (const row of CHEMICAL_ROWS) {
        const t = r?.targets?.[row.key] || {};
        nextDrafts[row.key] = { min: t.min ?? "", max: t.max ?? "" };
      }
      setDrafts(nextDrafts);
      setLoadErr("");
    } catch (e) {
      setLoadErr(e?.message || "Failed to load chemistry settings");
    }
  }, []);

  const loadFormulas = useCallback(async () => {
    try {
      const r = await api.get(
        "/tenants/mine/settings/chemistry/dosing-formulas",
      );
      setFormulaCfg(r || {});
      const nextDrafts = {};
      for (const row of FORMULA_ROWS) {
        nextDrafts[row.key] = r?.formulas?.[row.key]?.tenant_formula || "";
      }
      setFormulaDrafts(nextDrafts);
      setFormulaErr({});
    } catch (e) {
      setFormulaErr({ _load: e?.message || "Failed to load formulas" });
    }
  }, []);

  useEffect(() => { if (isAdmin) load(); }, [load, isAdmin]);
  useEffect(() => {
    if (isAdmin && formulasOpen && !formulaCfg) loadFormulas();
  }, [isAdmin, formulasOpen, formulaCfg, loadFormulas]);

  const saveTarget = async (key) => {
    if (!cfg || busy) return;
    const draft = drafts[key] || {};
    const payload = {
      targets: {
        [key]: { min: Number(draft.min), max: Number(draft.max) },
      },
    };
    setBusy(key);
    try {
      const r = await api.patch(
        "/tenants/mine/settings/chemistry", payload,
      );
      setCfg(r || {});
      toast.success(`${labelFor(key)} target saved`);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.body?.detail;
      const msg = (typeof detail === "object" ? detail?.message : null)
                    || e?.message || `Failed to save ${labelFor(key)}`;
      toast.error(msg);
    } finally {
      setBusy(null);
    }
  };

  const setGateMode = async (mode) => {
    if (!cfg || busy) return;
    setBusy("gate_mode");
    const prev = cfg.gate_mode;
    setCfg((s) => ({ ...s, gate_mode: mode }));
    try {
      const r = await api.patch(
        "/tenants/mine/settings/chemistry", { gate_mode: mode },
      );
      setCfg(r || {});
      toast.success(`Gate mode set to ${mode}`);
    } catch (e) {
      setCfg((s) => ({ ...s, gate_mode: prev }));
      toast.error(e?.message || "Failed to update gate mode");
    } finally {
      setBusy(null);
    }
  };

  const saveFormula = async (key) => {
    if (!formulaCfg || busy) return;
    const formula = formulaDrafts[key] ?? "";
    setBusy(`formula-${key}`);
    setFormulaErr((s) => ({ ...s, [key]: null }));
    try {
      const r = await api.patch(
        "/tenants/mine/settings/chemistry/dosing-formulas",
        { [key]: formula },
      );
      setFormulaCfg(r || {});
      toast.success(`${labelForFormula(key)} formula saved`);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.body?.detail;
      const err = (typeof detail === "object" ? detail?.error : null)
                    || (typeof detail === "object" ? detail?.message : null)
                    || e?.message || "invalid formula";
      setFormulaErr((s) => ({ ...s, [key]: err }));
      toast.error(err);
    } finally {
      setBusy(null);
    }
  };

  const testFormula = async (key) => {
    if (!formulaCfg || busy) return;
    const formula = formulaDrafts[key] ?? "";
    setBusy(`preview-${key}`);
    setFormulaErr((s) => ({ ...s, [key]: null }));
    try {
      // Synthetic reading — deliberately low so every "up" formula
      // returns a positive dose the admin can eyeball.
      const chem = key === "ph_down" ? "ph_down" : key;
      const current = key === "ph_down" ? 8.0
                    : key === "ph_up"   ? 7.0
                    : key === "chlorine" ? 1.0
                    : key === "alkalinity_up" ? 60
                    : key === "cyanuric_acid_up" ? 20
                    : key === "calcium_hardness_up" ? 150
                    : 2400;  // salt
      const r = await api.post(
        "/chemistry/dose/preview",
        { chemical: chem, current, volume_gallons: 10000, formula: formula || null },
      );
      setPreviewResults((s) => ({ ...s, [key]: r }));
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.body?.detail;
      const err = (typeof detail === "object" ? detail?.error : null)
                    || (typeof detail === "object" ? detail?.message : null)
                    || e?.message || "formula error";
      setFormulaErr((s) => ({ ...s, [key]: err }));
      setPreviewResults((s) => ({ ...s, [key]: null }));
    } finally {
      setBusy(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="rounded-2xl p-6"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="chemistry-config-forbidden">
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Admin access required
        </div>
        <div className="text-xs mt-1" style={{ color: colors.muted }}>
          Only admins can view or change chemistry configuration.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl p-5 space-y-5"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="chemistry-config-card">
      <div>
        <h2 className="text-lg font-semibold"
             style={{ color: colors.onSurface }}
             data-testid="chemistry-config-title">
          Chemistry Configuration
        </h2>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          Set the target ranges each chemical must fall within, choose
          how strictly the chemistry gate enforces them at submit, and
          (optionally) author custom dosing formulas.
        </p>
      </div>

      {loadErr ? (
        <div className="rounded-lg px-3 py-2 text-sm"
              style={{ background: "#FEF2F2", color: "#991B1B",
                        border: "1px solid #FECACA" }}
              data-testid="chemistry-config-error">
          {loadErr}
        </div>
      ) : null}

      {!cfg && !loadErr ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="chemistry-config-loading">
          Loading…
        </div>
      ) : null}

      {cfg ? (
        <>
          {/* Target ranges */}
          <section className="space-y-3" data-testid="chemistry-targets-section">
            <div className="flex items-center gap-2">
              <Beaker size={16} style={{ color: colors.brand }} />
              <div className="text-sm font-semibold"
                    style={{ color: colors.onSurface }}>
                Target Ranges
              </div>
            </div>
            <div className="divide-y" style={{ borderColor: colors.border }}>
              {CHEMICAL_ROWS.map(({ key, label, step }) => {
                const t = cfg.targets?.[key] || {};
                const draft = drafts[key] || {};
                const dirty = String(draft.min) !== String(t.min ?? "")
                           || String(draft.max) !== String(t.max ?? "");
                const outer = cfg.outer_bounds?.[key] || [0, 0];
                return (
                  <div key={key}
                        className="py-3"
                        data-testid={`chem-target-row-${key}`}>
                    <div className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold"
                              style={{ color: colors.onSurface }}>
                          {label}
                          {t.unit ? (
                            <span className="text-xs font-normal ml-2"
                                    style={{ color: colors.muted }}>
                              ({t.unit})
                            </span>
                          ) : null}
                        </div>
                        <div className="text-[11px]"
                              style={{ color: colors.muted }}>
                          Allowed range: {outer[0]}–{outer[1]}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs"
                                style={{ color: colors.muted }}>Min</label>
                        {/* CHECKLIST-DECIMAL-INPUT-FIX · ChemistryConfigurationSettings
                            sweep · Feb-2026 — the pre-fix shape rendered the raw
                            HTML5 ``number`` input which (per spec) made Chrome /
                            Firefox / iOS Safari return ``e.target.value === ""`` for
                            intermediate decimal states like ``"7."``. The onChange
                            wrote that blank straight into the ``drafts`` state, so
                            tenants could not set a target like pH 7.4 — only pH 7
                            or 8. Switch to ``type="text"`` + ``inputMode="decimal"``
                            + keystroke regex guard, mirroring the CustomerChemistry
                            AI Dosing fix (commit ``43a9f7bcf``). Using the pattern
                            inline (not ``<DecimalInput>``) because the parent
                            ``dirty`` flag + Save button enablement rely on LIVE
                            per-keystroke updates to ``drafts[key].min/max`` —
                            ``<DecimalInput>``'s blur-only commit would strand the
                            Save button disabled until the input lost focus. The
                            ``step`` attribute is kept because screen readers surface
                            it as "increment hint" even on text-mode inputs. */}
                        <input
                          type="text"
                          inputMode="decimal"
                          pattern="[0-9]*[.,]?[0-9]*"
                          step={step}
                          value={draft.min ?? ""}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v !== "" && !/^\d*\.?\d*$/.test(v)) return;
                            setDrafts((s) => ({
                              ...s, [key]: { ...s[key], min: v },
                            }));
                          }}
                          className="w-24 px-2 py-1 rounded-lg text-sm"
                          style={{ background: colors.surfaceSecondary,
                                    border: `1px solid ${colors.border}`,
                                    color: colors.onSurface }}
                          data-testid={`chem-target-min-${key}`}
                        />
                        <label className="text-xs"
                                style={{ color: colors.muted }}>Max</label>
                        <input
                          type="text"
                          inputMode="decimal"
                          pattern="[0-9]*[.,]?[0-9]*"
                          step={step}
                          value={draft.max ?? ""}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v !== "" && !/^\d*\.?\d*$/.test(v)) return;
                            setDrafts((s) => ({
                              ...s, [key]: { ...s[key], max: v },
                            }));
                          }}
                          className="w-24 px-2 py-1 rounded-lg text-sm"
                          style={{ background: colors.surfaceSecondary,
                                    border: `1px solid ${colors.border}`,
                                    color: colors.onSurface }}
                          data-testid={`chem-target-max-${key}`}
                        />
                        <button
                          type="button"
                          onClick={() => saveTarget(key)}
                          disabled={!dirty || busy === key}
                          className="inline-flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-bold"
                          style={{ background: dirty ? colors.brand : "#E5E7EB",
                                    color: dirty ? "#fff" : "#6B7280",
                                    opacity: busy === key ? 0.6 : 1 }}
                          data-testid={`chem-target-save-${key}`}
                        >
                          <Save size={12} /> Save
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Gate mode */}
          <section className="space-y-2 pt-2"
                    data-testid="chemistry-gate-mode-section">
            <div className="text-sm font-semibold"
                  style={{ color: colors.onSurface }}>
              Chemistry Gate Mode
            </div>
            <p className="text-xs" style={{ color: colors.muted }}>
              Controls how strictly the submit endpoint enforces the
              Required Four chemistry readings on pool jobs.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {GATE_MODES.map(({ value, label, hint, Icon, color }) => {
                const isOn = cfg.gate_mode === value;
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setGateMode(value)}
                    disabled={busy === "gate_mode"}
                    className="text-left rounded-lg p-3 transition-colors"
                    style={{
                      background: isOn ? "rgba(2,132,199,0.08)" : colors.surfaceSecondary,
                      border: `1px solid ${isOn ? colors.brand : colors.border}`,
                      color: colors.onSurface,
                      cursor: busy === "gate_mode" ? "wait" : "pointer",
                    }}
                    data-testid={`chem-gate-mode-${value}`}
                    data-active={isOn ? "1" : "0"}
                  >
                    <div className="flex items-center gap-2">
                      <Icon size={16} style={{ color }} />
                      <div className="text-sm font-semibold">{label}</div>
                    </div>
                    <div className="text-[11px] mt-1"
                          style={{ color: colors.muted }}>
                      {hint}
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Formulas collapsible */}
          <section className="pt-2"
                    data-testid="chemistry-formulas-section">
            <button
              type="button"
              onClick={() => setFormulasOpen((s) => !s)}
              className="w-full flex items-center gap-2 text-sm font-semibold"
              style={{ color: colors.onSurface }}
              data-testid="chem-formulas-toggle"
              aria-expanded={formulasOpen}
            >
              {formulasOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              <span>Dosing Formulas (advanced)</span>
              <span className="text-xs font-normal ml-2"
                    style={{ color: colors.muted }}>
                — override the built-in dosing math per chemical
              </span>
            </button>
            {formulasOpen ? (
              <div className="mt-3 space-y-3">
                <div className="rounded-lg p-3 text-xs"
                      style={{ background: colors.surfaceSecondary,
                                border: `1px solid ${colors.border}`,
                                color: colors.muted }}
                      data-testid="chem-formulas-cheatsheet">
                  <div className="font-semibold mb-1"
                        style={{ color: colors.onSurface }}>
                    Formula cheat sheet
                  </div>
                  <div>
                    Available names:{" "}
                    <code>current</code>, <code>min_target</code>,{" "}
                    <code>max_target</code>, <code>avg_target</code>,{" "}
                    <code>volume_gallons</code>, <code>delta</code>
                  </div>
                  <div>
                    Functions: <code>abs</code>, <code>min</code>,{" "}
                    <code>max</code>, <code>round</code>
                  </div>
                  <div className="mt-1">
                    Example:{" "}
                    <code>max(0, (avg_target - current) * volume_gallons * 0.00013)</code>
                  </div>
                </div>
                {formulaErr._load ? (
                  <div className="rounded-lg px-3 py-2 text-sm"
                        style={{ background: "#FEF2F2", color: "#991B1B",
                                  border: "1px solid #FECACA" }}
                        data-testid="chem-formulas-load-error">
                    {formulaErr._load}
                  </div>
                ) : null}
                {!formulaCfg && !formulaErr._load ? (
                  <div className="text-sm"
                        style={{ color: colors.muted }}
                        data-testid="chem-formulas-loading">
                    Loading formulas…
                  </div>
                ) : null}
                {formulaCfg ? FORMULA_ROWS.map(({ key, label }) => {
                  const row = formulaCfg.formulas?.[key] || {};
                  const draft = formulaDrafts[key] ?? "";
                  const dirty = draft !== (row.tenant_formula ?? "");
                  const err = formulaErr[key];
                  const preview = previewResults[key];
                  return (
                    <div key={key}
                          className="rounded-lg p-3 space-y-2"
                          style={{ background: colors.surfaceSecondary,
                                    border: `1px solid ${colors.border}` }}
                          data-testid={`chem-formula-row-${key}`}>
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-semibold"
                              style={{ color: colors.onSurface }}>
                          {label}
                          {row.using_default ? (
                            <span className="text-[11px] ml-2"
                                    style={{ color: colors.muted }}>
                              using default
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <input
                        type="text"
                        value={draft}
                        onChange={(e) => setFormulaDrafts((s) => ({
                          ...s, [key]: e.target.value,
                        }))}
                        placeholder={row.default_formula || ""}
                        className="w-full px-2 py-2 rounded-lg text-xs font-mono"
                        style={{ background: colors.surface,
                                  border: `1px solid ${colors.border}`,
                                  color: colors.onSurface }}
                        data-testid={`chem-formula-input-${key}`}
                      />
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => testFormula(key)}
                          disabled={busy === `preview-${key}`}
                          className="inline-flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-bold"
                          style={{ background: "#F3F4F6",
                                    border: `1px solid ${colors.border}`,
                                    color: colors.onSurface,
                                    opacity: busy === `preview-${key}` ? 0.6 : 1 }}
                          data-testid={`chem-formula-test-${key}`}
                        >
                          <Play size={12} /> Test formula
                        </button>
                        <button
                          type="button"
                          onClick={() => saveFormula(key)}
                          disabled={!dirty || busy === `formula-${key}`}
                          className="inline-flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-bold"
                          style={{ background: dirty ? colors.brand : "#E5E7EB",
                                    color: dirty ? "#fff" : "#6B7280",
                                    opacity: busy === `formula-${key}` ? 0.6 : 1 }}
                          data-testid={`chem-formula-save-${key}`}
                        >
                          <Save size={12} /> Save
                        </button>
                        {preview && preview.evaluation_ok ? (
                          <span className="text-xs"
                                 style={{ color: "#059669" }}
                                 data-testid={`chem-formula-preview-${key}`}>
                            → {Number(preview.recommended_dose_oz).toFixed(2)}
                            {" "}({preview.source})
                          </span>
                        ) : null}
                      </div>
                      {err ? (
                        <div className="text-xs"
                              style={{ color: "#991B1B" }}
                              data-testid={`chem-formula-error-${key}`}>
                          {err}
                        </div>
                      ) : null}
                    </div>
                  );
                }) : null}
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </div>
  );
}


function labelFor(key) {
  const row = CHEMICAL_ROWS.find((r) => r.key === key);
  return row?.label || key;
}

function labelForFormula(key) {
  const row = FORMULA_ROWS.find((r) => r.key === key);
  return row?.label || key;
}
