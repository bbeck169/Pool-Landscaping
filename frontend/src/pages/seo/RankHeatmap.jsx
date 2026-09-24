/**
 * Phase 17A.3 · Rank Heatmap — geo grid of local SERP ranks.
 */
import React, { useEffect, useState } from "react";
import { MapPin, Play, Info } from "lucide-react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";

function rankColor(rank) {
  if (rank == null) return "#F3F4F6";
  if (rank <= 3)   return "#059669";        // green
  if (rank <= 10)  return "#65A30D";        // light green
  if (rank <= 15)  return "#EAB308";        // yellow
  if (rank <= 20)  return "#F97316";        // orange
  return "#DC2626";                          // red
}

// Task J · Commit 2 · Feb-2026 — map a thrown ``api`` error into
// user-facing copy. Precedence per the ask-approved matrix:
//   1. Server-crafted ``detail.message`` on rich dict shape
//      (this is what ``require_feature`` puts on the 402 —
//      services/entitlements/deps.py :54-63).
//   2. Plain-string ``detail`` when the server uses the shorter
//      ``raise HTTPException(400, "text")`` form.
//   3. Status-code fallback matrix.
//   4. Last-resort "Something went wrong. Please try again."
//      for network errors + 500s + anything without a status.
//
// Pydantic 422 details are LISTS (``[{loc, msg, ...}, ...]``) —
// they intentionally fall through the two server-message branches
// and land on the 422 fallback so the user sees friendly copy
// instead of "Input should be less than or equal to 9" noise.
//
// Never surfaces raw stack traces or JSON blobs; the branches
// above emit strings only.
function _mapHeatmapError(e) {
  const status = Number(e?.status || 0);
  const detail = e?.data?.detail;
  let serverMessage = "";
  if (
    detail && typeof detail === "object" && !Array.isArray(detail)
    && typeof detail.message === "string"
    && detail.message.trim()
  ) {
    serverMessage = detail.message.trim();
  } else if (typeof detail === "string" && detail.trim()) {
    serverMessage = detail.trim();
  }
  if (serverMessage) return serverMessage;
  if (status === 402) {
    return (
      "Feature not enabled — contact your admin to activate "
      + "SEO Rank Heatmap."
    );
  }
  if (status === 422) {
    return (
      "Invalid map values — check your latitude, longitude, "
      + "grid size, and radius."
    );
  }
  if (status === 400) return "Invalid request.";
  if (status === 401 || status === 403) return "Not authorized.";
  if (status === 429) return "Rate limit hit — try again in a moment.";
  return "Something went wrong. Please try again.";
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
  // Task J · Commit 1 · Feb-2026 — client-side empty-field guard on
  // the Generate button. Bounds mirror ``RankHeatmapIn`` Pydantic
  // ``Field(...)`` constraints (routers/seo_agentic.py :759-764)
  // so the client-side validator can't disagree with the server:
  //   * keyword    — non-blank trimmed string
  //   * center_lat — finite ∈ [-90, 90]
  //   * center_lng — finite ∈ [-180, 180]
  //   * grid_size  — finite ∈ [2, 9]
  //   * radius_mi  — finite ∈ (0, 25]
  // A single form-level banner above Generate carries the copy;
  // this matches the ask-approved "one banner over per-field
  // errors" non-blocker decision. Cleared on every Generate click.
  const [validationError, setValidationError] = useState("");
  // Task J · Commit 2 · Feb-2026 — server-error banner. Distinct
  // from ``validationError`` (client-side guard) so both surfaces
  // can coexist without stomping each other, though in practice
  // the ``start`` handler clears both at the top of every click.
  //   * ``rank-heatmap-validation-error`` — client empty-field.
  //   * ``rank-heatmap-error``           — server or network.
  const [error, setError] = useState("");

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
  }, [current?.status, current?.id]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: deps 'current' intentionally omitted (mount-only or stable-ref)

  const start = async () => {
    // Task J · Commit 1 · Feb-2026 — reset any prior banner up-
    // front so a fresh click on Generate always starts from a
    // clean slate.
    setValidationError("");
    // Task J · Commit 2 · Feb-2026 — parallel clear of the server
    // error banner. Both banners reset on every click.
    setError("");
    // Empty-field / out-of-bounds guard. Runs BEFORE the fetch so
    // an invalid form never touches the network. Bounds mirror
    // the backend ``RankHeatmapIn`` Pydantic ``Field(...)`` limits
    // so client + server agree on legality.
    const kw = String(form.keyword || "").trim();
    const lat = Number(form.center_lat);
    const lng = Number(form.center_lng);
    const grid = Number(form.grid_size);
    const rad = Number(form.radius_miles);
    const invalid =
      !kw
      || !Number.isFinite(lat) || lat < -90 || lat > 90
      || !Number.isFinite(lng) || lng < -180 || lng > 180
      || !Number.isFinite(grid) || grid < 2 || grid > 9
      || !Number.isFinite(rad) || rad <= 0 || rad > 25;
    if (invalid) {
      setValidationError("Please fill all fields.");
      return;
    }
    setStarting(true);
    try {
      const r = await api.post("/seo/rank-heatmaps", form);
      // r has heatmap_id + mocked + reason
      const fresh = await api.get(`/seo/rank-heatmaps/${r.heatmap_id}`);
      setCurrent(fresh);
      loadList();
    } catch (e) {
      // Task J · Commit 2 · Feb-2026 — surface any thrown ``api``
      // error via the mapped copy. NEVER leak raw stack traces or
      // JSON blobs; ``_mapHeatmapError`` emits strings only.
      setError(_mapHeatmapError(e));
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

      {current?.mocked && (
        <div className="mb-4 p-3 rounded-xl text-xs flex items-start gap-2"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
             data-testid="rank-heatmap-mocked-banner">
          <Info size={14} style={{ marginTop: 1 }}/>
          <div>
            {current?.mocked_reason === "dataforseo_not_configured" ? (
              <>
                <b>SERP provider not configured</b> — ranks below are synthesized
                for UI preview. Configure a SERP integration (DataForSEO or SerpAPI)
                to see real data.
              </>
            ) : current?.mocked_reason === "tenant_domain_not_configured" ? (
              <>
                <b>Business website missing</b> — set your website URL in
                Settings → Business Card so we can find your ranking in the SERPs.
              </>
            ) : (
              <>
                <b>Synthesized preview</b> — {current?.mocked_reason ||
                "the SERP provider fell back to synthesized data. Re-run to try again."}
              </>
            )}
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
                  style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                  data-testid="rank-heatmap-run">
            <Play size={14}/> {starting ? "Running…" : "Generate heatmap"}
          </button>
          {/* Task J · Commit 1 · Feb-2026 — inline validation banner.
              Rendered ONLY when the client-side guard trips (never
              from a server response — that's the ``rank-heatmap-
              error`` sibling below). Copy is fixed to "Please fill
              all fields." per the ask-approved non-blocker decision. */}
          {validationError ? (
            <div
              className="mt-2 p-2 rounded-lg text-xs flex items-start gap-2"
              role="alert"
              style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}
              data-testid="rank-heatmap-validation-error"
            >
              <Info size={12} style={{ marginTop: 1 }}/>
              <span className="font-semibold">{validationError}</span>
            </div>
          ) : null}
          {/* Task J · Commit 2 · Feb-2026 — server-error banner.
              Populated by ``_mapHeatmapError`` in the ``start``
              catch branch. Same destructive palette + role="alert"
              as the sibling above so screen readers announce
              either. Two separate blocks (not a merged one) so
              testids stay orthogonal for granular assertions. */}
          {error ? (
            <div
              className="mt-2 p-2 rounded-lg text-xs flex items-start gap-2"
              role="alert"
              style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}
              data-testid="rank-heatmap-error"
            >
              <Info size={12} style={{ marginTop: 1 }}/>
              <span className="font-semibold">{error}</span>
            </div>
          ) : null}
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
