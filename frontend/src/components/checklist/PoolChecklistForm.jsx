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
import React, { useRef, useState } from "react";
import { Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { api } from "@/api";

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
      {/* Chemical Readings */}
      <div>
        <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>
          Chemical Readings
        </div>
        <div className="grid grid-cols-2 gap-2">
          {readings.map((r, i) => (
            <div key={r.key || r.name} className="flex flex-col">
              <label className="text-[10px] font-bold uppercase tracking-wide mb-1"
                     style={{ color: colors.muted }}>
                {r.name}{r.unit ? ` (${r.unit})` : ""}
              </label>
              <input
                type="number"
                inputMode="decimal"
                step="0.01"
                disabled={locked}
                value={r.value == null ? "" : r.value}
                onChange={(e) => updReading(i, e.target.value)}
                placeholder="—"
                className="px-2 py-1.5 rounded-md text-sm"
                style={{
                  border: `1px solid ${colors.border}`,
                  background: locked ? colors.surfaceAlt : colors.surface,
                  color: colors.onSurface,
                }}
                data-testid={`pool-reading-${r.key || r.name}`}
              />
            </div>
          ))}
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
