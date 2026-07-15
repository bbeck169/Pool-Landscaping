/**
 * Phase 27 Wave B admin pages — Churn dashboard + Content refresh.
 * Water photo analyzer is integrated as a modal in the service report page
 * (not a top-level admin page).
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, AlertTriangle, Users, Play, RefreshCw, TrendingDown,
  Sparkles, FileEdit, Copy, Check,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const TIER = {
  low:      ["#059669", "Low"],
  medium:   ["#F59E0B", "Medium"],
  high:     ["#EA580C", "High"],
  critical: ["#DC2626", "Critical"],
};

/* ═════════ CHURN DASHBOARD ═════════════════════════════════════════════ */
export default function ChurnDashboard() {
  const nav = useNavigate();
  const [data, setData] = useState({ items: [], counts_by_tier: {} });
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState("");
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/churn/scores");
      setData(r);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const runAll = async () => {
    setRunning(true); setMsg("");
    try {
      const r = await api.post("/churn/analyze-all", {});
      setMsg(`Scored ${r.scored} customers · ${r.at_risk_count} at risk · ${r.critical_count} critical`);
      await load();
    } catch (e) { setMsg(e.message); }
    finally { setRunning(false); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="churn-dashboard">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="churn-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <TrendingDown size={22} style={{ color: colors.brand }} />
            Customer churn risk
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Live Claude scoring based on 90d NPS, chat, and service history.
          </p>
        </div>
        <button onClick={load}
                className="p-2 rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="churn-refresh">
          <RefreshCw size={14} />
        </button>
        <button onClick={runAll} disabled={running}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="churn-run-all">
          <Play size={12} /> {running ? "Scoring…" : "Rescore all"}
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {Object.entries(TIER).map(([tier, [c, l]]) => (
          <div key={tier} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`churn-tier-${tier}`}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>{l}</div>
            <div className="text-2xl font-bold mt-1" style={{ color: c }}>
              {data.counts_by_tier?.[tier] || 0}
            </div>
          </div>
        ))}
      </div>

      {msg ? (
        <div className="rounded-xl p-3 mb-3 text-sm"
             style={{ backgroundColor: "#F0FDF4", color: "#166534",
                      border: "1px solid #86EFAC" }}
             data-testid="churn-msg">
          {msg}
        </div>
      ) : null}

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : data.items.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No scores yet. Click <b>Rescore all</b> to run Claude.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">Customer</th>
                <th className="p-2 text-right">Risk</th>
                <th className="p-2 text-left">Tier</th>
                <th className="p-2 text-left">Top signals</th>
                <th className="p-2 text-left">Analyzed</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.customer_id}
                    style={{ borderTop: `1px solid ${colors.border}`,
                              cursor: "pointer" }}
                    onClick={() => setDetail(r)}
                    data-testid={`churn-row-${r.customer_id}`}>
                  <td className="p-2 font-bold"
                      style={{ color: colors.onSurface }}>
                    {r.customer_name || r.customer_id.slice(0, 8)}
                  </td>
                  <td className="p-2 text-right font-bold font-mono"
                      style={{ color: TIER[r.tier]?.[0] || colors.onSurface }}>
                    {r.risk_score}
                  </td>
                  <td className="p-2">
                    <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold"
                          style={{ backgroundColor: `${TIER[r.tier]?.[0]}15`,
                                   color: TIER[r.tier]?.[0] }}>
                      {TIER[r.tier]?.[1] || r.tier}
                    </span>
                  </td>
                  <td className="p-2 text-xs"
                      style={{ color: colors.muted }}>
                    {(r.top_signals || []).slice(0, 2).join(" · ")}
                  </td>
                  <td className="p-2 text-[10px]"
                      style={{ color: colors.muted }}>
                    {(r.analyzed_at || "").slice(0, 10)}
                  </td>
                  <td className="p-2 text-right text-xs"
                      style={{ color: colors.brand }}>Details →</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
             data-testid="churn-detail-modal"
             onClick={() => setDetail(null)}>
          <div className="rounded-2xl w-full max-w-lg p-5 max-h-[90vh] overflow-auto"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold"
                    style={{ color: colors.onSurface }}>
                  {detail.customer_name}
                </h2>
                <div className="text-xs" style={{ color: colors.muted }}>
                  Risk score {detail.risk_score} · {detail.tier}
                </div>
              </div>
              <button onClick={() => setDetail(null)}
                      className="p-2 rounded"
                      style={{ color: colors.muted }}>×</button>
            </div>
            <div className="mb-3">
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>Top signals</div>
              <ul className="text-sm list-disc pl-4"
                  style={{ color: colors.onSurface }}>
                {(detail.top_signals || []).map((s, i) =>
                  <li key={i}>{s}</li>)}
              </ul>
            </div>
            <div>
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>Recommended actions</div>
              <ul className="text-sm list-disc pl-4"
                  style={{ color: colors.onSurface }}>
                {(detail.recommended_actions || []).map((s, i) =>
                  <li key={i}>{s}</li>)}
              </ul>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ═════════ CONTENT REFRESH ═════════════════════════════════════════════ */
export function ContentRefresh() {
  const nav = useNavigate();
  const [url, setUrl] = useState("");
  const [scan, setScan] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [rewriting, setRewriting] = useState(null);
  const [rewrite, setRewrite] = useState(null);
  const [err, setErr] = useState("");

  const doScan = async () => {
    setScanning(true); setErr(""); setScan(null); setRewrite(null);
    try {
      const r = await api.post("/seo/content-refresh/scan",
                                 { blog_root_url: url });
      setScan(r);
    } catch (e) { setErr(e.message); }
    finally { setScanning(false); }
  };

  const doRewrite = async (entry) => {
    setRewriting(entry.url_hash); setErr(""); setRewrite(null);
    try {
      const r = await api.post(
        `/seo/content-refresh/rewrite/${scan.id}/${entry.url_hash}`, {});
      setRewrite(r);
    } catch (e) { setErr(e.message); }
    finally { setRewriting(null); }
  };
  const copyHtml = () => {
    if (rewrite?.rewritten_html) {
      navigator.clipboard.writeText(rewrite.rewritten_html);
    }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6"
         data-testid="content-refresh">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Sparkles size={22} style={{ color: colors.brand }} />
            Content refresh engine
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Scan blog URLs, score them, and let Claude rewrite the lowest scoring.
          </p>
        </div>
      </div>

      <div className="rounded-2xl p-4 mb-4 flex gap-2 items-center flex-wrap"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <input value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder="https://yourdomain.com/blog"
               className="flex-1 min-w-[240px] p-2 rounded-lg text-sm"
               style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }}
               data-testid="content-url-input" />
        <button onClick={doScan} disabled={scanning || !url.trim()}
                className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="content-scan-btn">
          <RefreshCw size={14} /> {scanning ? "Scanning…" : "Scan"}
        </button>
      </div>

      {err ? (
        <div className="rounded-xl p-3 mb-3 text-sm"
             style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}>
          {err}
        </div>
      ) : null}

      {scan ? (
        <div className="rounded-2xl overflow-hidden mb-4"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="content-scan-results">
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-right">Score</th>
                <th className="p-2 text-left">URL</th>
                <th className="p-2 text-left">Title</th>
                <th className="p-2 text-right">Words</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {scan.urls_scored.map((e) => (
                <tr key={e.url_hash}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`content-scan-row-${e.url_hash}`}>
                  <td className="p-2 text-right font-bold font-mono"
                      style={{ color: e.score < 50 ? "#DC2626"
                                          : e.score < 75 ? "#F59E0B"
                                          : "#059669" }}>
                    {e.score}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    <a href={e.url} target="_blank" rel="noreferrer"
                       style={{ color: colors.brand }}>
                      {e.url.length > 60 ? e.url.slice(0, 60) + "…" : e.url}
                    </a>
                  </td>
                  <td className="p-2 text-xs"
                      style={{ color: colors.onSurface }}>
                    {(e.title || "").slice(0, 50)}
                  </td>
                  <td className="p-2 text-right text-xs"
                      style={{ color: colors.muted }}>{e.word_count}</td>
                  <td className="p-2 text-right">
                    <button onClick={() => doRewrite(e)}
                            disabled={rewriting === e.url_hash}
                            className="px-2 py-1 text-xs font-bold rounded"
                            style={{ backgroundColor: colors.brand,
                                     color: "#fff" }}
                            data-testid={`content-rewrite-${e.url_hash}`}>
                      <FileEdit size={10} style={{ display: "inline",
                                                       marginRight: 4 }} />
                      {rewriting === e.url_hash ? "…" : "Rewrite"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {rewrite ? (
        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="content-rewrite-panel">
          <div className="flex items-center gap-3 mb-3">
            <h2 className="text-lg font-bold flex-1"
                style={{ color: colors.onSurface }}>
              {rewrite.title}
            </h2>
            <span className="text-xs font-bold"
                  style={{ color: colors.muted }}>
              Score {rewrite.source_score} → {rewrite.rewritten_score}
            </span>
            <button onClick={copyHtml}
                    className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="content-rewrite-copy">
              <Copy size={12} /> Copy HTML
            </button>
          </div>
          {rewrite.diff_summary ? (
            <div className="rounded-xl p-3 mb-3 text-xs"
                 style={{ backgroundColor: "#EFF6FF", color: "#1E40AF" }}>
              <b>What changed:</b> {rewrite.diff_summary}
            </div>
          ) : null}
          <div className="p-3 rounded-lg text-xs overflow-auto max-h-96"
               style={{ backgroundColor: "#F1F5F9",
                        color: colors.onSurface,
                        border: `1px solid ${colors.border}`,
                        whiteSpace: "pre-wrap" }}
               data-testid="content-rewrite-html">
            {rewrite.rewritten_html}
          </div>
        </div>
      ) : null}
    </div>
  );
}
