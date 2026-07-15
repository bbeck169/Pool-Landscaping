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
  // Phase 34b — Churn → Marketing Studio retention bridge state.
  const [campaignOpen, setCampaignOpen] = useState(false);
  const [campaignThreshold, setCampaignThreshold] = useState(60);
  const [campaignChannel, setCampaignChannel] = useState("email");
  const [campaignBusy, setCampaignBusy] = useState(false);
  const [campaignSuccess, setCampaignSuccess] = useState(null);
  const [campaignErr, setCampaignErr] = useState("");

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
        {(data?.items || []).some((r) => (r.risk_score || 0) >= 60) ? (
          <button
            onClick={() => setCampaignOpen(true)}
            className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
            style={{ backgroundColor: "#DC2626", color: "#fff" }}
            data-testid="churn-create-campaign-btn"
          >
            <Sparkles size={12} /> Create Retention Campaign
          </button>
        ) : null}
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

      {campaignSuccess ? (
        <div
          className="rounded-xl p-3 mb-3 text-sm flex items-center gap-2"
          style={{
            background: campaignSuccess.mocked ? "#FEF3C7" : "#D1FAE5",
            color:      campaignSuccess.mocked ? "#B45309" : "#065F46",
            border: `1px solid ${campaignSuccess.mocked ? "#B45309" : "#059669"}`,
          }}
          data-testid="churn-campaign-success-banner"
        >
          <Sparkles size={14} />
          <span style={{ flex: 1 }}>
            Draft created for {campaignSuccess.target_count} at-risk customer(s).
            {campaignSuccess.mocked ? (
              <>
                {" "}<b>Note:</b> LLM unavailable — used fallback template.
                <span data-testid="churn-campaign-mocked-reason">
                  {" "}({campaignSuccess.reason})
                </span>
              </>
            ) : (
              " Retention pitch pre-filled in Goal field. Personalize before sending."
            )}
          </span>
          <button
            onClick={() => nav(`/marketing/campaigns/${campaignSuccess.campaign_id}`)}
            className="px-2 py-1 rounded-md text-xs font-bold"
            style={{ background: "#DC2626", color: "#fff", border: 0, cursor: "pointer" }}
            data-testid="churn-campaign-open-editor"
          >
            Open in Marketing Studio
          </button>
        </div>
      ) : null}

      {campaignOpen ? (
        <div
          onClick={() => !campaignBusy && setCampaignOpen(false)}
          style={{ position: "fixed", inset: 0, zIndex: 60,
                    background: "rgba(15,23,42,0.55)",
                    display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: "#fff", borderRadius: 12,
                      width: "min(480px, 96vw)", padding: 20,
                      boxShadow: "0 20px 60px rgba(0,0,0,0.35)" }}
            data-testid="churn-campaign-modal"
          >
            <div className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>
              Create Retention Campaign
            </div>
            <div className="text-xs mb-4" style={{ color: colors.muted }}>
              Claude drafts a warm retention pitch and lands a campaign in
              Marketing Studio. You can edit before sending.
            </div>

            <label className="text-[10px] font-bold uppercase tracking-wider"
                    style={{ color: colors.muted }}>
              Minimum risk score: <b style={{ color: colors.onSurface }}>{campaignThreshold}</b>
            </label>
            <input
              type="range" min={0} max={100} value={campaignThreshold}
              onChange={(e) => setCampaignThreshold(Number(e.target.value))}
              className="w-full my-2"
              disabled={campaignBusy}
              data-testid="churn-campaign-risk-slider"
            />
            <div className="text-xs mb-3" data-testid="churn-campaign-count-preview"
                  style={{ color: colors.muted }}>
              Matches: <b style={{ color: colors.onSurface }}>
                {(data?.items || []).filter((r) => (r.risk_score || 0) >= campaignThreshold).length}
              </b> customer(s)
            </div>

            <label className="text-[10px] font-bold uppercase tracking-wider"
                    style={{ color: colors.muted }}>Channel</label>
            <select
              value={campaignChannel}
              onChange={(e) => setCampaignChannel(e.target.value)}
              disabled={campaignBusy}
              className="w-full px-2 py-1.5 rounded-md text-sm mt-1 mb-3"
              style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
              data-testid="churn-campaign-channel"
            >
              <option value="email">Email</option>
              <option value="sms">SMS</option>
              <option value="facebook">Facebook</option>
              <option value="instagram">Instagram</option>
            </select>

            {campaignErr ? (
              <div className="text-xs px-2 py-2 rounded mb-3"
                    style={{ background: "#FEE2E2", color: "#991B1B" }}
                    data-testid="churn-campaign-error">{campaignErr}</div>
            ) : null}

            <div className="flex items-center gap-2 mt-2">
              <div style={{ flex: 1 }} />
              <button
                onClick={() => setCampaignOpen(false)}
                disabled={campaignBusy}
                className="px-3 py-1.5 rounded-md text-sm font-semibold"
                style={{ background: "#fff", border: `1px solid ${colors.border}`,
                          cursor: "pointer" }}
                data-testid="churn-campaign-cancel"
              >Cancel</button>
              <button
                onClick={async () => {
                  setCampaignBusy(true); setCampaignErr("");
                  try {
                    const r = await api.post("/churn/create-retention-campaign", {
                      channel: campaignChannel,
                      min_risk_score: campaignThreshold,
                      max_customers: 100,
                    });
                    if (!r.campaign_id) {
                      setCampaignErr(r.reason || "No customers matched threshold.");
                      return;
                    }
                    setCampaignSuccess(r);
                    setCampaignOpen(false);
                    // Navigate — even on mocked=true the campaign was created.
                    setTimeout(() => {
                      nav(`/marketing/campaigns/${r.campaign_id}`);
                    }, r.mocked ? 3500 : 800);
                  } catch (e) {
                    setCampaignErr(e?.message || "Failed to create campaign.");
                  } finally { setCampaignBusy(false); }
                }}
                disabled={campaignBusy ||
                  (data?.items || []).filter((r) => (r.risk_score || 0) >= campaignThreshold).length === 0}
                className="px-3 py-1.5 rounded-md text-sm font-bold"
                style={{ background: "#DC2626", color: "#fff", border: 0,
                          cursor: campaignBusy ? "wait" : "pointer",
                          opacity: campaignBusy ? 0.6 : 1 }}
                data-testid="churn-campaign-confirm"
              >
                {campaignBusy ? "Drafting…" : "Create draft"}
              </button>
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
