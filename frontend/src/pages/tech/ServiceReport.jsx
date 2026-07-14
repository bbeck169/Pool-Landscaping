/**
 * Phase 18B follow-up — Service Report page.
 * Auto-loads the correct template (pool/landscape/generic) for the given job,
 * autosaves every 5s while dirty, enforces 10-photo cap, and finalizes with
 * "Submit Report & Clock Out".
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import {
  Camera, X, Save, ShieldCheck, ChevronLeft, CheckSquare, Square,
  MapPin, Key, ClipboardCheck, FlaskConical, Beaker, Plus, Trash2, Timer,
} from "lucide-react";

const AUTOSAVE_MS = 5000;
const PHOTO_CAP = 10;
const CHEM_UNITS = ["lb", "oz", "gal", "tabs", "ppm", "L", "kg"];

const useElapsed = (startIso) => {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!startIso) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [startIso]);
  if (!startIso) return "—";
  const secs = Math.max(0, Math.floor((now - new Date(startIso).getTime()) / 1000));
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
};

export default function ServiceReport() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState("idle"); // idle | saving | saved | error
  const [submitting, setSubmitting] = useState(false);
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.get(`/jobs/${id}/service-report`);
      setReport(r);
    } catch (e) {
      alert(e.message);
    } finally { setBusy(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Elapsed timer — hoisted so hooks order stays stable across renders.
  const elapsedText = useElapsed(report?.started_at);

  // Autosave loop
  const autosave = useCallback(async () => {
    if (!dirtyRef.current || savingRef.current || !report) return;
    if (report.submitted_at) return;
    savingRef.current = true;
    setSaveState("saving");
    try {
      const patch = {
        chemical_readings: report.chemical_readings,
        chemicals_added: report.chemicals_added,
        checklist_items: report.checklist_items,
        notes: report.notes,
      };
      await api.patch(`/jobs/${id}/service-report`, patch);
      dirtyRef.current = false;
      setDirty(false);
      setSaveState("saved");
      setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1500);
    } catch (e) {
      setSaveState("error");
    } finally {
      savingRef.current = false;
    }
  }, [id, report]);

  useEffect(() => {
    const t = setInterval(autosave, AUTOSAVE_MS);
    return () => clearInterval(t);
  }, [autosave]);

  const markDirty = () => { dirtyRef.current = true; setDirty(true); };

  if (busy && !report) return (
    <div className="p-6" style={{ color: colors.muted }} data-testid="svc-report-loading">Loading report…</div>
  );
  if (!report) return (
    <div className="p-6" style={{ color: colors.error }} data-testid="svc-report-error">Report unavailable.</div>
  );

  const job = report.job || {};
  const isPool = report.template === "pool";
  const photoCount = (report.photos || []).length;
  const remaining = PHOTO_CAP - photoCount;

  const updChemistryReading = (idx, patch) => {
    const next = [...report.chemical_readings];
    next[idx] = { ...next[idx], ...patch, ts: new Date().toISOString() };
    setReport({ ...report, chemical_readings: next });
    markDirty();
  };
  const addChemical = () => {
    const next = [...(report.chemicals_added || []),
      { id: Math.random().toString(36).slice(2), name: "", amount: "", unit: "lb", ts: new Date().toISOString() }];
    setReport({ ...report, chemicals_added: next });
    markDirty();
  };
  const updChemical = (idx, patch) => {
    const next = [...report.chemicals_added];
    next[idx] = { ...next[idx], ...patch };
    setReport({ ...report, chemicals_added: next });
    markDirty();
  };
  const removeChemical = (idx) => {
    const next = report.chemicals_added.filter((_, i) => i !== idx);
    setReport({ ...report, chemicals_added: next });
    markDirty();
  };
  const toggleCheck = (idx) => {
    const next = [...report.checklist_items];
    next[idx] = { ...next[idx], checked: !next[idx].checked };
    setReport({ ...report, checklist_items: next });
    markDirty();
  };
  const setCheckNote = (idx, text) => {
    const next = [...report.checklist_items];
    next[idx] = { ...next[idx], notes: text };
    setReport({ ...report, checklist_items: next });
    markDirty();
  };
  const setNotes = (v) => { setReport({ ...report, notes: v }); markDirty(); };

  const addPhoto = async (file) => {
    if (remaining <= 0) { alert("10-photo cap reached"); return; }
    const dataUrl = await new Promise((res) => {
      const r = new FileReader();
      r.onload = () => res(r.result); r.readAsDataURL(file);
    });
    try {
      const updated = await api.post(`/jobs/${id}/photos`, {
        data: dataUrl, label: `svc-${new Date().toISOString()}`,
      });
      setReport({ ...report, photos: updated.photos || [] });
    } catch (e) {
      alert(e.message);
    }
  };

  const removePhoto = async (pid) => {
    if (!confirm("Delete this photo?")) return;
    try {
      const updated = await api.del(`/jobs/${id}/photos/${pid}`);
      setReport({ ...report, photos: updated.photos || [] });
    } catch (e) { alert(e.message); }
  };

  const submitAndClockOut = async () => {
    if (!confirm("Submit this report and clock out?")) return;
    setSubmitting(true);
    try {
      // Flush any pending edits first
      if (dirtyRef.current) await autosave();
      const submitted = await api.post(`/jobs/${id}/service-report/submit`);
      setReport({ ...report, ...submitted, submitted_at: submitted.submitted_at });
      // Clock out best-effort (may already be clocked out if user is manually testing)
      try {
        await api.post("/workforce/clock-out", {});
      } catch (e) {
        // clock-out failure isn't fatal for submission
        console.warn("clock-out skipped:", e.message);
      }
      navigate("/schedule/today");
    } catch (e) {
      alert(e.message);
    } finally { setSubmitting(false); }
  };

  const uncheckedCount = (report.checklist_items || []).filter((c) => !c.checked).length;
  const locked = !!report.submitted_at;

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="svc-report-page">
      <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm mb-3"
              style={{ color: colors.muted }} data-testid="svc-report-back">
        <ChevronLeft size={16}/> Back
      </button>

      <div className="rounded-2xl p-5 mb-5 text-white flex items-start justify-between gap-4 flex-wrap"
           style={{ background: brandGradientCss }} data-testid="svc-report-header">
        <div className="min-w-0">
          <div className="text-xs uppercase font-bold opacity-90 tracking-wider">
            {report.template} template
            {locked && <span className="ml-2 px-2 py-0.5 rounded bg-black/30">LOCKED</span>}
          </div>
          <h1 className="text-2xl font-bold truncate">{job.title || job.service_type || "Service"}</h1>
          <div className="text-sm opacity-90 mt-1 flex items-center gap-2 flex-wrap">
            <span>{job.customer_name || "—"}</span>
            {job.address && (
              <span className="flex items-center gap-1"><MapPin size={12}/> {job.address}</span>
            )}
            {job.gate_code && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded font-mono"
                    style={{ backgroundColor: "rgba(0,0,0,0.25)" }}>
                <Key size={11}/> {job.gate_code}
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs uppercase font-bold opacity-90 tracking-wider">Elapsed</div>
          <div className="text-2xl font-bold tabular-nums flex items-center gap-2 justify-end"
               data-testid="svc-report-elapsed">
            <Timer size={20}/> {elapsedText}
          </div>
          <div className="text-xs opacity-90 mt-1" data-testid="svc-report-save-state">
            {saveState === "saving" && "Saving…"}
            {saveState === "saved" && "Saved"}
            {saveState === "error" && "Save failed — retrying"}
            {saveState === "idle" && (dirty ? "Unsaved changes" : "All changes saved")}
          </div>
        </div>
      </div>

      {/* Photos */}
      <Section title="Photos" icon={<Camera size={16}/>}
               subtitle={`${photoCount} / ${PHOTO_CAP}`}
               testId="svc-report-photos">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {(report.photos || []).map((p) => (
            <div key={p.id} className="relative rounded-xl overflow-hidden"
                 style={{ border: `1px solid ${colors.border}`, aspectRatio: "1/1" }}
                 data-testid={`svc-photo-${p.id}`}>
              <img src={p.data || p.url} alt={p.label} className="w-full h-full object-cover"/>
              {!locked && (
                <button onClick={() => removePhoto(p.id)}
                        className="absolute top-1 right-1 rounded-full p-1"
                        style={{ backgroundColor: "rgba(0,0,0,0.7)", color: "#fff" }}
                        data-testid={`svc-photo-del-${p.id}`}
                        aria-label="Remove photo">
                  <X size={12}/>
                </button>
              )}
            </div>
          ))}
          {!locked && remaining > 0 && (
            <label className="rounded-xl flex items-center justify-center cursor-pointer"
                   style={{ border: `2px dashed ${colors.border}`,
                            backgroundColor: colors.surfaceSecondary,
                            color: colors.muted, aspectRatio: "1/1" }}
                   data-testid="svc-photo-add">
              <div className="text-center">
                <Camera size={22} className="mx-auto"/>
                <div className="text-[10px] uppercase font-bold mt-1">Add photo</div>
                <div className="text-[10px]">{remaining} left</div>
              </div>
              <input type="file" accept="image/*" capture="environment" className="hidden"
                     onChange={(e) => e.target.files?.[0] && addPhoto(e.target.files[0])}
                     data-testid="svc-photo-input"/>
            </label>
          )}
        </div>
      </Section>

      {isPool && (
        <Section title="Chemical Readings" icon={<FlaskConical size={16}/>}
                 testId="svc-report-readings">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {(report.chemical_readings || []).map((r, i) => (
              <div key={r.name} data-testid={`svc-reading-${r.name}`}>
                <label className="text-xs font-bold uppercase tracking-wider block mb-1"
                       style={{ color: colors.muted }}>
                  {r.name} {r.unit ? `(${r.unit})` : ""}
                </label>
                <input type="number" step="any"
                       value={r.value ?? ""} disabled={locked}
                       onChange={(e) => updChemistryReading(i, { value: e.target.value === "" ? null : parseFloat(e.target.value) })}
                       className="w-full px-2 py-2 rounded-lg text-sm"
                       style={{ border: `1px solid ${colors.border}` }}/>
              </div>
            ))}
          </div>
        </Section>
      )}

      {isPool && (
        <Section title="Chemicals Added" icon={<Beaker size={16}/>}
                 testId="svc-report-chems"
                 right={!locked && (
                   <button onClick={addChemical}
                           className="text-sm font-bold flex items-center gap-1"
                           style={{ color: colors.brand }}
                           data-testid="svc-add-chemical">
                     <Plus size={14}/> Add
                   </button>
                 )}>
          {(report.chemicals_added || []).length === 0 && (
            <div className="text-sm" style={{ color: colors.muted }}>No chemicals added yet.</div>
          )}
          <div className="space-y-2">
            {(report.chemicals_added || []).map((c, i) => (
              <div key={c.id || i}
                   className="grid grid-cols-12 gap-2 items-center"
                   data-testid={`svc-chem-row-${i}`}>
                <input value={c.name} disabled={locked}
                       onChange={(e) => updChemical(i, { name: e.target.value })}
                       placeholder="Chemical"
                       className="col-span-6 px-2 py-2 rounded-lg text-sm"
                       style={{ border: `1px solid ${colors.border}` }}/>
                <input type="number" step="any" value={c.amount} disabled={locked}
                       onChange={(e) => updChemical(i, { amount: e.target.value })}
                       placeholder="Amount"
                       className="col-span-3 px-2 py-2 rounded-lg text-sm"
                       style={{ border: `1px solid ${colors.border}` }}/>
                <select value={c.unit} disabled={locked}
                        onChange={(e) => updChemical(i, { unit: e.target.value })}
                        className="col-span-2 px-2 py-2 rounded-lg text-sm"
                        style={{ border: `1px solid ${colors.border}`, background: colors.surface }}>
                  {CHEM_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
                </select>
                {!locked && (
                  <button onClick={() => removeChemical(i)}
                          className="col-span-1 p-2 rounded"
                          style={{ color: colors.error }}
                          data-testid={`svc-chem-remove-${i}`}>
                    <Trash2 size={14}/>
                  </button>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Checklist */}
      <Section title="Checklist" icon={<ClipboardCheck size={16}/>}
               subtitle={`${uncheckedCount} unchecked`} testId="svc-report-checklist">
        <div className="space-y-2">
          {(report.checklist_items || []).map((c, i) => (
            <div key={c.id} className="p-3 rounded-lg"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${c.checked ? colors.success : colors.border}` }}
                 data-testid={`svc-check-${c.id}`}>
              <button onClick={() => !locked && toggleCheck(i)}
                      className="w-full flex items-start gap-2 text-left"
                      disabled={locked}
                      data-testid={`svc-check-toggle-${c.id}`}>
                {c.checked ? <CheckSquare size={20} style={{ color: colors.success }}/>
                           : <Square size={20} style={{ color: colors.muted }}/>}
                <span className="text-sm flex-1" style={{ color: colors.onSurface }}>
                  {c.label}
                </span>
              </button>
              {c.checked && !locked && (
                <input value={c.notes || ""} placeholder="Optional note"
                       onChange={(e) => setCheckNote(i, e.target.value)}
                       className="w-full mt-2 px-2 py-1 rounded text-xs"
                       style={{ border: `1px solid ${colors.border}` }}
                       data-testid={`svc-check-note-${c.id}`}/>
              )}
            </div>
          ))}
        </div>
      </Section>

      {/* Notes */}
      <Section title="Notes" testId="svc-report-notes-section">
        <textarea rows={4} value={report.notes || ""} disabled={locked}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Anything the customer or dispatcher should know…"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid="svc-report-notes"/>
      </Section>

      {!locked && (
        <div className="sticky bottom-0 left-0 right-0 mt-6 py-3 flex justify-end gap-2"
             style={{ backgroundColor: colors.surfaceSecondary,
                      borderTop: `1px solid ${colors.border}` }}>
          <button onClick={autosave} disabled={savingRef.current || !dirty}
                  className="px-4 py-2 rounded-xl text-sm font-semibold"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                  data-testid="svc-report-save-now">
            <Save size={13} className="inline mr-1"/> Save now
          </button>
          <button onClick={submitAndClockOut} disabled={submitting}
                  className="px-4 py-2 rounded-xl text-sm font-bold text-white"
                  style={{ background: brandGradientCss }}
                  data-testid="svc-report-submit">
            <ShieldCheck size={14} className="inline mr-1"/>
            {submitting ? "Submitting…" : "Submit Report & Clock Out"}
          </button>
        </div>
      )}
    </div>
  );
}

function Section({ title, icon, subtitle, right, children, testId }) {
  return (
    <div className="mb-5 rounded-2xl p-4"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid={testId}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-base font-bold" style={{ color: colors.onSurface }}>{title}</h2>
          {subtitle && <span className="text-xs" style={{ color: colors.muted }}>· {subtitle}</span>}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}
