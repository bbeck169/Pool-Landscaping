// Phase 17 · Feb-2026 — Dispatch Board page.
//
// Replaces the previous OpsHub-hosted dispatch tab with a Google
// Maps + Directions API powered layout that matches the two
// reference screenshots the user provided:
//
//   • Top: day-of-week tabs (Mon-Sun + All) + Global toggle
//   • Left column: route-type chips, tech dropdown, "Select
//     Customer" side panel
//   • Center: <Map> with color-coded pins + polyline overlay +
//     marker clustering for >30 pins
//   • Right column: Tech Load strip, Route Details drag-reorder
//     list, Optimize button + savings banner
//
// Full-page scroll — the outermost container has NO overflow rule
// so window scrolling stays intact per Phase 17 message 752.
// Only the map has a bounded height (min(72vh, 720px)).
//
// Techs never see this page — the route is wrapped in <AdminOnly>
// in App.js and the endpoints re-enforce role.
import React from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { DndContext, PointerSensor, useSensor, useSensors, useDroppable } from "@dnd-kit/core";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";
import { CalendarDays, Globe, Zap, MapPin, Users, ChevronDown, Sparkles, PlusCircle, Loader2, ArrowRight } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  fetchBoard, optimizeBoard, applyBoardOrder,
} from "@/pages/dispatch/dispatchBoardApi";
// Feb-2026 · Live-Tech-Map · Phase 4.core — ETag-aware poll helper.
import { fetchBoardWithEtag } from "@/pages/dispatch/dispatchBoardPoll";
import DispatchMapView from "@/pages/dispatch/DispatchMapView";
// Feb-2026 · Live-Tech-Map · Phase 4.a — schedule panel in the left col.
import DispatchSchedulePanel from "@/pages/dispatch/DispatchSchedulePanel";
import useLiveTechPositions from "@/hooks/useLiveTechPositions";
import useCrossingToasts from "@/hooks/useCrossingToasts";
import RouteDetailsList from "@/pages/dispatch/RouteDetailsList";
import TechLoadStrip from "@/pages/dispatch/TechLoadStrip";
import ShiftRouteDialog from "@/pages/dispatch/ShiftRouteDialog";
import ActiveShiftsSidebar from "@/pages/dispatch/ActiveShiftsSidebar";
import UnroutedPanel from "@/pages/dispatch/UnroutedPanel";
import OptimizeRouteModal from "@/pages/dispatch/OptimizeRouteModal";
import UnscheduledJobsPanel from "@/pages/dispatch/UnscheduledJobsPanel";
import AssignJobModal from "@/pages/dispatch/AssignJobModal";
import DispatchSavingsStrip from "@/pages/dispatch/DispatchSavingsStrip";
// Feb-2026 · Optimize Route (sub-phase C) — admin approval card + modal.
import PendingRouteOptimizations from "@/pages/dispatch/PendingRouteOptimizations";
import { PIN_COLOR_MODES, PIN_COLOR_BY_DAY, CREW_LEGEND, loadPinColorMode, savePinColorMode } from "@/pages/dispatch/dispatchColors";
import formatAddress from "@/utils/formatAddress";

const DAYS = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
  { key: "all", label: "All" },
];

const ROUTE_TYPE_OPTIONS = [
  { key: "all", label: "All routes" },
  { key: "pool", label: "Pool" },
  { key: "landscaping", label: "Landscaping" },
  { key: "vip", label: "VIP" },
];

function todayKey() {
  const map = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  return map[new Date().getDay()];
}

// Phase 3 · Feb-2026 — resolve a DOW key ("mon".."sun") to the ISO
// date (YYYY-MM-DD) of that weekday inside the CURRENT week (Mon=1,
// Sun=7 per ISO). Returns null for "all" so callers can gate the
// nearest-neighbor optimizer.
function isoDateForDayKey(dayKey) {
  if (!dayKey || dayKey === "all") return null;
  const order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const target = order.indexOf(dayKey);
  if (target < 0) return null;
  const now = new Date();
  const jsDow = now.getDay();          // 0..6, Sun=0
  const isoDow = jsDow === 0 ? 6 : jsDow - 1;  // 0..6, Mon=0
  const delta = target - isoDow;
  const d = new Date(now);
  d.setDate(now.getDate() + delta);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export default function DispatchBoardPage() {
  const navigate = useNavigate();
  const [day, setDay] = React.useState(todayKey());
  const [techId, setTechId] = React.useState(null);
  const [routeType, setRouteType] = React.useState("all");
  const [globalView, setGlobalView] = React.useState(false);
  const [board, setBoard] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [selectedCustomerId, setSelectedCustomerId] = React.useState(null);
  const [polyline, setPolyline] = React.useState(null);
  const [savings, setSavings] = React.useState(null); // {min, pct, distance_mi, duration_min}
  const [optimizing, setOptimizing] = React.useState(false);
  const [applying, setApplying] = React.useState(false);
  const [techs, setTechs] = React.useState([]); // {id, name, display_color_hex}
  // Phase 17 additions ── pin color mode + shift dialog + active shifts.
  const [pinColorMode, setPinColorMode] = React.useState(loadPinColorMode());
  const [shiftDialogOpen, setShiftDialogOpen] = React.useState(false);
  const [shiftScope, setShiftScope] = React.useState("whole_route");
  const [selectedStopIds, setSelectedStopIds] = React.useState([]);
  const [activeShifts, setActiveShifts] = React.useState([]);
  // Phase 3 · Feb-2026 — Nearest-neighbor optimizer modal state.
  const [nnModalOpen, setNnModalOpen] = React.useState(false);
  // Phase 4 · Feb-2026 — Unscheduled jobs (drag source) + assign-popup fallback.
  const [unschedJobs, setUnschedJobs] = React.useState([]);
  const [assignModalJob, setAssignModalJob] = React.useState(null);
  // Phase 10 · sub-item E — batch preview cache.
  const [previewsById, setPreviewsById] = React.useState({});
  const previewCacheRef = React.useRef({}); // key: `${tech}|${date}|${idsHash}` → {at, previews}
  const setPinColorModePersistent = (m) => { setPinColorMode(m); savePinColorMode(m); };

  // Feb-2026 · Live-Tech-Map Phase 4.core — isolate + focus state.
  // ``isolatedTechId`` dims every other tech's pin/polyline on the
  // map AND the schedule panel; ``focusedStopId`` pans the map to a
  // single stop. Both cleared when the user toggles filters or picks
  // a new day so the visual noise doesn't leak between contexts.
  const [isolatedTechId, setIsolatedTechId] = React.useState(null);
  const [focusedStopId, setFocusedStopId] = React.useState(null);

  // Phase P2 · Feb-2026 — live technician GPS markers on the map.
  // Toggle default ON, persisted to localStorage. Poll every 30 s while
  // the toggle is on; hook is a no-op when off.
  const [showLiveTechs, setShowLiveTechs] = React.useState(() => {
    try {
      const v = localStorage.getItem("dispatch.showLiveTechs");
      return v === null ? true : v === "true";
    } catch { return true; }
  });
  React.useEffect(() => {
    try { localStorage.setItem("dispatch.showLiveTechs", String(showLiveTechs)); } catch {}
  }, [showLiveTechs]);
  const { positions: livePositions, recentCrossings } = useLiveTechPositions({
    enabled: showLiveTechs,
    intervalMs: 30000,
  });
  // Phase G5a · Feb-2026 — toast on new geofence crossings (dedupe
  // via localStorage inside the hook). Only when live-techs is on.
  useCrossingToasts(recentCrossings, { enabled: showLiveTechs });

  // Load the tech directory once so the dropdown is populated even
  // when the current filter returns no pins for a tech (offline day).
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const raw = await api.get("/users?role=technician");
        const rows = Array.isArray(raw) ? raw : (raw?.users || raw?.items || []);
        if (!cancelled) {
          setTechs((rows || []).map((u) => ({
            id: u.id, name: u.name || u.email || u.id,
            display_color_hex: u.display_color_hex || null,
          })));
        }
      } catch (_e) {
        // Non-fatal — dropdown still works with the tech_load fallback.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Feb-2026 · Live-Tech-Map · Phase 4.core — ETag-aware polling
  // for the dispatch board.
  //   * First load: no ``If-None-Match``, we cache the returned ETag.
  //   * Subsequent polls (30 s cadence): send the cached ETag; if
  //     the server responds 304 we skip the ``setBoard`` call so
  //     React doesn't re-render on an unchanged payload.
  //   * A user-initiated filter change (day / tech / route type)
  //     re-runs ``load`` from scratch (no If-None-Match) so the
  //     new filter result always fetches fresh.
  //   * ``inFlightRef`` guards against overlapping polls if the
  //     30 s tick fires while a previous request hasn't returned.
  const etagRef = React.useRef(null);
  const inFlightRef = React.useRef(false);

  const load = React.useCallback(async ({ useEtag = false, signal } = {}) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    if (!useEtag) setLoading(true);
    try {
      const isoDate = isoDateForDayKey(day);  // null for "all"
      const res = await fetchBoardWithEtag({
        day, tech_user_id: techId,
        route_type: routeType, global_view: globalView,
        // Feb-2026 · resolve the weekday tab to a concrete calendar
        // date so the backend can fall back to db.jobs when the
        // customer-denorm path is empty. Null for the "All" tab so
        // legacy behaviour is preserved.
        date: isoDate,
      }, useEtag ? etagRef.current : null, signal);
      if (res.status === 304) {
        // Nothing changed — keep existing board + ETag as-is.
        return;
      }
      etagRef.current = res.etag;
      setBoard(res.data);
      // Reset optimizer state whenever a full (non-poll) load happens.
      if (!useEtag) {
        setPolyline(null);
        setSavings(null);
      }
    } catch (e) {
      if (e?.name === "AbortError") return;
      if (!useEtag) toast.error(`Failed to load dispatch board: ${e.message || e}`);
    } finally {
      if (!useEtag) setLoading(false);
      inFlightRef.current = false;
    }
  }, [day, techId, routeType, globalView]);

  // Fresh load whenever filters change.
  React.useEffect(() => {
    etagRef.current = null;
    setIsolatedTechId(null);
    setFocusedStopId(null);
    load({ useEtag: false });
  }, [load]);

  // Feb-2026 · Phase 4.core — 30 s poll with ETag. Poll cancels on
  // unmount + skips itself while another request is in flight. The
  // interval is intentionally low-frequency (30 s) — the board's
  // primary data (routes, tech load) shifts slowly; live tech pings
  // ride the separate ``useLiveTechPositions`` hook.
  React.useEffect(() => {
    const controller = new AbortController();
    const tick = () => { load({ useEtag: true, signal: controller.signal }); };
    const handle = setInterval(tick, 30_000);
    return () => {
      clearInterval(handle);
      controller.abort();
    };
  }, [load]);

  // Phase 17 · pull active shifts on mount + on reload for the sidebar.
  const loadActiveShifts = React.useCallback(async () => {
    try {
      const res = await api.get("/dispatch/reassign?active=true");
      setActiveShifts(res?.items || []);
    } catch {
      /* non-fatal — sidebar just stays quiet */
    }
  }, []);
  React.useEffect(() => { loadActiveShifts(); }, [loadActiveShifts]);

  // Phase 4 · Feb-2026 — Pull unscheduled jobs for the drag source panel.
  // Refetched after every successful insert.
  const loadUnscheduled = React.useCallback(async () => {
    try {
      const res = await api.get("/dispatch/route/unscheduled-jobs");
      setUnschedJobs(res?.items || []);
    } catch { /* non-fatal — panel just stays empty */ }
  }, []);
  React.useEffect(() => { loadUnscheduled(); }, [loadUnscheduled]);

  // Phase 10 · sub-item E — batch preview-insert for the visible unscheduled
  // panel, keyed by (tech, day). Debounced 300ms; 30s in-memory cache.
  React.useEffect(() => {
    const isoDate = isoDateForDayKey(day);
    if (!techId || !isoDate || day === "all" || unschedJobs.length === 0) {
      if (Object.keys(previewsById).length) setPreviewsById({});
      return;
    }
    const ids = unschedJobs.map((j) => j.id).slice(0, 50);
    const idsHash = ids.join(",");
    const cacheKey = `${techId}|${isoDate}|${idsHash}`;
    const cached = previewCacheRef.current[cacheKey];
    const now = Date.now();
    if (cached && now - cached.at < 30_000) {
      setPreviewsById(cached.previews);
      return;
    }
    let cancelled = false;
    const handle = setTimeout(async () => {
      try {
        const r = await api.post("/dispatch/route/preview-insert-batch", {
          tech_user_id: techId, route_date: isoDate, job_ids: ids,
        });
        if (cancelled) return;
        const map = {};
        for (const p of r.previews || []) map[p.job_id] = p;
        previewCacheRef.current[cacheKey] = { at: Date.now(), previews: map };
        setPreviewsById(map);
      } catch { /* non-fatal */ }
    }, 300);
    return () => { cancelled = true; clearTimeout(handle); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [techId, day, unschedJobs]);

  // Phase 4 · dnd-kit sensors + drop handler wired to /insert.
  const dndSensors = useSensors(useSensor(PointerSensor, {
    activationConstraint: { distance: 5 },
  }));
  const insertJob = React.useCallback(async (jobId, techIdArg, dayKeyArg) => {
    const isoDate = isoDateForDayKey(dayKeyArg);
    if (!techIdArg || !isoDate) {
      toast.error("Pick a specific day + tech before dropping.");
      return;
    }
    try {
      const r = await api.post("/dispatch/route/insert", {
        tech_user_id: techIdArg, route_date: isoDate, job_id: jobId,
      });
      const j = unschedJobs.find((x) => x.id === jobId);
      const title = j?.title || "Job";
      toast.success(
        `Inserted "${title}" at position ${r.inserted_at + 1}/${r.total_stops} · +${(r.added_distance_km || 0).toFixed(1)} km`,
      );
      loadUnscheduled();
      load();
    } catch (e) {
      const detail = e?.body?.detail || e?.message || "Insert failed";
      if (detail === "job_missing_coords") {
        toast.error("Job has no coords — geocode before scheduling.");
      } else if (detail === "job_already_scheduled") {
        toast.error("Job already scheduled.");
        loadUnscheduled();
      } else {
        toast.error(String(detail));
      }
    }
  }, [unschedJobs, loadUnscheduled, load]);
  const onDragEnd = (event) => {
    const { active, over } = event;
    if (!over || !active) return;
    if (over.id !== "route-details-drop") return;
    const activeId = String(active.id || "");
    if (!activeId.startsWith("unsched:")) return;
    const jobId = activeId.slice("unsched:".length);
    insertJob(jobId, techId, day);
  };

  const techColorById = React.useMemo(() => {
    const map = {};
    (board?.tech_load || []).forEach((t) => {
      map[t.tech_user_id] = t.color_hex;
    });
    techs.forEach((t) => {
      if (!map[t.id] && t.display_color_hex) map[t.id] = t.display_color_hex;
    });
    return map;
  }, [board, techs]);

  const activeStops = board?.route_stops || [];

  const onOptimize = async () => {
    if (!techId || day === "all") {
      toast.error("Pick a specific day + tech before optimizing.");
      return;
    }
    if (activeStops.length < 2) {
      toast.error("Need at least 2 geocoded stops to optimize.");
      return;
    }
    setOptimizing(true);
    try {
      const res = await optimizeBoard({
        day, tech_user_id: techId,
        stop_customer_ids: activeStops.map((s) => s.customer_id),
      });
      // Reorder locally without a round-trip.
      const byId = Object.fromEntries(activeStops.map((s) => [s.customer_id, s]));
      const newStops = (res.ordered_customer_ids || [])
        .map((cid) => byId[cid]).filter(Boolean);
      setBoard((prev) => prev ? { ...prev, route_stops: newStops } : prev);
      setPolyline(res.polyline || null);
      setSavings({
        min: res.savings_min, pct: res.savings_pct,
        distance_mi: res.total_distance_mi,
        duration_min: res.total_duration_min,
      });
      toast.success(
        res.savings_min > 0
          ? `Optimized — saves ${res.savings_min} min (${res.savings_pct}%)`
          : `Optimized route (${res.total_distance_mi} mi · ${res.total_duration_min} min)`,
      );
    } catch (e) {
      toast.error(`Optimize failed: ${e.message || e}`);
    } finally {
      setOptimizing(false);
    }
  };

  const onReorder = async (orderedIds) => {
    // Optimistic local update.
    const byId = Object.fromEntries(activeStops.map((s) => [s.customer_id, s]));
    const newStops = orderedIds.map((cid) => byId[cid]).filter(Boolean);
    setBoard((prev) => prev ? { ...prev, route_stops: newStops } : prev);
    setPolyline(null); // route changed — polyline stale
    setSavings(null);
  };

  const onRemoveStop = (cid) => {
    const next = activeStops.filter((s) => s.customer_id !== cid);
    setBoard((prev) => prev ? { ...prev, route_stops: next } : prev);
    setPolyline(null);
    setSavings(null);
  };

  const onSave = async () => {
    if (!techId || day === "all") {
      toast.error("Pick a specific day + tech before saving.");
      return;
    }
    setApplying(true);
    try {
      await applyBoardOrder({
        day, tech_user_id: techId,
        ordered_customer_ids: activeStops.map((s) => s.customer_id),
      });
      toast.success(`Saved route order (${activeStops.length} stops).`);
    } catch (e) {
      toast.error(`Save failed: ${e.message || e}`);
    } finally {
      setApplying(false);
    }
  };

  const pins = React.useMemo(() => board?.pins || [], [board]);
  const techLoad = React.useMemo(() => board?.tech_load || [], [board]);
  const unrouted = React.useMemo(() => board?.unrouted_customers || [], [board]);

  // Feb-2026 · Live-Tech-Map · Phase 4.b — client-side filter chain.
  // The endpoint already tenant-scopes and applies the coarse
  // ``tech_user_id`` + ``route_type`` server-side filters; this
  // layer stacks the additional customer-name filter (from the
  // ``Select Customer`` search box) on top so BOTH the map's pin
  // set AND the new schedule panel react to the same query. Order:
  //   1. ``pins`` already contains the tech/route-type-scoped set.
  //   2. Narrow by customer-name substring, when set.
  // The schedule panel derives its own view-model from
  // ``filteredPins`` so the pill panel + map stay in lockstep.
  const [customerQuery, setCustomerQuery] = React.useState("");
  const filteredPins = React.useMemo(() => {
    if (!customerQuery.trim()) return pins;
    const q = customerQuery.trim().toLowerCase();
    return pins.filter((p) => (p.name || "").toLowerCase().includes(q));
  }, [pins, customerQuery]);

  // Tech-name lookup for the panel + legend labels. Prefers the
  // ``tech_load`` entry (already tenant-scoped, always accurate)
  // and falls back to the ``techs`` directory for anyone who has
  // zero jobs today.
  const techNameById = React.useMemo(() => {
    const acc = {};
    for (const tl of techLoad) {
      if (tl.tech_user_id) acc[tl.tech_user_id] = tl.tech_name || tl.tech_user_id;
    }
    for (const t of techs) {
      if (t.id && !acc[t.id]) acc[t.id] = t.name || t.id;
    }
    return acc;
  }, [techLoad, techs]);

  // Phase 17 · derive banners for shift-in / shift-away when a
  // specific tech is selected.
  const shiftInCount = React.useMemo(() => {
    if (!techId) return 0;
    return pins.filter((p) => p.override_source_tech_id
        && p.assigned_tech_ids?.includes(techId)).length;
  }, [pins, techId]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: memoized deps are stable by value; wrapping the source in its own useMemo would obscure the read
  const shiftAwayCount = React.useMemo(() => {
    if (!techId) return 0;
    return activeShifts.filter((s) => s.source_tech_user_id === techId)
      .reduce((a, s) => a + (s.stop_count || 0), 0);
  }, [activeShifts, techId]);
  const shiftInSourceLabel = React.useMemo(() => {
    if (!techId) return null;
    const shifted = pins.find((p) => p.override_source_tech_id
        && p.assigned_tech_ids?.includes(techId));
    if (!shifted) return null;
    const src = techs.find((t) => t.id === shifted.override_source_tech_id);
    return src?.name || shifted.override_source_tech_id;
  }, [pins, techId, techs]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: memoized deps are stable by value; wrapping the source in its own useMemo would obscure the read

  return (
    // Feb-2026 · scroll-trap prevention convention — <SafeScrollContainer>
    // enforces "no overflow-hidden / no h-screen / no max-h on the outer
    // container + pb-24 bottom breathing room". See
    // ``components/layout/SafeScrollContainer.jsx`` + the
    // ``assertNoScrollTrap`` vitest helper.
    <DndContext sensors={dndSensors} onDragEnd={onDragEnd}>
    <SafeScrollContainer className="px-4 md:px-8 pt-4 space-y-4"
                          data-testid="dispatch-board-page">
      {/* ─────────── Header + Day tabs ─────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
              style={{ color: colors.onSurface }}
              data-testid="dispatch-board-title">
            Dispatch Board
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Route optimization powered by Google Directions.
          </p>
        </div>
        <DispatchSavingsStrip />
        <PendingRouteOptimizations />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { setShiftScope("whole_route"); setSelectedStopIds([]); setShiftDialogOpen(true); }}
            disabled={!techId}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="dispatch-shift-route-btn"
            title={techId ? "Shift the current tech's route to another tech" : "Pick a tech first"}
          >
            <Zap size={14} />
            Shift route
          </button>
          <button
            type="button"
            onClick={() => setGlobalView((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition hover:brightness-95"
            style={{
              backgroundColor: globalView ? colors.brand : colors.surface,
              color: globalView ? "#fff" : colors.onSurface,
              border: `1px solid ${globalView ? colors.brand : colors.border}`,
            }}
            data-testid="dispatch-global-toggle"
            aria-pressed={globalView}
          >
            <Globe size={14} />
            Global map
          </button>
          <button
            type="button"
            onClick={load}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition hover:brightness-95"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="dispatch-refresh"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
            Refresh
          </button>
        </div>
      </div>

      <div
        className="flex flex-wrap gap-1 p-1 rounded-xl"
        style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
        role="tablist"
        aria-label="Day of week"
        data-testid="dispatch-day-tabs"
      >
        {DAYS.map((d) => {
          const active = day === d.key;
          return (
            <button
              key={d.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setDay(d.key)}
              className="flex-1 min-w-[64px] px-3 py-2 rounded-lg text-sm font-semibold transition"
              style={{
                backgroundColor: active ? colors.brand : "transparent",
                color: active ? "#fff" : colors.onSurfaceSecondary,
              }}
              data-testid={`dispatch-day-tab-${d.key}`}
            >
              <CalendarDays size={13} className="inline mr-1 -mt-0.5" />
              {d.label}
            </button>
          );
        })}
        {/* Phase 21 · Feb 2026 · Addition A recovered — Workstream tab
            at the end of the day-tabs strip. Route-push (not a filter
            swap) so back-button behaviour is clean. Visually distinct
            (dashed left divider + outlined variant) to hint the
            route push. */}
        <button
          type="button"
          role="tab"
          onClick={() => navigate("/workstream")}
          className="ml-2 min-w-[112px] px-3 py-2 rounded-lg text-sm font-semibold transition inline-flex items-center gap-1 justify-center"
          style={{
            backgroundColor: "transparent",
            color: colors.brand,
            border: `1.5px dashed ${colors.brand}`,
          }}
          data-testid="dispatch-tab-workstream"
          title="Open the Workstream page (completed jobs)"
        >
          Workstream <ArrowRight size={12} />
        </button>
      </div>

      {/* ─── Pin-color mode selector + legend ─── */}
      <div
        className="flex items-center justify-between flex-wrap gap-2 p-2 rounded-xl"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="dispatch-pin-color-bar"
      >
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide font-semibold"
                style={{ color: colors.muted }}>Color pins by</span>
          <div
            className="flex gap-0.5 p-0.5 rounded-md"
            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
            role="tablist"
            data-testid="dispatch-pin-color-modes"
          >
            {PIN_COLOR_MODES.map((m) => {
              const active = pinColorMode === m.key;
              return (
                <button
                  key={m.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setPinColorModePersistent(m.key)}
                  className="px-2 py-1 rounded text-xs font-semibold transition"
                  style={{
                    backgroundColor: active ? colors.brand : "transparent",
                    color: active ? "#fff" : colors.onSurface,
                  }}
                  data-testid={`dispatch-pin-color-mode-${m.key}`}
                >{m.label}</button>
              );
            })}
          </div>
        </div>
        <ColorLegend mode={pinColorMode} techLoad={techLoad} />
        {/* Phase P2 · Feb-2026 — Show/Hide live technician GPS pins.
            Toggle persists to localStorage (dispatch.showLiveTechs). */}
        <button
          type="button"
          role="switch"
          aria-checked={showLiveTechs}
          onClick={() => setShowLiveTechs((v) => !v)}
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-semibold transition"
          style={{
            backgroundColor: showLiveTechs ? "#DCFCE7" : colors.surface,
            color: showLiveTechs ? "#065F46" : colors.onSurface,
            border: `1px solid ${showLiveTechs ? "#86EFAC" : colors.border}`,
          }}
          data-testid="dispatch-show-live-techs-toggle"
          title="Show live technician GPS pins on the map"
        >
          <span
            aria-hidden="true"
            style={{
              display: "inline-block",
              width: 8, height: 8, borderRadius: 999,
              background: showLiveTechs ? "#10B981" : "#94A3B8",
              boxShadow: showLiveTechs ? "0 0 0 2px rgba(16,185,129,0.25)" : "none",
            }}
          />
          {showLiveTechs ? "Live techs · on" : "Live techs · off"}
          {showLiveTechs && livePositions.length > 0 ? (
            <span
              style={{ marginLeft: 2, fontWeight: 500, opacity: 0.75 }}
              data-testid="dispatch-live-techs-count"
            >
              ({livePositions.length})
            </span>
          ) : null}
        </button>
      </div>

      {/* ─────────── 3-column grid: left filters / map / right sidebar ─────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left column ── filters + select customer panel */}
        <aside className="lg:col-span-3 space-y-3" data-testid="dispatch-left-col">
          <div
            className="rounded-xl p-3 space-y-3"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          >
            <div>
              <label
                className="text-xs uppercase tracking-wide font-semibold"
                style={{ color: colors.muted }}
              >
                Tech
              </label>
              <div className="relative mt-1">
                <select
                  value={techId || ""}
                  onChange={(e) => setTechId(e.target.value || null)}
                  className="w-full appearance-none rounded-lg px-3 py-2 pr-8 text-sm font-semibold focus:outline-none"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="dispatch-tech-select"
                >
                  <option value="">All techs</option>
                  {techs.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-2 top-1/2 -translate-y-1/2"
                  style={{ color: colors.muted, pointerEvents: "none" }}
                />
              </div>
            </div>

            <div>
              <label
                className="text-xs uppercase tracking-wide font-semibold"
                style={{ color: colors.muted }}
              >
                Route type
              </label>
              <div className="flex flex-wrap gap-1.5 mt-1"
                   data-testid="dispatch-route-type-chips">
                {ROUTE_TYPE_OPTIONS.map((r) => {
                  const active = routeType === r.key;
                  return (
                    <button
                      key={r.key}
                      type="button"
                      onClick={() => setRouteType(r.key)}
                      className="px-2.5 py-1 rounded-full text-xs font-semibold transition hover:brightness-95"
                      style={{
                        backgroundColor: active ? colors.brand : colors.surfaceSecondary,
                        color: active ? "#fff" : colors.onSurface,
                        border: `1px solid ${active ? colors.brand : colors.border}`,
                      }}
                      data-testid={`dispatch-route-type-${r.key}`}
                      aria-pressed={active}
                    >
                      {r.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <SelectCustomerPanel
            pins={filteredPins}
            selectedCustomerId={selectedCustomerId}
            onSelect={setSelectedCustomerId}
            query={customerQuery}
            onQueryChange={setCustomerQuery}
          />

          {/* Feb-2026 · Live-Tech-Map · Phase 4.a — schedule panel.
              Below existing filters + customer picker; groups the
              day's scheduled stops by tech/crew/service_day
              matching the active ``pinColorMode``. Q4: clicking a
              row focuses the map on that stop. */}
          <DispatchSchedulePanel
            pins={filteredPins}
            pinColorMode={pinColorMode}
            techColorById={techColorById}
            techNameById={techNameById}
            dayLabel={DAYS.find((d) => d.key === day)?.label || day}
            focusedStopId={focusedStopId}
            isolatedTechId={isolatedTechId}
            onFocusStop={(p) => {
              setFocusedStopId(p.customer_id);
              setSelectedCustomerId(p.customer_id);
            }}
          />
        </aside>

        {/* Center ── Map */}
        <section className="lg:col-span-6 space-y-3" data-testid="dispatch-center-col">
          {shiftInCount > 0 && shiftInSourceLabel ? (
            <div
              className="px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-2"
              style={{ backgroundColor: "#EFF6FF", color: "#1E3A8A", border: "1px solid #BFDBFE" }}
              data-testid="dispatch-shift-in-banner"
            >
              <Users size={12} />
              {shiftInCount} stop(s) shifted here from {shiftInSourceLabel} until Sat 11:59 PM.
            </div>
          ) : null}
          {shiftAwayCount > 0 ? (
            <div
              className="px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-2"
              style={{ backgroundColor: "#FEF3C7", color: "#92400E", border: "1px solid #FDE68A" }}
              data-testid="dispatch-shift-away-banner"
            >
              <Users size={12} />
              {shiftAwayCount} stop(s) shifted away this week.
            </div>
          ) : null}
          {savings ? (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold"
              style={{
                backgroundColor: "#ECFDF5",
                color: "#065F46",
                border: "1px solid #A7F3D0",
              }}
              data-testid="dispatch-savings-banner"
            >
              <Sparkles size={14} />
              {savings.min > 0
                ? `Optimized route saves ${savings.min} min (${savings.pct}%)`
                : `Optimized route`}
              <span style={{ color: "#047857", fontWeight: 500 }}>
                · {savings.distance_mi} mi · {savings.duration_min} min total
              </span>
            </div>
          ) : null}
          <DispatchMapView
            pins={filteredPins}
            unroutedPins={(unrouted || []).filter((u) => u.lat != null && u.lng != null)}
            polyline={polyline}
            techColorById={techColorById}
            techNameById={techNameById}
            activeCustomerId={selectedCustomerId}
            onSelectCustomer={setSelectedCustomerId}
            pinColorMode={pinColorMode}
            liveTechPositions={showLiveTechs ? livePositions : []}
            isolatedTechId={isolatedTechId}
            onIsolateTech={setIsolatedTechId}
            focusedStopId={focusedStopId}
          />
        </section>

        {/* Right column ── Tech load + Route Details */}
        <aside className="lg:col-span-3 space-y-3" data-testid="dispatch-right-col">
          <div
            className="rounded-xl p-3"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          >
            <div className="flex items-center justify-between mb-2">
              <div
                className="text-xs uppercase tracking-wide font-semibold flex items-center gap-1"
                style={{ color: colors.muted }}
              >
                <Users size={12} /> Tech load
              </div>
              <span
                className="text-xs font-semibold px-1.5 py-0.5 rounded-full"
                style={{
                  backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                }}
                data-testid="dispatch-tech-load-total"
              >
                {techLoad.reduce((a, t) => a + (t.count || 0), 0)} pins
              </span>
            </div>
            <TechLoadStrip
              loads={techLoad}
              selectedTechId={isolatedTechId || techId}
              onSelect={(id) => {
                // Feb-2026 · Phase 4.core — clicking a Tech Load row
                // isolates that tech on the map + schedule panel
                // (dim all others) rather than reloading the board
                // under a hard filter. Users can still hard-filter
                // via the Tech dropdown at the top; isolate is a
                // client-side dim that leaves the fetched data set
                // intact.
                setIsolatedTechId((prev) => prev === id ? null : id);
              }}
            />
          </div>

          <RouteDetailsDropZone techId={techId} day={day}
                                  unschedCount={unschedJobs.length}>
          <div
            className="rounded-xl p-3 space-y-3"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          >
            <div className="flex items-center justify-between">
              <div
                className="text-xs uppercase tracking-wide font-semibold flex items-center gap-1"
                style={{ color: colors.muted }}
              >
                <MapPin size={12} /> Route details
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={onOptimize}
                  disabled={optimizing || activeStops.length < 2 || !techId || day === "all"}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: colors.brand,
                    color: "#fff",
                  }}
                  data-testid="dispatch-optimize-btn"
                >
                  {optimizing ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                  Optimize
                </button>
                <button
                  type="button"
                  onClick={() => setNnModalOpen(true)}
                  disabled={!techId || day === "all"}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="dispatch-nn-optimize-btn"
                  title="Nearest-neighbor preview + apply route_index"
                >
                  <Sparkles size={12} />
                  NN Optimize
                </button>
                <button
                  type="button"
                  onClick={onSave}
                  disabled={applying || activeStops.length === 0 || !techId || day === "all"}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="dispatch-save-order-btn"
                >
                  {applying ? <Loader2 size={12} className="animate-spin" /> : <PlusCircle size={12} />}
                  Save
                </button>
              </div>
            </div>
            <RouteDetailsList
              stops={activeStops}
              onReorder={onReorder}
              onRemove={onRemoveStop}
              onSelect={setSelectedCustomerId}
              activeCustomerId={selectedCustomerId}
            />
            {!techId || day === "all" ? (
              <div
                className="text-[11px] leading-relaxed rounded-md p-2"
                style={{
                  backgroundColor: "#FEF3C7",
                  color: "#92400E",
                  border: "1px solid #FDE68A",
                }}
                data-testid="dispatch-route-details-hint"
              >
                Pick a specific day + tech to unlock route optimization + save.
              </div>
            ) : null}
          </div>
          </RouteDetailsDropZone>

          <UnscheduledJobsPanel
            jobs={unschedJobs}
            onAssignClick={(job) => setAssignModalJob(job)}
            previewsById={previewsById}
          />

          <ActiveShiftsSidebar
            items={activeShifts}
            onRefresh={() => { loadActiveShifts(); load(); }}
          />

          <UnroutedPanel
            items={unrouted}
            onSelect={setSelectedCustomerId}
            onApply={({ customer_id, suggestion }) => {
              // v1: fold the suggestion into the current view by
              // reloading with the suggestion's tech + day. Full
              // assignment persistence is left to a follow-up
              // (the existing add-to-route flow lives in Ops → Schedule).
              if (suggestion) {
                setDay(suggestion.service_day);
                setTechId(suggestion.tech_user_id);
                toast.success(
                  `Switched view to ${suggestion.tech_name}'s ${suggestion.day_label} — add ${customer_id} in Schedule.`,
                );
              } else {
                toast.info(`Open Customer ${customer_id} in Schedule to assign.`);
              }
            }}
          />
        </aside>
      </div>

      <ShiftRouteDialog
        open={shiftDialogOpen}
        onClose={() => setShiftDialogOpen(false)}
        sourceTech={techs.find((t) => t.id === techId) || null}
        techs={techs}
        customerIds={selectedStopIds}
        scope={shiftScope}
        day={day}
        onSuccess={() => { loadActiveShifts(); load(); }}
      />

      <OptimizeRouteModal
        open={nnModalOpen}
        onClose={() => setNnModalOpen(false)}
        onApplied={() => { load(); }}
        techUserId={techId}
        techName={techs.find((t) => t.id === techId)?.name || techId}
        day={isoDateForDayKey(day)}
      />

      <AssignJobModal
        open={!!assignModalJob}
        onClose={() => setAssignModalJob(null)}
        onAssigned={() => { loadUnscheduled(); load(); }}
        job={assignModalJob}
        techs={techs}
        defaultTechId={techId}
        defaultDayKey={day === "all" ? "mon" : day}
      />
    </SafeScrollContainer>
    </DndContext>
  );
}

// ─── Color legend ────────────────────────────────────────────
function ColorLegend({ mode, techLoad = [] }) {
  if (mode === "tech") {
    if (!techLoad.length) return null;
    return (
      <div className="flex items-center gap-2 text-xs flex-wrap"
           data-testid="dispatch-color-legend-tech">
        {techLoad.slice(0, 5).map((t) => (
          <span key={t.tech_user_id} className="flex items-center gap-1"
                style={{ color: colors.onSurface }}>
            <span
              aria-hidden
              style={{
                width: 10, height: 10, borderRadius: 999,
                backgroundColor: t.color_hex,
                border: "1px solid #fff",
                boxShadow: "0 0 0 1px rgba(0,0,0,0.1)",
              }}
            />
            {t.name}
          </span>
        ))}
      </div>
    );
  }
  if (mode === "crew") {
    return (
      <div className="flex items-center gap-2 text-xs flex-wrap"
           data-testid="dispatch-color-legend-crew">
        {CREW_LEGEND.map((c) => (
          <span key={c.label} className="flex items-center gap-1"
                style={{ color: colors.onSurface }}>
            <span aria-hidden style={{
              width: 10, height: 10, borderRadius: 999,
              backgroundColor: c.color, border: "1px solid #fff",
              boxShadow: "0 0 0 1px rgba(0,0,0,0.1)",
            }} />
            {c.label}
          </span>
        ))}
      </div>
    );
  }
  // service_day
  return (
    <div className="flex items-center gap-2 text-xs flex-wrap"
         data-testid="dispatch-color-legend-day">
      {Object.entries(PIN_COLOR_BY_DAY).map(([d, hex]) => (
        <span key={d} className="flex items-center gap-1"
              style={{ color: colors.onSurface, textTransform: "capitalize" }}>
          <span aria-hidden style={{
            width: 10, height: 10, borderRadius: 999,
            backgroundColor: hex, border: "1px solid #fff",
            boxShadow: "0 0 0 1px rgba(0,0,0,0.1)",
          }} />
          {d}
        </span>
      ))}
    </div>
  );
}

// ─── Side panel ────────────────────────────────────────────────
function SelectCustomerPanel({ pins, selectedCustomerId, onSelect, query, onQueryChange }) {
  const _q = (query || "").trim().toLowerCase();
  const filtered = React.useMemo(() => {
    const rows = _q
      ? pins.filter((p) => (p.name || "").toLowerCase().includes(_q)
          || formatAddress(p.address).toLowerCase().includes(_q))
      : pins;
    return rows.slice(0, 40);
  }, [pins, _q]);

  return (
    <div
      className="rounded-xl p-3"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="dispatch-select-customer-panel"
    >
      <div
        className="text-xs uppercase tracking-wide font-semibold mb-1"
        style={{ color: colors.muted }}
      >
        Select customer
      </div>
      <input
        type="search"
        value={query || ""}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder="Search name or address…"
        className="w-full rounded-lg px-2.5 py-1.5 text-sm mb-2 focus:outline-none"
        style={{
          backgroundColor: colors.surfaceSecondary,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="dispatch-select-customer-search"
      />
      <div
        className="text-[11px] mb-1"
        style={{ color: colors.muted }}
        data-testid="dispatch-select-customer-count"
      >
        {filtered.length} of {pins.length}
      </div>
      <ul className="space-y-1 max-h-72 overflow-y-auto"
          data-testid="dispatch-select-customer-list">
        {filtered.map((p) => {
          const active = p.customer_id === selectedCustomerId;
          return (
            <li key={p.customer_id}>
              <button
                type="button"
                onClick={() => onSelect(active ? null : p.customer_id)}
                className="w-full text-left px-2 py-1.5 rounded-md text-xs transition hover:brightness-95"
                style={{
                  backgroundColor: active ? colors.brandTertiary : "transparent",
                  color: active ? colors.onBrandTertiary : colors.onSurface,
                  border: `1px solid ${active ? colors.brand : "transparent"}`,
                }}
                data-testid={`dispatch-select-customer-${p.customer_id}`}
              >
                <div className="font-semibold truncate">{p.name || "(unnamed)"}</div>
                <div className="text-[11px] truncate" style={{ color: colors.muted }}>
                  {formatAddress(p.address) || "No address"}
                </div>
              </button>
            </li>
          );
        })}
        {filtered.length === 0 && (
          <li
            className="text-[11px] italic px-2 py-2"
            style={{ color: colors.muted }}
            data-testid="dispatch-select-customer-empty"
          >
            No matches.
          </li>
        )}
      </ul>
    </div>
  );
}


// Phase 4 · Feb-2026 — Droppable wrapper around the Route Details panel.
// Highlights when a job is dragged over. When no tech + day is picked
// yet, we still register the drop zone (the parent's onDragEnd shows a
// toast telling the dispatcher to pick a filter first).
function RouteDetailsDropZone({ techId, day, unschedCount, children }) {
  const { isOver, setNodeRef } = useDroppable({ id: "route-details-drop" });
  const armed = !!techId && day !== "all";
  const showHint = isOver && unschedCount > 0;
  return (
    <div
      ref={setNodeRef}
      data-testid="dispatch-route-drop-zone"
      style={{
        borderRadius: 14,
        outline: isOver
          ? `3px dashed ${armed ? "#0284C7" : "#F97316"}`
          : "3px dashed transparent",
        outlineOffset: 4,
        transition: "outline-color 120ms ease",
        position: "relative",
      }}
    >
      {showHint ? (
        <div
          data-testid="dispatch-route-drop-hint"
          style={{
            position: "absolute", top: -14, right: 8, zIndex: 10,
            padding: "3px 10px", borderRadius: 999,
            fontSize: 11, fontWeight: 700,
            background: armed ? "#0284C7" : "#F97316",
            color: "#FFFFFF",
            boxShadow: "0 2px 8px rgba(15,23,42,0.24)",
          }}
        >
          {armed
            ? `Drop to auto-insert · ${unschedCount} unscheduled`
            : "Pick a tech + day first"}
        </div>
      ) : null}
      {children}
    </div>
  );
}
