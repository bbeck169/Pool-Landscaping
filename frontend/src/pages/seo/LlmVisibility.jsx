/**
 * Phase 17B.2 · LLM Visibility Tracker page (queries + dashboard tabs).
 */
import React, { useEffect, useState } from "react";
import { Eye, Plus, PlayCircle, Trash2, X } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

export default function LlmVisibility() {
  const [tab, setTab] = useState("queries");
  const [queries, setQueries] = useState([]);
  const [dash, setDash] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ query_text: "", expected_brand: "AquaTerra",
                                       category: "general" });
  const [scanning, setScanning] = useState(false);

  const load = () => {
    api.get("/seo/llm-visibility/queries").then(setQueries);
    api.get("/seo/llm-visibility/dashboard").then(setDash);
  };
  useEffect(() => { load(); }, []);

  const add = async () => {
    if (!form.query_text.trim()) return;
    await api.post("/seo/llm-visibility/queries", form);
    setShowNew(false); setForm({ ...form, query_text: "" });
    load();
  };
  const del = async (id) => {
    await api.del(`/seo/llm-visibility/queries/${id}`).catch(() =>
      api.request?.(`/seo/llm-visibility/queries/${id}`, { method: "DELETE" }));
    load();
  };
  const runScan = async () => {
    setScanning(true);
    try { await api.post("/seo/llm-visibility/scan", {}); load(); }
    finally { setScanning(false); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="llm-visibility-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Eye size={22} style={{ color: colors.brand }}/>
            <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
              LLM Visibility
            </h1>
          </div>
          <p className="text-sm" style={{ color: colors.muted }}>
            Track how often your brand appears in AI answers.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={runScan} disabled={scanning}
                  className="flex items-center gap-1 px-3 py-2 text-sm font-bold rounded-xl disabled:opacity-60"
                  style={{ background: brandGradientCss, color: "#fff" }}
                  data-testid="llm-vis-run-scan">
            <PlayCircle size={14}/> {scanning ? "Scanning…" : "Run scan"}
          </button>
        </div>
      </div>

      {dash && (
        <div className="mb-4 text-xs p-3 rounded-xl"
             style={{ backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                      color: colors.muted }}
             data-testid="llm-vis-engines">
          Engines configured:{" "}
          {dash.engines_configured.map((e) => (
            <span key={e} className="mr-1 px-2 py-0.5 rounded font-bold"
                  style={{ backgroundColor: "#DCFCE7", color: "#166534" }}>
              {e}
            </span>
          ))}
          {["openai", "gemini", "perplexity"].filter(
            (e) => !dash.engines_configured.includes(e)).map((e) => (
            <span key={e} className="mr-1 px-2 py-0.5 rounded font-bold"
                  style={{ backgroundColor: "#F3F4F6", color: "#6B7280" }}>
              {e} · not configured
            </span>
          ))}
        </div>
      )}

      <div className="flex gap-2 mb-4">
        {["queries", "dashboard"].map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{
                    backgroundColor: tab === t ? colors.brand : colors.surface,
                    color: tab === t ? "#fff" : colors.onSurface,
                    border: `1px solid ${tab === t ? colors.brand : colors.border}`,
                  }}
                  data-testid={`llm-vis-tab-${t}`}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "queries" ? (
        <div className="rounded-2xl p-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="llm-vis-queries">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs font-bold uppercase" style={{ color: colors.muted }}>
              Tracked queries ({queries.length})
            </div>
            <button onClick={() => setShowNew(true)}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs font-bold rounded-lg"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="llm-vis-new-btn">
              <Plus size={12}/> Add
            </button>
          </div>
          {queries.length === 0 ? (
            <div className="text-sm text-center py-8" style={{ color: colors.muted }}>
              No queries tracked yet. Add one to start.
            </div>
          ) : (
            <div className="space-y-1">
              {queries.map((q) => (
                <div key={q.id} className="p-2 rounded-lg flex items-center gap-3"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`llm-vis-row-${q.id}`}>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                      {q.query_text}
                    </div>
                    <div className="text-xs" style={{ color: colors.muted }}>
                      Expects: <b>{q.expected_brand}</b> · {q.category}
                    </div>
                  </div>
                  <button onClick={() => del(q.id)}
                          className="p-1.5 rounded"
                          style={{ color: "#DC2626" }}
                          data-testid={`llm-vis-del-${q.id}`}>
                    <Trash2 size={14}/>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-2xl p-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="llm-vis-dashboard">
          {!dash ? (
            <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Metric label="Mention rate" value={`${dash.mention_rate_pct}%`}
                      testId="metric-mention" />
              <Metric label="Avg position"
                      value={dash.avg_position != null ? dash.avg_position : "—"}
                      testId="metric-position" />
              <Metric label="Total scans" value={dash.total_scans}
                      testId="metric-total" />
              <div className="md:col-span-3">
                <div className="text-xs font-bold uppercase mb-2"
                     style={{ color: colors.muted }}>Top competitors</div>
                <div className="flex gap-2 flex-wrap">
                  {dash.top_competitors.length === 0 && (
                    <span className="text-xs" style={{ color: colors.muted }}>
                      None yet.
                    </span>
                  )}
                  {dash.top_competitors.map((c) => (
                    <span key={c.name} className="text-xs px-2 py-1 rounded"
                          style={{ backgroundColor: colors.brandTertiary,
                                   color: colors.brand }}>
                      {c.name} · {c.mentions}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
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
                Track query
              </h3>
              <button onClick={() => setShowNew(false)}
                      style={{ color: colors.muted }}><X size={18}/></button>
            </div>
            <input value={form.query_text}
                   onChange={(e) => setForm({ ...form, query_text: e.target.value })}
                   placeholder="best pool cleaning in Phoenix"
                   className="w-full p-2.5 text-sm rounded-lg mb-2"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }}
                   data-testid="llm-vis-new-query" />
            <input value={form.expected_brand}
                   onChange={(e) => setForm({ ...form, expected_brand: e.target.value })}
                   placeholder="Expected brand (e.g., AquaTerra Pools)"
                   className="w-full p-2.5 text-sm rounded-lg mb-4"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }}
                   data-testid="llm-vis-new-brand" />
            <button onClick={add}
                    className="w-full py-2 text-sm font-bold rounded-lg"
                    style={{ background: brandGradientCss, color: "#fff" }}
                    data-testid="llm-vis-new-submit">
              Add query
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, testId }) {
  return (
    <div className="rounded-xl p-4"
         style={{ backgroundColor: colors.background,
                  border: `1px solid ${colors.border}` }}
         data-testid={testId}>
      <div className="text-[10px] font-bold uppercase" style={{ color: colors.muted }}>
        {label}
      </div>
      <div className="text-3xl font-bold mt-1" style={{ color: colors.brand }}>
        {value}
      </div>
    </div>
  );
}
