import React from "react";
import { toast } from "sonner";
import {
  Plus, Trash2, Copy as CopyIcon, Printer, Send, X, Info, Save,
  Camera, Mic, Square, Sparkles, AlertTriangle, Paintbrush, Paperclip,
  Loader2, CheckCircle2,
} from "lucide-react";
import { api, api_base } from "@/api";
import { TOKEN_KEY } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import CustomerCombobox from "@/components/customers/CustomerCombobox";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

/**
 * Feb-2026 · Pool Repair Pricing Calculator.
 *
 * Route `/ops/repair-calculator` (admin + super_admin only — techs
 * hidden by the App.js route guard).
 *
 * Left column  = input form (parts / labor / optional per-quote overrides).
 * Right column = live-computed quote preview + profit-margin tier tag
 *                + action row (Copy / Print / Email).
 *
 * Backed by /api/ops/repair-calculator/*.
 */

const MONEY = (v) => `$${(Number(v) || 0).toFixed(2)}`;
const PCT = (v) => `${(Number(v) * 100).toFixed(1)}%`;


export default function RepairCalculatorPage() {
  const [config, setConfig] = React.useState(null);
  const [parts, setParts] = React.useState([
    { name: "", cost: "" }, { name: "", cost: "" }, { name: "", cost: "" },
  ]);
  const [laborHours, setLaborHours] = React.useState("");
  const [override, setOverride] = React.useState({});
  const [quote, setQuote] = React.useState(null);
  const [customers, setCustomers] = React.useState([]);
  const [customerId, setCustomerId] = React.useState("");
  const [adHocEmail, setAdHocEmail] = React.useState("");
  const [emailBusy, setEmailBusy] = React.useState(false);
  const [showEmailConfirm, setShowEmailConfirm] = React.useState(false);
  const [showConfigEditor, setShowConfigEditor] = React.useState(false);
  // Phase 25 · AI Photo/Voice → repair estimate.
  const [aiResult, setAiResult] = React.useState(null);
  const [aiBusy, setAiBusy] = React.useState(null);       // "photo" | "voice" | null
  const [aiError, setAiError] = React.useState(null);
  // Feb-2026 · K55.a — SuperCool connection state removed as part
  // of the sunset (PHASE_K55_a_FRONTEND_REMOVAL.md).  Buttons no
  // longer gate on ``supercoolConnected``; image editing runs
  // through the Emergent nano-banana-2 fallback (see K56).
  // ``photoDataUrl`` is the last uploaded pool photo encoded as a
  // data URI; used both as the BEFORE preview and as the
  // ``source_image_url`` payload for /api/media/image/edit.
  const [photoDataUrl, setPhotoDataUrl] = React.useState(null);
  const [afterRender, setAfterRender] = React.useState(null);   // {url, prompt, provider, attached}
  const [renderBusy, setRenderBusy] = React.useState(false);

  React.useEffect(() => {
    api.get("/ops/repair-calculator/config").then(setConfig).catch(() => {});
    api.get("/customers?is_active=true").then((r) => {
      const list = Array.isArray(r) ? r : (r?.customers || r?.items || []);
      setCustomers(list.slice(0, 500));
    }).catch(() => {});
    // Feb-2026 · K55.a — SuperCool status polling removed.
  }, []);

  // Live-recompute quote whenever any input changes.
  React.useEffect(() => {
    const validParts = parts
      .map((p) => ({ name: p.name || "",
                       cost: Number.parseFloat(p.cost) || 0 }))
      .filter((p) => p.cost > 0);
    const payload = {
      parts: validParts,
      labor_hours: Number.parseFloat(laborHours) || 0,
      ...override,
    };
    let cancelled = false;
    api.post("/ops/repair-calculator/quote", payload).then((q) => {
      if (!cancelled) setQuote(q);
    }).catch(() => { if (!cancelled) setQuote(null); });
    return () => { cancelled = true; };
  }, [parts, laborHours, override]);

  const setPartField = (i, k, v) =>
    setParts((prev) => prev.map((p, idx) => idx === i ? { ...p, [k]: v } : p));
  const addPart = () => setParts((prev) => [...prev, { name: "", cost: "" }]);
  const removePart = (i) =>
    setParts((prev) => prev.length === 1 ? prev : prev.filter((_, idx) => idx !== i));

  const doCopy = async () => {
    if (!quote) return;
    const text = renderPlainText(quote);
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Quote copied to clipboard");
    } catch { toast.error("Clipboard blocked"); }
  };

  const doPrint = () => {
    if (!quote) return;
    const w = window.open("", "_blank", "width=800,height=900");
    if (!w) { toast.error("Popup blocked"); return; }
    w.document.write(`<pre style="font:14px/1.5 system-ui,Arial,sans-serif;padding:24px">${renderPlainText(quote)}</pre>`);
    w.document.close();
    w.focus();
    w.print();
  };

  const doEmail = async () => {
    if (!quote) return;
    if (!customerId && !adHocEmail.trim()) {
      toast.error("Pick a customer or enter an ad-hoc email");
      return;
    }
    setEmailBusy(true);
    try {
      // Phase B follow-up — when a concept render is attached, prepend
      // a note that surfaces the AI image URL + the legal caption so
      // the customer sees it inline in the email body. Snapshot also
      // includes the URL so admins can audit later.
      const attachedNote = afterRender?.attached && afterRender?.url
        ? `AI-generated concept render — actual results may vary.\n${afterRender.url}\n\n`
        : "";
      const enrichedSnapshot = afterRender?.attached && afterRender?.url
        ? { ...quote, ai_after_render_url: afterRender.url,
              ai_after_render_prompt: afterRender.prompt }
        : quote;
      const res = await api.post("/ops/repair-calculator/email", {
        customer_id: customerId || null,
        ad_hoc_email: adHocEmail.trim() || null,
        subject: "Your repair estimate",
        note: attachedNote || undefined,
        quote_snapshot: enrichedSnapshot,
      });
      if (res?.delivered) {
        toast.success("Quote emailed");
      } else {
        toast.error(`Recorded but not delivered: ${res?.delivery_error || "unknown"}`);
      }
      setShowEmailConfirm(false);
    } catch (e) {
      toast.error(e?.message || "Email failed");
    } finally { setEmailBusy(false); }
  };

  const tierColor = quote
    ? quote.profit_margin_tier === "green" ? "#16A34A"
    : quote.profit_margin_tier === "yellow" ? "#CA8A04" : "#DC2626"
    : colors.muted;

  // Phase 25 — hydrate the parts + labor hours field from an AI result.
  // Existing user-typed rows are preserved when they already have a cost;
  // empty rows get overwritten and new AI-suggested parts are appended.
  const hydrateFromAi = React.useCallback((result) => {
    if (!result) return;
    const aiParts = (result.parts || []).filter(
      (p) => Number(p?.cost) > 0 || (p?.name || "").trim(),
    );
    setParts((prev) => {
      const kept = prev.filter((p) => Number.parseFloat(p.cost) > 0);
      const merged = [
        ...kept,
        ...aiParts.map((p) => ({
          name: p.name || "",
          cost: Number(p.cost) > 0 ? String(p.cost) : "",
        })),
      ];
      // Always leave a trailing blank row so admins can add more.
      if (merged.length === 0 || (merged[merged.length - 1].name || merged[merged.length - 1].cost)) {
        merged.push({ name: "", cost: "" });
      }
      return merged;
    });
    if (Number(result.labor_hours_estimated) > 0) {
      setLaborHours(String(result.labor_hours_estimated));
    }
  }, []);

  const runAiEstimate = React.useCallback(async (endpoint, formData) => {
    setAiBusy(endpoint);
    setAiError(null);
    // Every new AI run invalidates the previous after-render — the
    // photo (and therefore the BEFORE image) has changed.
    setAfterRender(null);
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const res = await fetch(`${api_base()}/ai/estimate-from-${endpoint}`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data?.detail || `Request failed (${res.status})`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      if (data?.error === "voice_provider_disabled") {
        toast.error("Voice memo is disabled — the OpenAI Whisper key isn't configured yet.");
        setAiError({ code: "voice_provider_disabled",
                       message: data.reason || "OPENAI_API_KEY not configured." });
        return;
      }
      if (data?.error) {
        toast.error(`AI estimate failed: ${data.reason || data.error}`);
        setAiError({ code: data.error, message: data.reason || "" });
        return;
      }
      setAiResult(data);
      hydrateFromAi(data);
      toast.success(
        endpoint === "photo"
          ? "Photo analyzed — parts hydrated."
          : "Voice memo analyzed — parts hydrated.",
      );
    } catch (e) {
      const msg = e?.message || "AI estimate failed";
      toast.error(msg);
      setAiError({ code: "network_error", message: msg });
    } finally {
      setAiBusy(null);
    }
  }, [hydrateFromAi]);

  // Phase B follow-up · AI Photo-to-Estimate before/after ————————————
  //
  // Builds a prompt from the AI ``raw_analysis`` + top matched parts
  // and hits ``POST /api/media/image/edit`` with the customer's photo
  // (data URI) as ``source_image_url``. Result is rendered next to the
  // BEFORE image with a strict legal caption.
  const buildAfterPrompt = React.useCallback((result) => {
    const rawAnalysis = (result?.raw_analysis || "").trim();
    const matched = (result?.parts || [])
      .filter((p) => p?.source === "pricebook_match" && p?.name)
      .slice(0, 5)
      .map((p) => p.name);
    const partsLine = matched.length
      ? `Simulate the same pool/landscape after these repairs are complete: ${matched.join(", ")}.`
      : "Simulate the same pool/landscape after all obvious repairs are complete.";
    const brand = " Photorealistic concept render, natural daylight, restored equipment in clean working order, tidy surrounding area, no logos or watermarks, no text overlays.";
    const contextLine = rawAnalysis
      ? ` Original technician analysis: ${rawAnalysis}`
      : "";
    return `${partsLine}${contextLine}${brand}`.slice(0, 1800);
  }, []);

  const generateAfterRender = React.useCallback(async () => {
    if (!aiResult || !photoDataUrl) return;
    // Feb-2026 · K55.a — SuperCool connection gate removed.
    setRenderBusy(true);
    try {
      const prompt = buildAfterPrompt(aiResult);
      const r = await api.post("/media/image/edit", {
        prompt,
        source_image_url: photoDataUrl,
        aspect_ratio: "4:5",
        surface: "estimate",
      });
      setAfterRender({
        url: r?.url || null,
        prompt,
        provider: r?.provider,
        image_id: r?.image_id,
        attached: false,
      });
      toast.success(`Concept render ready · ${r?.provider || "emergent"}`);
    } catch (e) {
      const msg = e?.message || "Render failed";
      if (/daily_limit_reached/i.test(msg)) {
        toast.error("Daily image-generation limit reached. Resets at 00:00 UTC.");
      } else {
        toast.error(msg);
      }
    } finally { setRenderBusy(false); }
  }, [aiResult, photoDataUrl, buildAfterPrompt]);

  const attachRenderToEmail = React.useCallback(() => {
    if (!afterRender?.url) return;
    setAfterRender((prev) => prev ? { ...prev, attached: true } : prev);
    toast.success("Concept render will be attached to the next email.");
  }, [afterRender]);

  return (
    <SafeScrollContainer
      className="p-6 max-w-6xl mx-auto"
      data-testid="repair-calculator-page"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h1
            className="text-2xl font-bold mb-1"
            style={{ color: colors.onSurface }}
            data-testid="repair-calculator-title"
          >
            Repair Pricing Calculator
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Enter parts + labor, review the live estimate, and email a
            clean quote to the customer.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowConfigEditor((v) => !v)}
          className="px-3 py-1.5 rounded-lg text-sm font-semibold"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
          }}
          data-testid="repair-calculator-config-toggle"
        >
          Tenant defaults
        </button>
      </div>

      {showConfigEditor && config ? (
        <ConfigEditor
          config={config}
          onSaved={(next) => {
            setConfig(next);
            setShowConfigEditor(false);
            toast.success("Defaults saved");
          }}
        />
      ) : null}

      <AiCtaBar
        busy={aiBusy}
        onPhoto={(fd) => runAiEstimate("photo", fd)}
        onVoice={(fd) => runAiEstimate("voice", fd)}
        onPhotoDataUrl={setPhotoDataUrl}
      />

      {aiResult ? (
        <AiResultBanner
          result={aiResult}
          onDismiss={() => { setAiResult(null); setAfterRender(null); }}
        />
      ) : null}

      {aiResult && photoDataUrl ? (
        <BeforeAfterRender
          photoDataUrl={photoDataUrl}
          afterRender={afterRender}
          renderBusy={renderBusy}
          onGenerate={generateAfterRender}
          onAttachToEmail={attachRenderToEmail}
        />
      ) : null}

      {aiError && aiError.code === "voice_provider_disabled" ? (
        <div
          className="rounded-xl p-3 mb-3 flex items-start gap-2"
          style={{ backgroundColor: "#FEF3C7", border: "1px solid #FCD34D", color: "#92400E" }}
          data-testid="repair-calc-ai-voice-disabled"
        >
          <AlertTriangle size={16} />
          <div className="text-sm">
            <b>Voice memo is disabled</b> — the OpenAI Whisper API key isn't configured
            on this pod. Add <code>OPENAI_API_KEY</code> in the backend env and the button
            will flip live automatically. Photo analysis still works.
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <InputColumn
          parts={parts}
          setPartField={setPartField}
          addPart={addPart}
          removePart={removePart}
          laborHours={laborHours}
          setLaborHours={setLaborHours}
          override={override}
          setOverride={setOverride}
          config={config}
        />
        <PreviewColumn
          quote={quote}
          tierColor={tierColor}
          onCopy={doCopy}
          onPrint={doPrint}
          onEmail={() => setShowEmailConfirm(true)}
          canEmail={!!quote && quote.estimate_total > 0}
        />
      </div>

      {showEmailConfirm ? (
        <EmailConfirmModal
          quote={quote}
          customers={customers}
          customerId={customerId}
          setCustomerId={setCustomerId}
          adHocEmail={adHocEmail}
          setAdHocEmail={setAdHocEmail}
          busy={emailBusy}
          onClose={() => setShowEmailConfirm(false)}
          onSend={doEmail}
          afterRender={afterRender}
        />
      ) : null}
    </SafeScrollContainer>
  );
}


function AiCtaBar({ busy, onPhoto, onVoice, onPhotoDataUrl }) {
  const fileInputRef = React.useRef(null);
  const [recording, setRecording] = React.useState(false);
  const mediaRecorderRef = React.useRef(null);
  const audioChunksRef = React.useRef([]);
  const streamRef = React.useRef(null);

  const handlePhotoPicked = (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) {
      toast.error("Image is larger than 10 MB. Please choose a smaller file.");
      return;
    }
    const fd = new FormData();
    fd.append("file", f, f.name || "photo.jpg");
    // Phase B follow-up — expose the raw photo as a data URL so the
    // parent can pass it to /api/media/image/edit as source_image_url.
    // FileReader failures fall through silently — the AI photo estimate
    // still runs, only the after-render feature is affected.
    if (onPhotoDataUrl) {
      const reader = new FileReader();
      reader.onload = () => onPhotoDataUrl(String(reader.result || "") || null);
      reader.onerror = () => onPhotoDataUrl(null);
      reader.readAsDataURL(f);
    }
    onPhoto(fd);
  };

  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      toast.error("Microphone recording isn't supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mr = new MediaRecorder(stream);
      audioChunksRef.current = [];
      mr.ondataavailable = (evt) => {
        if (evt.data && evt.data.size > 0) audioChunksRef.current.push(evt.data);
      };
      mr.onstop = () => {
        const mime = mr.mimeType || "audio/webm";
        const blob = new Blob(audioChunksRef.current, { type: mime });
        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        if (blob.size === 0) {
          toast.error("No audio captured — try again.");
          return;
        }
        if (blob.size > 10 * 1024 * 1024) {
          toast.error("Recording is larger than 10 MB. Keep it under 60 seconds.");
          return;
        }
        const ext = mime.includes("ogg") ? "ogg" : mime.includes("mp4") ? "mp4" : "webm";
        const fd = new FormData();
        fd.append("file", blob, `memo.${ext}`);
        onVoice(fd);
      };
      mediaRecorderRef.current = mr;
      mr.start();
      setRecording(true);
    } catch (_e) {
      toast.error("Couldn't access the microphone — check browser permissions.");
    }
  };

  const stopRecording = () => {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") {
      mr.stop();
    }
    setRecording(false);
  };

  return (
    <div
      className="rounded-xl p-3 mb-3 flex flex-wrap items-center gap-2"
      style={{
        background: brandGradientCss,
        color: "#fff",
      }}
      data-testid="repair-calc-ai-cta-bar"
    >
      <Sparkles size={16} />
      <div className="text-xs sm:text-sm mr-2 font-semibold">
        Skip the typing — hand the parts list to the AI:
      </div>
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        disabled={busy === "photo" || recording}
        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs sm:text-sm font-bold disabled:opacity-60"
        style={{ backgroundColor: "rgba(255,255,255,0.18)", color: "#fff" }}
        data-testid="repair-calc-ai-photo-btn"
      >
        <Camera size={14} />
        {busy === "photo" ? "Analyzing…" : "📷 Snap a photo"}
      </button>
      <input
        ref={fileInputRef} type="file"
        accept="image/jpeg,image/png,image/heic,image/heif,image/webp"
        onChange={handlePhotoPicked} className="hidden"
        data-testid="repair-calc-ai-photo-input"
      />
      {recording ? (
        <button
          type="button" onClick={stopRecording}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs sm:text-sm font-bold"
          style={{ backgroundColor: "#DC2626", color: "#fff" }}
          data-testid="repair-calc-ai-voice-stop"
        >
          <Square size={14} /> Stop recording
        </button>
      ) : (
        <button
          type="button" onClick={startRecording}
          disabled={busy === "voice"}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs sm:text-sm font-bold disabled:opacity-60"
          style={{ backgroundColor: "rgba(255,255,255,0.18)", color: "#fff" }}
          data-testid="repair-calc-ai-voice-btn"
        >
          <Mic size={14} />
          {busy === "voice" ? "Transcribing…" : "🎙️ Voice memo"}
        </button>
      )}
    </div>
  );
}


function AiResultBanner({ result, onDismiss }) {
  const conf = Number(result?.confidence) || 0;
  const tone =
    conf >= 70 ? { bg: "#DCFCE7", border: "#86EFAC", ink: "#166534" }
    : conf >= 40 ? { bg: "#FEF9C3", border: "#FDE68A", ink: "#854D0E" }
    : { bg: "#FEE2E2", border: "#FCA5A5", ink: "#7F1D1D" };
  const matched = (result?.parts || []).filter((p) => p.source === "pricebook_match").length;
  const total = (result?.parts || []).length;
  return (
    <div
      className="rounded-xl p-3 mb-3 flex items-start gap-2"
      style={{ backgroundColor: tone.bg, border: `1px solid ${tone.border}`, color: tone.ink }}
      data-testid="repair-calc-ai-result-banner"
    >
      <Sparkles size={16} />
      <div className="text-sm flex-1">
        <div className="font-semibold flex flex-wrap items-center gap-2">
          <span data-testid="repair-calc-ai-result-title">
            AI estimate hydrated
            {result?.input_kind === "voice" ? " from voice memo" : " from photo"}
          </span>
          <span
            className="text-[11px] px-2 py-0.5 rounded-full"
            style={{ backgroundColor: `${tone.ink}22`, color: tone.ink }}
            data-testid="repair-calc-ai-result-confidence"
          >
            Confidence: {conf}%
          </span>
          {total > 0 ? (
            <span className="text-[11px] px-2 py-0.5 rounded-full"
                    style={{ backgroundColor: `${tone.ink}14`, color: tone.ink }}
                    data-testid="repair-calc-ai-result-match-count">
              {matched}/{total} parts matched pricebook
            </span>
          ) : null}
        </div>
        {result?.raw_analysis ? (
          <div className="mt-1 text-[13px]" data-testid="repair-calc-ai-result-analysis">
            {result.raw_analysis}
          </div>
        ) : null}
        {(result?.concerns || []).length ? (
          <ul className="mt-1 text-[12px] list-disc pl-4"
              data-testid="repair-calc-ai-result-concerns">
            {result.concerns.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        ) : null}
        {result?.transcript ? (
          <div className="mt-2 text-[12px] italic opacity-80"
                data-testid="repair-calc-ai-result-transcript">
            “{result.transcript}”
          </div>
        ) : null}
      </div>
      <button
        type="button" onClick={onDismiss}
        className="w-6 h-6 rounded-lg flex items-center justify-center"
        style={{ backgroundColor: `${tone.ink}22`, color: tone.ink }}
        aria-label="Dismiss AI banner"
        data-testid="repair-calc-ai-result-dismiss"
      >
        <X size={12} />
      </button>
    </div>
  );
}


function ConfigEditor({ config, onSaved }) {
  const [draft, setDraft] = React.useState({
    sales_tax_pct: config.sales_tax_pct,
    parts_markup_pct: config.parts_markup_pct,
    merchant_fees_pct: config.merchant_fees_pct,
    customer_labor_rate: config.customer_labor_rate,
    internal_labor_rate: config.internal_labor_rate,
    profit_margin_floor: config.profit_margin_floor,
  });
  const [saving, setSaving] = React.useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const next = await api.patch("/ops/repair-calculator/config", draft);
      onSaved(next);
    } catch (e) { toast.error(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: Number(e.target.value) }));
  return (
    <div
      className="rounded-xl p-4 mb-3 grid grid-cols-1 sm:grid-cols-3 gap-3"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="repair-calculator-config-editor"
    >
      <Field label="Sales tax %" testid="rc-cfg-tax"
             value={draft.sales_tax_pct} onChange={set("sales_tax_pct")} step={0.001} />
      <Field label="Parts markup %" testid="rc-cfg-markup"
             value={draft.parts_markup_pct} onChange={set("parts_markup_pct")} step={0.01} />
      <Field label="Merchant fees %" testid="rc-cfg-merchant"
             value={draft.merchant_fees_pct} onChange={set("merchant_fees_pct")} step={0.001} />
      <Field label="Customer labor rate $/hr" testid="rc-cfg-cust-rate"
             value={draft.customer_labor_rate} onChange={set("customer_labor_rate")} step={1} />
      <Field label="Internal labor rate $/hr" testid="rc-cfg-int-rate"
             value={draft.internal_labor_rate} onChange={set("internal_labor_rate")} step={1} />
      <Field label="Profit margin floor" testid="rc-cfg-floor"
             value={draft.profit_margin_floor} onChange={set("profit_margin_floor")} step={0.01} />
      <div className="sm:col-span-3 flex justify-end gap-2">
        <button type="button" onClick={save} disabled={saving}
          className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
          style={{ backgroundColor: colors.brand }}
          data-testid="rc-cfg-save"
        >
          <Save size={13} /> {saving ? "Saving…" : "Save defaults"}
        </button>
      </div>
    </div>
  );
}


function Field({ label, testid, value, onChange, step = 1 }) {
  const id = `${testid}-input`;
  return (
    <div>
      <label htmlFor={id} className="text-[10px] font-semibold uppercase tracking-wider block mb-1"
             style={{ color: colors.muted }}>{label}</label>
      <input
        id={id} type="number" step={step} value={value ?? ""}
        onChange={onChange}
        className="w-full px-3 py-2 rounded-lg border text-sm"
        style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.onSurface }}
        data-testid={testid}
      />
    </div>
  );
}


function InputColumn({ parts, setPartField, addPart, removePart,
                        laborHours, setLaborHours, override, setOverride,
                        config }) {
  const overrideOf = (k) => override[k] ?? "";
  const setOv = (k) => (e) => {
    const v = e.target.value;
    setOverride((o) => {
      const n = { ...o };
      if (v === "" || v === null || v === undefined) delete n[k];
      else n[k] = Number.parseFloat(v);
      return n;
    });
  };
  return (
    <div
      className="rounded-xl p-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="repair-calculator-inputs"
    >
      <h2 className="text-sm font-bold uppercase tracking-wider mb-2"
          style={{ color: colors.muted }}>
        Parts
      </h2>
      <ul className="space-y-2 mb-3" data-testid="repair-calculator-parts">
        {parts.map((p, i) => (
          <li key={i} className="flex items-center gap-2"
              data-testid={`repair-calculator-part-${i}`}>
            <input
              type="text" value={p.name}
              onChange={(e) => setPartField(i, "name", e.target.value)}
              placeholder={`Part ${i + 1} description (optional)`}
              className="flex-1 px-3 py-2 rounded-lg border text-sm"
              style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.onSurface }}
              data-testid={`repair-calculator-part-name-${i}`}
            />
            <input
              type="number" min={0} step={0.01}
              value={p.cost}
              onChange={(e) => setPartField(i, "cost", e.target.value)}
              placeholder="0.00"
              className="w-28 px-3 py-2 rounded-lg border text-sm text-right"
              style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.onSurface }}
              data-testid={`repair-calculator-part-cost-${i}`}
            />
            <button
              type="button" onClick={() => removePart(i)}
              className="text-xs" style={{ color: "#991B1B" }}
              disabled={parts.length === 1}
              aria-label="Remove part"
              data-testid={`repair-calculator-part-remove-${i}`}
            ><Trash2 size={14} /></button>
          </li>
        ))}
      </ul>
      <button
        type="button" onClick={addPart}
        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold"
        style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        data-testid="repair-calculator-add-part"
      >
        <Plus size={13} /> Add part
      </button>

      <div className="mt-4">
        <label htmlFor="rc-labor-hours"
          className="text-[10px] font-semibold uppercase tracking-wider block mb-1"
          style={{ color: colors.muted }}>Labor hours</label>
        <input
          id="rc-labor-hours" type="number" min={0} step={0.25}
          value={laborHours}
          onChange={(e) => setLaborHours(e.target.value)}
          placeholder="0.0"
          className="w-full px-3 py-2 rounded-lg border text-sm"
          style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.onSurface }}
          data-testid="repair-calculator-labor-hours"
        />
      </div>

      <details className="mt-4 rounded-lg" data-testid="repair-calculator-overrides">
        <summary
          className="text-xs font-semibold cursor-pointer"
          style={{ color: colors.muted }}
        >Per-quote overrides (leave blank to use tenant defaults)</summary>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Field label={`Markup % (${config ? PCT(config.parts_markup_pct) : "—"})`}
                 testid="rc-ov-markup" value={overrideOf("parts_markup_pct")}
                 onChange={setOv("parts_markup_pct")} step={0.01} />
          <Field label={`Sales tax % (${config ? PCT(config.sales_tax_pct) : "—"})`}
                 testid="rc-ov-tax" value={overrideOf("sales_tax_pct")}
                 onChange={setOv("sales_tax_pct")} step={0.001} />
          <Field label={`Merchant % (${config ? PCT(config.merchant_fees_pct) : "—"})`}
                 testid="rc-ov-merchant" value={overrideOf("merchant_fees_pct")}
                 onChange={setOv("merchant_fees_pct")} step={0.001} />
          <Field label={`Labor rate ($${config?.customer_labor_rate ?? "—"}/hr)`}
                 testid="rc-ov-rate" value={overrideOf("customer_labor_rate")}
                 onChange={setOv("customer_labor_rate")} step={1} />
        </div>
      </details>
    </div>
  );
}


function PreviewColumn({ quote, tierColor, onCopy, onPrint, onEmail, canEmail }) {
  return (
    <div
      className="rounded-xl p-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="repair-calculator-preview"
    >
      <h2 className="text-sm font-bold uppercase tracking-wider mb-2"
          style={{ color: colors.muted }}>
        Quote preview
      </h2>
      {!quote || quote.estimate_total === 0 ? (
        <div className="text-sm py-8 text-center" style={{ color: colors.muted }}
             data-testid="repair-calculator-preview-empty">
          Add at least one part cost to see a live estimate.
        </div>
      ) : (
        <>
          <ul className="mb-3 text-sm" data-testid="repair-calculator-preview-lines">
            {quote.line_items.map((li, i) => (
              <li key={i}
                  className="flex items-center justify-between py-0.5"
                  style={{ color: colors.onSurface }}>
                <span className="truncate mr-2">{li.name || `Part ${i + 1}`}</span>
                <span>{MONEY(li.cost)}</span>
              </li>
            ))}
            <li className="flex items-center justify-between py-0.5 mt-1 font-semibold"
                style={{ color: colors.onSurface, borderTop: `1px solid ${colors.border}` }}>
              <span>Parts subtotal</span>
              <span data-testid="rc-preview-parts-subtotal">{MONEY(quote.parts_subtotal)}</span>
            </li>
            <li className="flex items-center justify-between py-0.5"
                style={{ color: colors.muted }}>
              <span>Sales tax</span><span>{MONEY(quote.sales_tax)}</span>
            </li>
            <li className="flex items-center justify-between py-0.5"
                style={{ color: colors.muted }}>
              <span>Parts markup</span><span>{MONEY(quote.markup)}</span>
            </li>
            <li className="flex items-center justify-between py-0.5"
                style={{ color: colors.muted }}>
              <span>Labor</span><span>{MONEY(quote.labor)}</span>
            </li>
            <li className="flex items-center justify-between py-0.5"
                style={{ color: colors.muted }}>
              <span>Merchant fees</span><span>{MONEY(quote.merchant_fees)}</span>
            </li>
            <li className="flex items-center justify-between py-2 mt-1 font-bold text-lg"
                style={{ color: colors.onSurface, borderTop: `2px solid ${colors.onSurface}` }}>
              <span>Total</span>
              <span data-testid="rc-preview-estimate-total">{MONEY(quote.estimate_total)}</span>
            </li>
          </ul>

          <div
            className="rounded-lg p-3 flex items-center gap-2 mb-3"
            style={{ backgroundColor: `${tierColor}22`, color: tierColor,
                       border: `1px solid ${tierColor}44` }}
            data-testid="rc-preview-margin-tier"
            data-tier={quote.profit_margin_tier}
          >
            <Info size={14} />
            <div className="text-sm">
              <b>Profit margin: {quote.profit_margin_pct.toFixed(1)}%</b>
              {quote.profit_margin_tier === "yellow" && " — a bit thin. Consider raising the markup."}
              {quote.profit_margin_tier === "red" && " — below the 30% floor. Raise the markup."}
              {quote.profit_margin_tier === "green" && " — healthy."}
            </div>
          </div>
        </>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onCopy} disabled={!canEmail}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
          data-testid="rc-preview-copy"
        ><CopyIcon size={12} /> Copy</button>
        <button type="button" onClick={onPrint} disabled={!canEmail}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
          data-testid="rc-preview-print"
        ><Printer size={12} /> Print</button>
        <button type="button" onClick={onEmail} disabled={!canEmail}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold text-white disabled:opacity-50"
          style={{ backgroundColor: colors.brand }}
          data-testid="rc-preview-email"
        ><Send size={12} /> Email quote</button>
      </div>
    </div>
  );
}


function EmailConfirmModal({ quote, customers, customerId, setCustomerId,
                              adHocEmail, setAdHocEmail, busy, onClose, onSend,
                              afterRender }) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={onClose}
      data-testid="rc-email-modal"
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl overflow-hidden"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div
          className="px-5 py-3 flex items-center justify-between"
          style={{ background: brandGradientCss, color: "#fff" }}
        >
          <h2 className="text-lg font-bold">Email this quote</h2>
          <button type="button" onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: "rgba(255,255,255,0.18)" }}
            data-testid="rc-email-modal-close"
          ><X size={16} /></button>
        </div>
        <div className="p-5 space-y-3">
          {afterRender?.attached && afterRender?.url ? (
            <div
              className="rounded-lg p-2.5 flex items-center gap-2 text-xs"
              style={{ backgroundColor: "#ECFDF5", border: "1px solid #A7F3D0", color: "#065F46" }}
              data-testid="rc-email-render-attached-chip"
            >
              <Paperclip size={13} />
              <span className="font-semibold">AI concept render will be attached.</span>
              <span className="opacity-80">Actual results may vary.</span>
            </div>
          ) : null}
          <div>
            <label htmlFor="rc-email-cust"
              className="text-[10px] font-semibold uppercase tracking-wider block mb-1"
              style={{ color: colors.muted }}>Customer</label>
            <CustomerCombobox
              value={customerId}
              onChange={setCustomerId}
              customers={customers}
              testid="rc-email-customer"
              placeholder="— Pick or enter an ad-hoc email below —"
            />
          </div>
          <div>
            <label htmlFor="rc-email-adhoc"
              className="text-[10px] font-semibold uppercase tracking-wider block mb-1"
              style={{ color: colors.muted }}>Or ad-hoc email</label>
            <input
              id="rc-email-adhoc" type="email" value={adHocEmail}
              onChange={(e) => setAdHocEmail(e.target.value)}
              placeholder="name@example.com"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.onSurface }}
              data-testid="rc-email-adhoc"
            />
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Total: <b>{MONEY(quote?.estimate_total || 0)}</b>
          </div>
        </div>
        <div
          className="px-5 py-3 flex items-center justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}`, backgroundColor: colors.surfaceSecondary }}
        >
          <button type="button" onClick={onClose}
            className="px-3 py-2 rounded-lg text-sm font-semibold"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid="rc-email-cancel"
          >Cancel</button>
          <button type="button" onClick={onSend} disabled={busy}
            className="inline-flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brand }}
            data-testid="rc-email-send"
          ><Send size={13} /> {busy ? "Sending…" : "Send"}</button>
        </div>
      </div>
    </div>
  );
}


// Phase B follow-up · Feb-2026 — AI Photo-to-Estimate before/after.
//
// Renders a side-by-side BEFORE|AFTER grid + the mandatory legal
// caption.  Feb-2026 · K55.a — the "Generate 'after' concept render"
// button used to gate on the SuperCool connection flag; SuperCool
// was removed in the sunset, so the gate + hint banner are gone.
// Image editing now runs through the Emergent nano-banana-2
// fallback unconditionally (see K56).
function BeforeAfterRender({ photoDataUrl, afterRender, renderBusy,
                              onGenerate, onAttachToEmail }) {
  const canGenerate = !!photoDataUrl && !renderBusy;
  const tooltip = !photoDataUrl
    ? "Upload a photo via 📷 Snap a photo first."
    : "Generate an AI concept render of the finished repair.";
  return (
    <div
      className="rounded-xl p-4 mb-3"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="repair-calc-before-after"
    >
      <div className="flex items-start gap-2 mb-3 flex-wrap">
        <Paintbrush size={16} style={{ color: colors.brand, marginTop: 4 }} />
        <div className="flex-1 min-w-[180px]">
          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
            AI concept render
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Show the customer what the finished repair could look like — using
            their own pool photo as the base image.
          </div>
        </div>
        <button
          type="button"
          onClick={canGenerate ? onGenerate : undefined}
          disabled={!canGenerate}
          title={tooltip}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs sm:text-sm font-bold text-white disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ background: brandGradientCss }}
          data-testid="repair-calc-generate-after-btn"
        >
          {renderBusy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          {renderBusy
            ? "Rendering…"
            : afterRender?.url ? "🎨 Regenerate" : "🎨 Generate 'after' concept render"}
        </button>
      </div>

      {/* Feb-2026 · K55.a — SuperCool disconnected hint removed as
          part of the sunset (see PHASE_K55_a_FRONTEND_REMOVAL.md). */}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3"
           data-testid="repair-calc-before-after-grid">
        <figure
          className="rounded-lg overflow-hidden flex flex-col"
          style={{ border: `1px solid ${colors.border}`,
                     backgroundColor: colors.surfaceSecondary }}
          data-testid="repair-calc-before-tile"
        >
          <div className="text-[10px] font-bold uppercase tracking-wider px-2 py-1"
               style={{ backgroundColor: "#111827", color: "#FFFFFF" }}>
            Before
          </div>
          <img src={photoDataUrl} alt="Original pool photo"
               className="w-full aspect-[4/5] object-cover"
               data-testid="repair-calc-before-image" />
        </figure>
        <figure
          className="rounded-lg overflow-hidden flex flex-col"
          style={{ border: `1px solid ${colors.border}`,
                     backgroundColor: colors.surfaceSecondary }}
          data-testid="repair-calc-after-tile"
        >
          <div className="text-[10px] font-bold uppercase tracking-wider px-2 py-1"
               style={{ backgroundColor: "#065F46", color: "#FFFFFF" }}>
            After · AI concept
          </div>
          {afterRender?.url ? (
            <img src={_absoluteMediaUrl(afterRender.url)} alt="AI-generated concept render"
                 className="w-full aspect-[4/5] object-cover"
                 data-testid="repair-calc-after-image" />
          ) : (
            <div className="w-full aspect-[4/5] flex items-center justify-center text-xs px-3 text-center"
                 style={{ color: colors.muted }}
                 data-testid="repair-calc-after-placeholder">
              {renderBusy
                ? "Rendering AI concept…"
                : "No concept render yet. Click Generate above."}
            </div>
          )}
        </figure>
      </div>

      {/* Strict legal caption — required by the Phase B follow-up brief. */}
      <div
        className="mt-3 text-[11px] italic px-2 py-1.5 rounded-md"
        style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted,
                    border: `1px solid ${colors.border}` }}
        data-testid="repair-calc-after-legal-caption"
      >
        AI-generated concept render — actual results may vary.
      </div>

      {afterRender?.url ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onAttachToEmail}
            disabled={afterRender.attached}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold disabled:opacity-60"
            style={{ backgroundColor: afterRender.attached ? "#DCFCE7" : colors.brand,
                       color: afterRender.attached ? "#166534" : "#FFFFFF" }}
            data-testid="repair-calc-attach-render-btn"
          >
            {afterRender.attached
              ? <><CheckCircle2 size={12} /> Attached to email</>
              : <><Paperclip size={12} /> Attach to quote email</>}
          </button>
          <span className="text-[11px]" style={{ color: colors.muted }}>
            Provider · <b>{afterRender.provider || "emergent"}</b>
          </span>
        </div>
      ) : null}
    </div>
  );
}


// Local helper — mirrors ContentStudioPage's absoluteMediaUrl but scoped
// to this file so we don't leak a shared helper for one call site.
function _absoluteMediaUrl(u) {
  if (!u) return "";
  if (u.startsWith("http") || u.startsWith("data:")) return u;
  const base = api_base().replace(/\/api\/?$/, "");
  return base + u;
}


function renderPlainText(q) {
  const items = (q.line_items || [])
    .map((li, i) => `- ${li.name || `Part ${i + 1}`}: $${(li.cost || 0).toFixed(2)}`)
    .join("\n");
  return [
    "REPAIR ESTIMATE",
    "",
    items || "(no parts)",
    "",
    `Parts subtotal:  $${q.parts_subtotal.toFixed(2)}`,
    `Sales tax:       $${q.sales_tax.toFixed(2)}`,
    `Parts markup:    $${q.markup.toFixed(2)}`,
    `Labor:           $${q.labor.toFixed(2)}`,
    `Merchant fees:   $${q.merchant_fees.toFixed(2)}`,
    "".padEnd(40, "-"),
    `TOTAL:           $${q.estimate_total.toFixed(2)}`,
    "",
    `Profit margin:   ${q.profit_margin_pct.toFixed(1)}%`,
  ].join("\n");
}
