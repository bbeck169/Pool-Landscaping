import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import {
  ArrowLeft, Plus, Search, Save, Sparkles, Play, Calendar as CalIcon,
  Link as LinkIcon, Check, X, ExternalLink, Settings, MapPin, Star,
} from "lucide-react";
import { api } from "@/api";
import { colors, brandGradient } from "@/theme";

function Card({ children, className = "", testId }) {
  return <div className={`rounded-2xl ${className}`}
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid={testId}>{children}</div>;
}
function Header({ title, subtitle, right, backTo }) {
  const nav = useNavigate();
  return (
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <div className="flex items-center gap-3">
        <button onClick={() => (backTo ? nav(backTo) : nav(-1))}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
          {subtitle ? <p className="text-xs mt-0.5" style={{ color: colors.muted }}>{subtitle}</p> : null}
        </div>
      </div>
      {right}
    </div>
  );
}
function Toast({ msg, onDone }) {
  useEffect(() => { if (!msg) return; const t = setTimeout(onDone, 2500); return () => clearTimeout(t); }, [msg, onDone]);
  if (!msg) return null;
  return <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
              style={{ backgroundColor: colors.onSurface, color: "#fff" }} data-testid="seo-toast">{msg}</div>;
}
function Pill({ children, tone = "muted" }) {
  const map = {
    ok: { bg: "#DCFCE7", fg: "#16A34A" }, warn: { bg: "#FEF3C7", fg: "#92400E" },
    err: { bg: "#FEE2E2", fg: "#B91C1C" }, muted: { bg: colors.surfaceTertiary, fg: colors.muted },
    brand: { bg: colors.brandTertiary, fg: colors.onBrandTertiary },
  };
  const m = map[tone] || map.muted;
  return <span className="px-2 py-0.5 rounded-md text-xs font-bold" style={{ backgroundColor: m.bg, color: m.fg }}>{children}</span>;
}

// ─── SEO Hub ───────────────────────────────────────────────────────────────
export function SeoHub() {
  const [articles, setArticles] = useState([]);
  const [schedule, setSchedule] = useState(null);
  useEffect(() => {
    api.get("/seo/articles").then((r) => setArticles(Array.isArray(r) ? r : []));
    api.get("/seo/schedule").then(setSchedule).catch(() => {});
  }, []);
  const published = articles.filter((a) => a.status === "published").length;
  const tiles = [
    { to: "/seo/articles", label: "Articles", sub: "Draft, schedule, publish" },
    { to: "/seo/keywords", label: "Keywords", sub: "AI keyword suggestions" },
    { to: "/seo/audit", label: "Audit", sub: "Site SEO health check" },
    { to: "/seo/rank-grid", label: "Rank Grid", sub: "Rank by geo + keyword" },
    { to: "/seo/wordpress", label: "WordPress", sub: "Site connection + drip" },
  ];
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="seo-hub">
      <h1 className="text-3xl md:text-4xl font-bold mb-1" style={{ color: colors.onSurface }}>SEO Studio</h1>
      <p className="text-sm mb-6" style={{ color: colors.muted }}>Article drafting, keyword research, audits, and auto-drip.</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          { l: "Articles published", v: published },
          { l: "Drafts", v: articles.filter((a) => a.status === "draft").length },
          { l: "Scheduled", v: articles.filter((a) => a.status === "scheduled").length },
          { l: "Next drip", v: schedule?.next_run ? (schedule.next_run || "").slice(0, 10) : "—" },
        ].map((k) => (
          <div key={k.l} className="rounded-2xl p-4"
               style={{ background: `linear-gradient(135deg, ${brandGradient[0]}, ${brandGradient[1]})`, color: "#fff" }}
               data-testid={`seo-kpi-${k.l.toLowerCase().replace(/\s+/g, "-")}`}>
            <div className="text-xs opacity-90">{k.l}</div>
            <div className="text-2xl font-bold mt-1">{k.v}</div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {tiles.map((t) => (
          <Link key={t.to} to={t.to} className="rounded-2xl p-5 hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`seo-tile-${t.label.toLowerCase()}`}>
            <div className="font-semibold" style={{ color: colors.onSurface }}>{t.label}</div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>{t.sub}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ─── Articles ──────────────────────────────────────────────────────────────
export function ArticlesList() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ keyword: "", title: "", tone: "Local Expert", word_count: 800 });
  useEffect(() => { api.get("/seo/articles").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  const create = async () => {
    if (!form.keyword) return;
    setBusy(true);
    try {
      const doc = await api.post("/seo/articles", form);
      nav(`/seo/articles/${doc.id}`);
    } finally { setBusy(false); }
  };
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="articles-list">
      <Header title="SEO Articles" subtitle="Drafts, schedules, and published copy" backTo="/seo" />
      <Card className="p-4 mb-4">
        <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>New article (AI-drafted)</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <input value={form.keyword} onChange={(e) => setForm({ ...form, keyword: e.target.value })}
                 placeholder="Target keyword *"
                 className="px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="art-keyword" />
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                 placeholder="Working title (optional)"
                 className="px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="art-title" />
          <select value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })}
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="art-tone">
            {["Local Expert", "Friendly", "Professional", "Playful"].map((t) => <option key={t}>{t}</option>)}
          </select>
          <button onClick={create} disabled={busy || !form.keyword.trim()}
                  className="px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="art-generate">
            <Sparkles size={14} className="inline mr-1" /> Generate
          </button>
        </div>
      </Card>
      {rows.length === 0 ? (
        <Card className="p-8 text-center text-sm" testId="articles-empty">
          <div style={{ color: colors.muted }}>No articles yet.</div>
        </Card>
      ) : rows.map((a) => (
        <Card key={a.id} className="p-4 mb-2" testId={`article-row-${a.id}`}>
          <Link to={`/seo/articles/${a.id}`} className="block hover:brightness-95">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div>
                <div className="font-semibold" style={{ color: colors.onSurface }}>{a.title}</div>
                <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                  keyword: <b>{a.keyword}</b> · {a.word_count || 0} words
                </div>
              </div>
              <Pill tone={a.status === "published" ? "ok" : a.status === "scheduled" ? "brand" : "muted"}>{a.status}</Pill>
            </div>
          </Link>
        </Card>
      ))}
    </div>
  );
}

export function ArticleEditor() {
  const { id } = useParams();
  const [doc, setDoc] = useState(null);
  const [toast, setToast] = useState("");
  useEffect(() => {
    if (!id) return;
    api.get(`/seo/articles/${id}`).then(setDoc).catch(() => {});
  }, [id]);
  if (!doc) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  const save = async () => {
    const r = await api.patch(`/seo/articles/${id}`, {
      title: doc.title, meta_description: doc.meta_description,
      body_markdown: doc.body_markdown, tags: doc.tags,
    });
    setDoc(r); setToast(`Saved · ${r.word_count} words`);
  };
  const schedule = async () => {
    const at = window.prompt("Publish date/time (ISO, e.g. 2026-08-01T14:00)");
    if (!at) return;
    await api.post(`/seo/articles/${id}/schedule`, { scheduled_at: at });
    setToast("Scheduled");
    api.get(`/seo/articles/${id}`).then(setDoc);
  };
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="article-editor">
      <Header title={doc.title || "Untitled"}
              subtitle={`keyword: ${doc.keyword} · ${doc.word_count || 0} words · ${doc.status}`}
              backTo="/seo/articles"
              right={<div className="flex gap-2">
                <button onClick={schedule} className="px-3 py-2 text-sm font-semibold rounded-lg"
                        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                        data-testid="art-schedule">
                  <CalIcon size={13} className="inline mr-1" /> Schedule
                </button>
                <button onClick={save} className="px-3 py-2 text-sm font-semibold rounded-lg"
                        style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="art-save">
                  <Save size={13} className="inline mr-1" /> Save
                </button>
              </div>} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Card className="p-4">
          <label className="block mb-3">
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Title</div>
            <input value={doc.title || ""} onChange={(e) => setDoc({ ...doc, title: e.target.value })}
                   className="w-full px-3 py-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="ed-title" />
          </label>
          <label className="block mb-3">
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Meta description</div>
            <textarea rows={2} value={doc.meta_description || ""}
                      onChange={(e) => setDoc({ ...doc, meta_description: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="ed-meta" />
          </label>
          <label className="block">
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Body (markdown)</div>
            <textarea rows={20} value={doc.body_markdown || ""}
                      onChange={(e) => setDoc({ ...doc, body_markdown: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg text-xs font-mono"
                      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="ed-body" />
          </label>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>PREVIEW</div>
          <div className="prose prose-sm max-w-none overflow-y-auto"
               style={{ color: colors.onSurface, maxHeight: 560, lineHeight: 1.6 }} data-testid="ed-preview">
            <ReactMarkdown
              components={{
                h1: (p) => <h1 className="text-xl font-bold mt-4 mb-2" {...p} />,
                h2: (p) => <h2 className="text-lg font-bold mt-4 mb-2" {...p} />,
                h3: (p) => <h3 className="text-base font-bold mt-3 mb-1" {...p} />,
                p: (p) => <p className="text-sm mb-2.5" {...p} />,
                ul: (p) => <ul className="list-disc pl-5 mb-2.5 space-y-1" {...p} />,
              }}>
              {doc.body_markdown || ""}
            </ReactMarkdown>
          </div>
        </Card>
      </div>
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── Keywords ──────────────────────────────────────────────────────────────
export function KeywordSuggest() {
  const nav = useNavigate();
  const [form, setForm] = useState({ seed: "", geo: "85383" });
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const suggest = async () => {
    setBusy(true);
    try {
      const r = await api.post("/seo/keywords/suggest", form);
      setResults(r.keywords || []);
    } finally { setBusy(false); }
  };
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="keywords-page">
      <Header title="Keyword Suggestions" subtitle="AI-estimated volumes + difficulty" backTo="/seo" />
      <Card className="p-4 mb-4">
        <div className="grid grid-cols-3 gap-2 items-end">
          <input value={form.seed} onChange={(e) => setForm({ ...form, seed: e.target.value })}
                 placeholder="Seed keyword"
                 className="px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="kw-seed" />
          <input value={form.geo} onChange={(e) => setForm({ ...form, geo: e.target.value })}
                 placeholder="Geo (zip)"
                 className="px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="kw-geo" />
          <button onClick={suggest} disabled={busy || !form.seed}
                  className="px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="kw-suggest">
            <Search size={13} className="inline mr-1" /> Suggest
          </button>
        </div>
      </Card>
      {results.map((k, i) => (
        <Card key={i} className="p-3 mb-2 flex items-center gap-3" testId={`kw-row-${i}`}>
          <div className="flex-1">
            <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{k.keyword}</div>
            <div className="text-xs" style={{ color: colors.muted }}>volume {k.volume} · difficulty {k.difficulty}</div>
          </div>
          <button onClick={() => nav(`/seo/articles?kw=${encodeURIComponent(k.keyword)}`)}
                  className="px-3 py-1.5 text-xs font-semibold rounded-lg"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid={`kw-use-${i}`}>
            Add to article
          </button>
        </Card>
      ))}
    </div>
  );
}

// ─── Audit ─────────────────────────────────────────────────────────────────
export function SeoAudit() {
  const [url, setUrl] = useState("https://poolandlandscapingofvistancia.com");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api.post("/seo/audit", { url });
      setResult(r);
    } finally { setBusy(false); }
  };
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="audit-page">
      <Header title="Site Audit" subtitle="On-page SEO health check" backTo="/seo" />
      <Card className="p-4 mb-4">
        <div className="grid grid-cols-4 gap-2">
          <input value={url} onChange={(e) => setUrl(e.target.value)}
                 className="col-span-3 px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="audit-url" />
          <button onClick={run} disabled={busy}
                  className="px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="audit-run">
            {busy ? "Auditing…" : "Audit"}
          </button>
        </div>
      </Card>
      {result && (
        <Card className="p-5" testId="audit-result">
          {result.stubbed || result.__stubbed__ ? (
            <div className="text-xs mb-3" style={{ color: colors.muted }}>Estimated — real audit runs once EMERGENT_LLM_KEY is configured.</div>
          ) : null}
          {typeof result.score === "number" && (
            <div className="mb-3">
              <div className="text-xs" style={{ color: colors.muted }}>Score</div>
              <div className="text-3xl font-bold" style={{ color: colors.brand }}>{result.score}</div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 text-sm">
            {Object.entries(result.checks || {}).map(([k, v]) => (
              <div key={k} className="flex justify-between py-1" style={{ borderBottom: `1px solid ${colors.border}` }}>
                <span style={{ color: colors.muted }}>{k}</span><span style={{ color: colors.onSurface }}>{String(v)}</span>
              </div>
            ))}
          </div>
          {(result.recommendations || []).length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Recommendations</div>
              <ul className="list-disc pl-5 text-sm space-y-1" style={{ color: colors.onSurface }}>
                {result.recommendations.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

// ─── Rank Grid ─────────────────────────────────────────────────────────────
export function RankGrid() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/rank-grid").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="rank-grid-page">
      <Header title="Rank Grid" subtitle="Keyword rank by geography" backTo="/seo" />
      {rows.length === 0 ? (
        <Card className="p-8 text-center text-sm" testId="rank-empty">
          <div style={{ color: colors.muted }}>No tracked keywords yet.</div>
        </Card>
      ) : (
        <Card className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 text-xs font-semibold uppercase" style={{ color: colors.muted }}>Keyword</th>
                <th className="text-left px-3 py-2 text-xs font-semibold uppercase" style={{ color: colors.muted }}>ZIP</th>
                <th className="text-left px-3 py-2 text-xs font-semibold uppercase" style={{ color: colors.muted }}>Rank</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td className="px-3 py-2" style={{ color: colors.onSurface }}>{r.keyword}</td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{r.zip || "—"}</td>
                  <td className="px-3 py-2">
                    <Pill tone={r.rank && r.rank <= 3 ? "ok" : r.rank && r.rank <= 10 ? "warn" : "err"}>
                      {r.rank || "—"}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

// ─── WordPress ─────────────────────────────────────────────────────────────
export function WordPressSettings() {
  const [form, setForm] = useState({ site_url: "", username: "", app_password: "" });
  const [schedule, setSchedule] = useState({ enabled: false, days: [], hour: 9 });
  const [toast, setToast] = useState("");
  const [testResult, setTestResult] = useState(null);
  useEffect(() => {
    api.get("/seo/wp-settings").then((r) => r && setForm({ ...form, ...r })).catch(() => {});
    api.get("/seo/schedule").then((r) => r && setSchedule({ ...schedule, ...r })).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const save = async () => { await api.put("/seo/wp-settings", form); setToast("WP settings saved"); };
  const test = async () => {
    try {
      const r = await api.post("/seo/wp-settings/test", form);
      setTestResult(r); setToast(r.ok ? "Connection OK" : `Failed: ${r.error || r.message}`);
    } catch (e) { setTestResult({ ok: false, error: e.message }); setToast(e.message); }
  };
  const saveSchedule = async () => { await api.put("/seo/schedule", schedule); setToast("Drip schedule saved"); };
  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="wordpress-page">
      <Header title="WordPress" subtitle="Site connection + weekly drip publish" backTo="/seo" />
      <Card className="p-5 mb-4">
        <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>Connection</div>
        <div className="space-y-2">
          <input value={form.site_url || ""} onChange={(e) => setForm({ ...form, site_url: e.target.value })}
                 placeholder="https://your-wp-site.com"
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="wp-url" />
          <input value={form.username || ""} onChange={(e) => setForm({ ...form, username: e.target.value })}
                 placeholder="WordPress username"
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="wp-user" />
          <input type="password" value={form.app_password || ""} onChange={(e) => setForm({ ...form, app_password: e.target.value })}
                 placeholder="WP Application Password"
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="wp-pass" />
        </div>
        <div className="mt-3 flex gap-2 justify-end">
          <button onClick={test} className="px-3 py-2 text-sm font-semibold rounded-lg"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="wp-test">Test connection</button>
          <button onClick={save} className="px-3 py-2 text-sm font-semibold rounded-lg"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="wp-save">Save</button>
        </div>
        {testResult && (
          <div className="mt-3 text-xs p-2 rounded-lg" data-testid="wp-test-result"
               style={{ backgroundColor: testResult.ok ? "#DCFCE7" : "#FEE2E2", color: testResult.ok ? "#16A34A" : "#B91C1C" }}>
            {testResult.ok ? "✓ Connection successful" : `✗ ${testResult.error || testResult.message || "Failed"}`}
          </div>
        )}
      </Card>
      <Card className="p-5">
        <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>Auto-drip schedule</div>
        <label className="flex items-center gap-2 mb-3">
          <input type="checkbox" checked={!!schedule.enabled}
                 onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })}
                 data-testid="wp-drip-enabled" />
          <span className="text-sm" style={{ color: colors.onSurface }}>Enable weekly auto-drip publish</span>
        </label>
        <div className="flex flex-wrap gap-2 mb-3">
          {["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d) => {
            const on = (schedule.days || []).includes(d);
            return <button key={d}
                           onClick={() => setSchedule({ ...schedule, days: on ? schedule.days.filter((x) => x !== d) : [...(schedule.days || []), d] })}
                           className="px-3 py-1.5 text-xs font-semibold rounded-lg"
                           style={{ backgroundColor: on ? colors.brand : colors.surfaceSecondary,
                                    color: on ? "#fff" : colors.onSurface,
                                    border: `1px solid ${on ? colors.brand : colors.border}` }}
                           data-testid={`wp-day-${d}`}>{d}</button>;
          })}
        </div>
        <div className="flex gap-2 items-center mb-3">
          <span className="text-xs" style={{ color: colors.muted }}>Hour of day (UTC):</span>
          <input type="number" min={0} max={23} value={schedule.hour || 9}
                 onChange={(e) => setSchedule({ ...schedule, hour: parseInt(e.target.value, 10) })}
                 className="w-20 px-3 py-1.5 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="wp-hour" />
        </div>
        <div className="flex justify-end">
          <button onClick={saveSchedule} className="px-3 py-2 text-sm font-semibold rounded-lg"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="wp-schedule-save">Save schedule</button>
        </div>
      </Card>
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── GBP Hub ───────────────────────────────────────────────────────────────
export function GbpHub() {
  const [status, setStatus] = useState(null);
  const [tab, setTab] = useState("posts");
  const [posts, setPosts] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [ai, setAi] = useState({ autopost: false, auto_reply: false });
  useEffect(() => {
    api.get("/gbp/status").then(setStatus).catch(() => setStatus({ connected: false, message: "GBP unavailable" }));
    api.get("/gbp/posts").then((r) => setPosts(Array.isArray(r) ? r : [])).catch(() => {});
    api.get("/gbp/reviews").then((r) => setReviews(Array.isArray(r) ? r : [])).catch(() => {});
    api.get("/gbp/autopost").then((r) => r && setAi({ ...ai, ...r })).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const connect = async () => {
    try {
      const r = await api.get("/gbp/oauth/auth-url");
      window.open(r.url, "_blank");
    } catch (e) {
      alert(e.message || "GBP not connected — configure OAuth credentials in Business Info first.");
    }
  };
  if (!status) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="gbp-hub">
      <Header title="Google Business Profile" subtitle={status.message} backTo="/marketing" />
      {!status.connected ? (
        <Card className="p-8 text-center" testId="gbp-not-connected">
          <MapPin size={40} className="mx-auto mb-3" style={{ color: colors.brand }} />
          <div className="text-lg font-bold mb-1" style={{ color: colors.onSurface }}>Connect Google Business Profile</div>
          <p className="text-sm mb-4" style={{ color: colors.muted }}>
            {status.message}
          </p>
          <button onClick={connect}
                  className="px-4 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="gbp-connect-btn">
            Connect Google Business Profile
          </button>
          <div className="mt-4 text-xs" style={{ color: colors.muted }}>
            No OAuth credentials configured yet — the button will error with a friendly message until you set them.
          </div>
        </Card>
      ) : (
        <>
          <div className="flex gap-2 mb-4 flex-wrap">
            {["posts", "reviews", "business", "calendar", "ai-settings"].map((t) => (
              <button key={t} onClick={() => setTab(t)}
                      className="px-3 py-1.5 rounded-lg text-sm font-semibold"
                      style={{ backgroundColor: tab === t ? colors.brand : colors.surfaceSecondary,
                               color: tab === t ? "#fff" : colors.onSurface,
                               border: `1px solid ${tab === t ? colors.brand : colors.border}` }}
                      data-testid={`gbp-tab-${t}`}>{t}</button>
            ))}
          </div>
          {tab === "posts" && (
            <Card className="p-4">
              <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>Posts</div>
              {posts.map((p) => (
                <div key={p.id} className="py-2 border-t text-sm" style={{ borderColor: colors.border }}>
                  <div>{p.summary || p.body}</div>
                  <div className="text-xs" style={{ color: colors.muted }}>{p.status}</div>
                </div>
              ))}
              {!posts.length && <div className="text-xs" style={{ color: colors.muted }}>No posts yet.</div>}
            </Card>
          )}
          {tab === "reviews" && (
            <Card className="p-4">
              <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>Reviews</div>
              {reviews.map((r) => (
                <div key={r.id} className="py-2 border-t text-sm" style={{ borderColor: colors.border }}>
                  <div className="flex items-center gap-1">
                    {Array.from({ length: r.rating || 5 }).map((_, i) => <Star key={i} size={12} style={{ color: "#F59E0B" }} fill="#F59E0B" />)}
                  </div>
                  <div>{r.comment || r.body}</div>
                </div>
              ))}
              {!reviews.length && <div className="text-xs" style={{ color: colors.muted }}>No reviews.</div>}
            </Card>
          )}
          {tab === "ai-settings" && (
            <Card className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>AI Settings</div>
              {[["autopost", "AI weekly seasonal posts"], ["auto_reply", "AI auto-reply to reviews"]].map(([k, l]) => (
                <label key={k} className="flex items-center gap-2 mb-2">
                  <input type="checkbox" checked={!!ai[k]}
                         onChange={(e) => setAi({ ...ai, [k]: e.target.checked })} data-testid={`gbp-ai-${k}`} />
                  <span className="text-sm">{l}</span>
                </label>
              ))}
              <button onClick={() => api.put("/gbp/autopost", ai).then(() => alert("Saved"))}
                      className="mt-3 px-3 py-2 rounded-lg text-sm font-semibold"
                      style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="gbp-ai-save">Save</button>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
