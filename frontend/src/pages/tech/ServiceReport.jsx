/**
 * Phase 18B follow-up — Service Report page.
 * Auto-loads the correct template (pool/landscape/generic) for the given job,
 * autosaves every 5s while dirty, enforces 10-photo cap, and finalizes with
 * "Submit Report & Clock Out".
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import { Camera, X, Save, ShieldCheck, ChevronLeft, CheckSquare, Square, MapPin, Key, ClipboardCheck, FlaskConical, Beaker, Plus, Trash2, Timer, Share2, Video, Upload } from "lucide-react";
// Feb-2026 · Chemistry required-readings gate — shared with backend.
import { missingCoreReadings } from "@/utils/chemistryGate";
import { compressImageIfNeeded } from "@/lib/imageCompress";

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
  const [postSubmitToast, setPostSubmitToast] = useState("");
  const [chemGateError, setChemGateError] = useState(null);
  // Feb-2026 · Live client-side mirror of the backend chemistry
  // gate.  Same rules as ``utils/chemistryGate.js`` — declared
  // BEFORE the early-return branches so it obeys Rules of Hooks
  // (a component that render-returns from ``if (busy && !report)``
  // must call the same hooks on every render).
  const coreMissingLive = React.useMemo(
    () => missingCoreReadings(report?.chemical_readings || []),
    [report?.chemical_readings],
  );
  // Phase 22 · Feb 2026 — Share-visit clipboard state. Populated once
  // the report is submitted AND carries a ``public_uuid``.
  const [shareToast, setShareToast] = useState("");
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

  // Phase 27.3 · Water photo analyzer state (Wave C UI hook).
  const [showWaterAnalyzer, setShowWaterAnalyzer] = useState(false);
  const [waterBusy, setWaterBusy] = useState(false);
  const [waterResult, setWaterResult] = useState(null);
  const [waterError, setWaterError] = useState("");
  const runWaterAnalysis = useCallback(async () => {
    setWaterBusy(true); setWaterError(""); setWaterResult(null);
    try {
      const photos = report?.photos || [];
      const photo = photos[photos.length - 1];
      if (!photo?.url) {
        setWaterError("Add a water photo to the report first, then try again.");
        return;
      }
      const readings = {};
      (report?.chemical_readings || []).forEach((r) => {
        if (r.value != null) readings[r.key || r.name] = r.value;
      });
      const body = { photo_url: photo.url,
                       current_readings: readings,
                       job_id: id };
      const r = await api.post("/service-report/analyze-water-photo", body);
      setWaterResult(r);
    } catch (e) { setWaterError(e.message || "Analysis failed"); }
    finally { setWaterBusy(false); }
  }, [report, id]);
  const addRecToChemicals = (rec) => {
    const next = [...(report.chemicals_added || []),
                    { name: rec.chemical, amount: rec.amount,
                      unit: rec.unit,
                      notes: `AI recommended · ${rec.urgency}` }];
    setReport({ ...report, chemicals_added: next });
    dirtyRef.current = true; setDirty(true);
  };

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
        // Feb-2026 · Repair-mode notes. Persisted on every autosave
        // regardless of ``work_class`` (they're safe empty strings
        // for a standard service report), so a mid-visit retag from
        // service → repair doesn't lose in-progress text.
        internal_notes: report.internal_notes,
        customer_notes: report.customer_notes,
      };
      await api.patch(`/jobs/${id}/service-report`, patch);
      dirtyRef.current = false;
      setDirty(false);
      setSaveState("saved");
      setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1500);
    } catch (_e) {
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
  // Feb-2026 · Repair-mode form branch. A report inherits
  // ``work_class`` from its parent job at bootstrap. Repair reports
  // omit chemistry / chemicals / checklist and expose Internal +
  // External notes + a video uploader; photos remain shared. The
  // submit gate for repair is UNGATED (backend also skips the
  // chemistry-missing 422 when ``work_class == "repair"``).
  const isRepair = (report.work_class || "").toLowerCase() === "repair";
  const photoCount = (report.photos || []).length;
  const remaining = PHOTO_CAP - photoCount;
  // Feb-2026 · Video counts for the repair uploader UI.
  const videoCount = (report.videos || []).length;
  const VIDEO_CAP = 3;   // matches Phase 27 backend policy

  const _updChemistryReading = (idx, patch) => {
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

  const addPhoto = async (rawFile) => {
    if (remaining <= 0) { alert("10-photo cap reached"); return; }
    // Feb 2026 · iOS field-upload timeout fix — shrink modern iPhone
    // photos before the base64 blowup on /api/jobs/{jid}/photos.
    const file = await compressImageIfNeeded(rawFile);
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

  /**
   * Feb-2026 · Repair-mode video upload.
   *
   * Uses the modern ``/api/service-reports/{id}/media`` endpoint which
   * accepts multipart form-data for both photos and videos (Phase 27
   * infra: 3 videos × 60s × 100 MB). Kept scoped to repair mode so
   * the standard pool-service flow (legacy ``/api/jobs/{id}/photos``)
   * stays untouched.
   *
   * Errors surface via ``alert()`` — matches the sibling ``addPhoto``
   * UX pattern in this component.
   */
  const addRepairVideo = async (file) => {
    if (!file) return;
    if (videoCount >= VIDEO_CAP) {
      alert(`Max ${VIDEO_CAP} videos per report.`);
      return;
    }
    // 100 MB hard cap — matches Phase 27 backend policy. Surface a
    // clear message BEFORE the network call so users don't wait for
    // a slow upload to fail server-side.
    const MAX_BYTES = 100 * 1024 * 1024;
    if (file.size > MAX_BYTES) {
      alert("Video exceeds the 100 MB per-file cap. Please trim and retry.");
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", "video");
    try {
      // Direct ``fetch`` because ``api`` wrapper JSON-encodes bodies
      // and this endpoint needs multipart.
      const base = process.env.REACT_APP_BACKEND_URL || "";
      const token = localStorage.getItem("token") || "";
      const rsp = await fetch(
        `${base}/api/service-reports/${report.id}/media`,
        { method: "POST", body: fd,
           headers: { Authorization: `Bearer ${token}` } },
      );
      if (!rsp.ok) {
        const t = await rsp.text().catch(() => "");
        throw new Error(t || `Upload failed (${rsp.status})`);
      }
      const j = await rsp.json();
      // Endpoint returns the updated media list — merge into report.
      setReport({
        ...report,
        videos: j.videos || report.videos || [],
        photos: j.photos || report.photos || [],
      });
    } catch (e) {
      alert(e.message || "Video upload failed");
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
      if (submitted?.invoice_id) {
        const iid = String(submitted.invoice_id);
        setPostSubmitToast(`Report submitted · Invoice #${iid.slice(0, 8)} created`);
        // Give the user 2s to notice before we navigate away.
        setTimeout(() => navigate("/schedule/today"), 2000);
      } else {
        navigate("/schedule/today");
      }
    } catch (e) {
      // Feb-2026 · Defense-in-depth — the button is client-gated by
      // ``coreMissing``, but if a stale UI slips a submit past that
      // guard the backend returns 422 with a structured payload.
      // Surface it inline instead of the generic alert so the tech
      // does NOT lose their other entered data.
      const detail = e?.response?.data?.detail || e?.detail;
      if (
        detail && typeof detail === "object"
        && detail.detail === "chemistry_core_readings_missing"
      ) {
        setChemGateError(detail);
      } else {
        alert(e.message);
      }
    } finally { setSubmitting(false); }
  };

  const uncheckedCount = (report.checklist_items || []).filter((c) => !c.checked).length;
  const locked = !!report.submitted_at;

  // Phase 22 · Feb 2026 — Share visit link. Builds the public portal
  // URL and copies it to the OS clipboard. Only rendered when the
  // report is submitted AND carries a ``public_uuid`` (backend guarantees
  // both on submit — legacy reports get backfilled).
  const publicUuid = report?.public_uuid;
  const shareUrl = publicUuid
    ? `${(typeof window !== "undefined" ? window.location.origin : (process.env.REACT_APP_BACKEND_URL || "")).replace(/\/$/, "")}/portal/service/${publicUuid}`
    : "";
  const copyShareLink = async () => {
    if (!shareUrl) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(shareUrl);
      } else {
        // Fallback for older browsers / non-secure contexts.
        const ta = document.createElement("textarea");
        ta.value = shareUrl;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } finally { document.body.removeChild(ta); }
      }
      setShareToast("Link copied — you can text this to the customer.");
      setTimeout(() => setShareToast(""), 3000);
    } catch (_e) {
      setShareToast("Copy failed — long-press to copy manually.");
      setTimeout(() => setShareToast(""), 3000);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="svc-report-page">
      {postSubmitToast && (
        <div className="fixed top-4 right-4 z-50 rounded-xl shadow-xl p-4 max-w-sm"
             style={{ background: "#059669", color: "#fff" }}
             data-testid="svc-report-invoice-toast">
          <div className="text-xs uppercase font-bold tracking-wider opacity-80">
            ✓ Auto-invoiced
          </div>
          <div className="text-sm font-bold mt-1">{postSubmitToast}</div>
        </div>
      )}
      {shareToast && (
        <div className="fixed top-4 right-4 z-50 rounded-xl shadow-xl p-4 max-w-sm"
             style={{ background: "#2563eb", color: "#fff", marginTop: postSubmitToast ? 96 : 0 }}
             data-testid="svc-report-share-toast">
          <div className="text-xs uppercase font-bold tracking-wider opacity-80">
            ✓ Copied
          </div>
          <div className="text-sm font-bold mt-1">{shareToast}</div>
        </div>
      )}
      <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm mb-3"
              style={{ color: colors.muted }} data-testid="svc-report-back">
        <ChevronLeft size={16}/> Back
      </button>

      <div className="rounded-2xl p-5 mb-5 text-white flex items-start justify-between gap-4 flex-wrap"
           style={{ background: gradients.navyToGreen.css }} data-testid="svc-report-header">
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
          {locked && publicUuid && (
            <button onClick={copyShareLink}
                    className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition"
                    style={{ background: "rgba(255,255,255,0.15)",
                             color: "#fff",
                             border: "1px solid rgba(255,255,255,0.35)" }}
                    data-testid="svc-report-share-visit">
              <Share2 size={12} /> Share visit
            </button>
          )}
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

      {isPool && !isRepair && (
        <Section title="Chemical Readings" icon={<FlaskConical size={16}/>}
                 testId="svc-report-readings">
          <button
            type="button"
            onClick={() => setShowWaterAnalyzer(true)}
            className="mb-3 px-3 py-2 text-xs font-bold rounded-xl inline-flex items-center gap-1"
            style={{ backgroundColor: colors.brandTertiary,
                     color: colors.brand,
                     border: `1px solid ${colors.brand}30` }}
            data-testid="svc-report-analyze-water-btn">
            🔬 Analyze water photo (Claude Vision)
          </button>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {(report.chemical_reading_fields || []).map((field) => {
              const key = field.key || field.name;
              const existingIdx = (report.chemical_readings || []).findIndex(
                (r) => (r.key || r.name) === key
              );
              const r = existingIdx >= 0
                ? report.chemical_readings[existingIdx]
                : { key, name: field.name, unit: field.unit, value: null };
              const opts = field.options || [];
              const upd = (patch) => {
                let arr = [...(report.chemical_readings || [])];
                if (existingIdx >= 0) {
                  arr[existingIdx] = { ...arr[existingIdx], ...patch, ts: new Date().toISOString() };
                } else {
                  arr = [...arr, { ...r, ...patch, ts: new Date().toISOString() }];
                }
                setReport({ ...report, chemical_readings: arr });
                markDirty();
              };
              return (
                <div key={key} data-testid={`svc-reading-${key}`}>
                  <label className="text-xs font-bold uppercase tracking-wider block mb-1"
                         style={{ color: colors.muted }}>
                    {field.name} {field.unit ? `(${field.unit})` : ""}
                  </label>
                  {opts.length > 0 ? (
                    <select value={r.value == null ? "" : String(r.value)} disabled={locked}
                            onChange={(e) => upd({
                              value: e.target.value === "" ? null : parseFloat(e.target.value),
                            })}
                            className="w-full px-2 py-2 rounded-lg text-sm"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface }}>
                      <option value="">—</option>
                      {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input type="number" step="any"
                           value={r.value ?? ""} disabled={locked}
                           onChange={(e) => upd({
                             value: e.target.value === "" ? null : parseFloat(e.target.value),
                           })}
                           className="w-full px-2 py-2 rounded-lg text-sm"
                           style={{ border: `1px solid ${colors.border}` }}/>
                  )}
                  {field.ideal && (
                    <div className="text-[10px] mt-1" style={{ color: colors.muted }}>
                      ideal {field.ideal}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {isPool && !isRepair && (
        <Section title="Chemicals Added" icon={<Beaker size={16}/>}
                 testId="svc-report-chems"
                 right={!locked && (
                   <button onClick={addChemical}
                           className="text-sm font-bold flex items-center gap-1"
                           style={{ color: colors.brand }}
                           data-testid="svc-add-chemical">
                     <Plus size={14}/> Add another chemical
                   </button>
                 )}>
          {(report.chemicals_added || []).length === 0 && (
            <div className="text-sm" style={{ color: colors.muted }}>No chemicals added yet.</div>
          )}
          <div className="space-y-2">
            {(report.chemicals_added || []).map((c, i) => {
              const catalogEntry = (report.chemicals_catalog || []).find((k) => k.name === c.name);
              const amountOpts = catalogEntry?.amount_options || [];
              const unitOpts = catalogEntry?.common_units?.length
                ? catalogEntry.common_units
                : (report.chemical_units && report.chemical_units.length
                    ? report.chemical_units : CHEM_UNITS);
              return (
                <div key={c.id || i}
                     className="grid grid-cols-12 gap-2 items-center"
                     data-testid={`svc-chem-row-${i}`}>
                  <select value={c.name} disabled={locked}
                          onChange={(e) => {
                            const nm = e.target.value;
                            const entry = (report.chemicals_catalog || []).find((k) => k.name === nm);
                            updChemical(i, { name: nm, unit: entry?.default_unit || c.unit });
                          }}
                          className="col-span-6 px-2 py-2 rounded-lg text-sm"
                          style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
                          data-testid={`svc-chem-name-${i}`}>
                    <option value="">Select chemical…</option>
                    {(report.chemicals_catalog || []).map((k) => (
                      <option key={k.name} value={k.name}>{k.name}</option>
                    ))}
                  </select>
                  {amountOpts.length > 0 ? (
                    <select value={c.amount} disabled={locked}
                            onChange={(e) => updChemical(i, { amount: e.target.value })}
                            className="col-span-3 px-2 py-2 rounded-lg text-sm"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
                            data-testid={`svc-chem-amount-${i}`}>
                      <option value="">—</option>
                      {amountOpts.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input type="number" step="any" value={c.amount} disabled={locked}
                           onChange={(e) => updChemical(i, { amount: e.target.value })}
                           placeholder="Amount"
                           className="col-span-3 px-2 py-2 rounded-lg text-sm"
                           style={{ border: `1px solid ${colors.border}` }}
                           data-testid={`svc-chem-amount-${i}`}/>
                  )}
                  <select value={c.unit} disabled={locked}
                          onChange={(e) => updChemical(i, { unit: e.target.value })}
                          className="col-span-2 px-2 py-2 rounded-lg text-sm"
                          style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
                          data-testid={`svc-chem-unit-${i}`}>
                    {unitOpts.map((u) => <option key={u} value={u}>{u}</option>)}
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
              );
            })}
          </div>
        </Section>
      )}

      {/* Checklist — hidden on repair mode per Feb-2026 spec */}
      {!isRepair && (
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
      )}

      {/* Feb-2026 · Repair-mode video uploader + notes. Rendered
          ONLY for ``work_class == "repair"`` reports. Uses the modern
          ``/api/service-reports/{id}/media`` endpoint (accepts both
          photos and videos natively; matches the Phase 27 policy of
          3 videos × 60s × 100 MB). Standard service reports keep the
          legacy ``/api/jobs/{id}/photos`` flow unchanged. */}
      {isRepair && (
        <Section title="Videos"
                 icon={<Video size={16}/>}
                 subtitle={`${videoCount} / ${VIDEO_CAP} · up to 60s · 100 MB each`}
                 testId="id-repair-log-videos">
          {(report.videos || []).length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
              {report.videos.map((v, i) => (
                <div key={v.id || i}
                     className="rounded-xl overflow-hidden bg-black"
                     data-testid={`id-repair-log-video-${i}`}>
                  <video controls preload="metadata"
                         src={v.stream_url || v.url}
                         className="w-full h-40 object-contain bg-black" />
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm mb-3" style={{ color: colors.muted }}>
              No videos yet.
            </div>
          )}
          {!locked && videoCount < VIDEO_CAP && (
            <label className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold cursor-pointer"
                   style={{ backgroundColor: colors.surface,
                            border: `1px dashed ${colors.border}`,
                            color: colors.onSurface }}
                   data-testid="id-repair-log-video-upload-label">
              <Upload size={14}/> Upload video
              <input type="file"
                     accept="video/mp4,video/quicktime,video/webm,video/x-m4v,video/avi"
                     className="hidden"
                     onChange={(e) => e.target.files?.[0] && addRepairVideo(e.target.files[0])}
                     data-testid="id-repair-log-videos"/>
            </label>
          )}
          <div className="text-[11px] mt-2" style={{ color: colors.muted }}>
            Tip · keep clips under 60&nbsp;seconds. Larger files
            (max 100 MB) upload but take longer on cell signal.
          </div>
        </Section>
      )}

      {isRepair && (
        <Section title="Internal Notes"
                 testId="id-repair-log-notes-internal-section">
          <div className="text-[11px] mb-2" style={{ color: colors.muted }}>
            Internal only. Visible to admin + tech in workstream.
            <b> NOT surfaced in customer portal.</b>
          </div>
          <textarea rows={4}
                    value={report.internal_notes || ""}
                    disabled={locked}
                    onChange={(e) => {
                      setReport({ ...report, internal_notes: e.target.value });
                      markDirty();
                    }}
                    placeholder="Root cause · parts used · warranty status · anything the office needs to know…"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ border: `1px solid ${colors.border}`,
                             background: colors.surface }}
                    data-testid="id-repair-log-notes-internal" />
        </Section>
      )}

      {isRepair && (
        <Section title="External Notes"
                 testId="id-repair-log-notes-external-section">
          <div className="text-[11px] mb-2" style={{ color: colors.muted }}>
            <b>Visible to the customer</b> in their portal service history.
          </div>
          <textarea rows={4}
                    value={report.customer_notes || ""}
                    disabled={locked}
                    onChange={(e) => {
                      setReport({ ...report, customer_notes: e.target.value });
                      markDirty();
                    }}
                    placeholder="What the customer should know — what was fixed, next steps, follow-up dates…"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ border: `1px solid ${colors.border}`,
                             background: colors.surface }}
                    data-testid="id-repair-log-notes-external" />
        </Section>
      )}

      {/* Notes — legacy free-text block on standard service reports */}
      {!isRepair && (
        <Section title="Notes" testId="svc-report-notes-section">
        <textarea rows={4} value={report.notes || ""} disabled={locked}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Anything the customer or dispatcher should know…"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid="svc-report-notes"/>
      </Section>
      )}

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
          <button onClick={submitAndClockOut}
                  disabled={submitting || (!isRepair && coreMissingLive.length > 0)}
                  title={
                    !isRepair && coreMissingLive.length > 0
                      ? `Missing: ${coreMissingLive.join(", ")}`
                      : undefined
                  }
                  className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                  style={{ background: (!isRepair && coreMissingLive.length > 0) ? colors.muted : gradients.navyToGreen.css }}
                  data-testid={isRepair ? "id-repair-log-submit" : "svc-report-submit"}>
            <ShieldCheck size={14} className="inline mr-1"/>
            {submitting ? "Submitting…" : "Submit Report & Clock Out"}
          </button>
        </div>
      )}
      {chemGateError && (
        <div className="mx-3 mt-2 px-3 py-2 rounded-lg text-sm"
             role="alert"
             data-testid="chem-gate-error-banner"
             style={{ backgroundColor: "#FEF3C7", color: "#78350F",
                       border: "1px solid #FDE68A" }}>
          <b>Cannot submit yet.</b> Missing required chemistry readings:{" "}
          {(chemGateError.missing_labels || chemGateError.missing_fields || []).join(", ")}.
          <button type="button" onClick={() => setChemGateError(null)}
                  className="ml-3 underline text-xs"
                  data-testid="chem-gate-error-dismiss">Dismiss</button>
        </div>
      )}

      {showWaterAnalyzer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
             data-testid="water-analyzer-modal">
          <div className="rounded-2xl w-full max-w-lg p-5 max-h-[90vh] overflow-auto"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-bold"
                  style={{ color: colors.onSurface }}>
                🔬 Water photo analysis
              </h2>
              <button onClick={() => setShowWaterAnalyzer(false)}
                      className="p-2" style={{ color: colors.muted }}>×</button>
            </div>
            {!waterResult && !waterBusy && !waterError ? (
              <button onClick={runWaterAnalysis}
                      className="w-full py-2 text-sm font-bold rounded-xl"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="water-analyzer-run">
                Analyze latest photo
              </button>
            ) : null}
            {waterBusy ? (
              <div className="text-center py-4 text-sm"
                   style={{ color: colors.muted }}>Analyzing…</div>
            ) : null}
            {waterError ? (
              <div className="rounded-xl p-3 text-sm"
                   style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                   data-testid="water-analyzer-error">{waterError}</div>
            ) : null}
            {waterResult ? (
              <div data-testid="water-analyzer-result">
                {waterResult.mocked ? (
                  <div className="rounded-xl p-2 mb-2 text-xs"
                       style={{ backgroundColor: "#FEF3C7",
                                color: "#92400E" }}>
                    MOCKED · {waterResult.reason || "unknown"}
                  </div>
                ) : null}
                <div className="mb-2 text-sm"
                     style={{ color: colors.onSurface }}>
                  <b>Clarity:</b> {waterResult.clarity || "—"}
                </div>
                {waterResult.issues?.length ? (
                  <div className="mb-3">
                    <div className="text-xs font-bold mb-1"
                         style={{ color: colors.muted }}>Issues</div>
                    <ul className="text-sm list-disc pl-4"
                        style={{ color: colors.onSurface }}>
                      {waterResult.issues.map((i, idx) =>
                        <li key={idx}>{i}</li>)}
                    </ul>
                  </div>
                ) : null}
                <div className="text-xs font-bold mb-1"
                     style={{ color: colors.muted }}>Recommendations</div>
                {(waterResult.recommendations || []).map((rec, i) => (
                  <div key={i}
                       className="rounded-lg p-2 mb-2 flex items-start gap-2"
                       style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}` }}
                       data-testid={`water-rec-${i}`}>
                    <div className="flex-1 text-sm"
                         style={{ color: colors.onSurface }}>
                      <b>{rec.chemical}</b> · {rec.amount} {rec.unit}
                      <span className="text-xs ml-2"
                            style={{ color: colors.muted }}>
                        ({rec.urgency})
                      </span>
                      <div className="text-xs mt-1"
                           style={{ color: colors.muted }}>
                        {rec.reasoning}
                      </div>
                    </div>
                    <button onClick={() => addRecToChemicals(rec)}
                            className="px-2 py-1 text-xs font-bold rounded"
                            style={{ backgroundColor: colors.brand,
                                     color: "#fff" }}
                            data-testid={`water-rec-add-${i}`}>
                      + Add
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
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
