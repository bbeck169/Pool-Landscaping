/**
 * Phase 5a · Feb-2026 — AEO (Answer Engine Optimization) Suite.
 *
 * Admin / Super Admin / Manager only. Three tabs:
 *   1. Auditor       — trigger a fresh SEO scan (which now includes
 *                      the aeo_signals block) and render the sub-signal
 *                      scorecard.
 *   2. JSON-LD       — form-driven generator that emits copy-pasteable
 *                      <script type="application/ld+json"> blocks.
 *   3. LLMs.txt      — concise/full toggle + FAQ inclusion; renders
 *                      plain-text content with copy + install callout.
 */
import React from "react";
import { toast } from "sonner";
import { Sparkles, ScanSearch, Copy, RefreshCw, PlusCircle, X,
          FileText, ClipboardCheck } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const TABS = [
  { key: "auditor",   label: "Auditor",         icon: ScanSearch },
  { key: "jsonld",    label: "JSON-LD Generator", icon: Sparkles },
  { key: "llmstxt",   label: "LLMs.txt",         icon: FileText },
];

async function _copy(text, label = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(label);
  } catch {
    toast.error("Copy failed — select the text manually.");
  }
}

function _scoreColor(n) {
  if (n == null) return colors.muted;
  if (n >= 75) return "#16A34A";
  if (n >= 50) return "#CA8A04";
  return "#DC2626";
}

// ── Auditor tab ──────────────────────────────────────────────────
function AuditorTab() {
  const [url, setUrl] = React.useState("");
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState(null);

  const run = async () => {
    if (!url) { toast.error("Enter a URL first."); return; }
    setRunning(true);
    setResult(null);
    try {
      const r = await api.post("/seo/scans", { target_url: url, async: false });
      setResult(r);
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Scan failed");
    } finally {
      setRunning(false);
    }
  };

  const aeo = result?.results?.aeo_signals || null;
  return (
    <div className="space-y-4" data-testid="aeo-auditor-tab">
      <div className="flex items-center gap-2">
        <input
          type="url" value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://your-site.com"
          className="flex-1 rounded-lg px-3 py-2 text-sm"
          style={{ backgroundColor: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}` }}
          data-testid="aeo-auditor-url"
        />
        <button
          type="button" onClick={run} disabled={running || !url}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
          style={{ backgroundColor: colors.brand, color: "#fff" }}
          data-testid="aeo-auditor-run"
        >
          {running ? <RefreshCw size={14} className="animate-spin" /> : <ScanSearch size={14} />}
          {running ? "Scanning…" : "Run AEO scan"}
        </button>
      </div>
      <p className="text-xs" style={{ color: colors.muted }}>
        Runs the existing SEO scanner and shows the new AEO signal scorecard
        below. Full scan reuses the same rate limits (5/hour per user).
      </p>

      {!aeo && !running ? (
        <div className="rounded-xl p-10 text-center"
              style={{ backgroundColor: colors.surface,
                        border: `1px dashed ${colors.border}`,
                        color: colors.muted }}
              data-testid="aeo-auditor-empty">
          Enter a URL and click "Run AEO scan" to see the scorecard.
        </div>
      ) : null}

      {aeo ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3"
              data-testid="aeo-signals-card">
          <div className="col-span-full rounded-xl p-4"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
            <div className="text-xs uppercase tracking-wide font-semibold"
                  style={{ color: colors.muted }}>Overall AEO score</div>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-4xl font-bold"
                    style={{ color: _scoreColor(aeo.overall_aeo_score) }}
                    data-testid="aeo-overall-score">
                {aeo.overall_aeo_score}
              </span>
              <span className="text-sm" style={{ color: colors.muted }}>
                / 100 · weighted across 5 sub-signals
              </span>
            </div>
          </div>
          <SignalCard title="Schema.org" score={aeo.schema.score}
                       body={<>
                         <div>Present: <b>{aeo.schema.types_present.join(", ") || "—"}</b></div>
                         <div>Missing recommended: <b>{aeo.schema.types_missing_recommended.join(", ") || "—"}</b></div>
                       </>} testid="aeo-signal-schema" />
          <SignalCard title="FAQ presence" score={aeo.faq.score}
                       body={<>
                         <div>Detected: <b>{aeo.faq.count}</b> FAQ-like blocks</div>
                         <div>Schema FAQPage: <b>{aeo.faq.schema_faq ? "yes" : "no"}</b></div>
                       </>} testid="aeo-signal-faq" />
          <SignalCard title="LLMs.txt" score={aeo.llms_txt.score}
                       body={<>
                         <div>Present: <b>{aeo.llms_txt.present ? "yes" : "no"}</b></div>
                         <div className="truncate">Checked: <code>{aeo.llms_txt.url_checked}</code></div>
                       </>} testid="aeo-signal-llms" />
          <SignalCard title="Passage length" score={aeo.passages.score}
                       body={<>
                         <div>Paragraphs: <b>{aeo.passages.total}</b></div>
                         <div>Median words: <b>{aeo.passages.median_words}</b></div>
                         <div>Over 90 words: <b>{aeo.passages.over_90_words}</b></div>
                       </>} testid="aeo-signal-passages" />
          <SignalCard title="Entity clarity" score={aeo.entity_clarity.score}
                       body={<>
                         <div>Has H1: <b>{aeo.entity_clarity.has_h1 ? "yes" : "no"}</b></div>
                         <div>Meta desc length: <b>{aeo.entity_clarity.meta_description_len}</b></div>
                         <div>sameAs links: <b>{aeo.entity_clarity.same_as_count}</b></div>
                       </>} testid="aeo-signal-entity" />
        </div>
      ) : null}
    </div>
  );
}

function SignalCard({ title, score, body, testid }) {
  return (
    <div className="rounded-xl p-4"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs uppercase tracking-wide font-semibold"
              style={{ color: colors.muted }}>{title}</span>
        <span className="text-lg font-bold"
              style={{ color: _scoreColor(score) }}>{score}</span>
      </div>
      <div className="text-xs space-y-0.5" style={{ color: colors.onSurface }}>
        {body}
      </div>
    </div>
  );
}

// ── JSON-LD Generator tab ─────────────────────────────────────────
const AVAILABLE_TYPES = ["LocalBusiness", "Organization", "Service",
                          "FAQPage", "HowTo"];

function JsonldTab() {
  const [types, setTypes] = React.useState(["LocalBusiness", "FAQPage"]);
  const [profile, setProfile] = React.useState({
    name: "", url: "", phone: "", email: "",
  });
  const [faqs, setFaqs] = React.useState([{ question: "", answer: "" }]);
  const [result, setResult] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

  const toggleType = (t) => setTypes((cur) =>
    cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]);

  const generate = async () => {
    if (!types.length) { toast.error("Pick at least one type."); return; }
    setBusy(true);
    setResult(null);
    try {
      const body = {
        types,
        business_profile: profile,
        faqs: types.includes("FAQPage")
          ? faqs.filter((f) => f.question && f.answer)
          : undefined,
      };
      const r = await api.post("/aeo/jsonld/generate", body);
      setResult(r);
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Generate failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="aeo-jsonld-tab">
      <div className="rounded-xl p-4 space-y-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div>
          <div className="text-xs uppercase tracking-wide font-semibold mb-2"
                style={{ color: colors.muted }}>Types</div>
          <div className="flex flex-wrap gap-1.5" data-testid="aeo-jsonld-types">
            {AVAILABLE_TYPES.map((t) => {
              const active = types.includes(t);
              return (
                <button key={t} type="button" onClick={() => toggleType(t)}
                         className="px-2.5 py-1 rounded-full text-xs font-semibold"
                         style={{
                           backgroundColor: active ? colors.brand : colors.surfaceSecondary,
                           color: active ? "#fff" : colors.onSurface,
                           border: `1px solid ${active ? colors.brand : colors.border}`,
                         }}
                         data-testid={`aeo-jsonld-type-${t}`}>
                  {t}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {["name","url","phone","email"].map((k) => (
            <input key={k} value={profile[k]}
                    onChange={(e) => setProfile((p) => ({ ...p, [k]: e.target.value }))}
                    placeholder={k}
                    className="rounded-lg px-3 py-2 text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid={`aeo-jsonld-profile-${k}`} />
          ))}
        </div>
        <p className="text-[11px]" style={{ color: colors.muted }}>
          Missing fields are auto-filled from your tenant profile.
        </p>

        {types.includes("FAQPage") ? (
          <div>
            <div className="text-xs uppercase tracking-wide font-semibold mb-1 flex items-center justify-between"
                  style={{ color: colors.muted }}>
              <span>FAQs</span>
              <button type="button"
                       onClick={() => setFaqs((cur) => [...cur, { question: "", answer: "" }])}
                       className="text-xs font-semibold flex items-center gap-1 px-1.5 py-0.5 rounded"
                       style={{ backgroundColor: colors.surfaceSecondary,
                                 color: colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                       data-testid="aeo-jsonld-faq-add">
                <PlusCircle size={12} /> Add FAQ
              </button>
            </div>
            <div className="space-y-2" data-testid="aeo-jsonld-faq-list">
              {faqs.map((f, i) => (
                <div key={i} className="flex items-start gap-2">
                  <div className="flex-1 space-y-1">
                    <input value={f.question}
                            onChange={(e) => setFaqs((cur) => cur.map((x, j) => j === i ? { ...x, question: e.target.value } : x))}
                            placeholder="Question"
                            className="w-full rounded-lg px-3 py-1.5 text-sm"
                            style={{ backgroundColor: colors.surfaceSecondary,
                                      color: colors.onSurface,
                                      border: `1px solid ${colors.border}` }}
                            data-testid={`aeo-jsonld-faq-q-${i}`} />
                    <textarea value={f.answer}
                              onChange={(e) => setFaqs((cur) => cur.map((x, j) => j === i ? { ...x, answer: e.target.value } : x))}
                              placeholder="Answer"
                              rows={2}
                              className="w-full rounded-lg px-3 py-1.5 text-sm"
                              style={{ backgroundColor: colors.surfaceSecondary,
                                        color: colors.onSurface,
                                        border: `1px solid ${colors.border}` }}
                              data-testid={`aeo-jsonld-faq-a-${i}`} />
                  </div>
                  <button type="button"
                           onClick={() => setFaqs((cur) => cur.filter((_, j) => j !== i))}
                           className="p-1 rounded hover:brightness-95"
                           style={{ color: colors.muted }}
                           aria-label="remove"
                           data-testid={`aeo-jsonld-faq-remove-${i}`}>
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <button type="button" onClick={generate} disabled={busy}
                 className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                 style={{ backgroundColor: colors.brand, color: "#fff" }}
                 data-testid="aeo-jsonld-generate">
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Sparkles size={14} />}
          Generate JSON-LD
        </button>
      </div>

      {result ? (
        <div className="rounded-xl p-4 space-y-2"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="aeo-jsonld-result">
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-wide font-semibold"
                  style={{ color: colors.muted }}>
              Combined &lt;script&gt; block · {result.count} type(s)
            </div>
            <button type="button"
                     onClick={() => _copy(result.combined_script, "Copied JSON-LD to clipboard")}
                     className="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
                     style={{ backgroundColor: colors.brand, color: "#fff" }}
                     data-testid="aeo-jsonld-copy">
              <Copy size={12} /> Copy
            </button>
          </div>
          <pre className="text-[11px] rounded p-3 overflow-auto max-h-[420px]"
                style={{ backgroundColor: "#0F172A", color: "#E2E8F0",
                          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
                data-testid="aeo-jsonld-pre">
            {result.combined_script}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

// ── LLMs.txt tab ─────────────────────────────────────────────────
function LlmsTxtTab() {
  const [style, setStyle] = React.useState("concise");
  const [includeFaqs, setIncludeFaqs] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);

  const generate = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api.post("/aeo/llms-txt/generate",
                                  { style, include_faqs: includeFaqs });
      setResult(r);
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Generate failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="aeo-llms-tab">
      <div className="rounded-xl p-4 space-y-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex gap-0.5 p-0.5 rounded-md"
                style={{ backgroundColor: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}` }}>
            {[["concise", "Concise (llms.txt)"], ["full", "Full (llms-full.txt)"]].map(([k, label]) => (
              <button key={k} type="button" onClick={() => setStyle(k)}
                       className="px-2.5 py-1 rounded text-xs font-semibold"
                       style={{
                         backgroundColor: style === k ? colors.brand : "transparent",
                         color: style === k ? "#fff" : colors.onSurface,
                       }}
                       data-testid={`aeo-llms-style-${k}`}>
                {label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs"
                  style={{ color: colors.onSurface }}>
            <input type="checkbox" checked={includeFaqs}
                    onChange={(e) => setIncludeFaqs(e.target.checked)}
                    data-testid="aeo-llms-include-faqs" />
            Include FAQ section
          </label>
        </div>
        <button type="button" onClick={generate} disabled={busy}
                 className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                 style={{ backgroundColor: colors.brand, color: "#fff" }}
                 data-testid="aeo-llms-generate">
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <FileText size={14} />}
          Generate {style === "full" ? "llms-full.txt" : "llms.txt"}
        </button>
      </div>

      {result ? (
        <>
          <div className="rounded-xl p-4 space-y-2"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="aeo-llms-result">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="text-xs uppercase tracking-wide font-semibold"
                    style={{ color: colors.muted }}>
                {result.filename} · {result.byte_size} bytes
              </div>
              <button type="button"
                       onClick={() => _copy(result.content, `Copied ${result.filename}`)}
                       className="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
                       style={{ backgroundColor: colors.brand, color: "#fff" }}
                       data-testid="aeo-llms-copy">
                <Copy size={12} /> Copy
              </button>
            </div>
            <pre className="text-[12px] rounded p-3 overflow-auto max-h-[420px] whitespace-pre-wrap"
                  style={{ backgroundColor: "#0F172A", color: "#E2E8F0",
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
                  data-testid="aeo-llms-pre">
              {result.content}
            </pre>
          </div>
          <div className="rounded-xl p-3 text-xs flex items-start gap-2"
                style={{ backgroundColor: "#EFF6FF", color: "#1E3A8A",
                          border: "1px solid #BFDBFE" }}
                data-testid="aeo-llms-install">
            <ClipboardCheck size={14} className="mt-0.5 shrink-0" />
            <div>{result.install_instructions}</div>
          </div>
        </>
      ) : null}
    </div>
  );
}

// ── Page shell ───────────────────────────────────────────────────
export default function AEOPage() {
  const [tab, setTab] = React.useState("auditor");
  return (
    <div className="px-4 md:px-8 pt-4 space-y-4 pb-24"
          data-testid="aeo-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
            style={{ color: colors.onSurface }}
            data-testid="aeo-title">
          Answer Engine Optimization
        </h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          Get surfaced by ChatGPT, Perplexity, Gemini, and Google AI
          Overviews. Free tools — no external LLM cost, no data leaves
          your site.
        </p>
      </div>

      <div className="flex gap-1 p-1 rounded-xl"
            style={{ backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}` }}
            role="tablist" data-testid="aeo-tabs">
        {TABS.map((t) => {
          const Ic = t.icon;
          const active = tab === t.key;
          return (
            <button key={t.key} type="button" role="tab"
                     aria-selected={active}
                     onClick={() => setTab(t.key)}
                     className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold"
                     style={{ backgroundColor: active ? colors.brand : "transparent",
                               color: active ? "#fff" : colors.onSurface }}
                     data-testid={`aeo-tab-${t.key}`}>
              <Ic size={14} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "auditor" ? <AuditorTab /> : null}
      {tab === "jsonld" ? <JsonldTab /> : null}
      {tab === "llmstxt" ? <LlmsTxtTab /> : null}
    </div>
  );
}
