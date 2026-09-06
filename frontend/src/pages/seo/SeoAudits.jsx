/**
 * Phase 17A.1 · SEO Site Auditor — list + detail (single file, two exports).
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Search, Plus, RefreshCw, AlertTriangle, AlertCircle, Info, ChevronRight, X, ArrowLeft } from "lucide-react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";

const STATUS_META = {
  queued:    { bg: "#FEF3C7", fg: "#92400E" },
  running:   { bg: "#DBEAFE", fg: "#1E40AF" },
  done:      { bg: "#DCFCE7", fg: "#166534" },
  failed:    { bg: "#FEE2E2", fg: "#991B1B" },
  cancelled: { bg: "#F3F4F6", fg: "#4B5563" },
};

/** ── LIST: /admin/seo/audits ────────────────────────────────────────── */
export default function SeoAudits() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ url: "https://", depth: 3, max_pages: 50 });
  const [starting, setStarting] = useState(false);

  const load = () => {
    setLoading(true);
    api.get("/seo/audits").then((r) => { setRows(r); setLoading(false); });
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    // Poll running audits every 4s.
    if (!rows.some((r) => ["queued", "running"].includes(r.status))) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [rows]);

  const start = async () => {
    setStarting(true);
    try {
      await api.post("/seo/audits", form);
      setShowNew(false);
      setForm({ url: "https://", depth: 3, max_pages: 50 });
      load();
    } finally { setStarting(false); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="seo-audits-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Search size={22} style={{ color: colors.brand }}/>
            <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
              Site Auditor
            </h1>
          </div>
          <p className="text-sm" style={{ color: colors.muted }}>
            Crawl your website and surface every SEO issue that matters.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load}
                  className="p-2 rounded-lg"
                  style={{ backgroundColor: colors.surface,
                           border: `1px solid ${colors.border}` }}
                  data-testid="seo-audits-refresh">
            <RefreshCw size={16}/>
          </button>
          <button onClick={() => setShowNew(true)}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                  data-testid="seo-audits-new-btn">
            <Plus size={14}/> New Audit
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-sm text-center py-8" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="text-center py-16 rounded-2xl"
             style={{ backgroundColor: colors.surface, border: `1px dashed ${colors.border}` }}>
          <Search size={40} className="mx-auto mb-3" style={{ color: colors.muted }}/>
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            No audits yet
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            Click "New Audit" to crawl your first site.
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => {
            const m = STATUS_META[r.status] || STATUS_META.queued;
            return (
              <button key={r.id}
                      onClick={() => nav(`/admin/seo/audits/${r.id}`)}
                      className="w-full text-left rounded-xl p-4 flex items-center gap-3 hover:brightness-95 transition"
                      style={{ backgroundColor: colors.surface,
                               border: `1px solid ${colors.border}` }}
                      data-testid={`seo-audit-row-${r.id}`}>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                    {r.url}
                  </div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    {r.summary?.pages_crawled ?? "—"} pages ·{" "}
                    {r.summary?.issues_total ?? "—"} issues ·{" "}
                    depth {r.depth}
                  </div>
                </div>
                {r.summary?.scores?.overall != null && (
                  <div className="text-2xl font-bold"
                       style={{ color: r.summary.scores.overall >= 80 ? "#059669"
                                       : r.summary.scores.overall >= 60 ? "#D97706"
                                       : "#DC2626" }}>
                    {r.summary.scores.overall}
                  </div>
                )}
                <span className="text-xs font-bold uppercase px-2 py-0.5 rounded"
                      style={{ backgroundColor: m.bg, color: m.fg }}>
                  {r.status}
                </span>
                <ChevronRight size={16} style={{ color: colors.muted }} />
              </button>
            );
          })}
        </div>
      )}

      {showNew && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
             style={{ background: "rgba(0,0,0,0.5)" }} onClick={() => setShowNew(false)}>
          <div className="max-w-md w-full p-6 rounded-2xl"
               onClick={(e) => e.stopPropagation()}
               style={{ backgroundColor: colors.surface }}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                Run new audit
              </h3>
              <button onClick={() => setShowNew(false)} style={{ color: colors.muted }}>
                <X size={18}/>
              </button>
            </div>
            <input value={form.url}
                   onChange={(e) => setForm({ ...form, url: e.target.value })}
                   className="w-full p-2.5 text-sm rounded-lg mb-3"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }}
                   placeholder="https://your-site.com"
                   data-testid="seo-audits-new-url" />
            <div className="grid grid-cols-2 gap-2 mb-4">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.muted }}>Depth</label>
                <input type="number" min={1} max={6}
                       value={form.depth}
                       onChange={(e) => setForm({ ...form, depth: Number(e.target.value) })}
                       className="w-full p-2 text-sm rounded-lg"
                       style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }}
                       data-testid="seo-audits-new-depth" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.muted }}>Max pages</label>
                <input type="number" min={1} max={200}
                       value={form.max_pages}
                       onChange={(e) => setForm({ ...form, max_pages: Number(e.target.value) })}
                       className="w-full p-2 text-sm rounded-lg"
                       style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }}
                       data-testid="seo-audits-new-max-pages" />
              </div>
            </div>
            <button onClick={start} disabled={starting}
                    className="w-full py-2 rounded-lg text-sm font-bold disabled:opacity-60"
                    style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                    data-testid="seo-audits-new-submit">
              {starting ? "Starting…" : "Run audit"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** ── DETAIL: /admin/seo/audits/:id ─────────────────────────────────── */
export function SeoAuditDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [pages, setPages] = useState({ rows: [], total: 0 });
  const [severity, setSeverity] = useState("");

  const load = async () => {
    const a = await api.get(`/seo/audits/${id}`);
    setAudit(a);
    const p = await api.get(`/seo/audits/${id}/pages?limit=200`);
    setPages(p);
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: load intentionally omitted (mount-only / stable-ref)

  useEffect(() => {
    if (!audit || ["done", "failed", "cancelled"].includes(audit.status)) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [audit?.status]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: deps 'audit' intentionally omitted (mount-only or stable-ref)

  const allIssues = useMemo(() => {
    const out = [];
    (pages.rows || []).forEach((p) => {
      (p.issues || []).forEach((i) => {
        out.push({ ...i, url: p.url });
      });
    });
    return out;
  }, [pages]);

  const filteredIssues = severity
    ? allIssues.filter((i) => i.severity === severity)
    : allIssues;

  const rerun = async () => {
    const r = await api.post(`/seo/audits/${id}/rerun`);
    nav(`/admin/seo/audits/${r.audit_id}`);
  };

  if (!audit) return <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  const scores = audit.summary?.scores || {};

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="seo-audit-detail">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav("/admin/seo/audits")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="seo-audit-back">
          <ArrowLeft size={16}/>
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold truncate" style={{ color: colors.onSurface }}>
            {audit.url}
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Status: <b>{audit.status}</b> · Pages: {audit.summary?.pages_crawled ?? "…"}
          </p>
        </div>
        <button onClick={() => nav(`/admin/seo/audits/${id}/otto`)}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="seo-audit-otto-btn">
          Auto-Fixes
        </button>
        <button onClick={rerun}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                data-testid="seo-audit-rerun">
          Rerun
        </button>
      </div>

      {/* Score cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <ScoreCard label="Overall" score={scores.overall} big />
        <ScoreCard label="Technical" score={scores.technical} />
        <ScoreCard label="On-page" score={scores.on_page} />
        <ScoreCard label="UX" score={scores.ux} />
      </div>

      {/* Severity filter */}
      <div className="flex gap-2 mb-3 flex-wrap">
        {["", "critical", "warning", "info"].map((s) => (
          <button key={s || "all"}
                  onClick={() => setSeverity(s)}
                  className="px-3 py-1.5 text-xs font-semibold rounded-full"
                  style={{
                    backgroundColor: severity === s ? colors.brand : colors.surface,
                    color: severity === s ? "#fff" : colors.onSurface,
                    border: `1px solid ${severity === s ? colors.brand : colors.border}`,
                  }}
                  data-testid={`seo-audit-sev-${s || "all"}`}>
            {s || "All"} {s && `(${allIssues.filter((i) => i.severity === s).length})`}
          </button>
        ))}
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        {filteredIssues.length === 0 ? (
          <div className="p-8 text-center" style={{ color: colors.muted }}>
            {audit.status === "done" ? "No issues in this severity." : "Crawling…"}
          </div>
        ) : (
          filteredIssues.slice(0, 200).map((i, idx) => (
            <div key={idx} className="p-3 flex items-start gap-3"
                 style={{ borderTop: idx ? `1px solid ${colors.border}` : "none" }}>
              {i.severity === "critical" ? (
                <AlertCircle size={16} style={{ color: "#DC2626" }} />
              ) : i.severity === "warning" ? (
                <AlertTriangle size={16} style={{ color: "#D97706" }} />
              ) : (
                <Info size={16} style={{ color: "#2563EB" }} />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-xs font-bold" style={{ color: colors.onSurface }}>
                  {i.code}
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {i.hint}
                </div>
                <div className="text-[10px] truncate mt-0.5" style={{ color: colors.brand }}>
                  {i.url}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ScoreCard({ label, score, big }) {
  const v = score ?? "—";
  const color = score == null ? colors.muted
              : score >= 80 ? "#059669"
              : score >= 60 ? "#D97706" : "#DC2626";
  return (
    <div className="rounded-2xl p-5"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid={`seo-audit-score-${label.toLowerCase().replace(/[^a-z]/g, "-")}`}>
      <div className="text-[10px] font-bold uppercase tracking-wider"
           style={{ color: colors.muted }}>{label}</div>
      <div className={`font-bold mt-2 ${big ? "text-5xl" : "text-3xl"}`}
           style={{ color }}>
        {v}
      </div>
      <div className="text-[10px]" style={{ color: colors.muted }}>/ 100</div>
    </div>
  );
}
