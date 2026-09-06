/**
 * Phase 17C.1 · OTTO Auto-Fix — panel embedded as a tab on the audit
 * detail page (and reachable directly at /admin/seo/audits/:id/otto).
 */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Sparkles, CheckCircle2, XCircle, Download, AlertTriangle, AlertCircle, Info } from "lucide-react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";

const SEV_ICON = {
  critical: <AlertCircle size={14} style={{ color: "#DC2626" }} />,
  warning: <AlertTriangle size={14} style={{ color: "#D97706" }} />,
  info: <Info size={14} style={{ color: "#2563EB" }} />,
};

export default function OttoAutoFix() {
  const { id: auditId } = useParams();
  const nav = useNavigate();
  const [fixes, setFixes] = useState([]);
  const [totals, setTotals] = useState({});
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [filter, setFilter] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const q = filter ? `?status=${filter}` : "";
      const r = await api.get(`/seo/otto/fixes/${auditId}${q}`);
      setFixes(r.fixes || []);
      setTotals(r.totals || {});
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [auditId, filter]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  const generate = async () => {
    setGenerating(true);
    try {
      await api.post("/seo/otto/generate-fixes", { audit_id: auditId, max_fixes: 40 });
      await load();
    } finally {
      setGenerating(false);
    }
  };

  const mark = async (fix, action) => {
    await api.post(`/seo/otto/fixes/${fix.id}/${action}`);
    await load();
  };

  const download = (fixId) => {
    const base = process.env.REACT_APP_BACKEND_URL;
    const url = `${base}/api/seo/otto/fixes/${fixId}/patch-file`;
    const token = localStorage.getItem("token") || "";
    const tenant = localStorage.getItem("tenant_slug") || "";
    fetch(url, { headers: { Authorization: `Bearer ${token}`,
                                "X-Tenant-Slug": tenant } })
      .then((r) => r.blob())
      .then((blob) => {
        const dl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = dl;
        a.download = `otto-${fixId.slice(0, 8)}.html`;
        a.click();
        URL.revokeObjectURL(dl);
      });
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6"
         data-testid="otto-auto-fix-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(`/admin/seo/audits/${auditId}`)}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="otto-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Sparkles size={22} style={{ color: colors.brand }} />
            OTTO · Auto-Fix
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            AI-generated, ready-to-paste patches for each on-page &amp; technical
            issue found in this audit.
          </p>
        </div>
        <button onClick={generate}
                disabled={generating}
                className="px-4 py-2 text-sm font-bold rounded-xl disabled:opacity-60"
                style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                data-testid="otto-generate-btn">
          {generating ? "Generating…" : "Generate fixes"}
        </button>
      </div>

      {/* Totals */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[
          ["Pending", "pending", "#D97706"],
          ["Applied", "applied", "#059669"],
          ["Dismissed", "dismissed", "#64748B"],
        ].map(([label, key, c]) => (
          <button
            key={key}
            onClick={() => setFilter(filter === key ? "" : key)}
            className="rounded-2xl p-4 text-left"
            style={{
              backgroundColor: filter === key ? "#F0F9FF" : colors.surface,
              border: `1px solid ${filter === key ? colors.brand : colors.border}`,
            }}
            data-testid={`otto-filter-${key}`}
          >
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>
              {label}
            </div>
            <div className="text-2xl font-bold mt-1" style={{ color: c }}>
              {totals[key] || 0}
            </div>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : fixes.length === 0 ? (
        <div className="rounded-2xl p-8 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.muted }}>
          No fixes generated yet — click <b>Generate fixes</b> to produce
          concrete patches for every issue this audit found.
        </div>
      ) : (
        <div className="space-y-3">
          {fixes.map((f) => (
            <div key={f.id}
                 className="rounded-2xl overflow-hidden"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                 data-testid={`otto-fix-${f.id}`}>
              <div className="p-4 flex items-start gap-3">
                {SEV_ICON[f.severity] || SEV_ICON.info}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-bold"
                          style={{ color: colors.onSurface }}>
                      {f.issue_code}
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                          style={{ backgroundColor: "#EFF6FF", color: "#1E40AF" }}>
                      {f.patch_type}
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                          style={{
                            backgroundColor:
                              f.status === "applied" ? "#DCFCE7" :
                              f.status === "dismissed" ? "#F3F4F6" : "#FEF3C7",
                            color:
                              f.status === "applied" ? "#166534" :
                              f.status === "dismissed" ? "#4B5563" : "#92400E",
                          }}>
                      {f.status}
                    </span>
                  </div>
                  <div className="text-[11px] mt-1 truncate"
                       style={{ color: colors.brand }}>
                    {f.page_url}
                  </div>
                  {f.rationale && (
                    <div className="text-xs mt-2"
                         style={{ color: colors.onSurfaceSecondary || colors.muted }}>
                      {f.rationale}
                    </div>
                  )}
                </div>
                <div className="flex flex-col gap-1">
                  {f.status === "pending" && (
                    <>
                      <button onClick={() => mark(f, "mark-applied")}
                              className="px-3 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1"
                              style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
                              data-testid={`otto-apply-${f.id}`}>
                        <CheckCircle2 size={12} /> Applied
                      </button>
                      <button onClick={() => mark(f, "dismiss")}
                              className="px-3 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1"
                              style={{ backgroundColor: "#F3F4F6", color: "#4B5563" }}
                              data-testid={`otto-dismiss-${f.id}`}>
                        <XCircle size={12} /> Dismiss
                      </button>
                    </>
                  )}
                  <button onClick={() => download(f.id)}
                          className="px-3 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1"
                          style={{ backgroundColor: colors.surfaceTertiary || "#F1F5F9",
                                    color: colors.onSurface }}
                          data-testid={`otto-download-${f.id}`}>
                    <Download size={12} /> .html
                  </button>
                </div>
              </div>
              {f.patch_snippet && (
                <pre className="text-[11px] p-3 overflow-x-auto"
                     style={{
                       backgroundColor: "#0F172A",
                       color: "#E2E8F0",
                       margin: 0,
                       borderTop: `1px solid ${colors.border}`,
                     }}>
                  {f.patch_snippet}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
