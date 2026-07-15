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
            <button
              type="button"
              onClick={() => analyzeRef.current?.click()}
              disabled={analyzing}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-bold"
              style={{
                background: colors.brand,
                color: "#fff",
                border: 0,
                cursor: analyzing ? "wait" : "pointer",
              }}
              data-testid="pool-analyze-water-btn"
            >
              {analyzing
                ? <Loader2 size={14} className="animate-spin" />
                : <Sparkles size={14} />}
              {analyzing ? "Analyzing…" : "Analyze water photo"}
            </button>
            <input
              ref={analyzeRef}
              type="file"
              accept="image/*"
              style={{ display: "none" }}
              onChange={(e) => analyzeWater(e.target.files?.[0])}
              data-testid="pool-analyze-water-input"
            />
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
