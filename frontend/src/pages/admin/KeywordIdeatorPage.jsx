/**
 * Phase SEO-C · Feb-2026 — Keyword Ideation.
 *
 * Free keyword-suggestion tool. Runs Google Autocomplete via
 * ``POST /api/keywords/ideate`` in 4 modifier flavours + Google
 * Trends via pytrends (best-effort — surfaced as a yellow banner
 * on error).
 *
 * Admin+/manager only. Sidebar entry under Reports.
 */
import React from "react";
import { toast } from "sonner";
import {
  LineChart as ReLineChart, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer,
} from "recharts";
import { Search, Copy, Download, RefreshCw, AlertTriangle, Clock, Sparkles } from "lucide-react";
import { api } from "@/api";

const TABS = [
  { id: "autocomplete", label: "Autocomplete" },
  { id: "questions",    label: "Questions" },
  { id: "comparisons",  label: "Comparisons" },
  { id: "prepositions", label: "Prepositions" },
  { id: "trends",       label: "Trends" },
];

const REGIONS = [
  { code: "US", label: "United States" },
  { code: "GB", label: "United Kingdom" },
  { code: "CA", label: "Canada" },
  { code: "AU", label: "Australia" },
];
const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "fr", label: "Français" },
];

function _copyList(list) {
  if (!list?.length) {
    toast.info("Nothing to copy"); return;
  }
  navigator.clipboard?.writeText(list.join("\n"));
  toast.success(`Copied ${list.length} rows`);
}

function _downloadCsv(list, seed, category) {
  if (!list?.length) return;
  const csv = "keyword,category\n"
              + list.map((k) =>
                `"${k.replace(/"/g, '""')}","${category}"`).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${seed}-${category}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Suggestion chip list ─────────────────────────────────────────

function ChipList({ items, seed, category }) {
  return (
    <div className="space-y-3" data-testid={`chiplist-${category}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs text-zinc-500">
          {items.length} suggestions
        </span>
        <div className="flex gap-1">
          <button type="button" onClick={() => _copyList(items)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border border-zinc-200 hover:bg-zinc-50"
                  data-testid={`chiplist-copy-${category}`}>
            <Copy size={12} /> Copy all
          </button>
          <button type="button"
                  onClick={() => _downloadCsv(items, seed, category)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border border-zinc-200 hover:bg-zinc-50"
                  data-testid={`chiplist-export-${category}`}>
            <Download size={12} /> Export CSV
          </button>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-zinc-500 italic py-6 text-center border border-dashed border-zinc-300 rounded"
             data-testid={`chiplist-empty-${category}`}>
          No suggestions returned.
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((s, i) => (
            <span key={`${s}-${i}`}
                  className="inline-block bg-white border border-zinc-200 rounded-full px-3 py-1 text-xs text-zinc-700 hover:bg-sky-50 hover:border-sky-300 transition-colors"
                  data-testid={`chip-${category}-${i}`}>
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Trends panel ────────────────────────────────────────────────

function TrendsPanel({ trends, seed }) {
  if (!trends) {
    return (
      <div className="text-sm text-zinc-500 italic p-6 text-center border border-dashed border-zinc-300 rounded"
           data-testid="trends-empty">
        No Trends data captured on this run.
      </div>
    );
  }
  return (
    <div className="space-y-4" data-testid="trends-panel">
      {trends.error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded bg-amber-50 border border-amber-200 text-amber-900 text-sm"
             data-testid="trends-warning-banner">
          <AlertTriangle size={16} />
          Google Trends unavailable this run — try again in a few minutes.
          <span className="text-xs text-amber-700 ml-2">
            ({trends.error})
          </span>
        </div>
      )}
      {(trends.interest_over_time?.length || 0) > 0 && (
        <div className="bg-white border border-zinc-200 rounded p-3"
             data-testid="trends-chart">
          <div className="text-xs text-zinc-500 mb-2">
            Interest over last 12 months for <strong>{seed}</strong>
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <ReLineChart data={trends.interest_over_time}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E4E4E7" />
                <XAxis dataKey="date"
                        tickFormatter={(v) => {
                          try { return new Date(v).toLocaleDateString(
                            undefined, { month: "short" }); }
                          catch { return v; }
                        }}
                        fontSize={10} />
                <YAxis domain={[0, 100]} fontSize={10} />
                <Tooltip />
                <Line type="monotone" dataKey="value"
                        stroke="#0284C7" strokeWidth={2}
                        dot={false} />
              </ReLineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-zinc-200 rounded p-3"
             data-testid="trends-related-top">
          <div className="text-xs font-semibold mb-2 text-zinc-700">
            Related queries · Top
          </div>
          {(trends.related_queries_top || []).length === 0 ? (
            <div className="text-xs text-zinc-500 italic">
              (none)
            </div>
          ) : (
            <ol className="text-xs text-zinc-700 space-y-1 list-decimal ml-5">
              {trends.related_queries_top.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ol>
          )}
        </div>
        <div className="bg-white border border-zinc-200 rounded p-3"
             data-testid="trends-related-rising">
          <div className="text-xs font-semibold mb-2 text-zinc-700">
            Related queries · Rising
          </div>
          {(trends.related_queries_rising || []).length === 0 ? (
            <div className="text-xs text-zinc-500 italic">
              (none)
            </div>
          ) : (
            <ol className="text-xs text-zinc-700 space-y-1 list-decimal ml-5">
              {trends.related_queries_rising.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────

export default function KeywordIdeatorPage() {
  const [seed, setSeed] = React.useState("");
  const [language, setLanguage] = React.useState("en");
  const [region, setRegion] = React.useState("US");
  const [forceRefresh, setForceRefresh] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);
  const [tab, setTab] = React.useState("autocomplete");
  const [history, setHistory] = React.useState([]);

  const loadHistory = React.useCallback(async () => {
    try {
      const r = await api.get("/keywords/history?limit=20");
      setHistory(r?.items || []);
    } catch { /* keep silent — non-fatal */ }
  }, []);

  React.useEffect(() => { loadHistory(); }, [loadHistory]);

  const runIdeate = async () => {
    const s = seed.trim();
    if (!s) { toast.error("Enter a seed keyword"); return; }
    setBusy(true);
    try {
      const r = await api.post("/keywords/ideate", {
        seed_keyword: s,
        language, region,
        force_refresh: forceRefresh,
      }, 60000);
      setResult(r);
      setTab("autocomplete");
      toast.success(r.cached
                     ? "Loaded from cache (24h TTL)"
                     : "Fresh ideation complete");
      await loadHistory();
    } catch (e) {
      toast.error("Ideate failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };

  const loadFromHistory = async (h) => {
    setSeed(h.seed_keyword);
    if (h.lookup_id) {
      try {
        const r = await api.get(`/keywords/lookup/${h.lookup_id}`);
        setResult({ ...r, cached: true });
        setTab("autocomplete");
      } catch (e) {
        toast.error("Failed", { description: e?.message });
      }
    }
  };

  const listFor = (tabId) => {
    if (!result) return [];
    switch (tabId) {
      case "autocomplete": return result.autocomplete_suggestions || [];
      case "questions":    return result.question_suggestions || [];
      case "comparisons":  return result.comparison_suggestions || [];
      case "prepositions": return result.preposition_suggestions || [];
      default:             return [];
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="keyword-ideator-page">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="keyword-ideator-title">
            Keyword Ideation
          </h1>
          <p className="text-sm text-zinc-500 mt-1">
            Free keyword ideas via Google Autocomplete + Google Trends.
            Cached 24h. Rate-limited to 20 fresh lookups/hour.
          </p>
        </div>
      </header>

      {/* Search bar */}
      <div className="bg-white border border-zinc-200 rounded-lg p-3 shadow-sm flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 px-3 py-2 border border-zinc-200 rounded flex-1 min-w-[240px]">
          <Search size={14} className="text-[#0284C7]" />
          <input type="text" placeholder="Seed keyword (e.g. pool service phoenix)"
                 value={seed}
                 onChange={(e) => setSeed(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") runIdeate(); }}
                 className="flex-1 text-sm focus:outline-none"
                 data-testid="keyword-seed-input" />
        </div>
        <select value={region}
                onChange={(e) => setRegion(e.target.value)}
                className="px-3 py-2 border border-zinc-200 rounded text-sm"
                data-testid="keyword-region-select">
          {REGIONS.map((r) => (
            <option key={r.code} value={r.code}>{r.label}</option>
          ))}
        </select>
        <select value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="px-3 py-2 border border-zinc-200 rounded text-sm"
                data-testid="keyword-language-select">
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>{l.label}</option>
          ))}
        </select>
        <label className="text-xs text-zinc-600 inline-flex items-center gap-1">
          <input type="checkbox" checked={forceRefresh}
                  onChange={(e) => setForceRefresh(e.target.checked)}
                  data-testid="keyword-force-refresh" />
          Force refresh
        </label>
        <button type="button" onClick={runIdeate} disabled={busy}
                className="inline-flex items-center gap-2 px-4 py-2 rounded bg-sky-600 text-white text-sm font-medium disabled:opacity-50 hover:bg-sky-700"
                data-testid="keyword-ideate-btn">
          {busy ? <RefreshCw size={14} className="animate-spin" />
                : <Sparkles size={14} />}
          {busy ? "Ideating…" : "Ideate"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-6">
        {/* Recent searches sidebar */}
        <section className="md:col-span-1 bg-white border border-zinc-200 rounded-lg shadow-sm p-3"
                  data-testid="keyword-history">
          <div className="text-xs font-semibold mb-2 text-zinc-700 flex items-center gap-1">
            <Clock size={12} /> Recent searches
          </div>
          {history.length === 0 ? (
            <div className="text-xs text-zinc-500 italic"
                  data-testid="keyword-history-empty">
              No searches yet.
            </div>
          ) : (
            <ul className="space-y-1"
                data-testid="keyword-history-list">
              {history.map((h) => (
                <li key={h.id}>
                  <button type="button" onClick={() => loadFromHistory(h)}
                            className="text-xs text-sky-700 hover:underline truncate max-w-full block text-left"
                            title={h.seed_keyword}
                            data-testid={`keyword-history-row-${h.id}`}>
                    {h.seed_keyword}
                    {h.cached ? (
                      <span className="ml-1 text-[10px] text-zinc-400">
                        · cache
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Results panel */}
        <section className="md:col-span-4 bg-white border border-zinc-200 rounded-lg shadow-sm p-4"
                  data-testid="keyword-results-panel">
          {!result ? (
            <div className="text-sm text-zinc-500 italic p-8 text-center"
                  data-testid="keyword-results-empty">
              Run an ideation to see suggestions here.
            </div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <div className="text-sm">
                  <strong data-testid="keyword-result-seed">
                    {result.seed_keyword}
                  </strong>
                  {" "}
                  <span className="text-zinc-500 text-xs">
                    · {result.region} / {result.language}
                    {result.cached && (
                      <span className="ml-2 text-[10px] bg-zinc-100 text-zinc-600 rounded-full px-2 py-0.5"
                            data-testid="keyword-result-cached">
                        cached
                      </span>
                    )}
                  </span>
                </div>
              </div>
              <div className="flex gap-1 border-b border-zinc-200 mb-4">
                {TABS.map((t) => (
                  <button key={t.id} type="button"
                          onClick={() => setTab(t.id)}
                          className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                            tab === t.id
                              ? "border-sky-600 text-sky-700"
                              : "border-transparent text-zinc-500 hover:text-zinc-800"}`}
                          data-testid={`keyword-tab-${t.id}`}>
                    {t.label}
                  </button>
                ))}
              </div>
              {tab === "trends" ? (
                <TrendsPanel trends={result.trends_summary}
                             seed={result.seed_keyword} />
              ) : (
                <ChipList items={listFor(tab)}
                          seed={result.seed_keyword}
                          category={tab} />
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
