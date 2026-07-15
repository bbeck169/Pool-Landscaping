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
import { AlertTriangle, CheckCircle2, FlaskConical, Plus, RefreshCw, Trash2, Pencil, X as CloseX } from "lucide-react";
import { api } from "@/api";

// Phase 36 — chip-scale defaults per reading key.
const CHIP_SCALES = {
  total_chlorine:    { values: [0, 0.5, 1, 2, 3, 5, 10],                       palette: "chlorine" },
  free_chlorine:     { values: [0, 0.5, 1, 2, 3, 5, 10],                       palette: "chlorine" },
  chlorine:          { values: [0, 0.5, 1, 2, 3, 5, 10],                       palette: "chlorine" },
  combined_chlorine: { values: [0, 0.2, 0.5, 1, 2],                            palette: "chlorine" },
  ph:                { values: [6.2, 6.6, 7.0, 7.2, 7.4, 7.6, 7.8, 8.0, 8.4], palette: "ph" },
  alkalinity:        { values: ["N/A", 0, 40, 60, 80, 100, 120, 140, 180, 240], palette: "alkalinity" },
  total_alkalinity:  { values: ["N/A", 0, 40, 60, 80, 100, 120, 140, 180, 240], palette: "alkalinity" },
  cyanuric_acid:     { values: ["N/A", 0, 20, 30, 40, 50, 60, 80, 100],       palette: "optional" },
  cya:               { values: ["N/A", 0, 20, 30, 40, 50, 60, 80, 100],       palette: "optional" },
  calcium_hardness:  { values: ["N/A", 0, 100, 150, 200, 250, 300, 400, 500], palette: "optional" },
  phosphate:         { values: ["N/A", 0, 125, 250, 500, 1000, 2500],         palette: "optional" },
  phosphates:        { values: ["N/A", 0, 125, 250, 500, 1000, 2500],         palette: "optional" },
  salt:              { values: ["N/A", 0, 1000, 2000, 2700, 3200, 3600, 4500], palette: "optional" },
  tds:               { values: ["N/A", 0, 500, 1000, 1500, 2000, 3000],       palette: "optional" },
  water_temp:        { values: ["N/A", 40, 50, 60, 65, 70, 75, 80, 85, 90],   palette: "optional" },
  temperature:       { values: ["N/A", 40, 50, 60, 65, 70, 75, 80, 85, 90],   palette: "optional" },
  filter_psi:        { values: ["N/A", 0, 5, 10, 15, 20, 25, 30],              palette: "optional" },
  psi:               { values: ["N/A", 0, 5, 10, 15, 20, 25, 30],              palette: "optional" },
};

const PALETTES = {
  chlorine:   { bg: "#cffafe", sel: "#0891b2", selFg: "#fff", fg: "#155e75" },
  ph:         { bg: "#fee2e2", sel: "#dc2626", selFg: "#fff", fg: "#7f1d1d",
                inRangeBg: "#dcfce7", inRangeSel: "#16a34a", inRangeFg: "#14532d" },
  alkalinity: { bg: "#dcfce7", sel: "#16a34a", selFg: "#fff", fg: "#14532d" },
  optional:   { bg: "#ffedd5", sel: "#ea580c", selFg: "#fff", fg: "#7c2d12" },
};

const _resolveScale = (r) => {
  const key = String(r.key || r.name || "").toLowerCase().replace(/[\s()]+/g, "_");
  return CHIP_SCALES[key];
};

const _phSweet = (v) => typeof v === "number" && v >= 7.2 && v <= 7.6;

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
  chemicalsAdded = [],
  chemicalsCatalog = [],
  chemicalUnits = ["gal", "lbs", "oz", "tabs"],
  checklistItems = [],
  notes = "",
  onChange,
}) {
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [analyzeErr, setAnalyzeErr] = useState("");
  const analyzeRef = useRef(null);

  // Phase 34e — chemical dose recommendations state.
  const [recs, setRecs] = useState(null); // {recommendations, mocked, reason, source, pool_gallons}
  const [recsLoading, setRecsLoading] = useState(false);
  const [recsError, setRecsError] = useState("");

  const updReading = (idx, val) => {
    const next = readings.map((r, i) =>
      i === idx
        ? { ...r, value: val === "" ? null : parseFloat(val) }
        : r
    );
    onChange({ chemical_readings: next });
  };

  const addChem = () => {
    const next = [
      ...chemicalsAdded,
      { id: Math.random().toString(36).slice(2), name: "", amount: "", unit: chemicalUnits[0] || "lbs" },
    ];
    onChange({ chemicals_added: next });
  };
  const updChem = (idx, patch) => {
    const next = chemicalsAdded.map((c, i) => (i === idx ? { ...c, ...patch } : c));
    onChange({ chemicals_added: next });
  };
  const rmChem = (idx) => {
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
      });
      setRecs(res);
    } catch (e) {
      setRecsError(e?.message || "Could not fetch recommendations.");
    } finally {
      setRecsLoading(false);
    }
    // eslint-disable-next-line
  }, [jobId, readingsDict, locked]);

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
    // Try to match a catalog entry by chemical name — case-insensitive.
    const next = [
      ...chemicalsAdded,
      {
        id: Math.random().toString(36).slice(2),
        name: rec.chemical,
        amount: String(rec.quantity ?? ""),
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
  useEffect(() => {
    if (!customerId) return;
    let alive = true;
    api.get(`/service-reports/last-readings?customer_id=${customerId}`)
      .then((r) => { if (alive) setLastReadings(r?.readings || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [customerId]);

  // Phase 36 — pencil-edit popover: `editingKey` is the reading `key` (or
  // name) currently open in numeric-input mode. `null` when closed.
  const [editingKey, setEditingKey] = useState(null);
  const [editDraft, setEditDraft] = useState("");
  const openEdit = (r) => {
    if (locked) return;
    setEditDraft(r.value == null ? "" : String(r.value));
    setEditingKey(r.key || r.name);
  };
  const commitEdit = (idx) => {
    updReading(idx, editDraft === "" ? null : editDraft);
    setEditingKey(null);
  };

  const analyzeWater = async (file) => {
    if (!file || locked) return;
    setAnalyzing(true); setAnalyzeErr(""); setAnalysis(null);
    try {
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

  return (
    <div data-testid="checklist-modal-pool" className="space-y-4">
      {/* Chemical Readings — Phase 36 chip UI */}
      <div>
        <div className="text-sm font-bold mb-3" style={{ color: colors.onSurface }}>
          Chemical Readings
        </div>
        <div className="space-y-4">
          {readings.map((r, i) => {
            const key = r.key || r.name;
            const scale = _resolveScale(r);
            const pal = scale ? PALETTES[scale.palette] : PALETTES.optional;
            const prev = lastReadings[key];
            const isEditing = editingKey === key;
            const currentVal = r.value;
            return (
              <div
                key={key}
                data-testid={`pool-reading-${key}-slider`}
                className="border rounded-lg p-3"
                style={{ borderColor: colors.border, background: colors.surface }}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => openEdit(r)}
                      disabled={locked}
                      className="p-1 rounded-md"
                      style={{ background: "transparent", border: 0, cursor: locked ? "default" : "pointer" }}
                      data-testid={`pool-reading-${key}-edit`}
                      aria-label={`Edit ${r.name}`}
                    >
                      <Pencil size={13} style={{ color: colors.muted }} />
                    </button>
                    <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.onSurface }}>
                      {r.name}{r.unit ? ` (${r.unit})` : ""}
                    </span>
                  </div>
                  <div className="text-sm font-bold" style={{ color: pal.sel }}>
                    {currentVal == null || currentVal === "" ? "—" : String(currentVal)}
                  </div>
                </div>

                {isEditing ? (
                  <div className="flex items-center gap-2 mb-2">
                    <input
                      type="number"
                      step={r.step || "0.01"}
                      min={r.min != null ? r.min : 0}
                      max={r.max != null ? r.max : undefined}
                      autoFocus
                      value={editDraft}
                      onChange={(e) => setEditDraft(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") commitEdit(i); if (e.key === "Escape") setEditingKey(null); }}
                      className="flex-1 px-2 py-1 rounded-md text-sm"
                      style={{ border: `1px solid ${colors.border}` }}
                      data-testid={`pool-reading-${key}-input`}
                    />
                    <button type="button" onClick={() => commitEdit(i)}
                            className="px-2 py-1 rounded-md text-xs font-bold"
                            style={{ background: colors.brand, color: "#fff", border: 0, cursor: "pointer" }}>
                      Set
                    </button>
                    <button type="button" onClick={() => setEditingKey(null)}
                            className="p-1 rounded-md" style={{ background: "transparent", border: 0, cursor: "pointer" }}>
                      <CloseX size={14} style={{ color: colors.muted }} />
                    </button>
                  </div>
                ) : null}

                {scale ? (
                  <div className="flex gap-1.5 overflow-x-auto pb-1" style={{ scrollbarWidth: "thin" }}>
                    {scale.values.map((v) => {
                      const isNA = v === "N/A";
                      const chipVal = isNA ? null : v;
                      const isSelected = (chipVal === null && (currentVal == null || currentVal === ""))
                        || (chipVal !== null && currentVal != null && Number(currentVal) === Number(chipVal));
                      // pH chips get the green sweet-spot palette override.
                      const useGreen = scale.palette === "ph" && _phSweet(chipVal);
                      const bg = isSelected
                        ? (useGreen ? pal.inRangeSel : pal.sel)
                        : (useGreen ? pal.inRangeBg : pal.bg);
                      const fg = isSelected
                        ? pal.selFg
                        : (useGreen ? pal.inRangeFg : pal.fg);
                      return (
                        <button
                          type="button"
                          key={String(v)}
                          disabled={locked}
                          onClick={() => updReading(i, chipVal)}
                          data-testid={`pool-reading-${key}-chip-${String(v)}`}
                          className="px-2.5 py-1.5 rounded-md text-xs font-bold whitespace-nowrap"
                          style={{
                            background: bg, color: fg,
                            border: isSelected ? `2px solid ${useGreen ? pal.inRangeSel : pal.sel}` : `1px solid ${bg}`,
                            cursor: locked ? "default" : "pointer",
                            minWidth: 44,
                          }}
                        >
                          {String(v)}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <input
                    type="number"
                    inputMode="decimal"
                    step={r.step || "0.01"}
                    min={r.min != null ? r.min : 0}
                    max={r.max != null ? r.max : undefined}
                    disabled={locked}
                    value={r.value == null ? "" : r.value}
                    onChange={(e) => updReading(i, e.target.value)}
                    placeholder="—"
                    className="w-full px-2 py-1.5 rounded-md text-sm"
                    style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                    data-testid={`pool-reading-${key}-input`}
                  />
                )}

                <div className="text-[10px] mt-1" style={{ color: colors.muted }}
                     data-testid={`pool-reading-${key}-previous`}>
                  Previously tested at: {prev
                    ? `${prev.value}${r.unit ? ` ${r.unit}` : ""} · ${_fmtRel(prev.at)}`
                    : "—"}
                </div>
              </div>
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
      </div>

      {/* Phase 34e — Recommended Chemicals card */}
      <div
        className="rounded-lg p-3"
        style={{ background: colors.surfaceAlt, border: `1px solid ${colors.border}` }}
        data-testid="pool-recommendations-card"
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
            {recs.recommendations.map((r, i) => (
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

      {/* Chemicals Added */}
      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Chemicals Added
        </div>
        {chemicalsAdded.map((c, i) => (
          <div key={c.id || i} className="grid grid-cols-12 gap-2 mb-2"
               data-testid={`pool-chem-row-${i}`}>
            <input
              type="text"
              disabled={locked}
              value={c.name}
              placeholder="Chemical"
              onChange={(e) => updChem(i, { name: e.target.value })}
              list={`pool-chem-catalog-${jobId}`}
              className="col-span-6 px-2 py-1.5 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
              data-testid={`pool-chem-name-${i}`}
            />
            <input
              type="number"
              disabled={locked}
              value={c.amount || ""}
              placeholder="Qty"
              onChange={(e) => updChem(i, { amount: e.target.value })}
              className="col-span-2 px-2 py-1.5 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
              data-testid={`pool-chem-amount-${i}`}
            />
            <select
              disabled={locked}
              value={c.unit || ""}
              onChange={(e) => updChem(i, { unit: e.target.value })}
              className="col-span-3 px-2 py-1.5 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
              data-testid={`pool-chem-unit-${i}`}
            >
              {chemicalUnits.map((u) => (<option key={u} value={u}>{u}</option>))}
            </select>
            {!locked && (
              <button
                type="button"
                onClick={() => rmChem(i)}
                className="col-span-1 flex items-center justify-center rounded-md"
                style={{ background: "transparent", border: 0, cursor: "pointer" }}
                data-testid={`pool-chem-rm-${i}`}
                aria-label="Remove row"
              >
                <Trash2 size={14} color="#DC2626" />
              </button>
            )}
          </div>
        ))}
        {chemicalsCatalog.length > 0 && (
          <datalist id={`pool-chem-catalog-${jobId}`}>
            {chemicalsCatalog.map((c) => (
              <option key={c.name} value={c.name} />
            ))}
          </datalist>
        )}
        {!locked && (
          <button
            type="button"
            onClick={addChem}
            className="inline-flex items-center gap-1 text-sm font-bold"
            style={{ color: colors.brand, background: "transparent", border: 0, cursor: "pointer" }}
            data-testid="pool-chem-add"
          >
            <Plus size={14} /> Add chemical
          </button>
        )}
      </div>

      {/* Checklist */}
      {checklistItems.length > 0 && (
        <div>
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

      {/* Notes */}
      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>Notes</div>
        <textarea
          rows={3}
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
    </div>
  );
}
