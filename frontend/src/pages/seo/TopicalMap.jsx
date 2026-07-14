/**
 * Phase 17B.1 · Topical Map viewer.
 */
import React, { useEffect, useState } from "react";
import { Network, Plus, X, Copy, Sparkles } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

const INTENT_COLOR = {
  informational: "#2563EB", commercial: "#059669",
  navigational: "#7C3AED",  transactional: "#DC2626",
};

export default function TopicalMap() {
  const [rows, setRows] = useState([]);
  const [current, setCurrent] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [seed, setSeed] = useState("");
  const [ctx, setCtx] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);

  const loadList = () => api.get("/seo/topical-maps").then(setRows);
  useEffect(() => { loadList(); }, []);

  const create = async () => {
    if (!seed.trim()) return;
    setBusy(true);
    try {
      const r = await api.post("/seo/topical-maps",
                                { seed_keyword: seed, business_context: ctx });
      const full = await api.get(`/seo/topical-maps/${r.map_id}`);
      setCurrent(full);
      setShowNew(false); setSeed(""); setCtx("");
      loadList();
    } finally { setBusy(false); }
  };

  const exportCsv = () => {
    if (!current) return;
    const rows_ = [["id","title","intent","level","volume","slug","parent"]];
    (current.tree.nodes || []).forEach((n) => rows_.push([
      n.id, n.title, n.intent, n.level,
      n.estimated_search_volume, n.suggested_url_slug, n.parent || "",
    ]));
    const csv = rows_.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `topical-map-${current.seed_keyword}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  const byLevel = (current?.tree?.nodes || []).reduce((acc, n) => {
    acc[n.level] = acc[n.level] || [];
    acc[n.level].push(n);
    return acc;
  }, {});

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="topical-map-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Network size={22} style={{ color: colors.brand }}/>
            <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
              Topical Map
            </h1>
          </div>
          <p className="text-sm" style={{ color: colors.muted }}>
            Pillar + cluster + support content plan around any seed keyword.
          </p>
        </div>
        <div className="flex gap-2">
          {current && (
            <button onClick={exportCsv}
                    className="px-3 py-2 text-sm rounded-xl"
                    style={{ backgroundColor: colors.surface,
                             border: `1px solid ${colors.border}` }}
                    data-testid="topical-map-export">
              Export CSV
            </button>
          )}
          <button onClick={() => setShowNew(true)}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ background: brandGradientCss, color: "#fff" }}
                  data-testid="topical-map-new">
            <Plus size={14}/> Generate
          </button>
        </div>
      </div>

      <div className="grid md:grid-cols-4 gap-4">
        <div className="rounded-2xl p-3"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="topical-map-list">
          <div className="text-[10px] font-bold uppercase mb-2"
               style={{ color: colors.muted }}>Recent maps</div>
          {rows.map((r) => (
            <button key={r.id} onClick={async () => {
                       setCurrent(await api.get(`/seo/topical-maps/${r.id}`));
                       setSelectedNode(null);
                     }}
                    className="w-full text-left p-2 text-sm rounded-lg hover:brightness-95 truncate"
                    style={{
                      backgroundColor: current?.id === r.id ? colors.brandTertiary : "transparent",
                      color: colors.onSurface,
                    }}
                    data-testid={`topical-map-row-${r.id}`}>
              {r.seed_keyword}
            </button>
          ))}
          {rows.length === 0 && (
            <div className="text-xs" style={{ color: colors.muted }}>
              No maps yet.
            </div>
          )}
        </div>

        <div className="md:col-span-3 rounded-2xl p-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="topical-map-view">
          {!current ? (
            <div className="text-sm text-center py-16" style={{ color: colors.muted }}>
              Generate a map to see the pillar + cluster graph.
            </div>
          ) : (
            <div>
              <div className="mb-3">
                <div className="text-xs" style={{ color: colors.muted }}>Seed</div>
                <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  {current.seed_keyword}
                </div>
                <div className="text-[10px]" style={{ color: colors.muted }}>
                  {current.tree.nodes.length} nodes ·{" "}
                  {current.mocked ? "AI stubbed" : "AI live"}
                </div>
              </div>
              {/* Simple 3-column layout by level */}
              <div className="grid grid-cols-3 gap-3">
                {[0, 1, 2].map((lvl) => (
                  <div key={lvl}>
                    <div className="text-[10px] font-bold uppercase mb-2"
                         style={{ color: colors.muted }}>
                      {lvl === 0 ? "Pillar" : lvl === 1 ? "Clusters" : "Support"}
                    </div>
                    <div className="space-y-1">
                      {(byLevel[lvl] || []).slice(0, 40).map((n) => (
                        <button key={n.id} onClick={() => setSelectedNode(n)}
                                className="w-full text-left p-2 rounded-lg text-xs"
                                style={{
                                  backgroundColor: selectedNode?.id === n.id
                                    ? INTENT_COLOR[n.intent] || colors.brand
                                    : colors.background,
                                  color: selectedNode?.id === n.id ? "#fff" : colors.onSurface,
                                  border: `1px solid ${INTENT_COLOR[n.intent] || colors.border}`,
                                }}
                                data-testid={`topical-node-${n.id}`}>
                          <div className="font-semibold">{n.title}</div>
                          <div className="text-[9px] opacity-80">
                            {n.intent} · vol {n.estimated_search_volume}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {selectedNode && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
             style={{ background: "rgba(0,0,0,0.5)" }} onClick={() => setSelectedNode(null)}>
          <div className="max-w-md w-full p-6 rounded-2xl"
               onClick={(e) => e.stopPropagation()}
               style={{ backgroundColor: colors.surface }}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                {selectedNode.title}
              </h3>
              <button onClick={() => setSelectedNode(null)}
                      style={{ color: colors.muted }}>
                <X size={18}/>
              </button>
            </div>
            <div className="text-xs space-y-1 mb-4" style={{ color: colors.muted }}>
              <div>Intent: <b style={{ color: colors.onSurface }}>{selectedNode.intent}</b></div>
              <div>Level: <b style={{ color: colors.onSurface }}>{selectedNode.level}</b></div>
              <div>Est. volume: <b style={{ color: colors.onSurface }}>
                {selectedNode.estimated_search_volume}
              </b> (est.)</div>
              <div>Suggested slug: <code>{selectedNode.suggested_url_slug}</code></div>
            </div>
            <button onClick={async () => {
                       const r = await api.post(
                         `/seo/topical-maps/${current.id}/generate-content`,
                         { node_id: selectedNode.id });
                       alert(`Outline drafted — ${(r.outline || []).length} H2s. Check console.`);
                       console.log("Outline:", r);
                     }}
                    className="w-full py-2 text-sm font-bold rounded-lg flex items-center justify-center gap-1"
                    style={{ background: brandGradientCss, color: "#fff" }}
                    data-testid="topical-node-outline">
              <Sparkles size={14}/> Generate outline
            </button>
          </div>
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
                New Topical Map
              </h3>
              <button onClick={() => setShowNew(false)}
                      style={{ color: colors.muted }}>
                <X size={18}/>
              </button>
            </div>
            <input value={seed} onChange={(e) => setSeed(e.target.value)}
                   placeholder="Seed keyword"
                   className="w-full p-2.5 text-sm rounded-lg mb-2"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }}
                   data-testid="topical-map-seed" />
            <textarea value={ctx} onChange={(e) => setCtx(e.target.value)}
                      rows={3} placeholder="Business context (optional)"
                      className="w-full p-2.5 text-sm rounded-lg mb-4"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}`,
                               color: colors.onSurface }}
                      data-testid="topical-map-ctx" />
            <button onClick={create} disabled={busy}
                    className="w-full py-2 text-sm font-bold rounded-lg disabled:opacity-60"
                    style={{ background: brandGradientCss, color: "#fff" }}
                    data-testid="topical-map-generate">
              {busy ? "Generating…" : "Generate map"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
