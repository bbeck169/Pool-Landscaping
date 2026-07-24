import React from "react";
import { toast } from "sonner";
import {
  Plus, RefreshCw, Trash2, AlertTriangle, MapPin, TrendingUp, Info,
  Search as SearchIcon,
} from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

/**
 * Feb-2026 · Phase 23-A — Local Rank Tracker + Geo-Grid heatmap.
 *
 * Two-column layout:
 *   • Left  — tracked keywords list + "Add keyword" form.
 *   • Right — for the currently selected keyword: a 3x3 heatmap grid,
 *             a rank-trend line chart (last 12 mean ranks), and a
 *             manual "Refresh now" button (6h cooldown per keyword).
 *
 * Backed by /api/rank-tracker/*.  Admin-only via App.js route guard.
 * The weekly cron on the backend is feature-flagged off by default
 * (`RANK_TRACKER_CRON_ENABLED`) — this page's Refresh button is the
 * only way to burn DataForSEO credits in v1.
 */

function relativeAge(iso) {
  if (!iso) return "Never";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "Never";
  const days = Math.floor((Date.now() - t) / 86400000);
  if (days < 1) return "Today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  return `${Math.floor(days / 30)}mo ago`;
}


function bucketColor(rank) {
  if (rank === null || rank === undefined) return { bg: "#FEE2E2", fg: "#7F1D1D" };
  const r = Number(rank);
  if (r <= 3)   return { bg: "#065F46", fg: "#ECFDF5" };
  if (r <= 10)  return { bg: "#16A34A", fg: "#F0FDF4" };
  if (r <= 20)  return { bg: "#CA8A04", fg: "#FEFCE8" };
  if (r <= 50)  return { bg: "#EA580C", fg: "#FFF7ED" };
  return { bg: "#DC2626", fg: "#FEF2F2" };
}


export default function RankTrackerPage() {
  const [keywords, setKeywords] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [detail, setDetail] = React.useState(null);
  const [credits, setCredits] = React.useState(null);
  const [refreshBusy, setRefreshBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const list = await api.get("/rank-tracker/keywords");
      const items = Array.isArray(list?.keywords) ? list.keywords : [];
      setKeywords(items);
      if (!selectedId && items.length) setSelectedId(items[0].id);
    } catch (e) {
      toast.error(e?.message || "Failed to load keywords");
      setKeywords([]);
    }
    try {
      const c = await api.get("/rank-tracker/dataforseo-credits");
      setCredits(c);
    } catch { /* non-blocking */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const loadDetail = React.useCallback(async (kid) => {
    if (!kid) { setDetail(null); return; }
    try {
      const d = await api.get(`/rank-tracker/keywords/${kid}/heatmap`);
      setDetail(d);
    } catch (e) {
      toast.error(e?.message || "Failed to load heatmap");
      setDetail(null);
    }
  }, []);
  React.useEffect(() => { loadDetail(selectedId); }, [selectedId, loadDetail]);

  const addKeyword = async ({ keyword, radiusKm }) => {
    try {
      const created = await api.post("/rank-tracker/keywords", {
        keyword: keyword.trim(),
        radius_km: radiusKm ? Number(radiusKm) : undefined,
      });
      toast.success(`Tracking "${created.keyword}"`);
      const next = [created, ...(keywords || [])];
      setKeywords(next);
      setSelectedId(created.id);
    } catch (e) {
      toast.error(e?.message || "Failed to add keyword");
    }
  };

  const deleteKeyword = async (kid) => {
    try {
      await api.delete(`/rank-tracker/keywords/${kid}`);
      toast.success("Keyword removed");
      const next = (keywords || []).filter((k) => k.id !== kid);
      setKeywords(next);
      if (selectedId === kid) setSelectedId(next[0]?.id || null);
    } catch (e) {
      toast.error(e?.message || "Delete failed");
    }
  };

  const refreshNow = async (kid) => {
    setRefreshBusy(true);
    try {
      const res = await api.post(`/rank-tracker/keywords/${kid}/refresh-now`);
      if (res?.api_error === "out_of_credits") {
        toast.error("DataForSEO account has run out of credits — top up at dataforseo.com to resume rank tracking");
      } else if (res?.api_error === "auth_failed") {
        toast.error("DataForSEO auth failed — check DATAFORSEO_* env vars");
      } else if (res?.api_error === "account_unverified") {
        toast.error("DataForSEO account not verified — complete verification at https://app.dataforseo.com/");
      } else if (res?.api_error) {
        toast.error(`Rank check failed: ${res.api_error}`);
      } else {
        toast.success("Snapshot recorded");
      }
      loadDetail(kid);
      load(); // pull refreshed last_refreshed_at
    } catch (e) {
      toast.error(e?.message || "Refresh failed");
    } finally {
      setRefreshBusy(false);
    }
  };

  const selected = React.useMemo(
    () => (keywords || []).find((k) => k.id === selectedId) || null,
    [keywords, selectedId]
  );

  return (
    <SafeScrollContainer
      className="p-6 max-w-6xl mx-auto"
      data-testid="rank-tracker-page"
    >
      <Header credits={credits} />

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
        <div>
          <AddKeywordForm onAdd={addKeyword} />
          <KeywordList
            keywords={keywords}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDelete={deleteKeyword}
          />
        </div>
        <div>
          {selected ? (
            <KeywordDetail
              keyword={selected}
              detail={detail}
              onRefresh={() => refreshNow(selected.id)}
              refreshBusy={refreshBusy}
            />
          ) : (
            <EmptyState />
          )}
        </div>
      </div>
    </SafeScrollContainer>
  );
}


function Header({ credits }) {
  const banner = (() => {
    if (!credits) return null;
    if (credits.available) {
      return {
        tint: "#DCFCE7", fg: "#166534",
        text: credits.balance !== null && credits.balance !== undefined
          ? `DataForSEO credits remaining: $${Number(credits.balance).toFixed(2)}`
          : "DataForSEO credits: connected (balance not reported)",
        testid: "rank-tracker-credits-ok",
      };
    }
    return {
      tint: "#FEE2E2", fg: "#991B1B",
      text: credits.reason || "DataForSEO unavailable — check your DataForSEO dashboard",
      testid: "rank-tracker-credits-error",
    };
  })();

  return (
    <div className="mb-4">
      <h1
        className="text-2xl font-bold mb-1"
        style={{ color: colors.onSurface }}
        data-testid="rank-tracker-title"
      >
        Local Rank Tracker
      </h1>
      <p className="text-sm mb-2" style={{ color: colors.muted }}>
        Watch how you rank on Google for the keywords that matter, from
        every corner of your service area.
      </p>
      {banner ? (
        <div
          className="rounded-lg px-3 py-2 text-sm inline-flex items-center gap-2"
          style={{ backgroundColor: banner.tint, color: banner.fg }}
          data-testid={banner.testid}
        >
          <Info size={14} /> {banner.text}
        </div>
      ) : null}
    </div>
  );
}


function AddKeywordForm({ onAdd }) {
  const [keyword, setKeyword] = React.useState("");
  const [radiusKm, setRadiusKm] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const submit = async (e) => {
    e?.preventDefault?.();
    if (!keyword.trim()) return;
    setBusy(true);
    try {
      await onAdd({ keyword, radiusKm });
      setKeyword(""); setRadiusKm("");
    } finally { setBusy(false); }
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-xl p-3 mb-3 space-y-2"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="rank-tracker-add-form"
    >
      <div>
        <label
          htmlFor="rank-tracker-add-keyword"
          className="text-[10px] font-semibold uppercase tracking-wider block mb-1"
          style={{ color: colors.muted }}
        >
          Keyword to track
        </label>
        <input
          id="rank-tracker-add-keyword"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="pool cleaning peoria az"
          className="w-full px-3 py-2 rounded-lg border text-sm"
          style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.onSurface }}
          data-testid="rank-tracker-add-input"
        />
      </div>
      <div>
        <label
          htmlFor="rank-tracker-add-radius"
          className="text-[10px] font-semibold uppercase tracking-wider block mb-1"
          style={{ color: colors.muted }}
        >
          Radius (km) — optional (default 2)
        </label>
        <input
          id="rank-tracker-add-radius"
          type="number" min={0.5} max={50} step={0.5}
          value={radiusKm}
          onChange={(e) => setRadiusKm(e.target.value)}
          placeholder="2"
          className="w-full px-3 py-2 rounded-lg border text-sm"
          style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.onSurface }}
          data-testid="rank-tracker-add-radius"
        />
      </div>
      <button
        type="submit" disabled={busy || !keyword.trim()}
        className="w-full inline-flex items-center justify-center gap-1 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60 disabled:cursor-not-allowed"
        style={{ backgroundColor: colors.brand }}
        data-testid="rank-tracker-add-submit"
      >
        <Plus size={14} /> {busy ? "Adding…" : "Add keyword"}
      </button>
    </form>
  );
}


function KeywordList({ keywords, selectedId, onSelect, onDelete }) {
  if (keywords === null) {
    return (
      <div
        className="h-40 rounded-xl animate-pulse"
        style={{ backgroundColor: colors.surfaceSecondary }}
        data-testid="rank-tracker-keywords-loading"
      />
    );
  }
  if (keywords.length === 0) {
    return (
      <div
        className="rounded-xl p-3 text-sm text-center"
        style={{ backgroundColor: colors.surface, border: `1px dashed ${colors.border}`, color: colors.muted }}
        data-testid="rank-tracker-keywords-empty"
      >
        No keywords yet. Add one above to start tracking.
      </div>
    );
  }
  return (
    <ul className="space-y-1" data-testid="rank-tracker-keywords-list">
      {keywords.map((k) => {
        const isSelected = k.id === selectedId;
        return (
          <li
            key={k.id}
            className="rounded-lg p-2 flex items-center gap-2 cursor-pointer transition"
            style={{
              backgroundColor: isSelected ? colors.brand : colors.surface,
              color: isSelected ? "#fff" : colors.onSurface,
              border: `1px solid ${isSelected ? colors.brand : colors.border}`,
            }}
            onClick={() => onSelect(k.id)}
            data-testid={`rank-tracker-keyword-${k.id}`}
            data-selected={isSelected ? "1" : "0"}
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate">
                {k.keyword}
              </div>
              <div
                className="text-[10px]"
                style={{ color: isSelected ? "rgba(255,255,255,0.85)" : colors.muted }}
              >
                Last refresh: {relativeAge(k.last_refreshed_at)}
              </div>
            </div>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDelete(k.id); }}
              className="text-[11px] opacity-80"
              style={{ color: isSelected ? "#fff" : "#991B1B" }}
              aria-label={`Delete ${k.keyword}`}
              data-testid={`rank-tracker-keyword-delete-${k.id}`}
            >
              <Trash2 size={13} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}


function KeywordDetail({ keyword, detail, onRefresh, refreshBusy }) {
  const [cooldownMsg, setCooldownMsg] = React.useState("");
  const [boostBusy, setBoostBusy] = React.useState(false);
  React.useEffect(() => {
    if (!keyword?.last_refreshed_at) { setCooldownMsg(""); return; }
    const t = new Date(keyword.last_refreshed_at).getTime();
    const cooldownEnd = t + 6 * 3600 * 1000;
    const now = Date.now();
    if (now >= cooldownEnd) { setCooldownMsg(""); return; }
    const hoursLeft = Math.ceil((cooldownEnd - now) / 3600000);
    setCooldownMsg(`Refresh available in ~${hoursLeft}h`);
  }, [keyword]);

  const grid = detail?.grid || Array(9).fill(null);
  const history = detail?.history || [];

  // Feb-2026 — identify the worst-ranking cell so the "Boost this area"
  // CTA can seed the GBP post drafter. null (not in top 100) beats any
  // numeric rank as "worst"; among numeric ranks, higher = worse.
  const worstIdx = React.useMemo(() => {
    let worstI = -1;
    let worstScore = -1;
    grid.forEach((cell, i) => {
      const r = cell?.rank;
      const score = (r === null || r === undefined) ? 999 : r;
      if (score > worstScore) { worstScore = score; worstI = i; }
    });
    return grid.some((c) => c) ? worstI : -1;
  }, [grid]);

  const boostArea = async (idx) => {
    const cell = grid[idx];
    if (!cell) return;
    setBoostBusy(true);
    try {
      // Reverse-geocode the cell coords → nearest city name so the topic
      // hint reads naturally ("in Peoria, AZ" not "at 33.77,-112.26").
      let cityHint = "";
      try {
        const geo = await api.get(
          `/maps/reverse-geocode?lat=${cell.grid_lat}&lng=${cell.grid_lng}`
        );
        cityHint = (geo?.city || geo?.formatted_address || "").split(",").slice(0, 2).join(",").trim();
      } catch { /* non-fatal */ }
      const topicHint = cityHint
        ? `${keyword.keyword} — targeting ${cityHint}`
        : `${keyword.keyword} — targeting the coverage gap around ${cell.grid_lat.toFixed(3)},${cell.grid_lng.toFixed(3)}`;
      // Try to hand off to the GBP post drafter dialog if it's globally
      // registered by the marketing page; otherwise fall back to a direct
      // link so the admin still lands on the drafter.
      if (typeof window !== "undefined" && typeof window.openGbpPostDrafter === "function") {
        window.openGbpPostDrafter({
          topic_hint: topicHint,
          purpose: "promo",
          source: "rank_tracker_boost",
          keyword_id: keyword.id,
          grid_point_index: idx,
        });
      } else {
        // Persist the seed in sessionStorage so the marketing page can
        // pick it up on load, then navigate.
        try {
          sessionStorage.setItem("gbp_post_drafter_seed", JSON.stringify({
            topic_hint: topicHint,
            purpose: "promo",
            source: "rank_tracker_boost",
          }));
        } catch { /* ignore quota */ }
        window.location.href = "/marketing/gbp-posts?draft=1";
      }
      toast.success("Opening GBP post drafter — seeded with the low-rank cell context");
    } catch (e) {
      toast.error(e?.message || "Failed to open drafter");
    } finally { setBoostBusy(false); }
  };

  return (
    <div
      className="rounded-xl p-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="rank-tracker-detail"
    >
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div className="min-w-0">
          <h2
            className="text-lg font-bold"
            style={{ color: colors.onSurface }}
            data-testid="rank-tracker-detail-keyword"
          >
            {keyword.keyword}
          </h2>
          <div
            className="text-xs flex items-center gap-1"
            style={{ color: colors.muted }}
          >
            <MapPin size={11} />
            Grid: 3×3 · radius {(keyword.market_geo?.radius_km || 2).toFixed(1)} km
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshBusy || !!cooldownMsg}
          className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60 disabled:cursor-not-allowed"
          style={{ backgroundColor: colors.brand }}
          title={cooldownMsg || "Trigger a fresh 9-point snapshot"}
          data-testid="rank-tracker-refresh-now"
        >
          <RefreshCw size={14} className={refreshBusy ? "animate-spin" : ""} />
          {refreshBusy ? "Checking…" : cooldownMsg || "Refresh now"}
        </button>
      </div>

      <div
        className="grid grid-cols-3 gap-2 mb-4"
        role="grid"
        aria-label="Rank heatmap 3 by 3 grid"
        data-testid="rank-tracker-heatmap-grid"
      >
        {grid.map((cell, idx) => {
          const rank = cell?.rank ?? null;
          const c = bucketColor(rank);
          const label = rank === null ? "—" : String(rank);
          const isWorst = idx === worstIdx && !!cell;
          return (
            <div
              key={idx}
              className="rounded-lg aspect-square flex flex-col items-center justify-center text-center relative"
              style={{ backgroundColor: c.bg, color: c.fg }}
              data-testid={`rank-tracker-heatmap-cell-${idx}`}
              data-rank={rank === null ? "null" : String(rank)}
              data-worst={isWorst ? "1" : "0"}
              title={cell
                ? `Rank ${rank ?? "not in top 100"} · ${cell.grid_lat?.toFixed?.(3)},${cell.grid_lng?.toFixed?.(3)}`
                : "No data yet"}
            >
              <div className="text-2xl font-bold">{label}</div>
              <div className="text-[9px] opacity-80">pt {idx + 1}</div>
              {isWorst ? (
                <button
                  type="button"
                  onClick={() => boostArea(idx)}
                  disabled={boostBusy}
                  className="absolute bottom-1 left-1 right-1 rounded text-[9px] font-bold px-1 py-0.5"
                  style={{ backgroundColor: "rgba(0,0,0,0.55)", color: "#fff" }}
                  title="Draft a GBP post targeting this cell"
                  data-testid={`rank-tracker-boost-cell-${idx}`}
                >
                  Boost this area
                </button>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="mb-2">
        <div
          className="text-[10px] font-semibold uppercase tracking-wider mb-1"
          style={{ color: colors.muted }}
        >
          Mean rank — last {history.length || 0} snapshots
        </div>
        {history.length ? (
          <TrendChart data={history} />
        ) : (
          <div
            className="rounded-lg p-3 text-xs text-center"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}
            data-testid="rank-tracker-history-empty"
          >
            No history yet. Refresh at least twice to see the trend.
          </div>
        )}
      </div>

      <LegendBar />
    </div>
  );
}


function TrendChart({ data }) {
  const w = 480, h = 80, pad = 6;
  const values = data.map((d) => Number(d.mean_rank) || 0);
  const maxRank = Math.max(...values, 10);
  const points = values.map((v, i) => {
    const x = pad + (i / Math.max(1, values.length - 1)) * (w - 2 * pad);
    const y = pad + (v / maxRank) * (h - 2 * pad); // higher rank = worse = lower on y-axis
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
         data-testid="rank-tracker-trend-chart">
      <polyline
        fill="none" stroke="#0284C7" strokeWidth="2" points={points}
      />
      {values.map((v, i) => {
        const x = pad + (i / Math.max(1, values.length - 1)) * (w - 2 * pad);
        const y = pad + (v / maxRank) * (h - 2 * pad);
        return (
          <circle
            key={i} cx={x} cy={y} r={3}
            fill="#0284C7"
          />
        );
      })}
    </svg>
  );
}


function LegendBar() {
  const buckets = [
    { label: "1-3", ...bucketColor(1) },
    { label: "4-10", ...bucketColor(4) },
    { label: "11-20", ...bucketColor(11) },
    { label: "21-50", ...bucketColor(21) },
    { label: "51+ / —", ...bucketColor(null) },
  ];
  return (
    <div
      className="flex flex-wrap items-center gap-2 text-[10px]"
      data-testid="rank-tracker-legend"
    >
      <span style={{ color: colors.muted }} className="font-semibold uppercase tracking-wider">
        Legend
      </span>
      {buckets.map((b) => (
        <span
          key={b.label}
          className="px-2 py-0.5 rounded font-semibold"
          style={{ backgroundColor: b.bg, color: b.fg }}
        >
          {b.label}
        </span>
      ))}
    </div>
  );
}


function EmptyState() {
  return (
    <div
      className="rounded-xl p-8 text-center"
      style={{
        backgroundColor: colors.surface,
        border: `1px dashed ${colors.border}`,
      }}
      data-testid="rank-tracker-empty"
    >
      <div
        className="w-12 h-12 rounded-full mx-auto mb-3 flex items-center justify-center"
        style={{ backgroundColor: "#DBEAFE", color: "#1E40AF" }}
      >
        <TrendingUp size={22} />
      </div>
      <div className="font-semibold" style={{ color: colors.onSurface }}>
        Track your first keyword
      </div>
      <div className="text-sm mt-1" style={{ color: colors.muted }}>
        Add a keyword like "pool cleaning peoria az" on the left, then click
        Refresh now to see where you rank across a 3×3 grid of your service area.
      </div>
    </div>
  );
}
