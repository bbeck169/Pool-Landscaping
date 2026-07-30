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
          FileText, ClipboardCheck, TrendingUp, Wrench, CheckCircle2,
          AlertCircle } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { api } from "@/api";
import { colors } from "@/theme";

const TABS = [
  { key: "auditor",    label: "Auditor",           icon: ScanSearch },
  { key: "jsonld",     label: "JSON-LD Generator", icon: Sparkles },
  { key: "llmstxt",    label: "LLMs.txt",          icon: FileText },
  { key: "visibility", label: "AI Visibility",     icon: TrendingUp },
  { key: "fixes",      label: "Fixes",             icon: Wrench },
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

// ── AI Visibility tab ────────────────────────────────────────────
function VisibilityTab() {
  const [dash, setDash] = React.useState(null);
  const [history, setHistory] = React.useState(null);
  const [range, setRange] = React.useState("30d");
  const [busy, setBusy] = React.useState(false);
  const [runResult, setRunResult] = React.useState(null);

  const load = React.useCallback(async () => {
    try {
      const [d, h] = await Promise.all([
        api.get("/aeo/visibility/dashboard"),
        api.get(`/aeo/visibility/history?range=${range}`),
      ]);
      setDash(d);
      setHistory(h);
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Failed to load");
    }
  }, [range]);
  React.useEffect(() => { load(); }, [load]);

  const runNow = async () => {
    setBusy(true);
    setRunResult(null);
    try {
      const r = await api.post("/aeo/visibility/run-now", {});
      setRunResult(r);
      if (r.skipped_reason === "cooldown") {
        toast(`Cooldown active — last scan < ${r.next_available_after_hours}h ago`);
      } else {
        toast.success(`Ran ${r.summary?.total || 0} probes · ${r.summary?.mentions || 0} mentions`);
      }
      load();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Run failed");
    } finally { setBusy(false); }
  };

  // Cooldown check — disable button if last probe < 20h.
  const cooldownLeft = React.useMemo(() => {
    const ts = dash?.latest_ran_at;
    if (!ts) return 0;
    const mins = (Date.now() - new Date(ts).getTime()) / 60000;
    const remaining = Math.max(0, 20 * 60 - mins);
    return remaining;
  }, [dash]);

  return (
    <div className="space-y-4" data-testid="aeo-visibility-tab">
      {/* KPI row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <KPI label="Avg score (30d)" value={dash?.avg_score_30d ?? 0}
              color={_scoreColor(dash?.avg_score_30d)} testid="aeo-vis-avg" />
        <KPI label="Probes (30d)" value={dash?.probes_30d ?? 0}
              testid="aeo-vis-probes" />
        <KPI label="Providers checked"
              value={(dash?.providers || []).length}
              testid="aeo-vis-providers" />
        <KPI label="Spend this month"
              value={`$${(dash?.cost_this_month || 0).toFixed(2)}`}
              sub={`cap $${(dash?.cost_cap || 0).toFixed(2)}`}
              color={dash?.cost_capped ? "#DC2626" : colors.onSurface}
              testid="aeo-vis-cost" />
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex gap-0.5 p-0.5 rounded-md"
              style={{ backgroundColor: colors.surfaceSecondary,
                        border: `1px solid ${colors.border}` }}>
          {["7d", "30d", "90d"].map((r) => (
            <button key={r} type="button" onClick={() => setRange(r)}
                     className="px-2.5 py-1 rounded text-xs font-semibold"
                     style={{
                       backgroundColor: range === r ? colors.brand : "transparent",
                       color: range === r ? "#fff" : colors.onSurface,
                     }}
                     data-testid={`aeo-vis-range-${r}`}>
              {r}
            </button>
          ))}
        </div>
        <button type="button" onClick={runNow}
                 disabled={busy || cooldownLeft > 0}
                 className="ml-auto flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                 style={{ backgroundColor: colors.brand, color: "#fff" }}
                 data-testid="aeo-vis-run-now"
                 title={cooldownLeft > 0
                   ? `Cooldown · ${Math.ceil(cooldownLeft/60)}h remaining`
                   : "Run all default probes now"}>
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <TrendingUp size={14} />}
          Run scan now
        </button>
      </div>

      {/* Chart */}
      <div className="rounded-xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="aeo-vis-chart">
        <div className="text-xs uppercase tracking-wide font-semibold mb-2"
              style={{ color: colors.muted }}>Score over time · {range}</div>
        {(history?.series || []).length === 0 ? (
          <div className="text-center py-10 text-xs"
                style={{ color: colors.muted }}
                data-testid="aeo-vis-chart-empty">
            No probes in this range yet. Click "Run scan now" to start.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={history.series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
              <XAxis dataKey="date" stroke={colors.muted} fontSize={11} />
              <YAxis domain={[0, 100]} stroke={colors.muted} fontSize={11} />
              <Tooltip />
              <Line type="monotone" dataKey="avg_score"
                     stroke={colors.brand} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Latest probes table (or run-result summary) */}
      {runResult?.probes?.length ? (
        <div className="rounded-xl p-4"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="aeo-vis-runresult">
          <div className="text-xs uppercase tracking-wide font-semibold mb-2"
                style={{ color: colors.muted }}>
            Latest run · {runResult.summary.total} probes ·
            {" "}{runResult.summary.mentions} mentions ·
            {" "}avg {runResult.summary.avg_score}
          </div>
          <ul className="space-y-2 text-xs" data-testid="aeo-vis-runlist">
            {runResult.probes.map((p) => (
              <li key={p.probe_id} className="flex items-start gap-2 p-2 rounded-md"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}` }}
                   data-testid={`aeo-vis-probe-${p.probe_id}`}>
                <span className="text-sm font-bold shrink-0"
                       style={{ color: _scoreColor(p.score), minWidth: 32 }}>{p.score}</span>
                <div className="min-w-0">
                  <div className="font-semibold truncate">{p.provider} · {p.query}</div>
                  <div className="text-[11px] truncate"
                        style={{ color: colors.muted }}>{p.snippet || (p.error ? `error: ${p.error}` : "")}</div>
                </div>
                {p.brand_mentioned ? (
                  <CheckCircle2 size={14} color="#16A34A" />
                ) : (
                  <AlertCircle size={14} color="#CA8A04" />
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (history?.pairs?.length ? (
        <div className="rounded-xl p-4"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="aeo-vis-pairs">
          <div className="text-xs uppercase tracking-wide font-semibold mb-2"
                style={{ color: colors.muted }}>
            Latest by provider × query
          </div>
          <ul className="space-y-2 text-xs">
            {history.pairs.map((p, i) => (
              <li key={i} className="flex items-start gap-2 p-2 rounded-md"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}` }}>
                <span className="text-sm font-bold shrink-0"
                       style={{ color: _scoreColor(p.latest_score), minWidth: 32 }}>{p.latest_score}</span>
                <div className="min-w-0">
                  <div className="font-semibold truncate">{p.provider} · {p.query_template}</div>
                  <div className="text-[11px] truncate"
                        style={{ color: colors.muted }}>{p.latest_snippet}</div>
                </div>
                {p.latest_brand_mentioned ? (
                  <CheckCircle2 size={14} color="#16A34A" />
                ) : (
                  <AlertCircle size={14} color="#CA8A04" />
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null)}
    </div>
  );
}

function KPI({ label, value, sub, color, testid }) {
  return (
    <div className="rounded-xl p-4"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid={testid}>
      <div className="text-xs uppercase tracking-wide font-semibold"
            style={{ color: colors.muted }}>{label}</div>
      <div className="text-2xl font-bold mt-1"
            style={{ color: color || colors.onSurface }}>{value}</div>
      {sub ? <div className="text-[11px]"
                    style={{ color: colors.muted }}>{sub}</div> : null}
    </div>
  );
}

// ── Fixes tab ────────────────────────────────────────────────────
function FixesTab() {
  const [scanId, setScanId] = React.useState("");
  const [pending, setPending] = React.useState([]);
  const [busy, setBusy] = React.useState(false);

  const loadPending = React.useCallback(async () => {
    try {
      const q = scanId ? `?scan_id=${encodeURIComponent(scanId)}` : "";
      const r = await api.get(`/aeo/fixes/pending${q}`);
      setPending(r.items || []);
    } catch { /* silent */ }
  }, [scanId]);
  React.useEffect(() => { loadPending(); }, [loadPending]);

  const generate = async () => {
    if (!scanId) { toast.error("Enter a scan ID first."); return; }
    setBusy(true);
    try {
      const r = await api.post("/aeo/fixes/generate", { scan_id: scanId });
      toast.success(`Generated ${r.fixes?.length || 0} fix(es)`);
      loadPending();
    } catch (e) {
      const s = e?.status;
      if (s === 429) toast.error("Rate limit — try in an hour.");
      else toast.error(e?.body?.detail || e?.message || "Generate failed");
    } finally { setBusy(false); }
  };

  const markApplied = async (fixId, applied) => {
    try {
      await api.post(`/aeo/fixes/${fixId}/apply`, { applied });
      toast.success(applied ? "Marked applied" : "Marked pending");
      loadPending();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Failed");
    }
  };

  return (
    <div className="space-y-4" data-testid="aeo-fixes-tab">
      <div className="rounded-xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="flex items-center gap-2 flex-wrap">
          <input value={scanId}
                  onChange={(e) => setScanId(e.target.value)}
                  placeholder="Scan ID (from Auditor tab)"
                  className="flex-1 rounded-lg px-3 py-2 text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                  data-testid="aeo-fixes-scan-id" />
          <button type="button" onClick={generate}
                   disabled={busy || !scanId}
                   className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                   style={{ backgroundColor: colors.brand, color: "#fff" }}
                   data-testid="aeo-fixes-generate">
            {busy ? <RefreshCw size={14} className="animate-spin" /> : <Wrench size={14} />}
            Generate fixes
          </button>
        </div>
        <p className="text-[11px] mt-2" style={{ color: colors.muted }}>
          Rate limit: 5 fix-generation calls per hour per tenant.
        </p>
      </div>

      {pending.length === 0 ? (
        <div className="rounded-xl p-10 text-center"
              style={{ backgroundColor: colors.surface,
                        border: `1px dashed ${colors.border}`,
                        color: colors.muted }}
              data-testid="aeo-fixes-empty">
          No pending fixes. Paste a scan ID and click Generate.
        </div>
      ) : (
        <div className="space-y-3" data-testid="aeo-fixes-list">
          {pending.map((f) => (
            <FixCard key={f._id} fix={f}
                      onApply={() => markApplied(f._id, true)} />
          ))}
        </div>
      )}
    </div>
  );
}

const PRIORITY_STYLES = {
  high: { bg: "#FEE2E2", fg: "#991B1B", border: "#FECACA" },
  med:  { bg: "#FEF3C7", fg: "#92400E", border: "#FDE68A" },
  low:  { bg: "#DBEAFE", fg: "#1E40AF", border: "#BFDBFE" },
};

function FixCard({ fix, onApply }) {
  const tone = PRIORITY_STYLES[fix.priority] || PRIORITY_STYLES.med;
  return (
    <div className="rounded-xl p-4 space-y-2"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid={`aeo-fix-card-${fix.sub_signal}`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide font-semibold"
                style={{ color: colors.muted }}>{fix.sub_signal}</span>
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                 style={{ backgroundColor: tone.bg, color: tone.fg,
                           border: `1px solid ${tone.border}` }}>
            {fix.priority}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button"
                   onClick={() => _copy(
                     fix.generated_content || fix.suggestion_markdown,
                     "Copied fix content")}
                   className="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid={`aeo-fix-copy-${fix.sub_signal}`}>
            <Copy size={12} /> Copy
          </button>
          <button type="button" onClick={onApply}
                   className="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
                   style={{ backgroundColor: colors.brand, color: "#fff" }}
                   data-testid={`aeo-fix-apply-${fix.sub_signal}`}>
            <CheckCircle2 size={12} /> Mark done
          </button>
        </div>
      </div>
      <pre className="text-[12px] whitespace-pre-wrap"
            style={{ color: colors.onSurface,
                      fontFamily: "inherit", margin: 0 }}>
        {fix.suggestion_markdown}
      </pre>
      {fix.generated_content ? (
        <pre className="text-[11px] rounded p-3 overflow-auto max-h-[240px]"
              style={{ backgroundColor: "#0F172A", color: "#E2E8F0",
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
              data-testid={`aeo-fix-content-${fix.sub_signal}`}>
          {fix.generated_content}
        </pre>
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
      {tab === "visibility" ? <VisibilityTab /> : null}
      {tab === "fixes" ? <FixesTab /> : null}
    </div>
  );
}
