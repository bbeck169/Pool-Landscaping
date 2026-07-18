/**
 * Phase T1 + T2 — Pool Calculators (web).
 *
 * 5 stateless calculators (LSI, Volume, Salt, Turnover Compliance,
 * Heater Size) rendered as a tabbed panel. Every result has a copy
 * button that writes a plain-text summary to the clipboard so techs
 * can paste into a customer note or a service report.
 *
 * RBAC: web route is available to techs + admins via ToolsHub link.
 * The backend endpoints enforce role via `require_tech_or_above` so
 * customers get 403 on direct hits regardless of the UI.
 */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Calculator, FlaskConical, Ruler, Droplets,
  Timer, Flame, Copy, CheckCircle2, AlertTriangle,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const TABS = [
  { key: "lsi",       label: "LSI",              icon: FlaskConical },
  { key: "volume",    label: "Pool Volume",      icon: Ruler },
  { key: "salt",      label: "Salt",             icon: Droplets },
  { key: "turnover",  label: "Turnover",         icon: Timer },
  { key: "heater",    label: "Heater Size",      icon: Flame },
];

function copyResult(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text);
}

function Field({ label, value, onChange, unit, type = "number", testid, placeholder = "0" }) {
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
        {unit ? (
          <span className="text-xs font-semibold"
                style={{ color: colors.muted }}>{unit}</span>
        ) : null}
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
                       border: `1px solid ${colors.border}`,
                       color: colors.onSurface }}
              data-testid={testid}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

function ResultBox({ tone = "brand", title, value, note, extra, testid }) {
  const [attached, setAttached] = useState(null);
  const bg = tone === "success" ? "#DCFCE7"
    : tone === "warning" ? "#FEF3C7"
    : tone === "error" ? "#FEE2E2"
    : `${colors.brand}10`;
  const fg = tone === "success" ? "#166534"
    : tone === "warning" ? "#92400E"
    : tone === "error" ? "#991B1B"
    : colors.brand;
  const Icon = tone === "success" ? CheckCircle2
    : (tone === "warning" || tone === "error") ? AlertTriangle
    : Calculator;
  const summary = `${title}: ${value} — ${note || ""}`;

  const attach = async () => {
    try {
      const r = await api.post("/service-report/attach-note", { text: summary });
      if (r?.status === "attached") {
        setAttached({ ok: true, msg: "Attached to service report ✓" });
      } else if (r?.status === "multiple_open_reports") {
        setAttached({ ok: false, msg: `Multiple open reports (${r.reports.length}) — open a job and try again.` });
      } else {
        setAttached({ ok: false, msg: "Not attached." });
      }
    } catch (e) {
      const m = String(e?.message || "");
      if (m.includes("404")) setAttached({ ok: false, msg: "No open service report — start a job first." });
      else setAttached({ ok: false, msg: m || "Attach failed." });
    }
    setTimeout(() => setAttached(null), 5000);
  };

  return (
    <div className="rounded-xl p-4 flex items-start gap-3 mt-4"
         style={{ backgroundColor: bg }}
         data-testid={testid}>
      <Icon size={20} style={{ color: fg, flexShrink: 0 }} />
      <div className="flex-1">
        <div className="text-xs font-bold uppercase tracking-wider"
             style={{ color: fg }}>{title}</div>
        <div className="text-2xl font-bold mt-1"
             style={{ color: fg }}>{value}</div>
        {note ? (
          <div className="text-sm mt-2" style={{ color: fg }}>{note}</div>
        ) : null}
        {extra}
        {attached ? (
          <div className="text-xs mt-2 font-semibold"
               style={{ color: attached.ok ? "#166534" : "#991B1B" }}
               data-testid={`${testid}-attach-status`}>
            {attached.msg}
          </div>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <button onClick={() => copyResult(summary)}
                className="text-xs font-semibold rounded-lg px-2 py-1 flex items-center gap-1"
                style={{ backgroundColor: `${fg}22`, color: fg }}
                data-testid={`${testid}-copy`}>
          <Copy size={12} /> Copy
        </button>
        <button onClick={attach}
                className="text-xs font-semibold rounded-lg px-2 py-1 flex items-center gap-1"
                style={{ backgroundColor: `${fg}22`, color: fg }}
                data-testid={`${testid}-attach`}
                title="Attach to open service report">
          + Attach
        </button>
      </div>
    </div>
  );
}

function CalcCard({ tab, children }) {
  const Icon = tab.icon;
  return (
    <div className="rounded-2xl p-6"
         style={{ backgroundColor: colors.surface,
                   border: `1px solid ${colors.border}` }}
         data-testid={`calc-panel-${tab.key}`}>
      <div className="flex items-center gap-2 mb-4">
        <Icon size={20} style={{ color: colors.brand }} />
        <h2 className="text-xl font-bold"
            style={{ color: colors.onSurface }}>{tab.label}</h2>
      </div>
      {children}
    </div>
  );
}

// ─── LSI ─────────────────────────────────────────────────────────────
function LsiPanel({ tab }) {
  const [ph, setPh] = useState("7.4");
  const [temp, setTemp] = useState("80");
  const [ch, setCh] = useState("300");
  const [ta, setTa] = useState("100");
  const [tds, setTds] = useState("500");
  const [cya, setCya] = useState("");
  const [corr, setCorr] = useState("third");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/lsi", {
        ph: parseFloat(ph), temp_f: parseFloat(temp),
        ch: parseFloat(ch), ta: parseFloat(ta),
        tds: parseFloat(tds) || 1000,
        cya: cya ? parseFloat(cya) : null,
        cya_correction: corr,
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  const tone = result?.interpretation === "balanced" ? "success"
    : result?.interpretation === "scaling" ? "warning"
    : result?.interpretation === "corrosive" ? "error" : "brand";

  return (
    <CalcCard tab={tab}>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Field label="pH" value={ph} onChange={setPh} testid="lsi-ph" />
        <Field label="Water temp" unit="°F" value={temp} onChange={setTemp} testid="lsi-temp" />
        <Field label="Calcium hardness" unit="ppm" value={ch} onChange={setCh} testid="lsi-ch" />
        <Field label="Total alkalinity" unit="ppm" value={ta} onChange={setTa} testid="lsi-ta" />
        <Field label="TDS" unit="ppm" value={tds} onChange={setTds} testid="lsi-tds" />
        <Field label="CYA (optional)" unit="ppm" value={cya} onChange={setCya} testid="lsi-cya" />
        <Select label="CYA correction" value={corr} onChange={setCorr}
                options={[{value: "third", label: "− ⅓ CYA"},
                           {value: "quarter", label: "− ¼ CYA"},
                           {value: "none", label: "None"}]}
                testid="lsi-corr" />
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="lsi-compute">Compute LSI</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <ResultBox tone={tone} testid="lsi-result"
                    title="Saturation Index (LSI)"
                    value={result.lsi.toFixed(2)}
                    note={result.note} />
      ) : null}
    </CalcCard>
  );
}

// ─── Volume ──────────────────────────────────────────────────────────
function VolumePanel({ tab }) {
  const [shape, setShape] = useState("rectangle");
  const [length, setLength] = useState("20");
  const [width, setWidth] = useState("40");
  const [radius, setRadius] = useState("15");
  const [avgDepth, setAvgDepth] = useState("5");
  const [shallow, setShallow] = useState("");
  const [deep, setDeep] = useState("");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const body = {
        shape,
        length: (shape !== "circle") ? parseFloat(length) || null : null,
        width: (shape !== "circle") ? parseFloat(width) || null : null,
        radius: (shape === "circle") ? parseFloat(radius) || null : null,
        avg_depth: avgDepth ? parseFloat(avgDepth) : null,
        shallow_depth: shallow ? parseFloat(shallow) : null,
        deep_depth: deep ? parseFloat(deep) : null,
      };
      const r = await api.post("/calculators/volume", body);
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  return (
    <CalcCard tab={tab}>
      <Select label="Shape" value={shape} onChange={setShape}
              options={[
                {value: "rectangle", label: "Rectangle"},
                {value: "oval", label: "Oval"},
                {value: "circle", label: "Circle"},
                {value: "freeform", label: "Freeform"},
              ]}
              testid="vol-shape" />
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-3">
        {shape === "circle" ? (
          <Field label="Radius" unit="ft" value={radius} onChange={setRadius} testid="vol-radius" />
        ) : (
          <>
            <Field label="Length" unit="ft" value={length} onChange={setLength} testid="vol-length" />
            <Field label="Width" unit="ft" value={width} onChange={setWidth} testid="vol-width" />
          </>
        )}
        <Field label="Average depth" unit="ft" value={avgDepth} onChange={setAvgDepth} testid="vol-avgdepth" />
        <Field label="Shallow (optional)" unit="ft" value={shallow} onChange={setShallow} testid="vol-shallow" />
        <Field label="Deep (optional)" unit="ft" value={deep} onChange={setDeep} testid="vol-deep" />
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="vol-compute">Compute volume</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <ResultBox testid="vol-result"
                    title="Estimated volume"
                    value={`${result.gallons.toLocaleString()} gal`}
                    note={`${result.formula} · shape: ${result.shape}`} />
      ) : null}
    </CalcCard>
  );
}

// ─── Salt ────────────────────────────────────────────────────────────
function SaltPanel({ tab }) {
  const [gal, setGal] = useState("20000");
  const [cur, setCur] = useState("2500");
  const [tgt, setTgt] = useState("3200");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/salt", {
        pool_gallons: parseFloat(gal),
        current_salt: parseFloat(cur),
        target_salt: parseFloat(tgt),
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  return (
    <CalcCard tab={tab}>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Field label="Pool volume" unit="gal" value={gal} onChange={setGal} testid="salt-gal" />
        <Field label="Current salt" unit="ppm" value={cur} onChange={setCur} testid="salt-cur" />
        <Field label="Target salt" unit="ppm" value={tgt} onChange={setTgt} testid="salt-tgt" />
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="salt-compute">Compute salt</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <ResultBox tone={result.lbs_to_add > 0 ? "brand" : "success"}
                    testid="salt-result"
                    title="Salt to add"
                    value={result.lbs_to_add > 0
                              ? `${result.lbs_to_add} lbs (${result.bags_40lb} × 40-lb)`
                              : "At/above target"}
                    note={result.note} />
      ) : null}
    </CalcCard>
  );
}

// ─── Turnover ────────────────────────────────────────────────────────
function TurnoverPanel({ tab }) {
  const [gal, setGal] = useState("20000");
  const [gpm, setGpm] = useState("60");
  const [ptype, setPtype] = useState("residential");
  const [depth, setDepth] = useState("");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/turnover", {
        pool_gallons: parseFloat(gal),
        pump_gpm: parseFloat(gpm),
        pool_type: ptype,
        depth_ft: depth ? parseFloat(depth) : null,
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  const tone = result?.compliant === true ? "success"
    : result?.compliant === false ? "error" : "brand";

  return (
    <CalcCard tab={tab}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Pool volume" unit="gal" value={gal} onChange={setGal} testid="turn-gal" />
        <Field label="Pump flow" unit="GPM" value={gpm} onChange={setGpm} testid="turn-gpm" />
        <Select label="Pool type" value={ptype} onChange={setPtype}
                options={[
                  {value: "residential", label: "Residential"},
                  {value: "commercial", label: "Commercial"},
                  {value: "spa", label: "Spa"},
                ]}
                testid="turn-type" />
        {ptype === "commercial" ? (
          <Field label="Depth" unit="ft" value={depth} onChange={setDepth} testid="turn-depth" />
        ) : null}
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="turn-compute">Compute turnover</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <ResultBox tone={tone} testid="turn-result"
                    title="Turnover time"
                    value={`${result.turnover_hours} hours`}
                    note={`${result.code_standard} · ${result.note}`} />
      ) : null}
    </CalcCard>
  );
}

// ─── Heater ──────────────────────────────────────────────────────────
function HeaterPanel({ tab }) {
  const [gal, setGal] = useState("20000");
  const [cur, setCur] = useState("60");
  const [tgt, setTgt] = useState("82");
  const [amb, setAmb] = useState("70");
  const [area, setArea] = useState("800");
  const [htype, setHtype] = useState("gas");
  const [hup, setHup] = useState("24");
  const [therm, setTherm] = useState("1.50");
  const [kwh, setKwh] = useState("0.15");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const compute = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/heater-size", {
        pool_gallons: parseFloat(gal),
        current_temp: parseFloat(cur),
        target_temp: parseFloat(tgt),
        avg_ambient: parseFloat(amb),
        surface_area: parseFloat(area),
        heater_type: htype,
        heat_up_hours: parseFloat(hup) || 24,
        per_therm: parseFloat(therm) || 1.5,
        per_kwh: parseFloat(kwh) || 0.15,
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  return (
    <CalcCard tab={tab}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Pool volume" unit="gal" value={gal} onChange={setGal} testid="heat-gal" />
        <Field label="Current temp" unit="°F" value={cur} onChange={setCur} testid="heat-cur" />
        <Field label="Target temp" unit="°F" value={tgt} onChange={setTgt} testid="heat-tgt" />
        <Field label="Avg ambient" unit="°F" value={amb} onChange={setAmb} testid="heat-amb" />
        <Field label="Surface area" unit="sqft" value={area} onChange={setArea} testid="heat-area" />
        <Field label="Heat-up hours" value={hup} onChange={setHup} testid="heat-hup" />
        <Select label="Heater type" value={htype} onChange={setHtype}
                options={[
                  {value: "gas", label: "Gas"},
                  {value: "heat_pump", label: "Heat pump"},
                  {value: "electric", label: "Electric resistance"},
                  {value: "solar", label: "Solar"},
                ]}
                testid="heat-type" />
      </div>
      <div className="grid grid-cols-2 gap-3 mt-3">
        <Field label="$/therm (gas)" value={therm} onChange={setTherm} testid="heat-per-therm" />
        <Field label="$/kWh (elec)" value={kwh} onChange={setKwh} testid="heat-per-kwh" />
      </div>
      <button onClick={compute}
              className="mt-4 w-full py-2 rounded-xl font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="heat-compute">Compute heater</button>
      {err ? <div className="mt-3 text-sm" style={{ color: "#991B1B" }}>{err}</div> : null}
      {result ? (
        <ResultBox testid="heat-result"
                    title="Required BTU/hr"
                    value={result.btu_required.toLocaleString()}
                    note={`ΔT ${result.delta_t}°F · Est. monthly cost $${result.monthly_cost}`}
                    extra={
                      <ul className="mt-2 space-y-1 text-xs" style={{ color: colors.brand }}>
                        {(result.notes || []).map((n, i) => (
                          <li key={i}>• {n}</li>
                        ))}
                      </ul>
                    } />
      ) : null}
    </CalcCard>
  );
}

export default function PoolCalculators() {
  const nav = useNavigate();
  const [tab, setTab] = useState("lsi");
  const Panel = { lsi: LsiPanel, volume: VolumePanel, salt: SaltPanel,
                   turnover: TurnoverPanel, heater: HeaterPanel }[tab];
  const tabDef = TABS.find((t) => t.key === tab);

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="pool-calculators-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/tech/tools")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="calc-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Calculator size={22} style={{ color: colors.brand }} />
            Pool Calculators
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Chemistry &amp; sizing math — LSI, volume, salt, turnover code compliance, heater sizing.
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
                    data-testid={`calc-tab-${t.key}`}>
              <Icon size={14} /> {t.label}
            </button>
          );
        })}
      </div>

      <Panel tab={tabDef} />
    </div>
  );
}
