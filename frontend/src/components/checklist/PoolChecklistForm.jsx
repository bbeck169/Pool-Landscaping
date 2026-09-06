/**
 * Phase 31 · Step 2b — PoolChecklistForm (web).
 *
 * Web mirror of the mobile PoolChecklistForm. All field shapes are
 * driven by the backend template returned by the bootstrap GET —
 * `chemical_reading_fields`, `chemicals_catalog`, `checklist_items`,
 * `chemical_units`. No hardcoded reading lists (per the Step 2b brief:
 * "reuse same endpoints from Step 1 discovery").
 *
 * "Analyze water photo": mirrors mobile — upload the image via
 * POST /api/jobs/{id}/photos to obtain a URL, then call
 * POST /api/service-report/analyze-water-photo. Renders the returned
 * overall_assessment / recommendations / issues. Does NOT auto-fill
 * numeric readings — the endpoint returns qualitative advice, not
 * numeric values. `mocked: true` payloads surface the `reason`
 * string verbatim.
 */
import React, { useRef, useState, useEffect, useMemo, useCallback } from "react";
import { AlertTriangle, CheckCircle2, FlaskConical, RefreshCw } from 'lucide-react';
import { api } from "@/api";
import { compressImageIfNeeded } from "../../lib/imageCompress";
import ChemicalDropdownStack, { snapRecommendationToPreset } from "./ChemicalDropdownStack";
// K60 · Feb-2026 — expand short-form chemistry labels (FC, TA, CYA, …)
// to full names on the display surface.  Data keys unchanged.  Kept in
// lockstep with mobile/src/lib/expandChemistryLabel.ts.
import { expandChemistryLabel } from "../../lib/expandChemistryLabel";

// Phase 48 — per-key validation rules for the manual-entry reading rows.
// Keys are normalized snake_case; aliases share the same rule.
const _READING_RULES = {
  free_chlorine:    { min: 0, max: 10,   decimals: 2, unit: "ppm" },
  total_chlorine:   { min: 0, max: 10,   decimals: 2, unit: "ppm" },
  chlorine:         { min: 0, max: 10,   decimals: 2, unit: "ppm" },
  ph:               { min: 0, max: 14,   decimals: 2, unit: "pH" },
  total_alkalinity: { min: 0, max: 500,  decimals: 1, unit: "ppm" },
  alkalinity:       { min: 0, max: 500,  decimals: 1, unit: "ppm" },
  cyanuric_acid:    { min: 0, max: 300,  decimals: 1, unit: "ppm" },
  cya:              { min: 0, max: 300,  decimals: 1, unit: "ppm" },
  salt:             { min: 0, max: 6000, decimals: 0, unit: "ppm" },
};
const _READING_DEFAULTS = {
  free_chlorine: 3, total_chlorine: 3, combined_chlorine: 0.5, chlorine: 3, tcl: 3,
  ph: 7.6, total_alkalinity: 100, alkalinity: 100,
  cyanuric_acid: 70, cya: 70,
};
// Phase 49.1 — keys whose "blank" state means "not typed yet" (not
// "not tested"). Users must explicitly toggle Not-tested for these rows.
const _DEFAULT_TESTED_KEYS = new Set([
  "free_chlorine", "total_chlorine", "combined_chlorine", "chlorine", "tcl",
  "ph",
  "total_alkalinity", "alkalinity",
  "cyanuric_acid", "cya",
]);

function _validateReading(rule, raw) {
  if (raw === "" || raw == null) return { value: null, invalid: false };
  if (!/^\d*\.?\d*$/.test(raw)) return { value: null, invalid: true };
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return { value: null, invalid: true };
  if (rule) {
    if (n < rule.min || n > rule.max) return { value: null, invalid: true };
    const dot = raw.indexOf(".");
    if (dot >= 0 && raw.length - dot - 1 > rule.decimals) return { value: null, invalid: true };
  }
  return { value: rule && rule.decimals === 0 ? Math.round(n) : n, invalid: false };
}

/** Phase 48 — Manual-entry reading row. Phase 49.1 — default-tested keys.
 *  Phase 50.C — inline 4-dot sparkline of `recent[]`. */
function ReadingInputRow({ testKey, reading, previous, recent, locked, onChange }) {
  const rule = _READING_RULES[testKey];
  const unit = reading.unit || (rule ? rule.unit : "");
  const hasValue = reading.value != null && reading.value !== "";
  const [manualNotTested, setManualNotTested] = React.useState(
    !hasValue && !_DEFAULT_TESTED_KEYS.has(testKey),
  );
  const notTested = manualNotTested;
  const [draft, setDraft] = useState(hasValue ? String(reading.value) : "");
  React.useEffect(() => {
    setDraft(hasValue ? String(reading.value) : "");
    if (hasValue) setManualNotTested(false);
  }, [reading.value, hasValue]);
  const { value, invalid } = _validateReading(rule, draft);
  const commit = () => {
    if (locked) return;
    if (draft === "") { onChange(null); return; }
    if (invalid) return;
    onChange(value);
  };

  // Phase 49.6 — recent median + outlier flag (was defined but ref'd in JSX
  // without being computed on web — Phase 50 fixes both problems).
  const recentArr = Array.isArray(recent) ? recent.filter((x) => Number.isFinite(x)) : []; // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: derived value stable-by-reference; downstream useMemo already tracks the real source deps
  const median = React.useMemo(() => {
    if (recentArr.length === 0) return null;
    const sorted = [...recentArr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }, [recentArr]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: memoized deps are stable by value; wrapping the source in its own useMemo would obscure the read
  const draftNum = Number(draft);
  const isOutlier = median != null && median > 0 && Number.isFinite(draftNum) && draftNum > 0
    && (draftNum > 2 * median || draftNum < 0.5 * median);

  return (
    <div
      data-testid={`pool-reading-${testKey}-slider`}
      className="border rounded-lg p-3"
      style={{ borderColor: colors.border, background: colors.surface, opacity: notTested ? 0.7 : 1 }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-bold uppercase tracking-wider inline-flex items-center gap-2" style={{ color: colors.onSurface }}>
          <span>{expandChemistryLabel(reading.name)}{reading.unit ? ` (${reading.unit})` : ""}</span>
          <ReadingSparkline recent={recentArr} median={median} testKey={testKey} />
        </span>
        <button
          type="button"
          disabled={locked}
          onClick={() => {
            if (notTested) {
              // Toggle OFF: return to tested state with empty input +
              // placeholder default.
              setManualNotTested(false);
              onChange(null);
            } else {
              // Toggle ON: mark not-tested + clear value.
              setManualNotTested(true);
              setDraft("");
              onChange(null);
            }
          }}
          data-testid={`pool-reading-${testKey}-not-tested`}
          className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-md"
          style={{
            border: `1px solid ${notTested ? colors.brand : colors.border}`,
            background: notTested ? colors.brandTertiary : colors.surface,
            color: notTested ? colors.brand : colors.muted,
            cursor: locked ? "not-allowed" : "pointer",
          }}
        >
          {notTested ? "Not tested" : "—"}
        </button>
      </div>
      <div className="flex items-center gap-2">
        <input
          type="number"
          inputMode="decimal"
          step={rule && rule.decimals === 0 ? "1" : (rule && rule.decimals === 1 ? "0.1" : "0.01")}
          min="0"
          disabled={locked || notTested}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
          placeholder={String(_READING_DEFAULTS[testKey] ?? "")}
          data-testid={`pool-reading-${testKey}-input`}
          className="flex-1 px-2 py-1.5 rounded-md text-sm font-semibold"
          style={{
            border: `${invalid ? 2 : 1}px solid ${invalid ? "#DC2626" : colors.border}`,
            background: (locked || notTested) ? colors.surfaceSecondary : colors.surface,
            color: (locked || notTested) ? colors.muted : colors.onSurface,
          }}
        />
        {unit ? (
          <span className="text-xs font-semibold min-w-[40px]"
                style={{ color: colors.muted }}
                data-testid={`pool-reading-${testKey}-unit`}>
            {unit}
          </span>
        ) : null}
      </div>
      {invalid ? (
        <div className="text-[11px] font-semibold mt-1" style={{ color: "#B91C1C" }}
             data-testid={`pool-reading-${testKey}-error`}>
          Value out of range{rule ? ` (${rule.min}–${rule.max}, ${rule.decimals}dp)` : ""}.
        </div>
      ) : null}
      {isOutlier ? (
        <div
          className="text-[11px] font-semibold mt-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded"
          style={{ background: "#FEF9C3", border: "1px solid #FDE68A", color: "#854D0E" }}
          data-testid={`pool-reading-${testKey}-recheck`}
        >
          ⚠ Recheck? Recent median {median} · you typed {draftNum}
        </div>
      ) : null}
      <div className="text-[10px] mt-2" style={{ color: colors.muted }}
           data-testid={`pool-reading-${testKey}-previous`}>
        Previously tested at: {previous
          ? `${previous.value}${reading.unit ? ` ${reading.unit}` : ""} · ${_fmtRel(previous.at)}`
          : "—"}
      </div>
    </div>
  );
}

// Phase 50.C — 4-dot inline sparkline of the most recent readings.
// Silent when we have fewer than 2 recent values. Green when the latest
// sample is within ±20% of the median, yellow when drifting, red on
// > 2× or < 0.5× outliers. Uses simple divs (no SVG chart lib).
function ReadingSparkline({ recent, median, testKey }) {
  const arr = Array.isArray(recent) ? recent.filter((x) => Number.isFinite(x)) : [];
  if (arr.length < 2 || !median) return null;
  const values = arr.slice(-4);
  const dots = [];
  for (let i = 0; i < 4; i += 1) {
    const val = values[i];
    let tone = "empty";
    if (Number.isFinite(val)) {
      const ratio = val / median;
      if (ratio > 2 || ratio < 0.5) tone = "red";
      else if (ratio > 1.2 || ratio < 0.8) tone = "yellow";
      else tone = "green";
    }
    const bg = tone === "green" ? "#22C55E"
      : tone === "yellow" ? "#F59E0B"
      : tone === "red" ? "#DC2626"
      : "#E2E8F0";
    dots.push(
      <span
        key={i}
        style={{
          width: 6, height: 6, borderRadius: 3, display: "inline-block",
          background: bg,
        }}
        data-testid={`pool-reading-${testKey}-sparkline-dot-${i}`}
        data-tone={tone}
      />
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 align-middle"
      data-testid={`pool-reading-${testKey}-sparkline`}
      title={`Recent: ${values.join(", ")} · median ${median}`}
    >
      {dots}
    </span>
  );
}

// Phase 37 — refined chip-scale defaults per reading key.
// Chlorine: 0.5 ppm increments up to 20. pH: 0.1 increments 6.0..8.5 with
// a "<6" sentinel chip. Alkalinity: 10 ppm increments 20..200. Temp:
// 5 °F increments. Filter PSI: 2.5 psi increments.
const _seqInc = (start, stop, step) => {
  const out = [];
  const n = Math.round((stop - start) / step) + 1;
  for (let i = 0; i < n; i += 1) {
    const v = start + i * step;
    // Fix float noise (0.30000000000000004) so testids stay stable.
    out.push(Number(v.toFixed(2)));
  }
  return out;
};
const _chlorineVals = _seqInc(0, 20, 0.5);           // 0, 0.5, ... 20
const _phVals = ["<6", ..._seqInc(6.0, 8.5, 0.1)];   // <6, 6.0, ... 8.5
const _alkVals = _seqInc(20, 200, 10);               // 20, 30, ... 200
const _tempVals = ["N/A", 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100];
const _psiVals  = ["N/A", 0, 2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 30];

// The "<6" chip stores as numeric 5.9 (backend accepts float; no schema
// change). isSelected matches any value < 6.0 so tapping stays honest.
const PH_UNDER_SIX_VALUE = 5.9;

const _cyaVals = ["N/A", ...Array.from({ length: 49 }, (_, i) => 20 + i * 10), ">500"];
// The ">500" chip stores as numeric 501; N/A stays null.
const CYA_OVER_500_VALUE = 501;

const CHIP_SCALES = {
  total_chlorine:    { values: _chlorineVals,    palette: "chlorine" },
  free_chlorine:     { values: _chlorineVals,    palette: "chlorine" },
  chlorine:          { values: _chlorineVals,    palette: "chlorine" },
  combined_chlorine: { values: _chlorineVals,    palette: "chlorine" },
  ph:                { values: _phVals,          palette: "ph" },
  alkalinity:        { values: _alkVals,         palette: "alkalinity" },
  total_alkalinity:  { values: _alkVals,         palette: "alkalinity" },
  cyanuric_acid:     { values: _cyaVals,         palette: "optional" },
  cya:               { values: _cyaVals,         palette: "optional" },
  calcium_hardness:  { values: ["N/A", 0, 100, 150, 200, 250, 300, 400, 500],     palette: "optional" },
  phosphate:         { values: ["N/A", 0, 125, 250, 500, 1000, 2500],             palette: "optional" },
  phosphates:        { values: ["N/A", 0, 125, 250, 500, 1000, 2500],             palette: "optional" },
  salt:              { values: ["N/A", 0, 1000, 2000, 2700, 3200, 3600, 4500],    palette: "optional" },
  tds:               { values: ["N/A", 0, 500, 1000, 1500, 2000, 3000],           palette: "optional" },
  water_temp:        { values: _tempVals,        palette: "optional" },
  temperature:       { values: _tempVals,        palette: "optional" },
  filter_psi:        { values: _psiVals,         palette: "optional" },
  psi:               { values: _psiVals,         palette: "optional" },
};

const _PALETTES = {
  chlorine:   { bg: "#cffafe", sel: "#0891b2", selFg: "#fff", fg: "#155e75" },
  ph:         { bg: "#fee2e2", sel: "#dc2626", selFg: "#fff", fg: "#7f1d1d",
                inRangeBg: "#dcfce7", inRangeSel: "#16a34a", inRangeFg: "#14532d" },
  alkalinity: { bg: "#dcfce7", sel: "#16a34a", selFg: "#fff", fg: "#14532d" },
  optional:   { bg: "#ffedd5", sel: "#ea580c", selFg: "#fff", fg: "#7c2d12" },
};

const _resolveScale = (r) => {
  const key = canonicalReadingKey(r);
  return CHIP_SCALES[key];
};

// Phase 37 — canonical testid key. Backend often uses shorter keys like
// `chlorine`, `alkalinity`, `cyanuric` while the tester expects the
// canonical `free_chlorine`, `total_alkalinity`, `cyanuric_acid`. Map
// via display name first, then fall back to a normalized version of
// whichever key came in.
const _NAME_TO_CANONICAL = {
  "free chlorine": "free_chlorine",
  "total chlorine": "total_chlorine",
  "combined chlorine": "combined_chlorine",
  "chlorine": "free_chlorine",
  "ph": "ph",
  "ph level": "ph",
  "total alkalinity": "total_alkalinity",
  "alkalinity": "total_alkalinity",
  "calcium hardness": "calcium_hardness",
  "cyanuric acid": "cyanuric_acid",
  "cya": "cyanuric_acid",
  "cyanuric": "cyanuric_acid",
  "salt": "salt",
  "total dissolved solids": "tds",
  "tds": "tds",
  "phosphates": "phosphates",
  "phosphate": "phosphates",
  "water temp": "water_temp",
  "water temperature": "water_temp",
  "temperature": "water_temp",
  "filter psi": "filter_psi",
  "psi": "filter_psi",
};
function canonicalReadingKey(r) {
  const name = String(r?.name || "").toLowerCase().trim();
  if (_NAME_TO_CANONICAL[name]) return _NAME_TO_CANONICAL[name];
  const rawKey = String(r?.key || r?.name || "").toLowerCase().trim();
  if (_NAME_TO_CANONICAL[rawKey]) return _NAME_TO_CANONICAL[rawKey];
  return rawKey.replace(/[\s()]+/g, "_").replace(/[^a-z0-9_]/g, "");
}

const _phSweet = (v) => typeof v === "number" && v >= 7.2 && v <= 7.6;

// Phase 37 — coerce a chip's array value into the numeric (or null)
// value that gets persisted. "N/A" → null, "<6" → 5.9, ">500" → 501,
// otherwise the number itself. Keeps the backend contract unchanged.
const _chipToValue = (v) => {
  if (v === "N/A") return null;
  if (v === "<6") return PH_UNDER_SIX_VALUE;
  if (v === ">500") return CYA_OVER_500_VALUE;
  return v;
};
const _isChipSelected = (chipRaw, current) => {
  if (chipRaw === "N/A") return current == null || current === "";
  if (chipRaw === "<6") return typeof current === "number" && current < 6.0;
  if (chipRaw === ">500") return typeof current === "number" && current > 500;
  return current != null && current !== "" && Number(current) === Number(chipRaw);
};

const _fmtRel = (iso) => {
  if (!iso) return "—";
  try {
    const d = typeof iso === "string" ? new Date(iso) : iso;
    const ms = Date.now() - d.getTime();
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const dd = Math.floor(h / 24);
    if (dd < 30) return `${dd}d ago`;
    return d.toLocaleDateString();
  } catch { return "—"; }
};


const colors = {
  brand: "#0EA5E9",
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#FFFFFF",
  surfaceAlt: "#F8FAFC",
  success: "#059669",
  successBg: "#D1FAE5",
  warnBg: "#FEF3C7",
  warnText: "#92400E",
  onSurface: "#0F172A",
};

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.readAsDataURL(file);
  });
}

export default function PoolChecklistForm({
  jobId,
  customerId,
  locked,
  readings = [],
  readingFields = [],
  chemicalsAdded = [],
  _chemicalsCatalog = [],
  chemicalUnits = ["gal", "lbs", "oz", "tabs"],
  checklistItems = [],
  notes = "",
  internalNotes = "",
  observations = {},
  onChange,
  // Phase 56.6 — when set (1..6), only render the section matching that
  // step. Unset ⇒ render everything (legacy single-scroll mode).
  wizardStep = null,
  // Feb-2026 · Checklist reclassifier — when the report's backend
  // template is ``generic`` AND ``readingFields`` is empty, render an
  // inline picker so the tech (or admin) can retag the job's
  // ``service_type`` and repopulate the chemistry section without
  // leaving the checklist. Callers that don't wire ``onReclassify`` opt
  // out; the section falls back to the legacy silent empty state.
  template = null,
  canEditServiceType = false,
  onReclassify = null,
}) {
  const [_analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [analyzeErr, setAnalyzeErr] = useState("");
  const analyzeRef = useRef(null);

  // Feb-2026 · Checklist reclassifier — busy flag flips true between
  // the picker tap and the parent's PATCH+refetch completing.
  const [reclassifyBusy, setReclassifyBusy] = useState(false);

  // Phase 46.5 — Web parity for mobile Quick-add sheet.
  const [_pickerOpen, _setPickerOpen] = useState(false);

  // Phase 34e — chemical dose recommendations state.
  const [recs, setRecs] = useState(null); // {recommendations, mocked, reason, source, pool_gallons}
  const [recsLoading, setRecsLoading] = useState(false);
  const [recsError, setRecsError] = useState("");

  // Phase 49.0 — Merge backend `chemical_reading_fields` (canonical field
  // list) with saved values so all default rows always render.
  const mergedReadings = React.useMemo(() => {
    if (!readingFields || readingFields.length === 0) return readings;
    const byKey = {};
    for (const r of readings || []) {
      const k = String(r.key || r.name || "").toLowerCase();
      if (k) byKey[k] = r;
    }
    const out = [];
    for (const f of readingFields) {
      const k = String(f.key || f.name || "").toLowerCase();
      const found = byKey[k];
      out.push({
        key: f.key || k,
        name: f.name || f.label || k,
        unit: f.unit,
        step: f.step,
        min: f.min,
        max: f.max,
        ...(found || { value: null }),
      });
      if (found) delete byKey[k];
    }
    for (const remaining of Object.values(byKey)) out.push(remaining);
    return out;
  }, [readingFields, readings]);

  const updReading = (idx, val) => {
    // Phase 37 — accept null (from "N/A"), numbers (from chips), or strings
    // (from the pencil-input popover). Coerce cleanly so we never store NaN.
    let nextVal;
    if (val === null || val === undefined || val === "") {
      nextVal = null;
    } else if (typeof val === "number") {
      nextVal = Number.isFinite(val) ? val : null;
    } else {
      const n = parseFloat(val);
      nextVal = Number.isFinite(n) ? n : null;
    }
    const next = mergedReadings.map((r, i) =>
      i === idx ? { ...r, value: nextVal } : r
    );
    onChange({ chemical_readings: next });
  };

  const _addChem = () => {
    const next = [
      ...chemicalsAdded,
      { id: Math.random().toString(36).slice(2), name: "", amount: "", unit: chemicalUnits[0] || "lbs" },
    ];
    onChange({ chemicals_added: next });
  };
  const _updChem = (idx, patch) => {
    const next = chemicalsAdded.map((c, i) => (i === idx ? { ...c, ...patch } : c));
    onChange({ chemicals_added: next });
  };
  const _rmChem = (idx) => {
    onChange({ chemicals_added: chemicalsAdded.filter((_, i) => i !== idx) });
  };

  const toggleCheck = (idx) => {
    const next = checklistItems.map((c, i) =>
      i === idx ? { ...c, checked: !c.checked } : c
    );
    onChange({ checklist_items: next });
  };

  // Phase 34e — build the readings dict from the current form state.
  const readingsDict = useMemo(() => {
    const acc = {};
    for (const r of readings) {
      const key = r.key || r.name;
      if (!key) continue;
      if (r.value != null && r.value !== "") acc[key] = r.value;
    }
    return acc;
  }, [readings]);

  const fetchRecommendations = useCallback(async () => {
    if (locked) return;
    setRecsLoading(true);
    setRecsError("");
    try {
      const res = await api.post("/service-report/recommend-chemicals", {
        job_id: jobId,
        readings: readingsDict,
        use_llm_phrasing: true,
        // Phase 56.10 — algae-remediation branch trigger.
        visible_algae: (observations?.visible_algae || "none"),
      });
      setRecs(res);
    } catch (e) {
      setRecsError(e?.message || "Could not fetch recommendations.");
    } finally {
      setRecsLoading(false);
    }
    // eslint-disable-next-line
  }, [jobId, readingsDict, locked, observations?.visible_algae]);

  // 800ms debounce after any reading change.
  useEffect(() => {
    if (locked) return;
    if (Object.keys(readingsDict).length === 0) {
      setRecs(null);
      return;
    }
    const h = setTimeout(fetchRecommendations, 800);
    return () => clearTimeout(h);
    // eslint-disable-next-line
  }, [readingsDict, locked]);

  const addChemFromRec = (rec) => {
    if (locked) return;
    // Phase 37 — snap the raw LLM quantity to the closest dropdown preset
    // for that chemical type. If no matching type is registered, fall back
    // to the old append-a-raw-row behaviour so the tech never loses the rec.
    const snapped = snapRecommendationToPreset(rec.chemical, rec.quantity);
    if (snapped) {
      const { type, option, snappedFrom } = snapped;
      const existingIdx = chemicalsAdded.findIndex(
        (c) => String(c?.chemical || c?.name || "").toLowerCase() === type.name.toLowerCase()
      );
      const entry = {
        chemical: type.name,
        name: type.name,
        quantity: option.quantity,
        amount: String(option.quantity),
        unit: type.unit,
        raw_label: option.label,
        source: "recommendation",
        reading_key: rec.reading_key,
        snapped_from: snappedFrom,
      };
      const next = [...chemicalsAdded];
      if (existingIdx >= 0) next[existingIdx] = { ...next[existingIdx], ...entry };
      else next.push(entry);
      onChange({ chemicals_added: next });
      return;
    }
    // Fallback — legacy path.
    const next = [
      ...chemicalsAdded,
      {
        id: Math.random().toString(36).slice(2),
        name: rec.chemical,
        chemical: rec.chemical,
        amount: String(rec.quantity ?? ""),
        quantity: rec.quantity,
        unit: rec.unit || (chemicalUnits[0] || "oz"),
        source: "recommendation",
        reading_key: rec.reading_key,
      },
    ];
    onChange({ chemicals_added: next });
  };

  // Phase 36 — previously-tested values per reading key (loaded once per
  // customer and refreshed if customerId changes).
  const [lastReadings, setLastReadings] = useState({});
  // Phase 49.6 — recent 4 values per key for the "Recheck?" outlier hint.
  const [recentReadings, setRecentReadings] = useState({});
  useEffect(() => {
    if (!customerId) return;
    let alive = true;
    api.get(`/service-reports/last-readings?customer_id=${customerId}`)
      .then((r) => {
        if (!alive) return;
        setLastReadings(r?.readings || {});
        setRecentReadings(r?.recent_readings || {});
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [customerId]);

  // Phase 36 — pencil-edit popover: `editingKey` is the reading `key` (or
  // name) currently open in numeric-input mode. `null` when closed.
  const [_editingKey, setEditingKey] = useState(null);
  const [editDraft, setEditDraft] = useState("");
  const _openEdit = (r) => {
    if (locked) return;
    setEditDraft(r.value == null ? "" : String(r.value));
    setEditingKey(canonicalReadingKey(r));
  };
  const _commitEdit = (idx) => {
    updReading(idx, editDraft === "" ? null : editDraft);
    setEditingKey(null);
  };

  const _analyzeWater = async (rawFile) => {
    if (!rawFile || locked) return;
    setAnalyzing(true); setAnalyzeErr(""); setAnalysis(null);
    try {
      // Feb 2026 · iOS field-upload timeout fix — techs shoot water
      // photos on the pool deck; shrink before base64 blowup on
      // /api/jobs/{jid}/photos.
      const file = await compressImageIfNeeded(rawFile);
      const dataUrl = await fileToDataUrl(file);
      const uploaded = await api.post(`/jobs/${jobId}/photos`, {
        data: dataUrl, label: `water-analysis-${new Date().toISOString()}`,
      });
      const latest = (uploaded?.photos || []).slice(-1)[0];
      const photoUrl = latest?.url || latest?.data;
      if (!photoUrl) throw new Error("Uploaded photo did not return a URL.");
      const currentReadings = readings.reduce((acc, r) => {
        if (r.value != null && r.value !== "") acc[r.key || r.name] = r.value;
        return acc;
      }, {});
      const result = await api.post(
        "/service-report/analyze-water-photo",
        {
          photo_url: photoUrl,
          current_readings: Object.keys(currentReadings).length ? currentReadings : null,
          job_id: jobId,
        },
        45000
      );
      setAnalysis(result);
    } catch (e) {
      setAnalyzeErr(e?.message || "Analysis failed.");
    } finally {
      setAnalyzing(false);
      if (analyzeRef.current) analyzeRef.current.value = "";
    }
  };

  // Phase 56.6 — helper: when a wizardStep is active, only render the
  // section matching that step. Returns `null` to hide a section. When
  // `wizardStep` is `null`, everything shows (legacy scroll mode).
  const inStep = (n) => wizardStep === null || wizardStep === n;

  return (
    <div data-testid="checklist-modal-pool" className="space-y-4">
      {/* Chemical Readings — Phase 48 manual text entry — Wizard step 1 */}
      {inStep(1) ? (
      <div data-wizard-section="readings">
        <div className="text-sm font-bold mb-3" style={{ color: colors.onSurface }}>
          Chemical Readings
        </div>
        {/* Feb-2026 · Checklist reclassifier — inline "Service Type"
            picker shown ONLY when the report's backend template is
            ``generic`` AND the field list is empty. A tenant that has
            genuinely customised a pool template down to zero readings
            (``template === "pool"`` + ``readingFields=[]``) falls
            through to the legacy silent empty state — that's a
            different bug and should not be masked here. */}
        {(readingFields || []).length === 0 && template === "generic" ? (
          <div
            className="rounded-md p-3 mb-3"
            style={{ background: colors.warnBg, border: "1px solid #FCD34D" }}
            data-testid="pool-service-type-picker-block"
          >
            <div className="text-sm font-bold mb-1" style={{ color: colors.warnText }}>
              This job isn&apos;t classified as Pool or Landscape
            </div>
            <div className="text-xs mb-2" style={{ color: colors.warnText }}>
              Set its Service Type to enable chemical readings.
            </div>
            {canEditServiceType && onReclassify ? (
              <div className="flex items-center gap-2 flex-wrap" data-testid="pool-service-type-picker">
                {[
                  { value: "Pool Service",      label: "Pool Service" },
                  { value: "Landscape Service", label: "Landscape Service" },
                  { value: "Other",             label: "Other" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    disabled={reclassifyBusy || locked}
                    onClick={async () => {
                      if (reclassifyBusy || locked) return;
                      setReclassifyBusy(true);
                      try { await onReclassify(opt.value); } finally { setReclassifyBusy(false); }
                    }}
                    className="text-xs font-bold px-3 py-1.5 rounded-full transition"
                    style={{
                      background: "#fff",
                      color: colors.onSurface,
                      border: `1.5px solid ${colors.border}`,
                      cursor: (locked || reclassifyBusy) ? "not-allowed" : "pointer",
                      opacity: reclassifyBusy ? 0.6 : 1,
                    }}
                    data-testid={`pool-service-type-set-${opt.value.toLowerCase().replace(/\s+/g, "-")}`}
                  >
                    {opt.label}
                  </button>
                ))}
                {reclassifyBusy ? (
                  <span
                    className="text-xs"
                    style={{ color: colors.warnText }}
                    data-testid="pool-service-type-picker-busy"
                  >Applying…</span>
                ) : null}
              </div>
            ) : (
              <div
                className="text-xs italic"
                style={{ color: colors.muted }}
                data-testid="pool-service-type-readonly-hint"
              >
                Ask an admin to set Service Type.
              </div>
            )}
          </div>
        ) : null}
        <div className="space-y-3">
          {mergedReadings.map((r, i) => {
            const key = canonicalReadingKey(r);
            const prev = lastReadings[key]
              || lastReadings[r.key]
              || lastReadings[r.name];
            const recentRaw = recentReadings[key]
              || recentReadings[r.key]
              || recentReadings[r.name]
              || [];
            return (
              <ReadingInputRow
                key={key}
                testKey={key}
                reading={r}
                previous={prev}
                recent={recentRaw}
                locked={locked}
                onChange={(val) => updReading(i, val)}
              />
            );
          })}
        </div>

        {!locked && (
          <div className="mt-3">
            {/* Phase 34d-follow-b — "Analyze water photo" button removed per
                user request. Backend endpoint retained for other flows. */}
          </div>
        )}

        {analyzeErr ? (
          <div className="text-xs px-2 py-1 rounded mt-2"
               style={{ color: "#991B1B", background: "#FEE2E2" }}
               data-testid="pool-analyze-error">
            {analyzeErr}
          </div>
        ) : null}

        {analysis && (
          <div className="mt-3 rounded-md p-3 text-sm space-y-2"
               style={{ border: `1px solid ${colors.border}`, background: colors.surfaceAlt }}
               data-testid="pool-analysis-card">
            {analysis.mocked && (
              <div className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                   style={{ background: colors.warnBg, color: colors.warnText }}>
                AI mocked · {analysis.reason || "no reason provided"}
              </div>
            )}
            {analysis.overall_assessment && (
              <div style={{ color: colors.onSurface }}>{analysis.overall_assessment}</div>
            )}
            {(analysis.recommendations || []).length > 0 && (
              <div>
                <div className="text-xs font-bold" style={{ color: colors.onSurface }}>
                  Recommendations
                </div>
                {analysis.recommendations.map((r, i) => (
                  <div key={i} className="text-xs">• {r}</div>
                ))}
              </div>
            )}
            {(analysis.issues || []).length > 0 && (
              <div>
                <div className="text-xs font-bold" style={{ color: colors.onSurface }}>Issues</div>
                {analysis.issues.map((r, i) => (
                  <div key={i} className="text-xs">• {r}</div>
                ))}
              </div>
            )}
            <div className="text-xs italic" style={{ color: colors.muted }}>
              Readings are NOT auto-filled — enter values you observed on the meter.
            </div>
          </div>
        )}

        {/* Phase 56.10 — Visible algae toggle group */}
        <div className="mt-4 rounded-md p-3"
             style={{ background: colors.surfaceAlt, border: `1px solid ${colors.border}` }}
             data-testid="pool-visible-algae-card">
          <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
            Visible algae on walls
          </div>
          <div className="flex items-center gap-2" data-testid="pool-visible-algae-toggles">
            {[
              { value: "none",  label: "None",  bg: "#fff",     fg: colors.onSurface, border: colors.border },
              { value: "light", label: "Light", bg: "#FEF3C7", fg: "#92400E",         border: "#FCD34D" },
              { value: "heavy", label: "Heavy", bg: "#FEE2E2", fg: "#991B1B",         border: "#FCA5A5" },
            ].map((opt) => {
              const current = (observations?.visible_algae || "none").toLowerCase();
              const active = current === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  disabled={locked}
                  onClick={() => onChange({
                    observations: { ...(observations || {}), visible_algae: opt.value },
                  })}
                  className="text-xs font-bold px-3 py-1.5 rounded-full transition"
                  style={{
                    background: active ? opt.bg : "transparent",
                    color: active ? opt.fg : colors.muted,
                    border: `1.5px solid ${active ? opt.border : colors.border}`,
                    cursor: locked ? "not-allowed" : "pointer",
                    opacity: locked ? 0.6 : 1,
                  }}
                  data-testid={`pool-visible-algae-${opt.value}`}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
          <div className="text-[11px] mt-2" style={{ color: colors.muted }}>
            Triggers an algae remediation dosing plan in Step 2 when set to Light or Heavy.
          </div>
        </div>
      </div>
      ) : null}

      {/* Phase 34e — Recommended Chemicals card — Wizard step 2 (part A) */}
      {inStep(2) ? (
      <div
        className="rounded-lg p-3"
        style={{ background: colors.surfaceAlt, border: `1px solid ${colors.border}` }}
        data-testid="pool-recommendations-card"
        data-wizard-section="recommendations"
      >
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-bold inline-flex items-center gap-1.5" style={{ color: colors.onSurface }}>
            <FlaskConical size={14} /> Recommended Chemicals
          </div>
          {!locked && (
            <button
              type="button"
              onClick={fetchRecommendations}
              disabled={recsLoading || Object.keys(readingsDict).length === 0}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
              style={{
                background: "transparent",
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
                cursor: recsLoading ? "wait" : "pointer",
                opacity: Object.keys(readingsDict).length === 0 ? 0.4 : 1,
              }}
              data-testid="pool-recommendations-refresh"
            >
              <RefreshCw size={11} className={recsLoading ? "animate-spin" : ""} /> Refresh
            </button>
          )}
        </div>

        {recs?.mocked ? (
          <div
            className="rounded-md p-2 text-xs inline-flex items-start gap-1.5"
            style={{ background: colors.warnBg, color: colors.warnText, border: `1px solid ${colors.warnText}20` }}
            data-testid="pool-gallons-missing-banner"
          >
            <AlertTriangle size={12} className="mt-0.5" />
            <span>
              <span className="font-semibold" data-testid="pool-recommendations-mocked-reason">
                {recs.reason}
              </span>
              {" — recommendations require a pool volume. "}
              <a href="#" onClick={(e) => { e.preventDefault(); window.location.hash = "customer-profile"; }} className="underline">
                Set on customer profile
              </a>.
            </span>
          </div>
        ) : Object.keys(readingsDict).length === 0 ? (
          <div className="text-xs" style={{ color: colors.muted }}>
            Enter chemical readings above to see dosing recommendations.
          </div>
        ) : recs && recs.recommendations && recs.recommendations.length === 0 ? (
          <div
            className="inline-flex items-center gap-1.5 text-xs font-semibold"
            style={{ color: colors.success }}
            data-testid="pool-recommendations-empty"
          >
            <CheckCircle2 size={13} /> All readings look good — no chemicals needed.
          </div>
        ) : recs && recs.recommendations ? (
          <div className="space-y-2">
            {/* Phase 56.10 — high-pH ordering guard rendered as a top callout */}
            {(recs.recommendations || []).filter((r) => r.category === "ordering_note").map((r, i) => (
              <div
                key={`ord-${i}`}
                className="rounded-md p-2 flex items-start gap-2"
                style={{ background: "#FEF3C7", border: "1.5px solid #F59E0B" }}
                data-testid="pool-recommendation-ordering-note"
              >
                <AlertTriangle size={14} color="#B45309" className="flex-shrink-0 mt-0.5" />
                <div className="text-xs font-semibold" style={{ color: "#92400E" }}>
                  {r.reason}
                </div>
              </div>
            ))}

            {(recs.recommendations || []).filter((r) => !r.category || r.category === "routine").map((r, i) => (
              <div
                key={`${r.chemical}-${i}`}
                className="flex items-start gap-2 rounded-md p-2"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="pool-recommendation-row"
              >
                <div className="flex-shrink-0 mt-0.5">
                  {r.urgency === "immediate" ? (
                    <AlertTriangle size={14} color={colors.warnText} />
                  ) : (
                    <FlaskConical size={14} color={colors.brand} />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm" style={{ color: colors.onSurface }}>
                    <span className="font-bold">
                      {r.quantity > 0 ? `${r.quantity} ${r.unit} ` : ""}
                      {r.chemical}
                    </span>
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: colors.muted }}>{r.reason}</div>
                </div>
                {!locked && r.quantity > 0 && (
                  <button
                    type="button"
                    onClick={() => addChemFromRec(r)}
                    className="flex-shrink-0 px-2 py-1 rounded-md text-xs font-bold"
                    style={{ background: colors.brand, color: "#fff", border: 0, cursor: "pointer" }}
                    data-testid="pool-recommendation-add-btn"
                  >
                    Add
                  </button>
                )}
              </div>
            ))}

            {/* Phase 56.10 — Algae Protocol sub-section (light or heavy) */}
            {(recs.recommendations || []).some((r) => r.category === "algae_remediation") && (
              <div className="mt-3 rounded-md p-2"
                   style={{ background: "#FEF2F2", border: "1.5px solid #FCA5A5" }}
                   data-testid="pool-algae-protocol-card">
                <div className="text-sm font-bold flex items-center gap-1.5 mb-2"
                     style={{ color: "#991B1B" }}>
                  <AlertTriangle size={14} /> Algae Protocol
                </div>
                <div className="space-y-2">
                  {(recs.recommendations || []).filter((r) => r.category === "algae_remediation").map((r, i) => (
                    <div
                      key={`algae-${r.chemical}-${i}`}
                      className="rounded-md p-2 flex items-start gap-2"
                      style={{ background: "#fff", border: "1px solid #FECACA" }}
                      data-testid="pool-recommendation-algae-row"
                    >
                      <div className="flex-shrink-0 mt-0.5">
                        <AlertTriangle size={14} color="#B91C1C" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm" style={{ color: "#0F172A" }}>
                          <span className="font-bold">
                            {r.quantity > 0 ? `${r.quantity} ${r.unit} ` : ""}
                            {r.chemical}
                          </span>
                        </div>
                        <div className="text-xs mt-0.5" style={{ color: colors.muted }}>{r.reason}</div>
                        {r.guidance_note ? (
                          <ul className="mt-1 space-y-0.5 text-[11px]"
                              style={{ color: "#7F1D1D" }}
                              data-testid="pool-algae-guidance">
                            {r.guidance_note.split(/(?<=\.)\s+/).filter(Boolean).map((line, j) => (
                              <li key={j} className="flex items-start gap-1">
                                <span>•</span><span>{line}</span>
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                      {!locked && r.quantity > 0 && (
                        <button
                          type="button"
                          onClick={() => addChemFromRec(r)}
                          className="flex-shrink-0 px-2 py-1 rounded-md text-xs font-bold"
                          style={{ background: "#B91C1C", color: "#fff", border: 0, cursor: "pointer" }}
                          data-testid="pool-recommendation-algae-add-btn"
                        >
                          Add
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {recs.source === "deterministic-only" && recs.reason ? (
              <div className="text-[10px] italic" style={{ color: colors.muted }}>
                Plain-English phrasing unavailable — showing raw reasons.
              </div>
            ) : null}
          </div>
        ) : recsLoading ? (
          <div className="text-xs" style={{ color: colors.muted }}>Calculating…</div>
        ) : null}

        {recsError ? (
          <div className="text-xs mt-1" style={{ color: "#DC2626" }}>{recsError}</div>
        ) : null}
      </div>
      ) : null}

      {/* Chemicals Added — Phase 48 inline manual text entry per catalog — Wizard step 2 (part B) */}
      {inStep(2) ? (
      <div data-wizard-section="chemicals-added">
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Chemicals Added
        </div>
        <ChemicalDropdownStack
          chemicalsAdded={chemicalsAdded}
          locked={locked}
          onChange={onChange}
          jobId={jobId}
        />
      </div>
      ) : null}

      {/* Checklist — Wizard step 3 */}
      {inStep(3) && checklistItems.length > 0 && (
        <div data-wizard-section="checklist">
          <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
            Checklist
          </div>
          {checklistItems.map((c, i) => (
            <label
              key={c.id}
              className="flex items-center gap-2 px-3 py-2 rounded-md mb-1 cursor-pointer"
              style={{
                border: `1px solid ${c.checked ? colors.success : colors.border}`,
                background: c.checked ? colors.successBg : colors.surface,
              }}
              data-testid={`pool-check-${c.id}`}
            >
              <input
                type="checkbox"
                disabled={locked}
                checked={!!c.checked}
                onChange={() => toggleCheck(i)}
              />
              <span className="text-sm" style={{ color: colors.onSurface }}>{c.label}</span>
            </label>
          ))}
        </div>
      )}

      {/* Notes — Wizard step 5 (customer-facing notes) */}
      {inStep(5) ? (
      <div data-wizard-section="customer-notes">
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Customer Notes
        </div>
        <div className="text-xs mb-1" style={{ color: colors.muted }}>
          Visible on the customer portal and the emailed report.
        </div>
        <textarea
          rows={4}
          disabled={locked}
          value={notes || ""}
          onChange={(e) => onChange({ notes: e.target.value })}
          placeholder="Anything the customer or dispatcher should know…"
          className="w-full px-2 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${colors.border}`,
            background: locked ? colors.surfaceAlt : colors.surface,
            color: colors.onSurface,
            resize: "vertical",
          }}
          data-testid="pool-notes"
        />
      </div>
      ) : null}

      {/* Internal Notes — Wizard step 6 (private) */}
      {inStep(6) ? (
      <div data-wizard-section="internal-notes">
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Internal Notes
        </div>
        <div className="text-xs mb-1" style={{ color: colors.muted }}>
          Private — visible to admins + techs only, never to the customer.
        </div>
        <textarea
          rows={4}
          disabled={locked}
          value={internalNotes || ""}
          onChange={(e) => onChange({ internal_notes: e.target.value })}
          placeholder="Equipment issues, follow-up leads, tricky access details…"
          className="w-full px-2 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${colors.border}`,
            background: locked ? colors.surfaceAlt : colors.surface,
            color: colors.onSurface,
            resize: "vertical",
          }}
          data-testid="pool-internal-notes"
        />
      </div>
      ) : null}
    </div>
  );
}
