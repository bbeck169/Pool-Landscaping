/**
 * Phase SEO-A · Feb-2026 — Free on-page SEO Auditor.
 *
 * Admin+/manager only. Reads/writes ``/api/seo/scans*``.
 *
 * Layout:
 *   • Top strip: URL input + "Run scan" button.
 *   • Left column: Recent scans table (URL, score, status, ts).
 *   • Right drawer (populated on row-select): score gauge + issue
 *     counts + per-section detail panels + "Re-scan" / "History".
 *   • History modal: recharts line chart of score over time.
 */
import React from "react";
import { toast } from "sonner";
import {
  LineChart as ReLineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  RefreshCw, Play, ExternalLink, AlertTriangle, AlertCircle, Info,
  CheckCircle2, TrendingUp, X,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const STATUS_STYLES = {
  queued:   { bg: "#E0F2FE", fg: "#075985", label: "Queued" },
  running:  { bg: "#FEF3C7", fg: "#92400E", label: "Running" },
  complete: { bg: "#DCFCE7", fg: "#065F46", label: "Complete" },
  error:    { bg: "#FEE2E2", fg: "#7F1D1D", label: "Error" },
};

function _fmtTs(ts) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function _scoreColor(score) {
  if (score == null) return colors.muted;
  if (score >= 85) return "#16A34A";
  if (score >= 60) return "#CA8A04";
  return "#DC2626";
}

// ─── Score gauge (SVG donut) ───────────────────────────────────────

function ScoreGauge({ score }) {
  const s = score ?? 0;
  const R = 52;
  const C = 2 * Math.PI * R;
  const dash = (s / 100) * C;
  const color = _scoreColor(score);
  return (
    <div data-testid="seo-score-gauge"
         className="relative inline-flex items-center justify-center">
      <svg width="130" height="130" viewBox="0 0 130 130">
        <circle cx="65" cy="65" r={R} fill="none"
                stroke="#E4E4E7" strokeWidth="12" />
        <circle cx="65" cy="65" r={R} fill="none"
                stroke={color} strokeWidth="12"
                strokeDasharray={`${dash} ${C - dash}`}
                strokeDashoffset={C * 0.25}
                strokeLinecap="round"
                transform="rotate(-90 65 65)" />
        <text x="65" y="72" textAnchor="middle"
              fontSize="30" fontWeight="700" fill={color}>
          {score == null ? "—" : score}
        </text>
      </svg>
    </div>
  );
}

// ─── Issue count badges ────────────────────────────────────────────

function IssueBadges({ counts }) {
  if (!counts) return null;
  return (
    <div className="flex gap-2" data-testid="seo-issue-badges">
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
            style={{ background: "#FEE2E2", color: "#7F1D1D" }}
            data-testid="seo-issue-critical">
        <AlertCircle size={12} /> Critical {counts.critical}
      </span>
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
            style={{ background: "#FEF3C7", color: "#92400E" }}
            data-testid="seo-issue-warning">
        <AlertTriangle size={12} /> Warning {counts.warning}
      </span>
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
            style={{ background: "#E0F2FE", color: "#075985" }}
            data-testid="seo-issue-notice">
        <Info size={12} /> Notice {counts.notice}
      </span>
    </div>
  );
}

// ─── Per-section renderer helpers ──────────────────────────────────

function _row(label, value, ok, testid) {
  const Icon = ok === true ? CheckCircle2
              : ok === false ? AlertCircle : Info;
  const color = ok === true ? "#16A34A"
              : ok === false ? "#DC2626" : "#71717A";
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-zinc-100"
         key={label} data-testid={testid}>
      <div className="flex items-center gap-2">
        <Icon size={15} style={{ color }} />
        <span className="text-sm font-medium">{label}</span>
      </div>
      <span className="text-sm text-zinc-600 truncate max-w-[60%]"
            title={typeof value === "string" ? value : ""}>
        {value ?? "—"}
      </span>
    </div>
  );
}

function DetailSections({ results }) {
  if (!results) return null;
  const op = results.on_page || {};
  const sc = results.schema_org || {};
  const perf = results.performance || {};
  const sec = results.security || {};
  const robots = results.robots_txt || {};
  const sitemap = results.sitemap_xml || {};
  const mobile = results.mobile_friendly || {};

  return (
    <div className="space-y-6" data-testid="seo-detail-sections">
      <section data-testid="seo-section-on-page">
        <h3 className="text-sm font-semibold mb-2 text-zinc-900">On-page</h3>
        {_row("Title",
              op.title?.value || "(missing)",
              op.title?.present && !op.title?.issue,
              "seo-onpage-title")}
        {_row("Meta description",
              op.meta_description?.value
                ? `${op.meta_description.length} chars`
                : "(missing)",
              op.meta_description?.present && !op.meta_description?.issue,
              "seo-onpage-desc")}
        {_row("H1",
              op.h1?.count === 1
                ? op.h1.values?.[0] || "(single H1)"
                : `${op.h1?.count ?? 0} H1 tags`,
              op.h1?.count === 1,
              "seo-onpage-h1")}
        {_row("Canonical",
              op.canonical?.url || "(missing)",
              op.canonical?.present,
              "seo-onpage-canonical")}
        {_row("OG tags",
              op.og_tags?.missing?.length
                ? `Missing: ${op.og_tags.missing.join(", ")}`
                : "All present",
              op.og_tags?.present,
              "seo-onpage-og")}
        {_row("Viewport",
              op.viewport?.value || "(missing)",
              op.viewport?.present,
              "seo-onpage-viewport")}
        {_row("Images w/ alt",
              op.images_total
                ? `${op.images_total - (op.images_missing_alt || 0)} / ${op.images_total}`
                : "No images",
              (op.images_missing_alt || 0) === 0,
              "seo-onpage-alt")}
        {_row("Broken internal links",
              (op.broken_internal_links || []).length,
              (op.broken_internal_links || []).length === 0,
              "seo-onpage-broken")}
        {_row("Word count",
              op.word_count,
              op.word_count >= 300 ? true : null,
              "seo-onpage-words")}
      </section>

      <section data-testid="seo-section-schema">
        <h3 className="text-sm font-semibold mb-2 text-zinc-900">Schema.org</h3>
        {_row("JSON-LD blocks", sc.blocks_found, sc.blocks_found > 0,
                "seo-schema-blocks")}
        {_row("Types",
              (sc.types || []).join(", ") || "(none)",
              (sc.types || []).length > 0,
              "seo-schema-types")}
      </section>

      <section data-testid="seo-section-performance">
        <h3 className="text-sm font-semibold mb-2 text-zinc-900">Performance</h3>
        {_row("PSI mobile",
              perf.pagespeed_mobile_score != null
                ? `${perf.pagespeed_mobile_score} / 100`
                : perf.pagespeed_error || "unavailable",
              perf.pagespeed_mobile_score >= 50,
              "seo-perf-mobile")}
        {_row("PSI desktop",
              perf.pagespeed_desktop_score != null
                ? `${perf.pagespeed_desktop_score} / 100`
                : perf.pagespeed_error || "unavailable",
              perf.pagespeed_desktop_score >= 50,
              "seo-perf-desktop")}
        {_row("LCP",
              perf.lcp_ms != null ? `${(perf.lcp_ms / 1000).toFixed(2)}s` : "—",
              perf.lcp_ms != null && perf.lcp_ms < 2500,
              "seo-perf-lcp")}
        {_row("CLS",
              perf.cls != null ? perf.cls.toFixed(3) : "—",
              perf.cls != null && perf.cls < 0.1,
              "seo-perf-cls")}
      </section>

      <section data-testid="seo-section-mobile">
        <h3 className="text-sm font-semibold mb-2 text-zinc-900">
          Mobile friendly <span className="text-xs text-zinc-500">(heuristic)</span>
        </h3>
        {_row("Passes heuristic",
              (mobile.issues || []).join(", ") || "yes",
              mobile.pass,
              "seo-mobile-pass")}
      </section>

      <section data-testid="seo-section-security">
        <h3 className="text-sm font-semibold mb-2 text-zinc-900">Security headers</h3>
        {_row("HTTPS", sec.https ? "yes" : "no", sec.https, "seo-sec-https")}
        {_row("HSTS", sec.hsts ? "yes" : "no", sec.hsts, "seo-sec-hsts")}
        {_row("X-Content-Type-Options", sec.x_content_type_options ? "yes" : "no",
                sec.x_content_type_options, "seo-sec-xcto")}
        {_row("Referrer-Policy", sec.referrer_policy ? "yes" : "no",
                sec.referrer_policy, "seo-sec-referrer")}
        {_row("CSP", sec.content_security_policy ? "yes" : "no",
                sec.content_security_policy, "seo-sec-csp")}
      </section>

      <section data-testid="seo-section-robots-sitemap">
        <h3 className="text-sm font-semibold mb-2 text-zinc-900">
          robots.txt &amp; sitemap.xml
        </h3>
        {_row("robots.txt", robots.present ? "found" : "missing",
                robots.present, "seo-robots")}
        {_row("Sitemap referenced", robots.sitemap_ref ? "yes" : "no",
                robots.sitemap_ref, "seo-robots-sitemapref")}
        {_row("sitemap.xml",
              sitemap.present
                ? `${sitemap.url_count ?? 0} urls`
                : "missing",
              sitemap.present,
              "seo-sitemap")}
      </section>
    </div>
  );
}

// ─── Main page component ───────────────────────────────────────────

export default function SeoAuditorPage() {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [selected, setSelected] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [urlInput, setUrlInput] = React.useState("");
  const [scanBusy, setScanBusy] = React.useState(false);
  const [history, setHistory] = React.useState(null);
  const [historyLoading, setHistoryLoading] = React.useState(false);

  const loadList = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/seo/scans?limit=100");
      setItems(r?.items || []);
    } catch (e) {
      toast.error("Failed to load scans", { description: e?.message });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = React.useCallback(async (id) => {
    setSelectedId(id);
    setSelected(null);
    try {
      const r = await api.get(`/seo/scans/${id}`);
      setSelected(r);
    } catch (e) {
      toast.error("Failed to load scan", { description: e?.message });
    }
  }, []);

  React.useEffect(() => { loadList(); }, [loadList]);

  const handleRunScan = async () => {
    const url = urlInput.trim();
    if (!url) {
      toast.error("Enter a URL to scan");
      return;
    }
    setScanBusy(true);
    try {
      const r = await api.post("/seo/scans", { target_url: url, async: true });
      toast.success("Scan queued", {
        description: "Results will appear once complete (~30s)." });
      setUrlInput("");
      await loadList();
      // Poll the specific scan a few times to auto-select it once done.
      const sid = r?.scan_id;
      if (sid) {
        for (let i = 0; i < 20; i++) {
          // eslint-disable-next-line no-await-in-loop
          await new Promise((res) => setTimeout(res, 3000));
          try {
            // eslint-disable-next-line no-await-in-loop
            const d = await api.get(`/seo/scans/${sid}`);
            if (d.status === "complete" || d.status === "error") {
              setSelected(d);
              setSelectedId(sid);
              // eslint-disable-next-line no-await-in-loop
              await loadList();
              break;
            }
          } catch { /* keep polling */ }
        }
      }
    } catch (e) {
      toast.error("Scan failed to start", { description: e?.message });
    } finally {
      setScanBusy(false);
    }
  };

  const handleRerun = async () => {
    if (!selectedId) return;
    try {
      const r = await api.post(`/seo/scans/${selectedId}/rerun`, {});
      toast.success("Re-scan queued");
      setSelectedId(r?.scan_id || null);
      await loadList();
    } catch (e) {
      toast.error("Re-scan failed", { description: e?.message });
    }
  };

  const handleShowHistory = async () => {
    if (!selected?.target_url) return;
    setHistoryLoading(true);
    try {
      const r = await api.get(
        `/seo/scans/history?target_url=${encodeURIComponent(selected.target_url)}`);
      setHistory(r);
    } catch (e) {
      toast.error("History failed", { description: e?.message });
    } finally {
      setHistoryLoading(false);
    }
  };

  const results = selected?.results;

  return (
    <div className="p-6 space-y-6" data-testid="seo-auditor-page">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="seo-auditor-title">SEO Auditor</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Free on-page SEO scan. Uses Google PageSpeed Insights + direct
            HTTP crawling. 5 scans/hour/user.
          </p>
        </div>
      </header>

      {/* URL input row */}
      <div className="flex gap-2 items-center bg-white border border-zinc-200 rounded-lg p-3 shadow-sm">
        <input
          type="url"
          placeholder="https://your-site.com"
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleRunScan(); }}
          className="flex-1 px-3 py-2 border border-zinc-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
          data-testid="seo-url-input"
        />
        <button
          type="button"
          onClick={handleRunScan}
          disabled={scanBusy}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-sky-600 text-white font-medium disabled:opacity-50 hover:bg-sky-700 transition-colors"
          data-testid="seo-run-scan-btn"
        >
          {scanBusy ? <RefreshCw size={16} className="animate-spin" />
                      : <Play size={16} />}
          {scanBusy ? "Scanning…" : "Run scan"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-6">
        {/* Left: recent scans */}
        <section className="md:col-span-2 bg-white border border-zinc-200 rounded-lg shadow-sm overflow-hidden"
                  data-testid="seo-scans-list">
          <div className="px-4 py-3 border-b border-zinc-100 flex items-center justify-between">
            <span className="text-sm font-semibold">Recent scans</span>
            <button type="button" onClick={loadList}
                     className="text-xs text-sky-600 hover:underline"
                     data-testid="seo-refresh-list">
              Refresh
            </button>
          </div>
          <div className="max-h-[520px] overflow-y-auto">
            {loading ? (
              <div className="p-6 text-sm text-zinc-500"
                    data-testid="seo-list-loading">Loading…</div>
            ) : items.length === 0 ? (
              <div className="p-6 text-sm text-zinc-500"
                    data-testid="seo-list-empty">
                No scans yet. Run one above to get started.
              </div>
            ) : items.map((it) => {
              const style = STATUS_STYLES[it.status] || STATUS_STYLES.queued;
              const s = it.results?.score;
              return (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => loadDetail(it.id)}
                  className={`w-full text-left px-4 py-3 border-b border-zinc-100 hover:bg-zinc-50 transition-colors ${
                    selectedId === it.id ? "bg-sky-50" : ""}`}
                  data-testid={`seo-scan-row-${it.id}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium truncate max-w-[70%]"
                          title={it.target_url}>
                      {it.target_url}
                    </span>
                    <span className="inline-block rounded-full px-2 py-0.5 text-[11px] font-medium shrink-0"
                          style={{ background: style.bg, color: style.fg }}>
                      {style.label}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-1 text-xs text-zinc-500">
                    <span>{_fmtTs(it.requested_at)}</span>
                    <span className="font-semibold"
                          style={{ color: _scoreColor(s) }}>
                      {s == null ? "—" : `${s}`}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        {/* Right: detail drawer */}
        <section className="md:col-span-3 bg-white border border-zinc-200 rounded-lg shadow-sm p-6"
                  data-testid="seo-detail-panel">
          {!selected ? (
            <div className="text-sm text-zinc-500"
                  data-testid="seo-nothing-selected">
              Select a scan on the left to see the full report.
            </div>
          ) : (
            <div>
              <div className="flex items-start justify-between gap-4 mb-4">
                <div className="min-w-0">
                  <a href={selected.target_url}
                     target="_blank" rel="noopener noreferrer"
                     className="text-lg font-semibold text-sky-700 hover:underline inline-flex items-center gap-1 break-all"
                     data-testid="seo-detail-url">
                    {selected.target_url} <ExternalLink size={14} />
                  </a>
                  <div className="text-xs text-zinc-500 mt-1">
                    Requested {_fmtTs(selected.requested_at)}
                    {selected.duration_ms
                      ? ` · took ${(selected.duration_ms / 1000).toFixed(1)}s`
                      : ""}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button type="button" onClick={handleRerun}
                           className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-zinc-200 text-sm hover:bg-zinc-50"
                           data-testid="seo-rerun-btn">
                    <RefreshCw size={14} /> Re-scan
                  </button>
                  <button type="button" onClick={handleShowHistory}
                           className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-zinc-200 text-sm hover:bg-zinc-50"
                           data-testid="seo-history-btn">
                    <TrendingUp size={14} /> History
                  </button>
                </div>
              </div>

              {selected.status !== "complete" ? (
                <div className="p-6 border border-dashed border-zinc-300 rounded-md text-sm text-zinc-600"
                      data-testid="seo-detail-status">
                  Status: <strong>{selected.status}</strong>
                  {selected.error_message
                    ? ` · ${selected.error_message}` : ""}
                </div>
              ) : (
                <div className="flex flex-col gap-6">
                  <div className="flex items-center gap-6"
                        data-testid="seo-detail-summary">
                    <ScoreGauge score={results?.score} />
                    <div className="flex flex-col gap-2">
                      <IssueBadges counts={results?.issue_count} />
                      <div className="text-xs text-zinc-500">
                        HTML size: {results?.on_page?.html_size_kb ?? "—"} kB
                        {" · "}
                        Words: {results?.on_page?.word_count ?? "—"}
                      </div>
                    </div>
                  </div>
                  <DetailSections results={results} />
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      {/* History modal */}
      {history && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
              data-testid="seo-history-modal"
              onClick={() => setHistory(null)}>
          <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full p-6"
                onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">Score history</h3>
              <button type="button" onClick={() => setHistory(null)}
                       aria-label="Close"
                       data-testid="seo-history-close">
                <X size={18} />
              </button>
            </div>
            <p className="text-xs text-zinc-500 mb-3 break-all">
              {history.target_url}
            </p>
            {historyLoading ? (
              <div className="p-8 text-center text-sm text-zinc-500">
                Loading history…
              </div>
            ) : (history.points || []).length === 0 ? (
              <div className="p-8 text-center text-sm text-zinc-500"
                    data-testid="seo-history-empty">
                No previous scans for this URL yet.
              </div>
            ) : (
              <div style={{ width: "100%", height: 260 }}
                    data-testid="seo-history-chart">
                <ResponsiveContainer>
                  <ReLineChart data={history.points}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E4E4E7" />
                    <XAxis dataKey="requested_at"
                            tickFormatter={(v) =>
                              new Date(v).toLocaleDateString()}
                            fontSize={11} />
                    <YAxis domain={[0, 100]} fontSize={11} />
                    <Tooltip />
                    <Line type="monotone" dataKey="score"
                            stroke="#0284C7" strokeWidth={2}
                            dot={{ r: 3 }} />
                  </ReLineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
