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
          AlertCircle, Globe, ExternalLink, UploadCloud, Cloud, Save,
          PlayCircle, Trash2, ChevronDown, ChevronRight,
          LibraryBig } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  AreaChart, Area,
} from "recharts";
import { api } from "@/api";
import { colors } from "@/theme";
import ResponseDraftModal from "@/pages/admin/ResponseDraftModal";

const TABS = [
  { key: "auditor",    label: "Auditor",           icon: ScanSearch },
  { key: "jsonld",     label: "JSON-LD Generator", icon: Sparkles },
  { key: "llmstxt",    label: "LLMs.txt",          icon: FileText },
  { key: "visibility", label: "AI Visibility",     icon: TrendingUp },
  { key: "fixes",      label: "Fixes",             icon: Wrench },
  { key: "mentions",   label: "Brand Mentions",    icon: Globe },
  { key: "library",    label: "Response Library",  icon: LibraryBig },
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

      <PublishConfigPanel />
    </div>
  );
}

// ── Phase 9 · Publish LLMs.txt to Netlify / Vercel / CF Pages ────
const _P9_TABS = [
  { key: "netlify", label: "Netlify",
    fields: [
      { k: "site_id", label: "Site ID", placeholder: "12ab34cd-…",
        hint: "Netlify dashboard → Site → Settings → Site details → Site ID." },
      { k: "site_url", label: "Site URL (optional)",
        placeholder: "https://your-site.netlify.app",
        hint: "Used only to build the public URL shown in history." },
    ],
    docs: "https://app.netlify.com/user/applications#personal-access-tokens" },
  { key: "vercel", label: "Vercel",
    fields: [
      { k: "project_id", label: "Project ID",
        placeholder: "prj_…",
        hint: "Vercel → Project → Settings → General → Project ID." },
    ],
    docs: "https://vercel.com/account/tokens",
    note: "Vercel does not support single-file live upload — publishing creates a new production deployment containing only llms.txt. For git-linked projects prefer opening a commit PR." },
  { key: "cloudflare_pages", label: "Cloudflare Pages",
    fields: [
      { k: "account_id", label: "Account ID", placeholder: "abc123…",
        hint: "Cloudflare dashboard → Right sidebar → Account ID." },
      { k: "project_name", label: "Project name", placeholder: "your-project",
        hint: "The Pages project slug (URL: <name>.pages.dev)." },
    ],
    docs: "https://dash.cloudflare.com/profile/api-tokens" },
];

function PublishConfigPanel() {
  const [open, setOpen] = React.useState(true);
  const [active, setActive] = React.useState("netlify");
  const [configs, setConfigs] = React.useState({});
  const [form, setForm] = React.useState({});
  const [testResult, setTestResult] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const [history, setHistory] = React.useState([]);

  const activeMeta = _P9_TABS.find((t) => t.key === active);

  const load = React.useCallback(async () => {
    try {
      const [p, h] = await Promise.all([
        api.get("/aeo/llms-txt/publish/providers"),
        api.get("/aeo/llms-txt/publish/history?limit=20"),
      ]);
      const map = {};
      for (const c of p.items || []) map[c.provider] = c;
      setConfigs(map);
      setHistory(h.items || []);
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Failed to load");
    }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  React.useEffect(() => {
    // Seed the form for the active tab from the saved config.
    const c = configs[active] || {};
    setForm({
      api_token: "",  // paste-only, never round-tripped
      site_id: c.site_id || "",
      site_url: c.site_url || "",
      project_id: c.project_id || "",
      project_name: c.project_name || "",
      account_id: c.account_id || "",
      enabled: !!c.enabled,
      auto_publish_on_generate: !!c.auto_publish_on_generate,
    });
    setTestResult({});
  }, [active, configs]);

  const saved = configs[active];

  const save = async () => {
    setBusy(true);
    try {
      const payload = { provider: active,
                        enabled: !!form.enabled,
                        auto_publish_on_generate: !!form.auto_publish_on_generate };
      if (form.api_token) payload.api_token = form.api_token.trim();
      for (const f of activeMeta.fields) {
        if (form[f.k]) payload[f.k] = form[f.k].trim();
      }
      await api.post("/aeo/llms-txt/publish/config", payload);
      toast.success(`${activeMeta.label} config saved`);
      setForm({ ...form, api_token: "" });
      await load();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  const testConnection = async () => {
    setBusy(true); setTestResult({});
    try {
      const r = await api.post(`/aeo/llms-txt/publish/test/${active}`, {});
      setTestResult(r);
      if (r.ok) toast.success("Connection OK");
      else toast.error(`Connection failed: ${r.error || "unknown"}`);
    } catch (e) {
      const msg = e?.body?.detail || e?.message || "Test failed";
      setTestResult({ ok: false, error: String(msg).slice(0, 200) });
      toast.error(msg);
    } finally { setBusy(false); }
  };

  const publishNow = async (style) => {
    setBusy(true);
    try {
      const r = await api.post(`/aeo/llms-txt/publish/${active}`,
                                  { style });
      toast.success(`Published (${r.filename}, ${r.size_bytes}B) · ${r.status}`);
      await load();
    } catch (e) {
      toast.error(e?.body?.detail || e?.body?.error || e?.message || "Publish failed");
    } finally { setBusy(false); }
  };

  const removeConfig = async () => {
    if (!window.confirm(`Delete ${activeMeta.label} config?`)) return;
    setBusy(true);
    try {
      await api.del(`/aeo/llms-txt/publish/config/${active}`);
      toast.success("Removed");
      await load();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Delete failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="rounded-xl overflow-hidden"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="aeo-llms-publish-panel">
      <button type="button"
               onClick={() => setOpen(!open)}
               className="w-full flex items-center gap-2 px-4 py-3 text-left"
               style={{ color: colors.onSurface }}
               data-testid="aeo-llms-publish-toggle">
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <UploadCloud size={16} />
        <span className="text-sm font-semibold">Auto-publish to your site</span>
        <span className="text-[11px]" style={{ color: colors.muted }}>
          One-click push to Netlify / Vercel / Cloudflare Pages
        </span>
      </button>
      {open ? (
        <div className="px-4 pb-4 space-y-4">
          <div className="flex gap-0.5 p-0.5 rounded-md w-fit"
                style={{ backgroundColor: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                role="tablist" data-testid="aeo-llms-publish-tabs">
            {_P9_TABS.map((t) => (
              <button key={t.key} type="button"
                       onClick={() => setActive(t.key)}
                       className="px-3 py-1 rounded text-xs font-semibold flex items-center gap-1"
                       style={{
                         backgroundColor: active === t.key ? colors.brand : "transparent",
                         color: active === t.key ? "#fff" : colors.onSurface,
                       }}
                       data-testid={`aeo-llms-publish-tab-${t.key}`}>
                <Cloud size={12} /> {t.label}
                {configs[t.key]?.enabled ? (
                  <span className="inline-block w-1.5 h-1.5 rounded-full"
                         style={{ backgroundColor: "#10B981" }} />
                ) : null}
              </button>
            ))}
          </div>

          <div className="space-y-3">
            <div className="flex items-center gap-2 flex-wrap text-xs"
                  style={{ color: colors.muted }}>
              <span>API token</span>
              {saved?.api_token_masked ? (
                <span className="px-1.5 py-0.5 rounded font-mono"
                       style={{ backgroundColor: colors.surfaceSecondary,
                                 color: colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                       data-testid={`aeo-llms-publish-masked-${active}`}>
                  {saved.api_token_masked}
                </span>
              ) : (
                <span style={{ color: "#DC2626" }}>Not configured</span>
              )}
              <a href={activeMeta.docs} target="_blank" rel="noopener noreferrer"
                  className="ml-auto text-[11px] inline-flex items-center gap-1"
                  style={{ color: colors.brand }}>
                Where do I get this? <ExternalLink size={10} />
              </a>
            </div>
            <input type="password" value={form.api_token || ""}
                    onChange={(e) => setForm({ ...form, api_token: e.target.value })}
                    placeholder={saved?.api_token_masked
                                    ? "Paste to replace the current token…"
                                    : "Paste your Personal Access Token"}
                    className="w-full rounded-lg px-3 py-1.5 text-sm font-mono"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid={`aeo-llms-publish-token-${active}`} />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {activeMeta.fields.map((f) => (
                <div key={f.k}>
                  <label className="text-[11px] font-semibold block mb-0.5"
                          style={{ color: colors.muted }}>{f.label}</label>
                  <input value={form[f.k] || ""}
                          onChange={(e) => setForm({ ...form, [f.k]: e.target.value })}
                          placeholder={f.placeholder}
                          className="w-full rounded-lg px-2 py-1.5 text-sm"
                          style={{ backgroundColor: colors.surfaceSecondary,
                                    color: colors.onSurface,
                                    border: `1px solid ${colors.border}` }}
                          data-testid={`aeo-llms-publish-field-${active}-${f.k}`} />
                  {f.hint ? (
                    <div className="text-[10px] mt-0.5" style={{ color: colors.muted }}>
                      {f.hint}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              <label className="flex items-center gap-2 text-sm"
                      style={{ color: colors.onSurface }}>
                <input type="checkbox" checked={!!form.enabled}
                        onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                        data-testid={`aeo-llms-publish-enabled-${active}`} />
                Enabled
              </label>
              <label className="flex items-center gap-2 text-sm"
                      style={{ color: colors.onSurface }}>
                <input type="checkbox" checked={!!form.auto_publish_on_generate}
                        onChange={(e) => setForm({ ...form,
                                                      auto_publish_on_generate: e.target.checked })}
                        data-testid={`aeo-llms-publish-auto-${active}`} />
                Auto-publish on Generate
              </label>
            </div>

            {activeMeta.note ? (
              <div className="text-[11px] p-2 rounded-md"
                    style={{ backgroundColor: "#FEF3C7", color: "#92400E",
                              border: "1px solid #FCD34D" }}>
                {activeMeta.note}
              </div>
            ) : null}

            <div className="flex gap-2 flex-wrap">
              <button type="button" onClick={save} disabled={busy}
                       className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                       style={{ backgroundColor: colors.brand, color: "#fff" }}
                       data-testid={`aeo-llms-publish-save-${active}`}>
                <Save size={14} /> Save
              </button>
              <button type="button" onClick={testConnection} disabled={busy || !saved}
                       className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                       style={{ backgroundColor: colors.surfaceSecondary,
                                 color: colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                       data-testid={`aeo-llms-publish-test-${active}`}>
                <CheckCircle2 size={14} /> Test connection
              </button>
              <button type="button" onClick={() => publishNow("concise")} disabled={busy || !saved}
                       className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                       style={{ backgroundColor: "#059669", color: "#fff" }}
                       data-testid={`aeo-llms-publish-now-concise-${active}`}>
                <PlayCircle size={14} /> Publish llms.txt
              </button>
              <button type="button" onClick={() => publishNow("full")} disabled={busy || !saved}
                       className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                       style={{ backgroundColor: colors.surfaceSecondary,
                                 color: colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                       data-testid={`aeo-llms-publish-now-full-${active}`}>
                <PlayCircle size={14} /> Publish llms-full.txt
              </button>
              {saved ? (
                <button type="button" onClick={removeConfig} disabled={busy}
                         className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                         style={{ backgroundColor: "transparent",
                                   color: "#DC2626",
                                   border: `1px solid #FCA5A5` }}
                         data-testid={`aeo-llms-publish-delete-${active}`}>
                  <Trash2 size={14} /> Remove
                </button>
              ) : null}
            </div>

            {testResult && Object.keys(testResult).length ? (
              <div className="text-xs p-2 rounded-md flex items-start gap-2"
                    style={{ backgroundColor: testResult.ok ? "#ECFDF5" : "#FEE2E2",
                              color: testResult.ok ? "#065F46" : "#991B1B",
                              border: `1px solid ${testResult.ok ? "#A7F3D0" : "#FCA5A5"}` }}
                    data-testid={`aeo-llms-publish-test-result-${active}`}>
                {testResult.ok ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                <div>
                  {testResult.ok
                    ? `OK · ${JSON.stringify(testResult.account_info || {})}`
                    : `Failed · ${testResult.error || "unknown"}${testResult.detail ? " · " + testResult.detail : ""}`}
                </div>
              </div>
            ) : null}
          </div>

          <div className="pt-2 border-t"
                style={{ borderColor: colors.border }}
                data-testid="aeo-llms-publish-history">
            <div className="text-[11px] uppercase tracking-wide font-semibold mb-2"
                  style={{ color: colors.muted }}>Publish history</div>
            {history.length === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }}>
                No publishes yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs"
                        style={{ color: colors.onSurface }}>
                  <thead>
                    <tr style={{ color: colors.muted }}>
                      <th className="text-left py-1 pr-2">When</th>
                      <th className="text-left py-1 pr-2">Provider</th>
                      <th className="text-left py-1 pr-2">File</th>
                      <th className="text-right py-1 pr-2">Size</th>
                      <th className="text-left py-1 pr-2">Status</th>
                      <th className="text-left py-1 pr-2">Deploy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.publish_id}
                           style={{ borderTop: `1px solid ${colors.border}` }}
                           data-testid={`aeo-llms-publish-row-${h.publish_id}`}
                           title={h.error_message || ""}>
                        <td className="py-1 pr-2 font-mono text-[11px]">
                          {(h.requested_at || "").slice(0, 19).replace("T", " ")}
                        </td>
                        <td className="py-1 pr-2">{h.provider}</td>
                        <td className="py-1 pr-2 font-mono">{h.filename}</td>
                        <td className="py-1 pr-2 text-right">{h.size_bytes}B</td>
                        <td className="py-1 pr-2">
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                                 style={{
                                   backgroundColor: h.status === "success" ? "#D1FAE5"
                                     : h.status === "failed" ? "#FEE2E2" : "#E5E7EB",
                                   color: h.status === "success" ? "#065F46"
                                     : h.status === "failed" ? "#991B1B" : "#374151",
                                 }}>
                            {h.status}
                          </span>
                        </td>
                        <td className="py-1 pr-2">
                          {h.provider_url ? (
                            <a href={h.provider_url} target="_blank" rel="noopener noreferrer"
                                style={{ color: colors.brand }}
                                className="inline-flex items-center gap-1">
                              {(h.provider_deploy_id || "open").slice(0, 12)}
                              <ExternalLink size={10} />
                            </a>
                          ) : h.provider_deploy_id ? (
                            <span className="font-mono">{h.provider_deploy_id.slice(0, 12)}</span>
                          ) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
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

// ── Brand Mentions tab (Phase 5c) ─────────────────────────────────
function MentionsTab() {
  const [dash, setDash] = React.useState(null);
  const [range, setRange] = React.useState("30d");
  const [sentimentFilter, setSentimentFilter] = React.useState("");
  const [domainFilter, setDomainFilter] = React.useState("");
  const [list, setList] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [showCompetitors, setShowCompetitors] = React.useState(false);
  const [competitorInput, setCompetitorInput] = React.useState("");
  const [competitorDomains, setCompetitorDomains] = React.useState([]);
  // Phase 6 · Feb-2026 — response-draft modal state + pending KPI.
  const [draftMention, setDraftMention] = React.useState(null);
  const [pendingDrafts, setPendingDrafts] = React.useState(0);

  const load = React.useCallback(async () => {
    try {
      const params = new URLSearchParams({ range });
      if (domainFilter) params.set("domain", domainFilter);
      if (sentimentFilter) params.set("sentiment", sentimentFilter);
      const [d, l, p] = await Promise.all([
        api.get("/aeo/mentions/dashboard"),
        api.get(`/aeo/mentions/list?${params.toString()}`),
        api.get("/aeo/response/drafts/pending-count").catch(() => ({ pending: 0 })),
      ]);
      setDash(d);
      setList(l);
      setPendingDrafts(p?.pending || 0);
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Failed to load");
    }
  }, [range, domainFilter, sentimentFilter]);
  React.useEffect(() => { load(); }, [load]);

  const runNow = async () => {
    setBusy(true);
    try {
      const r = await api.post("/aeo/mentions/run-now", {});
      if (r.skipped_reason === "cooldown") {
        toast("Cooldown active — last scan < 20h ago");
      } else if (r.provider_configured === false) {
        toast.error("No search API key configured.");
      } else {
        toast.success(`Found ${r.new_mentions} new · ${r.updated_mentions} updated`);
      }
      load();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Run failed");
    } finally { setBusy(false); }
  };

  const saveCompetitors = async () => {
    try {
      const cleaned = competitorInput.split(",").map((s) => s.trim()).filter(Boolean);
      const r = await api.post("/aeo/mentions/competitors", { domains: cleaned });
      setCompetitorDomains(r.domains || []);
      toast.success(`Competitors saved · retagged ${r.retagged_true}`);
      load();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Save failed");
    }
  };

  const mark = async (mention_id, updates) => {
    try {
      await api.post(`/aeo/mentions/${mention_id}/mark`, updates);
      toast.success("Marked");
      load();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Failed");
    }
  };

  const providerConfigured = dash?.provider_configured;

  return (
    <div className="space-y-4" data-testid="aeo-mentions-tab">
      {providerConfigured === false ? (
        <div className="rounded-xl p-3 text-xs flex items-start gap-2"
              style={{ backgroundColor: "#FEF9C3", color: "#713F12",
                        border: "1px solid #FDE68A" }}
              data-testid="aeo-mentions-unconfigured">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div>
            <b>No Search API key configured.</b> Set
            {" "}<code>SERPER_API_KEY</code> (recommended) or
            {" "}<code>GOOGLE_CSE_API_KEY</code> + <code>GOOGLE_CSE_CX</code>
            {" "}in your environment to enable Brand Mention Crawling.
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        <KPI label="Total mentions (30d)" value={dash?.total_30d ?? 0}
              testid="aeo-mentions-total" />
        <KPI label="New this week" value={dash?.new_this_week ?? 0}
              testid="aeo-mentions-new" />
        <KPI label="Sentiment breakdown"
              value={dash ? Object.entries(dash.sentiment_breakdown || {})
                       .map(([k, v]) => `${k}:${v}`).join("  ") || "—" : "—"}
              testid="aeo-mentions-sentiment" />
        <KPI label="Spend / cap"
              value={`$${(dash?.cost_this_month || 0).toFixed(3)}`}
              sub={`cap $${(dash?.cost_cap || 0).toFixed(2)}`}
              color={dash?.cost_capped ? "#DC2626" : colors.onSurface}
              testid="aeo-mentions-cost" />
        <KPI label="Drafts pending action" value={pendingDrafts}
              color={pendingDrafts > 0 ? colors.brand : colors.onSurface}
              testid="aeo-mentions-drafts-pending" />
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
                     data-testid={`aeo-mentions-range-${r}`}>
              {r}
            </button>
          ))}
        </div>
        <input value={domainFilter}
                onChange={(e) => setDomainFilter(e.target.value)}
                placeholder="Filter domain (e.g. yelp.com)"
                className="rounded-lg px-3 py-1.5 text-xs"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface,
                          border: `1px solid ${colors.border}` }}
                data-testid="aeo-mentions-domain-filter" />
        <select value={sentimentFilter}
                onChange={(e) => setSentimentFilter(e.target.value)}
                className="rounded-lg px-2 py-1.5 text-xs"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface,
                          border: `1px solid ${colors.border}` }}
                data-testid="aeo-mentions-sentiment-filter">
          <option value="">All sentiment</option>
          <option value="positive">Positive</option>
          <option value="neutral">Neutral</option>
          <option value="negative">Negative</option>
        </select>
        <button type="button" onClick={runNow}
                 disabled={busy || providerConfigured === false}
                 className="ml-auto flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                 style={{ backgroundColor: colors.brand, color: "#fff" }}
                 data-testid="aeo-mentions-run">
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Globe size={14} />}
          Run scan now
        </button>
      </div>

      <div className="rounded-xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="aeo-mentions-chart">
        <div className="text-xs uppercase tracking-wide font-semibold mb-2"
              style={{ color: colors.muted }}>New mentions per day · {range}</div>
        {(dash?.series_range || []).length === 0 ? (
          <div className="text-center py-10 text-xs"
                style={{ color: colors.muted }}
                data-testid="aeo-mentions-chart-empty">
            No mentions in this range yet.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={dash.series_range}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
              <XAxis dataKey="date" stroke={colors.muted} fontSize={11} />
              <YAxis allowDecimals={false} stroke={colors.muted} fontSize={11} />
              <Tooltip />
              <Area type="monotone" dataKey="count" stroke={colors.brand}
                     fill={colors.brand} fillOpacity={0.2} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {list?.items?.length ? (
        <div className="rounded-xl overflow-hidden"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="aeo-mentions-table">
          <ul className="divide-y" style={{ borderColor: colors.border }}>
            {list.items.map((m) => (
              <MentionRow key={m.mention_id} m={m} onMark={mark}
                            onDraft={() => setDraftMention(m)} />
            ))}
          </ul>
        </div>
      ) : (
        <div className="rounded-xl p-10 text-center"
              style={{ backgroundColor: colors.surface,
                        border: `1px dashed ${colors.border}`,
                        color: colors.muted }}
              data-testid="aeo-mentions-empty">
          No mentions yet. Run a scan or wait for the daily cron.
        </div>
      )}

      <div className="rounded-xl p-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="aeo-mentions-competitors">
        <button type="button" onClick={() => setShowCompetitors((v) => !v)}
                 className="w-full text-left text-xs uppercase tracking-wide font-semibold flex items-center justify-between"
                 style={{ color: colors.muted }}>
          <span>Manage competitor domains</span>
          <span>{showCompetitors ? "−" : "+"}</span>
        </button>
        {showCompetitors ? (
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <input value={competitorInput}
                    onChange={(e) => setCompetitorInput(e.target.value)}
                    placeholder="acme-competitor.com, other-pool-co.com"
                    className="flex-1 rounded-lg px-3 py-1.5 text-xs"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="aeo-mentions-comp-input" />
            <button type="button" onClick={saveCompetitors}
                     className="px-2.5 py-1.5 rounded-md text-xs font-semibold"
                     style={{ backgroundColor: colors.brand, color: "#fff" }}
                     data-testid="aeo-mentions-comp-save">
              Save
            </button>
            {competitorDomains.length ? (
              <div className="w-full text-[11px]"
                    style={{ color: colors.muted }}>
                Current: {competitorDomains.join(", ")}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <ResponseDraftModal
        open={!!draftMention}
        mention={draftMention}
        onClose={() => setDraftMention(null)}
        onChange={() => load()}
      />
    </div>
  );
}

const SENTIMENT_STYLES = {
  positive: { bg: "#DCFCE7", fg: "#166534", border: "#BBF7D0" },
  neutral:  { bg: "#F1F5F9", fg: "#334155", border: "#E2E8F0" },
  negative: { bg: "#FEE2E2", fg: "#991B1B", border: "#FECACA" },
};

function MentionRow({ m, onMark, onDraft }) {
  const sTone = SENTIMENT_STYLES[m.sentiment] || SENTIMENT_STYLES.neutral;
  const [open, setOpen] = React.useState(false);
  // Phase 6 · Feb-2026 — show "Draft reply" for negative sentiment,
  // and for neutral on Reddit / Google Reviews (common complaint venues).
  const dom = (m.domain || "").toLowerCase();
  const neutralComplainVenue = m.sentiment === "neutral" && (
    dom.includes("reddit.com") || (dom.includes("google.com") && (m.url || "").includes("/maps/"))
  );
  const showDraftBtn = m.sentiment === "negative" || neutralComplainVenue;
  const draftStatus = m.latest_draft_status || null;
  return (
    <li className="p-3"
         data-testid={`aeo-mention-row-${m.mention_id}`}>
      <div className="flex items-start gap-3">
        <div className="text-[11px] shrink-0"
              style={{ color: colors.muted, minWidth: 84 }}>
          {(m.discovered_at || "").slice(0, 10)}
          <div className="mt-0.5">
            {m.sentiment ? (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                     style={{ backgroundColor: sTone.bg, color: sTone.fg,
                               border: `1px solid ${sTone.border}` }}>
                {m.sentiment}
              </span>
            ) : null}
            {m.is_competitor_domain ? (
              <span className="text-[10px] font-bold ml-1 px-1.5 py-0.5 rounded-full"
                     style={{ backgroundColor: "#FEF3C7", color: "#92400E",
                               border: "1px solid #FDE68A" }}>
                competitor
              </span>
            ) : null}
            {m.is_own_domain ? (
              <span className="text-[10px] font-bold ml-1 px-1.5 py-0.5 rounded-full"
                     style={{ backgroundColor: "#DBEAFE", color: "#1E40AF",
                               border: "1px solid #BFDBFE" }}>
                own
              </span>
            ) : null}
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <a href={m.url} target="_blank" rel="noopener noreferrer"
              className="text-sm font-semibold flex items-center gap-1 truncate"
              style={{ color: colors.brand }}>
            {m.title || m.url} <ExternalLink size={11} className="shrink-0" />
          </a>
          <div className="text-[11px]" style={{ color: colors.muted }}>
            {m.domain}
          </div>
          {m.snippet ? (
            <div className="text-[12px] mt-1 line-clamp-2"
                  style={{ color: colors.onSurface }}>
              {m.snippet}
            </div>
          ) : null}
        </div>
        <button type="button" onClick={() => setOpen((v) => !v)}
                 className="text-[11px] font-semibold px-2 py-1 rounded-md shrink-0"
                 style={{ backgroundColor: colors.surfaceSecondary,
                           color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                 data-testid={`aeo-mention-mark-${m.mention_id}`}>
          Mark
        </button>
        {showDraftBtn ? (
          draftStatus ? (
            <button type="button" onClick={() => onDraft?.()}
                     className="text-[11px] font-semibold px-2 py-1 rounded-md shrink-0 flex items-center gap-1"
                     style={{
                       backgroundColor: SENTIMENT_STYLES[
                         draftStatus === "posted" ? "positive"
                         : draftStatus === "discarded" ? "negative"
                         : "neutral"].bg,
                       color: SENTIMENT_STYLES[
                         draftStatus === "posted" ? "positive"
                         : draftStatus === "discarded" ? "negative"
                         : "neutral"].fg,
                       border: `1px solid ${SENTIMENT_STYLES[
                         draftStatus === "posted" ? "positive"
                         : draftStatus === "discarded" ? "negative"
                         : "neutral"].border}`,
                     }}
                     data-testid={`aeo-mention-view-draft-${m.mention_id}`}>
              View draft · {draftStatus}
            </button>
          ) : (
            <button type="button" onClick={() => onDraft?.()}
                     className="text-[11px] font-semibold px-2 py-1 rounded-md shrink-0 flex items-center gap-1"
                     style={{ backgroundColor: colors.brand, color: "#fff" }}
                     data-testid={`aeo-mention-draft-${m.mention_id}`}>
              Draft reply
            </button>
          )
        ) : null}
      </div>
      {open ? (
        <div className="mt-2 flex items-center gap-1 flex-wrap"
              data-testid={`aeo-mention-mark-menu-${m.mention_id}`}>
          {["positive", "neutral", "negative"].map((s) => (
            <button key={s} type="button"
                     onClick={() => onMark(m.mention_id, { sentiment: s })}
                     className="text-[10px] font-semibold px-2 py-1 rounded-md"
                     style={{ backgroundColor: colors.surfaceSecondary,
                               color: colors.onSurface,
                               border: `1px solid ${colors.border}` }}>
              sentiment:{s}
            </button>
          ))}
          {["competitor", "customer", "press", "ignore"].map((t) => (
            <button key={t} type="button"
                     onClick={() => onMark(m.mention_id, { tag: t })}
                     className="text-[10px] font-semibold px-2 py-1 rounded-md"
                     style={{ backgroundColor: colors.surfaceSecondary,
                               color: colors.onSurface,
                               border: `1px solid ${colors.border}` }}>
              tag:{t}
            </button>
          ))}
        </div>
      ) : null}
    </li>
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
      {tab === "mentions" ? <MentionsTab /> : null}
      {tab === "library" ? <ResponseLibraryTab /> : null}
    </div>
  );
}

// ── Phase 10 · sub-item D · Response Library tab ─────────────────
function ResponseLibraryTab() {
  const [items, setItems] = React.useState([]);
  const [platform, setPlatform] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setBusy(true);
    try {
      const q = platform ? `?platform=${platform}&limit=100` : "?limit=100";
      const r = await api.get(`/aeo/response/templates${q}`);
      setItems(r.items || []);
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Failed to load");
    } finally { setBusy(false); }
  }, [platform]);
  React.useEffect(() => { load(); }, [load]);

  const removeItem = async (tpl) => {
    if (!window.confirm(`Delete this template? "${tpl.template_text.slice(0, 40)}…"`)) return;
    try {
      await api.del(`/aeo/response/templates/${tpl.template_id}`);
      toast.success("Deleted");
      await load();
    } catch (e) { toast.error(e?.message || "Delete failed"); }
  };

  const filtered = items.filter((t) =>
    !query || (t.template_text || "").toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="space-y-3" data-testid="aeo-library-tab">
      <div className="rounded-xl p-3 space-y-2"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={platform}
                   onChange={(e) => setPlatform(e.target.value)}
                   className="rounded-lg px-2 py-1 text-sm"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="aeo-lib-platform-filter">
            <option value="">All platforms</option>
            {["yelp", "google_reviews", "nextdoor", "reddit", "facebook", "bbb", "generic"].map((p) =>
              <option key={p} value={p}>{p}</option>)}
          </select>
          <input value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search template text…"
                  className="flex-1 min-w-[200px] rounded-lg px-2 py-1 text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                  data-testid="aeo-lib-query" />
          <span className="text-xs" style={{ color: colors.muted }}>
            {filtered.length} of {items.length}
          </span>
        </div>
      </div>

      {items.length === 0 && !busy ? (
        <div className="rounded-xl p-6 text-center text-sm"
              style={{ backgroundColor: colors.surface,
                        color: colors.muted,
                        border: `1px dashed ${colors.border}` }}
              data-testid="aeo-lib-empty">
          <LibraryBig size={20} className="mx-auto mb-2 opacity-60" />
          Templates appear here once you post drafts on the Brand Mentions tab.
        </div>
      ) : (
        <div className="rounded-xl overflow-hidden"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs"
                  style={{ color: colors.onSurface }}
                  data-testid="aeo-lib-table">
            <thead>
              <tr style={{ color: colors.muted,
                            borderBottom: `1px solid ${colors.border}` }}>
                <th className="text-left py-2 px-3">Platform</th>
                <th className="text-left py-2 px-3">Tone</th>
                <th className="text-left py-2 px-3">Template</th>
                <th className="text-right py-2 px-3">Uses</th>
                <th className="text-right py-2 px-3">30d</th>
                <th className="text-left py-2 px-3">Last used</th>
                <th className="text-right py-2 px-3"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.template_id}
                     style={{ borderTop: `1px solid ${colors.border}` }}
                     data-testid={`aeo-lib-row-${t.template_id}`}>
                  <td className="py-2 px-3">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                           style={{ backgroundColor: colors.surfaceSecondary,
                                     border: `1px solid ${colors.border}` }}>
                      {t.platform}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                           style={{ backgroundColor: "#EDE9FE", color: "#5B21B6",
                                     border: "1px solid #DDD6FE" }}>
                      {t.tone}
                    </span>
                  </td>
                  <td className="py-2 px-3 max-w-md">
                    <div className="line-clamp-2" style={{ color: colors.onSurface }}>
                      {(t.template_text || "").slice(0, 120)}
                      {(t.template_text || "").length > 120 ? "…" : ""}
                    </div>
                  </td>
                  <td className="py-2 px-3 text-right font-mono">{t.use_count}</td>
                  <td className="py-2 px-3 text-right font-mono">{t.times_used_last_30d}</td>
                  <td className="py-2 px-3 font-mono text-[11px]"
                       style={{ color: colors.muted }}>
                    {(t.last_used_at || "").slice(0, 10) || "—"}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <button type="button" onClick={() => removeItem(t)}
                             className="p-1 rounded hover:bg-red-50"
                             style={{ color: "#DC2626" }}
                             data-testid={`aeo-lib-delete-${t.template_id}`}
                             aria-label="Delete">
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
