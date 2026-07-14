/**
 * Phase 17A.3 · Rank Heatmap — geo grid of local SERP ranks.
 */
import React, { useEffect, useState } from "react";
import { MapPin, Play, Info } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

function rankColor(rank) {
  if (rank == null) return "#F3F4F6";
  if (rank <= 3)   return "#059669";        // green
  if (rank <= 10)  return "#65A30D";        // light green
  if (rank <= 15)  return "#EAB308";        // yellow
  if (rank <= 20)  return "#F97316";        // orange
  return "#DC2626";                          // red
}

export default function RankHeatmap() {
  const [form, setForm] = useState({
    keyword: "", center_lat: 33.6, center_lng: -112.2,
    grid_size: 5, radius_miles: 5,
  });
  const [rows, setRows] = useState([]);
  const [current, setCurrent] = useState(null);
  const [starting, setStarting] = useState(false);
  const [selectedCell, setSelectedCell] = useState(null);

  const loadList = () => api.get("/seo/rank-heatmaps").then(setRows);
  useEffect(() => { loadList(); }, []);

  useEffect(() => {
    if (!current || current.status === "done" || current.status === "failed") return;
    const t = setInterval(async () => {
      const r = await api.get(`/seo/rank-heatmaps/${current.id}`);
      setCurrent(r);
      if (r.status === "done" || r.status === "failed") { loadList(); }
    }, 1500);
    return () => clearInterval(t);
  }, [current?.status, current?.id]);

  const start = async () => {
    if (!form.keyword.trim()) return;
    setStarting(true);
    try {
      const r = await api.post("/seo/rank-heatmaps", form);
      // r has heatmap_id + mocked + reason
      const fresh = await api.get(`/seo/rank-heatmaps/${r.heatmap_id}`);
      setCurrent(fresh);
      loadList();
    } finally { setStarting(false); }
  };

  const grid = current?.grid_size || form.grid_size;

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="rank-heatmap-page">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <MapPin size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Rank Heatmap
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          See where you rank for a keyword across every corner of your service area.
        </p>
      </div>

      {(current?.mocked || rows[0]?.mocked) && (
        <div className="mb-4 p-3 rounded-xl text-xs flex items-start gap-2"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
             data-testid="rank-heatmap-mocked-banner">
          <Info size={14} style={{ marginTop: 1 }}/>
          <div>
            <b>SERP provider not configured</b> — ranks below are synthesized
            for UI preview. Configure a SERP integration (SerpAPI, DataForSEO,
            or a Google Maps Local API key) to see real data.
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-3 gap-4 mb-6">
        <div className="rounded-2xl p-4 space-y-2 md:col-span-1"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="rank-heatmap-form">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider"
                   style={{ color: colors.muted }}>Keyword</label>
            <input value={form.keyword}
                   onChange={(e) => setForm({ ...form, keyword: e.target.value })}
                   className="w-full p-2 text-sm rounded-lg"
                   placeholder="pool cleaning phoenix"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }}
                   data-testid="rank-heatmap-kw" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider"
                     style={{ color: colors.muted }}>Center lat</label>
              <input type="number" step="0.001" value={form.center_lat}
                     onChange={(e) => setForm({ ...form, center_lat: Number(e.target.value) })}
                     className="w-full p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}
                     data-testid="rank-heatmap-lat" />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider"
                     style={{ color: colors.muted }}>Center lng</label>
              <input type="number" step="0.001" value={form.center_lng}
                     onChange={(e) => setForm({ ...form, center_lng: Number(e.target.value) })}
                     className="w-full p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}
                     data-testid="rank-heatmap-lng" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider"
                     style={{ color: colors.muted }}>Grid</label>
              <input type="number" min={2} max={9} value={form.grid_size}
                     onChange={(e) => setForm({ ...form, grid_size: Number(e.target.value) })}
                     className="w-full p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}
                     data-testid="rank-heatmap-grid" />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider"
                     style={{ color: colors.muted }}>Radius (mi)</label>
              <input type="number" step="0.5" min={0.5} max={25}
                     value={form.radius_miles}
                     onChange={(e) => setForm({ ...form, radius_miles: Number(e.target.value) })}
                     className="w-full p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}
                     data-testid="rank-heatmap-radius" />
            </div>
          </div>
          <button onClick={start} disabled={starting}
                  className="w-full py-2 text-sm font-bold rounded-lg flex items-center justify-center gap-1 disabled:opacity-60 mt-2"
                  style={{ background: brandGradientCss, color: "#fff" }}
                  data-testid="rank-heatmap-run">
            <Play size={14}/> {starting ? "Running…" : "Generate heatmap"}
          </button>
        </div>

        {/* Heatmap render */}
        <div className="rounded-2xl p-4 md:col-span-2"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="rank-heatmap-grid-view">
          {!current ? (
            <div className="h-full flex items-center justify-center text-sm py-16"
                 style={{ color: colors.muted }}>
              Run a keyword to see the heatmap.
            </div>
          ) : current.status !== "done" ? (
            <div className="h-full flex items-center justify-center text-sm py-16"
                 style={{ color: colors.muted }}>
              Generating grid… (status: {current.status})
            </div>
          ) : (
            <>
              <div className="grid gap-1 mb-3"
                   style={{ gridTemplateColumns: `repeat(${grid}, minmax(0, 1fr))` }}>
                {(current.points || []).map((p, i) => (
                  <button key={i}
                          onClick={() => setSelectedCell(p)}
                          className="aspect-square rounded transition hover:scale-105"
                          style={{ backgroundColor: rankColor(p.rank) }}
                          title={`Rank ${p.rank} · ${p.lat},${p.lng}`}
                          data-testid={`rank-heatmap-cell-${i}`}>
                    <div className="text-xs font-bold text-white">
                      {p.rank <= 20 ? p.rank : "20+"}
                    </div>
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs" style={{ color: colors.muted }}>
                <div>Avg rank: <b style={{ color: colors.onSurface }}>{current.avg_rank}</b></div>
                <div>Top-10 cells: <b style={{ color: colors.onSurface }}>{current.top_position_count}</b></div>
                <div>Grid: {current.grid_size}×{current.grid_size}</div>
              </div>
              {selectedCell && (
                <div className="mt-3 p-3 rounded-lg text-xs"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid="rank-heatmap-selected-cell">
                  <div className="font-bold" style={{ color: colors.onSurface }}>
                    Rank {selectedCell.rank} at {selectedCell.lat}, {selectedCell.lng}
                  </div>
                  <div className="text-[10px] font-bold uppercase tracking-wider mt-2 mb-1"
                       style={{ color: colors.muted }}>Top 10</div>
                  <ol className="ml-4 space-y-0.5" style={{ color: colors.brand }}>
                    {(selectedCell.top_10_urls || []).slice(0, 10).map((u, i) => (
                      <li key={i}>{i + 1}. {u}</li>
                    ))}
                  </ol>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {rows.length > 0 && (
        <div className="rounded-2xl p-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
               style={{ color: colors.muted }}>Recent</div>
          <div className="space-y-1">
            {rows.slice(0, 10).map((r) => (
              <button key={r.id}
                      onClick={() => setCurrent(r)}
                      className="w-full text-left p-2 rounded flex items-center gap-3 hover:brightness-95"
                      data-testid={`rank-heatmap-row-${r.id}`}>
                <div className="text-sm flex-1 min-w-0 truncate" style={{ color: colors.onSurface }}>
                  {r.keyword}
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  avg {r.avg_rank ?? "…"}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
