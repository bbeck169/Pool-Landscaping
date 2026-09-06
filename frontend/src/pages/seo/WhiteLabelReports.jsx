/**
 * Phase 17C.3 · White-Label Reports — branded PDF/HTML deliverables.
 * List: /admin/seo/reports  ·  Detail: /admin/seo/reports/:id
 */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Plus, Download, Send, FileText, X, Sparkles,
} from "lucide-react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";

/* ─── LIST ──────────────────────────────────────────────────────────── */
export default function WhiteLabelReports() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [audits, setAudits] = useState([]);
  const [heatmaps, setHeatmaps] = useState([]);
  const [tmaps, setTmaps] = useState([]);
  const [form, setForm] = useState({
    title: "SEO Report", brand_name: "", brand_color: "#0284C7", logo_url: "",
    audit_id: "", heatmap_id: "", topical_map_id: "",
    include_llm_visibility: true, range_days: 30, notes: "",
  });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/seo/reports");
      setRows(r.items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openNew = async () => {
    setShowNew(true);
    try {
      const [a, h, t] = await Promise.all([
        api.get("/seo/audits"),
        api.get("/seo/rank-heatmaps"),
        api.get("/seo/topical-maps"),
      ]);
      setAudits(Array.isArray(a) ? a : (a.items || []));
      setHeatmaps(Array.isArray(h) ? h : (h.items || []));
      setTmaps(Array.isArray(t) ? t : (t.items || []));
    } catch (_e) {
      // list endpoints may return either array or {items}; degrade quietly.
    }
  };

  const create = async () => {
    setError(""); setCreating(true);
    try {
      const payload = { ...form };
      // strip empty ids so backend treats them as unset
      ["audit_id", "heatmap_id", "topical_map_id"].forEach((k) => {
        if (!payload[k]) delete payload[k];
      });
      const r = await api.post("/seo/reports", payload);
      setShowNew(false);
      nav(`/admin/seo/reports/${r.id}`);
    } catch (e) {
      setError(e.message || "Failed");
    } finally { setCreating(false); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6"
         data-testid="white-label-reports-page">
      <div className="flex items-center gap-3 mb-6">
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <FileText size={22} style={{ color: colors.brand }} />
            White-Label Reports
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Branded PDF snapshots of the audit, LLM visibility, rank heatmap,
            and topical opportunities — with a Claude-generated exec summary.
          </p>
        </div>
        <button onClick={openNew}
                className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-2"
                style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                data-testid="report-new-btn">
          <Plus size={14} /> New report
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No reports yet.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          {rows.map((r, i) => (
            <div key={r.id}
                 onClick={() => nav(`/admin/seo/reports/${r.id}`)}
                 className="p-4 cursor-pointer flex items-center gap-3"
                 style={{ borderTop: i ? `1px solid ${colors.border}` : "none" }}
                 data-testid={`report-row-${r.id}`}>
              <div style={{ width: 8, height: 40, borderRadius: 4,
                            backgroundColor: r.brand_color || colors.brand }} />
              <div className="flex-1 min-w-0">
                <div className="font-bold" style={{ color: colors.onSurface }}>
                  {r.title}
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {r.brand_name} · {(r.created_at || "").slice(0, 10)}
                </div>
              </div>
              {r.last_sent_at && (
                <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                      style={{ backgroundColor: "#DCFCE7", color: "#166534" }}>
                  Sent
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {showNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}>
          <div className="rounded-2xl p-6 max-w-lg w-full max-h-[92vh] overflow-y-auto"
               style={{ backgroundColor: colors.surface }}
               data-testid="report-new-modal">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold flex items-center gap-2">
                <Sparkles size={18} style={{ color: colors.brand }} />
                New white-label report
              </h2>
              <button onClick={() => setShowNew(false)}><X size={18} /></button>
            </div>
            {error && (
              <div className="text-xs mb-3 p-2 rounded-lg"
                   style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                   data-testid="report-new-error">
                {error}
              </div>
            )}
            {[
              ["title", "Report title", "text"],
              ["brand_name", "Brand name (defaults to tenant name)", "text"],
              ["logo_url", "Logo URL", "text"],
            ].map(([k, l]) => (
              <label key={k} className="block mb-3">
                <div className="text-xs font-bold mb-1"
                     style={{ color: colors.muted }}>{l}</div>
                <input type="text" value={form[k] || ""}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  className="w-full p-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                  data-testid={`report-new-${k}`} />
              </label>
            ))}
            <label className="block mb-3">
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>Brand color</div>
              <input type="color" value={form.brand_color}
                onChange={(e) => setForm({ ...form, brand_color: e.target.value })}
                className="h-10 w-20 rounded-lg cursor-pointer"
                data-testid="report-new-brand-color" />
            </label>
            {[
              ["audit_id", "Include audit", audits, (a) => `${a.url} · ${a.status}`],
              ["heatmap_id", "Include rank heatmap", heatmaps,
                (h) => `${h.keyword} · ${(h.created_at || "").slice(0, 10)}`],
              ["topical_map_id", "Include topical map", tmaps,
                (t) => `${t.seed_keyword} · ${(t.created_at || "").slice(0, 10)}`],
            ].map(([k, l, opts, label]) => (
              <label key={k} className="block mb-3">
                <div className="text-xs font-bold mb-1"
                     style={{ color: colors.muted }}>{l}</div>
                <select value={form[k]}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  className="w-full p-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                  data-testid={`report-new-${k}`}>
                  <option value="">— None —</option>
                  {(opts || []).map((o) => (
                    <option key={o.id} value={o.id}>{label(o)}</option>
                  ))}
                </select>
              </label>
            ))}
            <label className="flex items-center gap-2 mb-4">
              <input type="checkbox" checked={form.include_llm_visibility}
                onChange={(e) => setForm({ ...form,
                    include_llm_visibility: e.target.checked })}
                data-testid="report-new-include-llm" />
              <span className="text-xs" style={{ color: colors.onSurface }}>
                Include LLM Visibility data ({form.range_days}-day range)
              </span>
            </label>
            <button onClick={create} disabled={creating || !form.title}
                    className="w-full py-3 text-sm font-bold rounded-xl disabled:opacity-50"
                    style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                    data-testid="report-new-submit">
              {creating ? "Generating…" : "Generate report"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── DETAIL ────────────────────────────────────────────────────────── */
export function WhiteLabelReportDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [rep, setRep] = useState(null);
  const [sendModal, setSendModal] = useState(false);
  const [to, setTo] = useState("");
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState(null);

  const load = async () => {
    const r = await api.get(`/seo/reports/${id}`);
    setRep(r);
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: load intentionally omitted (mount-only / stable-ref)

  if (!rep) return (
    <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>
  );

  const download = async (format) => {
    const base = process.env.REACT_APP_BACKEND_URL;
    const url = `${base}/api/seo/reports/${id}/download?format=${format}`;
    const token = localStorage.getItem("token") || "";
    const tenant = localStorage.getItem("tenant_slug") || "";
    const r = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, "X-Tenant-Slug": tenant },
    });
    const blob = await r.blob();
    const dl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = dl;
    a.download = `report-${id.slice(0, 8)}.${format}`;
    a.click();
    URL.revokeObjectURL(dl);
  };

  const send = async () => {
    setSending(true); setSendResult(null);
    try {
      const r = await api.post(`/seo/reports/${id}/send`, { to });
      setSendResult(r);
      if (r.sent) setTimeout(() => setSendModal(false), 1600);
      await load();
    } finally { setSending(false); }
  };

  const exec_ = rep.exec_summary || {};
  const data = rep.data || {};

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6"
         data-testid="report-detail-page">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav("/admin/seo/reports")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            {rep.title}
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            {rep.brand_name} · {(rep.created_at || "").slice(0, 16).replace("T", " ")}
          </p>
        </div>
        <button onClick={() => download("pdf")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="report-download-pdf">
          <Download size={14} /> PDF
        </button>
        <button onClick={() => download("html")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="report-download-html">
          <Download size={14} /> HTML
        </button>
        <button onClick={() => setSendModal(true)}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                data-testid="report-send-btn">
          <Send size={14} /> Email
        </button>
      </div>

      {rep.mocked && (
        <div className="mb-4 p-3 rounded-xl text-sm"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E",
                      border: "1px solid #FDE68A" }}>
          <b>MOCK MODE</b> — Claude exec summary unavailable
          (EMERGENT_LLM_KEY missing).
        </div>
      )}

      {exec_.summary && (
        <div className="rounded-2xl p-5 mb-4"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h2 className="font-bold mb-2" style={{ color: colors.onSurface }}>
            Executive Summary
          </h2>
          <p className="text-sm" style={{ color: colors.onSurface }}>
            {exec_.summary}
          </p>
          {(exec_.key_wins || []).length > 0 && (
            <>
              <h3 className="mt-4 mb-1 font-bold text-sm"
                  style={{ color: colors.onSurface }}>Key Wins</h3>
              <ul className="text-sm list-disc pl-6"
                  style={{ color: colors.onSurface }}>
                {exec_.key_wins.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </>
          )}
          {(exec_.top_opportunities || []).length > 0 && (
            <>
              <h3 className="mt-4 mb-1 font-bold text-sm"
                  style={{ color: colors.onSurface }}>Top Opportunities</h3>
              <ul className="text-sm list-disc pl-6"
                  style={{ color: colors.onSurface }}>
                {exec_.top_opportunities.map((o, i) => <li key={i}>{o}</li>)}
              </ul>
            </>
          )}
        </div>
      )}

      {data.audit && (
        <div className="rounded-2xl p-5 mb-4"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h2 className="font-bold mb-2" style={{ color: colors.onSurface }}>
            Site Audit · {data.audit.url}
          </h2>
          <div className="grid grid-cols-4 gap-2">
            {["overall", "technical", "on_page", "ux"].map((k) => {
              const v = (data.audit.summary?.scores || {})[k] ?? "—";
              return (
                <div key={k} className="p-3 rounded-xl text-center"
                     style={{ backgroundColor: colors.background }}>
                  <div className="text-[10px] uppercase font-bold"
                       style={{ color: colors.muted }}>{k}</div>
                  <div className="text-2xl font-bold"
                       style={{ color: colors.onSurface }}>{v}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {data.llm_visibility && (
        <div className="rounded-2xl p-5 mb-4"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h2 className="font-bold mb-2" style={{ color: colors.onSurface }}>
            LLM Visibility
          </h2>
          <p className="text-sm" style={{ color: colors.onSurface }}>
            Mention rate: <b>{data.llm_visibility.mention_rate_pct}%</b> across{" "}
            <b>{data.llm_visibility.total_scans}</b> scans.
          </p>
        </div>
      )}

      {sendModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}>
          <div className="rounded-2xl p-6 max-w-md w-full"
               style={{ backgroundColor: colors.surface }}
               data-testid="report-send-modal">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold">Email report</h2>
              <button onClick={() => setSendModal(false)}><X size={18} /></button>
            </div>
            <label className="block mb-3">
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>Recipient email</div>
              <input type="email" value={to}
                onChange={(e) => setTo(e.target.value)}
                className="w-full p-2 rounded-lg text-sm"
                style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }}
                data-testid="report-send-to" />
            </label>
            {sendResult && (
              <div className="text-xs mb-3 p-2 rounded-lg"
                   style={{
                     backgroundColor: sendResult.sent ? "#DCFCE7" : "#FEF3C7",
                     color: sendResult.sent ? "#166534" : "#92400E",
                   }}
                   data-testid="report-send-result">
                {sendResult.sent
                  ? `Sent to ${sendResult.to} (${sendResult.attachment_type})`
                  : `Not sent: ${sendResult.reason}`}
              </div>
            )}
            <button onClick={send} disabled={sending || !to}
                    className="w-full py-3 text-sm font-bold rounded-xl disabled:opacity-50"
                    style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                    data-testid="report-send-submit">
              {sending ? "Sending…" : "Send report"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
