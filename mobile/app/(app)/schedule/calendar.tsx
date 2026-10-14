/**
 * Phase 30 · Calendar Schedule (Expo mobile) — fix pass.
 *
 * Top-level mode is now a binary toggle: `[Calendar] [Grid]`. Default = Grid
 * (persists in AsyncStorage). Layout matches the two reference screenshots
 * the user provided.
 *
 *   Grid view (default)
 *     • Day header with < prev / today / next > controls
 *     • Bulk-action pill row: Complete · Move · Rearrange (all Jobs.write gated)
 *     • Stacked cards per job with a circular checkbox, service-type tag,
 *       customer + address, notepad+billable-hours row, status pill.
 *
 *   Calendar view
 *     • Multi-day columns (Mon–Sun sticky headers) with events stacked in
 *       each column. Colour-coded by service type. Recurring jobs get 🔁.
 *     • `BH 👁` toggle to hide/show billable hours on cards.
 *
 * Endpoints used (all pre-existing):
 *   GET  /api/jobs?start=&end=            (Phase 30 range filter)
 *   PUT  /api/jobs/{id}   {status,scheduled_date}   (mark complete / move)
 *   POST /api/jobs/reorder  {job_ids:[…]}           (admin rearrange)
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Platform, Linking,
  ActivityIndicator, Alert, Modal, FlatList } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter, Redirect } from "expo-router";

import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { storage } from "@/src/utils/storage";
import { logNav } from "@/src/utils/diagnostics";
import { ScheduleErrorBoundary } from "@/src/components/ScheduleErrorBoundary";
import { isStrictAdmin } from "@/src/components/RoleGate";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header, NotificationBell } from "@/src/components/widgets";
// Feb-2026 · Phase 1 offline foundation — write-through cache on
// successful load + read-fallback + header-level "Offline" pill.
import { cachedGet, writeThroughJobs, readCachedWeekJobs } from "@/src/lib/offline/apiCache";
import OfflineBadge from "@/src/components/OfflineBadge";
// Phase 2 · Sync badge — global "⤴ X items waiting" in schedule header.
import SyncBadge from "@/src/components/SyncBadge";
// Phase 2 · Per-job pending sync indicator.
import PendingSyncPill from "@/src/components/PendingSyncPill";
import { usePendingEntityIds } from "@/src/hooks/usePendingOps";
// Phase 1 Offline Read — route hydrator + cache status.
import { useRouteHydration } from "@/src/hooks/useRouteHydration";
import { useOnline } from "@/src/lib/offline/netStatus";
import { useCachedJobIds } from "@/src/hooks/useCachedJobIds";
import LandscapingClockWidget from "@/src/components/LandscapingClockWidget";
import WeatherWidget from "@/src/components/weather/WeatherWidget";
import RainFlag from "@/src/components/weather/RainFlag";
import WeekStrip from "@/src/components/schedule/WeekStrip";
import { showConfirm } from "@/src/components/ConfirmModal";
import { useToast } from "@/src/components/ToastProvider";
// Phase 23 · 2026-08-02 — Service / Repair progress ring tiles above the grid.
import JobTrackerTiles from "./JobTrackerTiles";
import ScheduleJobEditSheet from "@/src/components/schedule/ScheduleJobEditSheet";
// Phase K50 · Feb-2026 — Schedule job-card status background shading.
// Web mirror: ``frontend/src/lib/jobStatus.js``.
import { jobStatusColor as k50JobStatusColor, isBoldRedStatus, K50_ON_BOLD_RED_FG } from "@/src/lib/jobStatus";
import NavigateMapsButton from "@/src/components/schedule/NavigateMapsButton";
// Phase B mobile parity (web 2f14a7ea5 + e5d6fa01e) — Optimize Route modal.
import OptimizeRouteModal from "@/src/components/schedule/OptimizeRouteModal";
// Phase 27 · Feb-2026 — Global avatar swap for the per-job card in
// the schedule grid. Compact 20dp footprint keeps row height
// invariant vs the pre-Phase-27 layout.
// Feb-2026 · Schedule polish — the per-card <TechAvatar> was
// removed from the mobile JobRow; keeping the import out avoids
// an unused-symbol lint. The component still ships and is used
// by other surfaces (portal, dispatch, service detail).
import { getStatusBorderColor } from "@/src/utils/scheduleStatus";
import OnMyWayButton from "@/src/components/schedule/OnMyWayButton";
import CouldNotServiceButton from "@/src/components/schedule/CouldNotServiceButton";
import NavigateRouteButton from "@/src/components/schedule/NavigateRouteButton";
import { openNativeNavTo, resolveJobCoords } from "@/src/utils/nativeNav";
import CrewFilterBar from "@/src/components/schedule/CrewFilterBar";
// K36 · Schedule map is now lazy-mounted — react-native-maps only
// registers its native module when the tech toggles to the Map sub-view,
// preventing missing-Google-Maps-key crashes on Schedule tab open.
import ScheduleMapLazy from "@/src/components/schedule/ScheduleMapLazy";
// Feb-2026 — Daily Route Map (@rnmapbox/maps). Collapsible per-tech
// header, numbered pins by route_index, status-colored, tap for
// callout with Open→job checklist. Hides itself when 0 jobs.
import DailyRouteMap from "@/src/components/schedule/DailyRouteMap";
import { MapErrorBoundary } from "@/src/components/MapErrorBoundary";
// Feb-2026 · Schedule polish — amber-accented job-notes chip.
import JobNotesCallout from "@/src/components/schedule/JobNotesCallout";
import DraggableFlatList, { RenderItemParams, ScaleDecorator } from "react-native-draggable-flatlist";
import type { HourlyEntry } from "@/src/api/weather";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import AppTextInput from "@/src/components/ui/AppTextInput";
// P37c · GPS consent modal — mounted for techs, self-checks consent on focus.
import GpsConsentModal from "@/src/components/gps/GpsConsentModal";
import { AddressLink } from "@/src/components/customer";
import { resolveTechnicianId } from "@/lib/technicianResolver";
// P2 #9 · day-view timestamp filter — mirrors web P13 day bucketing.
import { jobDayKey, localDateKey } from "@/src/utils/scheduleDayKey";
import { tenantTz } from "@/src/utils/tenantTime";

type Job = {
  id: string;
  scheduled_date?: string | null;
  /** Full ISO datetime; P13 fallback day key when scheduled_date is empty. */
  scheduled_start?: string | null;
  scheduled_time?: string | null;
  service_type?: string;
  status?: string;
  customer_name?: string;
  address?: string;
  property_id?: string | null;
  property_label?: string | null;
  property_address?: string | null;
  technician_id?: string | null;
  estimated_hours?: number | null;
  actual_hours?: number | null;
  billable_hours?: number | null;
  duration_minutes?: number | null;
  route_order?: number | null;
  route_index?: number | null;
  location_lat?: number | null;
  location_lng?: number | null;
  is_recurring?: boolean;
  recurring?: boolean;
  recurrence?: string | null;
  title?: string;
  notes?: string | null;
  notes_truncated?: boolean;
};

type Mode = "grid" | "calendar";
const MODE_KEY = "aq-schedule-mode-v1";
const MAP_VISIBLE_KEY = "schedule.mapVisible";
const TECH_FILTER_KEY = "schedule.tech_filter";

// P2 #9 · device-local calendar key (was ``d.toISOString().slice(0, 10)`` —
// the UTC date, which put US devices on tomorrow after ~8 pm and east-of-UTC
// devices on yesterday after every strip tap). All 11 call sites route here.
const iso = (d: Date) => localDateKey(d);
const addDays = (d: Date, n: number) => { const c = new Date(d); c.setDate(c.getDate() + n); return c; };
const dayLabel = (d: Date) =>
  d.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "short", day: "numeric" });

// Status pill palette. "Closed" (=completed) is green; open/scheduled is amber.
const STATUS_PILL: Record<string, { bg: string; fg: string; label: string }> = {
  completed:  { bg: "#DCFCE7", fg: "#166534", label: "Closed" },
  active:     { bg: "#DBEAFE", fg: "#1E40AF", label: "In progress" },
  scheduled:  { bg: "#FEF3C7", fg: "#92400E", label: "Open" },
  pending:    { bg: "#FEF3C7", fg: "#92400E", label: "Pending" },
  requested:  { bg: "#EDE9FE", fg: "#5B21B6", label: "Requested" },
  reopened:   { bg: "#FEE2E2", fg: "#991B1B", label: "Reopened" },
  cancelled:  { bg: "#F3F4F6", fg: "#4B5563", label: "Cancelled" },
  on_hold:    { bg: "#FFEDD5", fg: "#9A3412", label: "On hold" },
  // Feb-2026 · Phase 1 — "Could Not Service" outcome. Amber tone
  // deliberately deeper than ``scheduled``/``pending`` so the pill is
  // visually distinct from a plain "Open" job on the same card.
  could_not_service: { bg: "#FDE68A", fg: "#78350F", label: "Could Not Service" },
  skipped:    { bg: "#E5E7EB", fg: "#374151", label: "Skipped" },
};

// Service-type → column card colour. Distinct hues for the Calendar view;
// unknown types fall back to a neutral surface.
const SERVICE_COLOR = (raw?: string): { bg: string; fg: string; tag: string } => {
  const s = (raw || "").toLowerCase();
  if (s.includes("weekly") && s.includes("landsc")) return { bg: "#DCFCE7", fg: "#166534", tag: "#059669" };
  if (s.includes("monthly") && s.includes("landsc")) return { bg: "#E0E7FF", fg: "#3730A3", tag: "#4F46E5" };
  if (s.includes("irrig")) return { bg: "#DBEAFE", fg: "#1E3A8A", tag: "#2563EB" };
  if (s.includes("rock")) return { bg: "#FEF3C7", fg: "#78350F", tag: "#B45309" };
  if (s.includes("pool") || s.includes("chem")) return { bg: "#CFFAFE", fg: "#155E75", tag: "#0891B2" };
  if (s.includes("clean")) return { bg: "#FCE7F3", fg: "#831843", tag: "#BE185D" };
  return { bg: "#F3F4F6", fg: "#111827", tag: "#6B7280" };
};

const jobHours = (j: Job): string => {
  const h = j.actual_hours ?? j.billable_hours ?? j.estimated_hours ?? 0;
  return `${(Number(h) || 0).toFixed(2)} BH`;
};
const isRecurring = (j: Job): boolean =>
  Boolean(j.is_recurring || j.recurring || (j.recurrence && j.recurrence !== "none"));

/** K36 · 20-second loading watchdog. If the initial load has not
 *  produced jobs or an error card within this window, we swap the
 *  spinner for an actionable fallback UI instead of leaving the tech
 *  staring at "Loading…" forever (which is exactly what the iOS
 *  watchdog kills at ~20 s). */
const LOADING_WATCHDOG_MS = 20_000;

function ScheduleCalendarInner() {
  const { showToast } = useToast();
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin" || role === "manager";
  const isTech = role === "technician" || role === "tech";
  const canWriteJobs = isAdmin || isTech;

  // Phase 1 Offline Read — trigger hydration + get cache stats.
  const { meta: hydrationMeta, triggerHydrate } = useRouteHydration();
  const online = useOnline();
  const [syncingRoute, setSyncingRoute] = useState(false);
  const [syncToast, setSyncToast] = useState<string | null>(null);
  const syncToastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [mode, setMode] = useState<Mode>("grid");
  const [modeLoaded, setModeLoaded] = useState(false);
  const [focus, setFocus] = useState(new Date());                // Grid: single day; Calendar: anchors the week
  const [jobs, setJobs] = useState<Job[]>([]);
  // Feb-2026 · Schedule inline-edit sheet state. In-place mutate on
  // save / delete so cards refresh without a full ``load()`` cycle.
  const [editingJob, setEditingJob] = useState<Job | null>(null);
  const patchJobInPlace = useCallback((patched: Partial<Job> & { id: string }) => {
    setJobs((prev) => prev.map((r) => (r.id === patched.id ? { ...r, ...patched } : r)));
  }, []);
  const removeJobInPlace = useCallback((jid: string) => {
    setJobs((prev) => prev.filter((r) => r.id !== jid));
  }, []);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [showBH, setShowBH] = useState(true);
  const [rearrangeMode, setRearrangeMode] = useState(false);
  const [gridSubMode, setGridSubMode] = useState<"list" | "map">("list");
  const [moveOpen, setMoveOpen] = useState(false);
  const [optimizeOpen, setOptimizeOpen] = useState(false);
  const [moveDate, setMoveDate] = useState("");
  const [reassignOpen, setReassignOpen] = useState(false);
  const [techs, setTechs] = useState<{ id: string; name: string }[]>([]);
  const [reassignTechId, setReassignTechId] = useState("");
  const [hourlyData, setHourlyData] = useState<HourlyEntry[]>([]);
  // K36 · loading watchdog — flips true when the initial load has
  // been in-flight for > LOADING_WATCHDOG_MS without producing an
  // error card. Consumed by the render path to swap the spinner for
  // a "Still loading — retry?" fallback.
  const [loadingTimedOut, setLoadingTimedOut] = useState(false);

  // ── Sync route handler ──────────────────────────────────────────────
  const handleSyncRoute = useCallback(async () => {
    if (syncingRoute || !online) return;
    setSyncingRoute(true);
    setSyncToast(null);
    try {
      // Call triggerHydrate and wait for the subscription to report completion.
      triggerHydrate();
      // Give hydration time to start + finish. The subscription updates
      // hydrationMeta reactively, but we need a concrete wait.
      // Poll hydrationMetaRef until inProgress===false (after it was true).
      let sawInProgress = false;
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 500));
        const m = hydrationMetaRef.current;
        if (m?.inProgress) sawInProgress = true;
        if (sawInProgress && !m?.inProgress) break;
        // If never saw inProgress (hydration completed instantly), break after 2s
        if (!sawInProgress && i >= 4) break;
      }
      const finalMeta = hydrationMetaRef.current;
      const cached = finalMeta?.cachedJobs ?? 0;
      if (syncToastTimer.current) clearTimeout(syncToastTimer.current);
      setSyncToast(`Route cached — ${cached} job${cached !== 1 ? "s" : ""} offline-ready`);
      syncToastTimer.current = setTimeout(() => setSyncToast(null), 3500);
    } catch {
      if (syncToastTimer.current) clearTimeout(syncToastTimer.current);
      setSyncToast("Sync failed — try again");
      syncToastTimer.current = setTimeout(() => setSyncToast(null), 3500);
    } finally {
      setSyncingRoute(false);
    }
  }, [syncingRoute, online, triggerHydrate]);

  // Ref to track latest hydrationMeta without re-rendering the callback
  const hydrationMetaRef = useRef(hydrationMeta);
  useEffect(() => { hydrationMetaRef.current = hydrationMeta; }, [hydrationMeta]);

  // Phase F6b — Crew filter state. Selecting a crew passes crew_id to
  // the schedule fetch; clearing resets to "All crews".
  // K25 — persisted to survive navigation (but defaults to "All" on cold start).
  const CREW_FILTER_KEY = "k25_schedule_crew_filter";
  const [crews, setCrews] = useState<any[]>([]);
  const [crewFilter, setCrewFilter] = useState("");
  const [crewMembers, setCrewMembers] = useState<string[]>([]);
  const [allTechs, setAllTechs] = useState<any[]>([]);

  // Phase S1 — Per-tech schedule filter (admin dropdown, tech auto-scope).
  // P9-C: techs initialize to own technician_id, never "all".
  const [techFilter, setTechFilter] = useState<string>(
    isTech ? (user?.technician_id || "all") : "all",
  );
  const [techPickerOpen, setTechPickerOpen] = useState(false);

  // K43 — Resolved technician_id: when user.technician_id is null
  // (pre-backfill tenant), we resolve it via GET /api/technicians/me.
  // null = genuinely not in roster; undefined = still resolving.
  const [resolvedTechId, setResolvedTechId] = useState<string | null | undefined>(
    user?.technician_id || undefined,
  );
  useEffect(() => {
    if (!isTech) { setResolvedTechId(undefined); return; }
    let alive = true;
    resolveTechnicianId(user).then((tid) => {
      if (alive) setResolvedTechId(tid);
    });
    return () => { alive = false; };
  }, [user?.id, user?.technician_id, isTech]);

  // Phase P17 — OOM fix: cache the last-fetched date range so day-tap
  // navigation inside the already-loaded window skips the network.
  // Margin = 3 days → only re-fetch when the user navigates close to
  // the edge of the cached range.
  const fetchedRangeRef = useRef<{ start: string; end: string } | null>(null);

  // Load persisted mode.
  useEffect(() => {
    (async () => {
      try {
        const saved = await storage.getItem<string>(MODE_KEY, "grid");
        if (saved === "grid" || saved === "calendar") setMode(saved);
      } finally { setModeLoaded(true); }
    })();
  }, []);

  // Phase F6b — Fetch crews + all techs on mount for crew filter.
  // K25 — hydrate persisted crew filter from storage.
  // K36 — Array.isArray guards on every response so an unexpected
  // shape (backend returns {detail: "..."} for a 200 with a message,
  // or a proxy HTML page) can't render-throw further down.
  useEffect(() => {
    api.get("/crews")
      .then((res: any) => setCrews(Array.isArray(res) ? res : Array.isArray(res?.items) ? res.items : []))
      .catch((e) => { console.warn("[schedule] /crews failed:", e?.message || e); setCrews([]); });
    api.get("/technicians")
      .then((res: any) => setAllTechs(Array.isArray(res) ? res : Array.isArray(res?.technicians) ? res.technicians : []))
      .catch((e) => { console.warn("[schedule] /technicians failed:", e?.message || e); setAllTechs([]); });
    // K25 — load persisted crew filter.
    storage.getItem<string>(CREW_FILTER_KEY, "").then((v: any) => {
      if (typeof v === "string" && v.length > 0) setCrewFilter(v);
    }).catch(() => {});
  }, []);

  // Phase S1 — Load persisted tech filter on mount.
  useEffect(() => {
    const uid = user?.id || "";
    if (!uid) { return; }
    const key = `${TECH_FILTER_KEY}.${uid}`;
    storage.getItem<string>(key, "").then((v: any) => {
      if (typeof v === "string" && v.length > 0) {
        setTechFilter(v);
      } else {
        // K43 — use resolvedTechId (handles pre-backfill tenants).
        setTechFilter(isTech ? (resolvedTechId || "all") : "all");
      }
    }).catch(() => {
      setTechFilter(isTech ? (resolvedTechId || "all") : "all");
    });
  }, [user?.id, resolvedTechId, isTech]);

  const setModePersist = (m: Mode) => {
    setMode(m);
    storage.setItem(MODE_KEY, m).catch(() => {/* incognito — in-memory only */});
  };

  // Phase F6b — Handle crew selection. Resolves member names from
  // crew.members or allTechs lookup. K25 — persists to AsyncStorage.
  const handleCrewSelect = useCallback((crewId: string) => {
    setCrewFilter(crewId);
    storage.setItem(CREW_FILTER_KEY, crewId).catch(() => {});
    if (!crewId) { setCrewMembers([]); return; }
    const crew = crews.find((c: any) => c.id === crewId);
    if (!crew) { setCrewMembers([]); return; }
    if (crew.members?.length) {
      setCrewMembers(crew.members.map((m: any) => m.name || m.full_name || ""));
    } else if (crew.tech_ids?.length && allTechs.length) {
      const names = crew.tech_ids
        .map((tid: string) => allTechs.find((t: any) => t.id === tid)?.name)
        .filter(Boolean) as string[];
      setCrewMembers(names);
    } else { setCrewMembers([]); }
  }, [crews, allTechs]);

  // Phase S1 — Tech filter helpers.
  const handleTechFilterChange = useCallback((val: string) => {
    setTechFilter(val);
    const uid = user?.id || "";
    if (uid) storage.setItem(`${TECH_FILTER_KEY}.${uid}`, val).catch(() => {});
  }, [user?.id]);

  const sortedTechs = useMemo(
    () => [...allTechs].sort((a: any, b: any) => (a.name || "").localeCompare(b.name || "")),
    [allTechs],
  );

  // Phase S1 — Client-side tech filter. "all" shows everything; a
  // specific tech_id keeps that tech's jobs + unassigned jobs.
  // P9-C: defense-in-depth — techs always scoped to own jobs, even if
  // "all" leaks into state (fail closed).
  const filteredJobs = useMemo(() => {
    if (isTech) {
      const tid = techFilter !== "all" ? techFilter : resolvedTechId;
      if (!tid) return []; // fail closed: no id → empty
      return jobs.filter((j) => j.technician_id === tid || !j.technician_id);
    }
    if (techFilter === "all") return jobs;
    return jobs.filter((j) => j.technician_id === techFilter || !j.technician_id);
  }, [jobs, techFilter, isTech, resolvedTechId]);

  // INACTIVE-CUSTOMER-CASCADE — hide cancelled/skipped by default.
  // Persisted under `schedule_show_cancelled` (matches web key).
  const [showCancelled, setShowCancelled] = useState(false);
  useEffect(() => {
    AsyncStorage.getItem("schedule_show_cancelled").then((v) => {
      if (v === "true") setShowCancelled(true);
    }).catch(() => {});
  }, []);
  const toggleShowCancelled = useCallback(() => {
    setShowCancelled((prev) => {
      const next = !prev;
      AsyncStorage.setItem("schedule_show_cancelled", String(next)).catch(() => {});
      return next;
    });
  }, []);
  const CANCELLED_SET = useMemo(() => new Set(["cancelled", "canceled", "skipped"]), []);
  const visibleJobs = useMemo(() => {
    if (showCancelled) return filteredJobs;
    return filteredJobs.filter(
      (j) => !CANCELLED_SET.has(String(j.status || "").toLowerCase()),
    );
  }, [filteredJobs, showCancelled, CANCELLED_SET]);
  const hiddenCancelledCount = useMemo(() => {
    if (showCancelled) return 0;
    return filteredJobs.filter(
      (j) => CANCELLED_SET.has(String(j.status || "").toLowerCase()),
    ).length;
  }, [filteredJobs, showCancelled, CANCELLED_SET]);

  // K15 · per-request AbortController — abort stale loads on new ones.
  const loadAbortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (force = false) => {
    // Phase P17 — OOM fix: narrower window (±14d instead of -14/+60d)
    // + skip fetch if the focus date is still inside the cached range.
    const BACK_DAYS = 7;
    const FWD_DAYS  = 14;
    const MARGIN    = 3;
    const focusStr = iso(focus);
    if (
      !force &&
      fetchedRangeRef.current &&
      focusStr >= iso(addDays(new Date(fetchedRangeRef.current.start + "T00:00:00"), MARGIN)) &&
      focusStr <= iso(addDays(new Date(fetchedRangeRef.current.end   + "T00:00:00"), -MARGIN))
    ) {
      return; // inside the cached interior — no network needed
    }
    // Abort any in-flight load before starting a new one.
    loadAbortRef.current?.abort();
    const ac = new AbortController();
    loadAbortRef.current = ac;
    setLoading(true); setErr(""); setLoadingTimedOut(false);
    // K36 · loading watchdog. Independent of the 25s network race
    // below — this one runs at 20s and flips a UI state so the tech
    // sees a fallback card rather than an infinite spinner.
    const watchdog = setTimeout(() => {
      if (loadAbortRef.current === ac) setLoadingTimedOut(true);
    }, LOADING_WATCHDOG_MS);
    try {
      const start = iso(addDays(focus, -BACK_DAYS));
      const end   = iso(addDays(focus,  FWD_DAYS));
      // Feb-2026 · Phase 1 offline — write-through on success, read
      // from the SQLite cache when the network throws.  Only cache
      // for the current tech (bulk-replace is scoped by user).
      const techUserId = user?.id || "";
      const crewFiltered = !!crewFilter;
      // K32 — tech auto-scope: always send technician_id for tech role
      // (defense in depth — server may also scope, but client enforces).
      // K42 — MUST use ``user.technician_id`` (authoritative technicians.id),
      // NOT ``user.id`` (users.id). Jobs store technicians.id in their
      // ``technician_id`` field, so a user-account ID won't match.
      // K43 — use resolvedTechId which falls back to /api/technicians/me
      // when user.technician_id is null (pre-backfill tenants).
      const techScope = isTech && resolvedTechId ? `&technician_id=${resolvedTechId}` : "";
      const jobsUrl = `/jobs?start=${start}&end=${end}${!isTech && crewFiltered ? `&crew_id=${crewFilter}` : ""}${techScope}`;
      // K15 · outer timeout race — if cachedGet (network+SQLite)
      // hasn't resolved in 25 s, give up and show the error card.
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("Schedule load timed out. Tap to retry.")), 25_000),
      );
      const data = await Promise.race([
        cachedGet<any>(jobsUrl, {
          writeThrough: crewFiltered ? undefined : async (d) => { await writeThroughJobs(techUserId, d, isTech ? { role: "technician", technicianId: resolvedTechId ?? null } : undefined); },
          readCache:    async ()  => { return techUserId ? await readCachedWeekJobs(techUserId) : []; },
          signal: ac.signal,
        }),
        timeoutPromise,
      ]);
      // If this controller was aborted while we awaited, discard.
      if (ac.signal.aborted) return;
      const arr = Array.isArray(data) ? data : (data.items || data.data || []);
      fetchedRangeRef.current = { start, end };
      setJobs(arr);
    } catch (e: any) {
      // K15 · intentional abort from a newer load() — silently discard.
      if (ac.signal.aborted) return;
      setErr(e.message || "Failed to load schedule");
    } finally {
      clearTimeout(watchdog);
      // Only write loading=false if THIS controller is still current.
      if (loadAbortRef.current === ac) { setLoading(false); setLoadingTimedOut(false); }
    }
  }, [focus, user?.id, crewFilter, isTech, resolvedTechId]);

  useFocusEffect(useCallback(() => {
    logNav("schedule/calendar.focus", {
      role: (user?.role as string) || null,
      user_id: user?.id || null,
    });
    load();
  }, [load, user?.role, user?.id]));

  const focusISO = iso(focus);
  const dayJobs = useMemo(() => {
    // P2 #9 · web P13 rule — scheduled_date prefix, else tenant-local
    // scheduled_start (was exact ``scheduled_date === focusISO``).
    const tz = tenantTz();
    const list = visibleJobs.filter((j) => jobDayKey(j, tz) === focusISO);
    list.sort((a, b) => (a.route_index ?? a.route_order ?? 999) - (b.route_index ?? b.route_order ?? 999));
    // Phase 30X · schedule is per-day; no time-of-day tiebreaker.
    return list;
  }, [visibleJobs, focusISO]);

  /** Job-count map for the 7 visible WeekStrip days (client-side). */
  const weekCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    // P2 #9 · same jobDayKey rule as dayJobs (was scheduled_date.slice).
    const tz = tenantTz();
    for (const j of visibleJobs) {
      const d = jobDayKey(j, tz);
      if (d) counts[d] = (counts[d] || 0) + 1;
    }
    return counts;
  }, [visibleJobs]);

  // Phase 1 Offline Read — which of today's jobs are cached for offline.
  const dayJobIds = useMemo(() => dayJobs.map((j) => j.id), [dayJobs]);
  const cachedJobIds = useCachedJobIds(dayJobIds);

  // Phase 2 — which jobs have pending offline writes.
  const pendingEntityIds = usePendingEntityIds();

  const [reorderList, setReorderList] = useState<Job[]>([]);
  useEffect(() => { setReorderList(dayJobs); }, [dayJobs]);

  const gridList = rearrangeMode ? reorderList : dayJobs;

  const toggleCheck = (id: string) => {
    setChecked((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  // Feb-2026 · Mobile Schedule "Select all in view" parity with web.
  // Admin+ gated at the button level; ``jobs`` is the currently
  // visible list post-filter, matching the web ``dayJobs`` derivation.
  const selectAllInView = () => {
    setChecked(new Set(jobs.map((j) => j.id)));
  };
  const clearSelection = () => setChecked(new Set());

  const bulkComplete = async () => {
    if (!checked.size) return;
    setBusy(true);
    let ok = 0, fail = 0;
    for (const id of checked) {
      try { await api.put(`/jobs/${id}`, { status: "completed" }); ok++; }
      catch { fail++; }
    }
    setBusy(false);
    setChecked(new Set());
    Alert.alert("Marked complete", `${ok} closed · ${fail} failed`);
    await load(true);
  };

  const bulkMove = async () => {
    if (!checked.size || !moveDate.match(/^\d{4}-\d{2}-\d{2}$/)) {
      Alert.alert("Pick a date", "Enter a YYYY-MM-DD target date to move to.");
      return;
    }
    setBusy(true);
    let ok = 0, fail = 0;
    for (const id of checked) {
      try { await api.put(`/jobs/${id}`, { scheduled_date: moveDate }); ok++; }
      catch { fail++; }
    }
    setBusy(false);
    setChecked(new Set());
    setMoveOpen(false); setMoveDate("");
    Alert.alert("Move complete", `${ok} moved · ${fail} failed`);
    await load(true);
  };

  const bulkDelete = async () => {
    if (!checked.size) return;
    showConfirm({
      title: `Delete ${checked.size} job${checked.size === 1 ? "" : "s"}?`,
      message: "Soft-deleted jobs can be recovered by a super admin.",
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
        setBusy(true);
        try {
          await api.post("/jobs/bulk-soft-delete", { job_ids: [...checked] });
          showToast(`${checked.size} job${checked.size === 1 ? "" : "s"} removed.`);
          setChecked(new Set());
          await load(true);
        } catch (e: any) {
          showToast(e?.message || "Delete failed.", "error");
        } finally { setBusy(false); }
      },
    });
  };

  const openReassign = async () => {
    if (!checked.size) return;
    try {
      const res = await api.get("/users?role=tech");
      const list = (res.users || res || []).filter((u: any) => u.id && u.name);
      setTechs(list);
    } catch { setTechs([]); }
    setReassignTechId("");
    setReassignOpen(true);
  };

  const bulkReassign = async () => {
    if (!checked.size || !reassignTechId) {
      Alert.alert("Select a tech", "Choose a technician to reassign the jobs.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/jobs/bulk-reassign", { job_ids: [...checked], tech_id: reassignTechId });
      const techName = techs.find((t) => t.id === reassignTechId)?.name || "tech";
      Alert.alert("Reassigned", `${checked.size} job${checked.size === 1 ? "" : "s"} assigned to ${techName}.`);
      setChecked(new Set());
      setReassignOpen(false);
      await load(true);
    } catch (e: any) {
      Alert.alert("Reassign failed", e.message || "Unknown error");
    } finally { setBusy(false); }
  };

  const saveReorder = async () => {
    if (!isAdmin) {
      setRearrangeMode(false);
      Alert.alert("Rearrange saved locally", "Only admins can persist a new route order — the reorder endpoint is admin-only.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/jobs/reorder", {
        ordered_job_ids: reorderList.map((j) => j.id),
        tech_user_id: user?.id || "",
        date: iso(focus),
      });
      Alert.alert("Route saved", `New order saved for ${reorderList.length} jobs.`);
      await load(true);
    } catch (e: any) {
      Alert.alert("Reorder failed", e.message || "Try again.");
    } finally {
      setBusy(false);
      setRearrangeMode(false);
    }
  };

  const shift = (id: string, dir: -1 | 1) => {
    setReorderList((cur) => {
      const i = cur.findIndex((j) => j.id === id);
      if (i < 0) return cur;
      const j = i + dir;
      if (j < 0 || j >= cur.length) return cur;
      const c = [...cur];
      [c[i], c[j]] = [c[j], c[i]];
      return c;
    });
  };

  /* ─── Calendar view — build 7-day column layout ─────────────────── */
  const weekStart = useMemo(() => {
    const d = new Date(focus);
    const day = d.getDay();
    d.setDate(d.getDate() - day + 1);         // Monday
    return d;
  }, [focus]);
  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );
  const weekTitle = useMemo(
    () => focus.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
    [focus],
  );
  const jobsByDay = useMemo(() => {
    const m: Record<string, Job[]> = {};
    // P2 #9 · jobDayKey (was the raw, unsliced scheduled_date string).
    const tz = tenantTz();
    for (const j of visibleJobs) {
      const d = jobDayKey(j, tz);
      if (!d) continue;
      (m[d] = m[d] || []).push(j);
    }
    return m;
  }, [visibleJobs]);

  if (role === "customer") return <Redirect href="/(app)/jobs" />;
  if (!modeLoaded) return null;

  return (
    <View style={styles.root}>
      <Header
        title="Schedule"
        subtitle={loading ? "Loading…" : `${visibleJobs.length} jobs in window · ${mode}`}
        right={
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            {/* Sync route button */}
            <Pressable
              onPress={handleSyncRoute}
              disabled={syncingRoute || hydrationMeta?.inProgress || !online}
              style={[gStyles.refreshBtn, (!online || syncingRoute || hydrationMeta?.inProgress) && { opacity: 0.5 }]}
              hitSlop={8}
              testID="schedule-sync-route"
              accessibilityLabel={!online ? "You're offline — sync when connected" : "Sync route"}
            >
              {(syncingRoute || hydrationMeta?.inProgress)
                ? <ActivityIndicator size={14} color={colors.brand} testID="schedule-sync-route-progress" />
                : <Ionicons name="cloud-download-outline" size={16} color={colors.brand} />}
            </Pressable>
            {/* ITEM 2 — Schedule Refresh Button */}
            <Pressable
              onPress={() => { if (!refreshing) { setRefreshing(true); load(true).finally(() => setRefreshing(false)); } }}
              disabled={refreshing}
              style={[gStyles.refreshBtn, refreshing && { opacity: 0.6 }]}
              hitSlop={8}
              testID="schedule-refresh"
              accessibilityLabel="Refresh schedule"
            >
              {refreshing
                ? <ActivityIndicator size={14} color={colors.onSurface} testID="schedule-refresh-spinner" />
                : <Ionicons name="refresh" size={16} color={colors.onSurface} />}
            </Pressable>
            <SyncBadge testID="schedule-header-sync-badge" />
            <OfflineBadge testID="schedule-header-offline-badge" cacheStats={hydrationMeta ? { cached: hydrationMeta.cachedJobs, total: hydrationMeta.totalJobs, lastSyncedAt: hydrationMeta.lastSyncedAt, syncStatus: hydrationMeta.syncStatus } : undefined} />
            {isTech ? (
              <View style={{ marginRight: 52 }} testID="schedule-header-bell">
                <NotificationBell />
              </View>
            ) : null}
          </View>
        }
      />

      {/* Sync route toast */}
      {syncToast && (
        <View style={gStyles.syncToast} testID="schedule-sync-toast">
          <Ionicons
            name={syncToast.includes("failed") ? "alert-circle" : "checkmark-circle"}
            size={14}
            color={syncToast.includes("failed") ? "#DC2626" : "#166534"}
          />
          <Text style={[gStyles.syncToastText, syncToast.includes("failed") && { color: "#DC2626" }]}>{syncToast}</Text>
        </View>
      )}

      {/* Cache freshness label — Fix 3: honest sync status */}
      {(hydrationMeta?.lastSyncedAt || hydrationMeta?.syncStatus === "partial" || hydrationMeta?.syncStatus === "failed") && !syncingRoute && !hydrationMeta?.inProgress && (
        <View style={gStyles.cacheFreshnessRow} testID="schedule-cache-freshness">
          <Ionicons
            name={hydrationMeta?.syncStatus === "failed" ? "alert-circle" : hydrationMeta?.syncStatus === "partial" ? "sync-outline" : "time-outline"}
            size={11}
            color={hydrationMeta?.syncStatus === "failed" ? "#DC2626" : hydrationMeta?.syncStatus === "partial" ? "#D97706" : colors.muted}
          />
          <Text style={[gStyles.cacheFreshnessText, hydrationMeta?.syncStatus === "failed" && { color: "#DC2626" }, hydrationMeta?.syncStatus === "partial" && { color: "#D97706" }]}>
            {(() => {
              const status = hydrationMeta?.syncStatus || "synced";
              if (status === "failed") return "Sync failed — tap sync to retry";
              if (status === "partial") return `Partial sync: ${hydrationMeta?.cachedJobs || 0} of ${hydrationMeta?.totalJobs || 0}`;
              const ts = new Date(hydrationMeta!.lastSyncedAt).getTime();
              const now = Date.now();
              const diffMin = Math.round((now - ts) / 60000);
              if (diffMin < 1) return "Cached just now";
              if (diffMin < 60) return `Cached ${diffMin} min ago`;
              const hrs = Math.floor(diffMin / 60);
              return `Cached ${hrs}h ${diffMin % 60}m ago`;
            })()}
          </Text>
        </View>
      )}

      {/* Phase 24 · Root scroll wrapper */}
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        showsVerticalScrollIndicator
        testID="schedule-root-scroll"
      >
      <View style={{ paddingHorizontal: spacing.lg, paddingTop: spacing.md }}>
        {user?.role !== "admin" && user?.role !== "super_admin" && <LandscapingClockWidget />}
      </View>

      {/* Phase 23 · 2026-08-02 — Service / Repair progress-ring
          tiles at the top of the schedule (above the WeekStrip).
          Client-side classification off ``service_type`` — no
          backend change. */}
      <JobTrackerTiles jobs={dayJobs} loading={busy} listError={err} />

      {/* Feb-2026 · Schedule-UI · 7-day toggle strip.
          The strip drives the shared `focus` state — tapping a day
          updates focus which triggers the existing ±14/+60 fetch window. */}
      <WeekStrip
        selectedDate={focusISO}
        onSelectDate={(dateIso) => {
          const [y, m, d] = dateIso.split("-").map(Number);
          setFocus(new Date(y, m - 1, d));
        }}
        counts={weekCounts}
      />

      {/* Top-level Grid ↔ Calendar toggle. */}
      <View style={styles.modeSwitch} testID="schedule-mode-switch">
        {(["calendar", "grid"] as const).map((m) => {
          const active = mode === m;
          return (
            <Pressable
              key={m}
              onPress={() => setModePersist(m)}
              style={[styles.modeBtn, active && styles.modeBtnActive]}
              testID={`schedule-mode-${m}`}
            >
              <Ionicons
                name={m === "grid" ? "list-outline" : "calendar-outline"}
                size={14}
                color={active ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text style={[styles.modeBtnText, active && { color: "#fff" }]}>
                {m === "grid" ? "Grid" : "Calendar"}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Phase S1 — Per-tech filter dropdown (admin/manager/owner only). */}
      {!isTech && (
        <View style={styles.techFilterRow} testID="schedule-tech-filter-row">
          <Pressable
            onPress={() => setTechPickerOpen(true)}
            style={styles.techFilterBtn}
            testID="schedule-tech-filter"
            accessibilityRole="button"
            accessibilityLabel="Filter schedule by technician"
          >
            <Ionicons name="person-outline" size={14} color={techFilter === "all" ? colors.muted : colors.brand} />
            <Text
              style={[styles.techFilterLabel, techFilter !== "all" && { color: colors.brand, fontFamily: font.bold }]}
              numberOfLines={1}
              testID="schedule-tech-filter-label"
            >
              {techFilter === "all"
                ? "All techs"
                : sortedTechs.find((t: any) => t.id === techFilter)?.name || "Tech"}
            </Text>
            <Ionicons name="chevron-down" size={12} color={techFilter === "all" ? colors.muted : colors.brand} />
          </Pressable>
        </View>
      )}

      {/* INACTIVE-CUSTOMER-CASCADE — show/hide cancelled toggle */}
      <View style={styles.cancelledToggleRow}>
        <Pressable
          onPress={toggleShowCancelled}
          style={styles.cancelledToggleBtn}
          testID="schedule-show-cancelled-toggle"
          accessibilityRole="switch"
          accessibilityState={{ checked: showCancelled }}
          accessibilityLabel={showCancelled ? "Hide cancelled" : "Show cancelled"}
        >
          <Ionicons
            name={showCancelled ? "eye-outline" : "eye-off-outline"}
            size={14}
            color={showCancelled ? colors.brand : colors.muted}
          />
          <Text style={[styles.cancelledToggleText, showCancelled && { color: colors.brand }]}>
            {showCancelled ? "Hide cancelled" : "Show cancelled"}
          </Text>
          {!showCancelled && hiddenCancelledCount > 0 ? (
            <View style={styles.cancelledCountPill}>
              <Text style={styles.cancelledCountText}>{hiddenCancelledCount}</Text>
            </View>
          ) : null}
        </Pressable>
      </View>

      {/* K15 · Error card with retry — replaces the old tiny inline bar */}
      {/* K43 — Empty-profile message when tech has no linked technician row. */}
      {isTech && resolvedTechId === null && !loading && !err ? (
        <View style={styles.noProfileCard} testID="schedule-no-profile">
          <Ionicons name="person-circle-outline" size={28} color={colors.warning} />
          <Text style={styles.noProfileText}>
            Your technician profile is not linked yet — contact your admin to get set up.
          </Text>
        </View>
      ) : null}

      {err ? (
        <View style={styles.errCard} testID="schedule-error">
          <View style={styles.errCardRow}>
            <Ionicons name="alert-circle" size={20} color="#991B1B" />
            <Text style={styles.errCardText} testID="schedule-error-message">
              {err || "Couldn't load your schedule. Tap to retry."}
            </Text>
          </View>
          <View style={styles.errCardActions}>
            <Pressable
              style={styles.errRetryBtn}
              onPress={() => { setErr(""); load(true); }}
              testID="schedule-error-retry"
            >
              <Ionicons name="refresh" size={14} color="#fff" />
              <Text style={styles.errRetryText}>Retry</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {isAdmin ? (
        <OptimizeRouteModal
          visible={optimizeOpen}
          jobs={dayJobs}
          date={focusISO}
          technicianId={techFilter !== "all" ? techFilter : null}
          onClose={() => setOptimizeOpen(false)}
          onSaved={() => load(true)}
        />
      ) : null}

      {mode === "grid" ? (
        <GridView
          focus={focus} setFocus={setFocus}
          jobs={gridList} loading={loading}
          loadingTimedOut={loadingTimedOut}
          onLoadRetry={() => load(true)}
          onLoadCancel={() => {
            loadAbortRef.current?.abort();
            setLoading(false);
            setLoadingTimedOut(false);
          }}
          checked={checked} onToggle={toggleCheck}
          canWrite={canWriteJobs}
          rearrangeMode={rearrangeMode}
          onToggleRearrange={() => setRearrangeMode((v) => !v)}
          onSaveReorder={saveReorder}
          onOptimizeRoute={() => setOptimizeOpen(true)}
          mapTechs={allTechs}
          onShift={shift}
          onBulkComplete={bulkComplete}
          onBulkDelete={bulkDelete}
          onOpenMove={() => setMoveOpen(true)}
          onOpenReassign={openReassign}
          moveOpen={moveOpen} setMoveOpen={setMoveOpen}
          moveDate={moveDate} setMoveDate={setMoveDate}
          onConfirmMove={bulkMove}
          busy={busy}
          onOpenJob={(id: string) => router.push(`/job/${id}/checklist` as any)}
          onNewJob={() => router.push(`/job/new?scheduled_date=${focusISO}` as any)}
          isAdmin={isAdmin}
          isStrictlyAdmin={isStrictAdmin(user)}
          userId={user?.id || ""}
          hourlyData={hourlyData}
          weatherWidget={(isTech || isAdmin) ? <WeatherWidget onHourlyLoaded={setHourlyData} /> : null}
          onOpenEdit={isAdmin ? ((jobRow: Job) => setEditingJob(jobRow)) : undefined}
          onSelectAllInView={isAdmin ? selectAllInView : undefined}
          onClearSelection={isAdmin ? clearSelection : undefined}
          role={role}
          gridSubMode={gridSubMode}
          setGridSubMode={setGridSubMode}
          dayJobs={dayJobs}
          setReorderList={setReorderList}
          crews={crews}
          crewFilter={crewFilter}
          crewMembers={crewMembers}
          onCrewSelect={handleCrewSelect}
          isTech={isTech}
          cachedJobIds={cachedJobIds}
          pendingEntityIds={pendingEntityIds}
          hydrationMeta={hydrationMeta}
        />
      ) : (
        <CalendarView
          weekDays={weekDays}
          weekTitle={weekTitle}
          jobsByDay={jobsByDay}
          showBH={showBH}
          onToggleBH={() => setShowBH((v) => !v)}
          onPrev={() => setFocus((d) => addDays(d, -7))}
          onNext={() => setFocus((d) => addDays(d, 7))}
          onOpenJob={(id) => router.push(`/job/${id}/checklist` as any)}
          weatherWidget={(isTech || isAdmin) ? <WeatherWidget onHourlyLoaded={setHourlyData} /> : null}
          isAdmin={isAdmin}
          isTech={isTech}
          onNewJob={isStrictAdmin(user) ? () => router.push(`/job/new?scheduled_date=${focusISO}` as any) : undefined}
        />
      )}

      </ScrollView>

      {/* Feb-2026 · Schedule inline-edit sheet. In-place mutate on
          save; drops the card on delete. Admin-gated at the button
          level; backend PUT + DELETE also role-gate. */}
      <ScheduleJobEditSheet
        open={!!editingJob}
        job={editingJob}
        onClose={() => setEditingJob(null)}
        onSaved={(patched) => {
          patchJobInPlace(patched);
          setEditingJob(null);
        }}
        onDeleted={(jid) => {
          removeJobInPlace(jid);
          setEditingJob(null);
        }}
      />

      {/* Reassign Tech Modal */}
      <Modal visible={reassignOpen} transparent animationType="fade" onRequestClose={() => setReassignOpen(false)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", paddingHorizontal: 24 }}>
          <View style={{ width: "100%", maxWidth: 380, backgroundColor: colors.surface, borderRadius: 16, padding: 20 }} testID="reassign-modal">
            <Text style={{ fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: 8 }}>
              Reassign {checked.size} job{checked.size !== 1 ? "s" : ""}
            </Text>
            <Text style={{ fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.lg }}>
              Select a technician:
            </Text>
            <ScrollView style={{ maxHeight: 300 }}>
              {techs.map((t) => (
                <Pressable
                  key={t.id}
                  onPress={() => setReassignTechId(t.id)}
                  style={{
                    flexDirection: "row", alignItems: "center", gap: 10,
                    paddingVertical: 10, paddingHorizontal: 12, borderRadius: radius.md,
                    backgroundColor: reassignTechId === t.id ? colors.brandTertiary : "transparent",
                    marginBottom: 4,
                  }}
                  testID={`reassign-tech-${t.id}`}
                >
                  <View style={{
                    width: 20, height: 20, borderRadius: 10,
                    borderWidth: 2, borderColor: reassignTechId === t.id ? colors.brand : colors.border,
                    backgroundColor: reassignTechId === t.id ? colors.brand : "transparent",
                    alignItems: "center", justifyContent: "center",
                  }}>
                    {reassignTechId === t.id ? <Ionicons name="checkmark" size={12} color="#fff" /> : null}
                  </View>
                  <Text style={{ fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface }}>{t.name}</Text>
                </Pressable>
              ))}
              {techs.length === 0 ? (
                <Text style={{ fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", paddingVertical: 20 }}>
                  No technicians available
                </Text>
              ) : null}
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 12, justifyContent: "flex-end", marginTop: spacing.lg }}>
              <Pressable
                onPress={() => setReassignOpen(false)}
                style={{ paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border }}
                testID="reassign-cancel"
              >
                <Text style={{ fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface }}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={bulkReassign}
                disabled={!reassignTechId || busy}
                style={{
                  paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md,
                  backgroundColor: reassignTechId ? colors.brand : colors.border,
                  opacity: (!reassignTechId || busy) ? 0.5 : 1,
                }}
                testID="reassign-confirm"
              >
                <Text style={{ fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" }}>Assign</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Phase S1 — Tech filter picker modal */}
      <Modal
        visible={techPickerOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setTechPickerOpen(false)}
      >
        <Pressable
          style={techPickerStyles.backdrop}
          onPress={() => setTechPickerOpen(false)}
        >
          <View style={techPickerStyles.sheet}>
            <Text style={techPickerStyles.title}>Filter by technician</Text>
            <ScrollView style={{ maxHeight: 350 }}>
              {/* P9-C: techs must never see "All techs" — defense in depth */}
              {!isTech && (
              <Pressable
                onPress={() => { handleTechFilterChange("all"); setTechPickerOpen(false); }}
                style={[techPickerStyles.row, techFilter === "all" && techPickerStyles.rowActive]}
                testID="tech-filter-option-all"
              >
                <Ionicons name="people-outline" size={16} color={techFilter === "all" ? colors.brand : colors.onSurface} />
                <Text style={[techPickerStyles.rowLabel, techFilter === "all" && { color: colors.brand, fontFamily: font.bold }]}>
                  All techs
                </Text>
                {techFilter === "all" && <Ionicons name="checkmark" size={16} color={colors.brand} />}
              </Pressable>
              )}
              {sortedTechs.map((t: any) => (
                <Pressable
                  key={t.id}
                  onPress={() => { handleTechFilterChange(t.id); setTechPickerOpen(false); }}
                  style={[techPickerStyles.row, techFilter === t.id && techPickerStyles.rowActive]}
                  testID={`tech-filter-option-${t.id}`}
                >
                  <Ionicons name="person-outline" size={16} color={techFilter === t.id ? colors.brand : colors.onSurface} />
                  <Text style={[techPickerStyles.rowLabel, techFilter === t.id && { color: colors.brand, fontFamily: font.bold }]}>
                    {t.name}
                  </Text>
                  {techFilter === t.id && <Ionicons name="checkmark" size={16} color={colors.brand} />}
                </Pressable>
              ))}
              {sortedTechs.length === 0 && (
                <Text style={techPickerStyles.empty}>No technicians found</Text>
              )}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

/* ═══ Grid view ══════════════════════════════════════════════════════ */
function GridView(props: any) {
  const {
    focus, setFocus, jobs, loading, loadingTimedOut, onLoadRetry, onLoadCancel,
    checked, onToggle, canWrite,
    rearrangeMode, onToggleRearrange, onSaveReorder, onOptimizeRoute, mapTechs, onShift,
    onBulkComplete, onBulkDelete, onOpenMove, onOpenReassign, moveOpen, setMoveOpen, moveDate, setMoveDate,
    onConfirmMove, busy, onOpenJob, onNewJob, isAdmin, isStrictlyAdmin, hourlyData, userId,
    weatherWidget, onOpenEdit, onSelectAllInView, onClearSelection, role,
    gridSubMode, setGridSubMode, dayJobs, setReorderList,
    crews, crewFilter, crewMembers, onCrewSelect, isTech,
    cachedJobIds, pendingEntityIds, hydrationMeta,
  } = props;
  const focusISO = iso(focus);
  const isToday = focusISO === iso(new Date());
  const [actionsOpen, setActionsOpen] = useState(false);

  // Map show/hide toggle — persisted per-device.
  const [mapVisible, setMapVisible] = useState(true);
  useEffect(() => {
    storage.getItem<boolean>(MAP_VISIBLE_KEY, true).then((v) => {
      setMapVisible(v !== false);
    }).catch(() => {});
  }, []);
  const toggleMapVisible = useCallback(() => {
    setMapVisible((prev) => {
      const next = !prev;
      storage.setItem(MAP_VISIBLE_KEY, next).catch(() => {});
      return next;
    });
  }, []);

  /** Next-job: first non-terminal job in route order. */
  const _TERMINAL = new Set(["completed", "canceled", "cancelled", "skipped", "could_not_service"]);
  const nextJob = jobs.find((j: Job) => !_TERMINAL.has((j.status || "").toLowerCase()));

  return (
    <View style={{ padding: spacing.md, paddingBottom: spacing["3xl"] }}>
      <View style={gStyles.dayHead} testID="schedule-day-head">
        <Pressable onPress={() => setFocus(addDays(focus, -1))} style={gStyles.navBtn} testID="grid-prev-day">
          <Ionicons name="chevron-back" size={18} color={colors.onSurface} />
        </Pressable>
        <Pressable
          onPress={() => setFocus(new Date())}
          style={[gStyles.todayPill, isToday && gStyles.todayPillActive]}
          testID="grid-today"
        >
          <Text style={[gStyles.todayText, isToday && { color: "#fff" }]}>Today</Text>
        </Pressable>
        <Pressable onPress={() => setFocus(addDays(focus, 1))} style={gStyles.navBtn} testID="grid-next-day">
          <Ionicons name="chevron-forward" size={18} color={colors.onSurface} />
        </Pressable>
        <Text style={gStyles.dayLabel} testID="grid-day-label">{dayLabel(focus)}</Text>
      </View>

      {/* Navigate Route + Crew filter + Reorder header */}
      {rearrangeMode ? (
        <View testID="reorder-route-header" style={gStyles.reorderHeader}>
          <Ionicons name="reorder-three-outline" size={18} color="#059669" />
          <View style={{ flex: 1 }}>
            <Text style={gStyles.reorderHeaderTitle}>Reorder route</Text>
            <Text style={gStyles.reorderHeaderSub}>Drag jobs to reorder. Position updates automatically.</Text>
          </View>
        </View>
      ) : (
        <View style={gStyles.filterRow}>
          <NavigateRouteButton jobs={jobs} />
          {!isTech && crews.length > 0 ? (
            <CrewFilterBar
              crews={crews}
              selectedCrewId={crewFilter}
              onSelect={onCrewSelect}
              memberNames={crewMembers}
              hideAllOption={isTech}
            />
          ) : null}
        </View>
      )}

      {/* Rearrange save / cancel bar */}
      {rearrangeMode ? (
        <View style={gStyles.reorderBar} testID="reorder-route-bar">
          <Pressable
            onPress={onToggleRearrange}
            style={gStyles.reorderCancelBtn}
            testID="reorder-route-cancel"
          >
            <Text style={gStyles.reorderCancelText}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={onSaveReorder}
            disabled={busy}
            style={[gStyles.reorderSaveBtn, busy && { opacity: 0.5 }]}
            testID="reorder-route-save"
          >
            <Ionicons name="save-outline" size={14} color="#fff" />
            <Text style={gStyles.reorderSaveText}>{busy ? "Saving…" : "Save order"}</Text>
          </Pressable>
        </View>
      ) : null}

      {/* Phase P18 — Consolidated bulk-action dropdown (was 3-row pill cluster).
          Single "Actions" button → dropdown list with all 6 options. */}
      {/* M1 hotfix — entire bulk-action strip hidden for tech role.
          Techs keep per-job row actions (On my way, Could not service). */}
      {isAdmin ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, marginBottom: spacing.sm }}>
          <Pressable
            onPress={() => setActionsOpen(true)}
            style={[gStyles.pill, { backgroundColor: colors.brand }]}
            testID="grid-actions-trigger"
          >
            <Ionicons name="ellipsis-horizontal" size={14} color="#fff" />
            <Text style={gStyles.pillText}>
              Actions{checked.size > 0 ? ` (${checked.size})` : ""}
            </Text>
          </Pressable>
          {checked.size > 0 ? (
            <Pressable
              onPress={onClearSelection}
              style={[gStyles.pill, gStyles.pillGrey]}
              testID="grid-bulk-clear-selection"
            >
              <Ionicons name="close-outline" size={13} color="#fff" />
              <Text style={gStyles.pillText}>Clear</Text>
            </Pressable>
          ) : null}
          {isStrictlyAdmin ? (
            <Pressable onPress={onNewJob} style={gStyles.newBtn} testID="mobile-schedule-add-job-btn-grid" accessibilityLabel="Add job">
              <Ionicons name="add-circle" size={14} color="#fff" />
              <Text style={gStyles.newBtnText}>Add job</Text>
            </Pressable>
          ) : null}
          <Modal
            visible={actionsOpen}
            transparent
            animationType="fade"
            onRequestClose={() => setActionsOpen(false)}
          >
            <Pressable
              style={actMenuStyles.backdrop}
              onPress={() => setActionsOpen(false)}
            >
              <View style={actMenuStyles.sheet}>
                <Text style={actMenuStyles.title}>Bulk Actions</Text>
                {([
                  { key: "select-all", label: `Select all (${jobs.length})`, icon: "checkbox-outline" as const, color: "#7C3AED", onPress: onSelectAllInView, disabled: !jobs.length, adminOnly: true },
                  { key: "complete", label: `Complete (${checked.size})`, icon: "checkmark-circle" as const, color: "#059669", onPress: onBulkComplete, disabled: busy || checked.size === 0, adminOnly: false },
                  { key: "move", label: `Move (${checked.size})`, icon: "calendar-outline" as const, color: "#2563EB", onPress: onOpenMove, disabled: busy || checked.size === 0, adminOnly: true },
                  { key: "delete", label: `Delete (${checked.size})`, icon: "trash-outline" as const, color: "#DC2626", onPress: onBulkDelete, disabled: busy || checked.size === 0, adminOnly: true },
                  { key: "assign", label: `Assign (${checked.size})`, icon: "people-outline" as const, color: "#D97706", onPress: onOpenReassign, disabled: busy || checked.size === 0, adminOnly: true },
                  { key: "optimize-route", label: "Optimize Route", icon: "navigate-outline" as const, color: "#0F766E", onPress: onOptimizeRoute, disabled: busy || rearrangeMode || (dayJobs || jobs).length < 2, adminOnly: true },
                  { key: "rearrange", label: rearrangeMode ? "Save order" : "Rearrange", icon: (rearrangeMode ? "save-outline" : "reorder-three-outline") as const, color: rearrangeMode ? "#059669" : "#7C3AED", onPress: rearrangeMode ? onSaveReorder : onToggleRearrange, disabled: false, adminOnly: true },
                ] as const).map((act) => {
                  if (act.adminOnly && !isAdmin) return null;
                  return (
                    <Pressable
                      key={act.key}
                      onPress={() => { setActionsOpen(false); act.onPress?.(); }}
                      disabled={act.disabled}
                      style={[actMenuStyles.row, act.disabled && { opacity: 0.4 }]}
                      testID={`grid-action-${act.key}`}
                    >
                      <View style={[actMenuStyles.dot, { backgroundColor: act.color }]} />
                      <Ionicons name={act.icon} size={18} color={act.disabled ? colors.muted : colors.onSurface} />
                      <Text style={[actMenuStyles.rowLabel, act.disabled && { color: colors.muted }]}>
                        {act.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </Pressable>
          </Modal>
        </View>
      ) : null}

      {/* On My Way — next job primary CTA */}
      {nextJob ? (
        <OnMyWayButton
          jobId={nextJob.id}
          customerName={nextJob.customer_name}
          variant="primary"
          role={role}
          testID="on-my-way-next-btn"
        />
      ) : null}

      {/* Map section — collapsible via toggle bar.
          When hidden, shows a compact "Show map" bar. When visible,
          shows DailyRouteMap + List|Map sub-mode toggle + ScheduleMapLazy. */}
      <Pressable
        onPress={toggleMapVisible}
        style={gStyles.mapToggleBar}
        testID="schedule-map-toggle"
        accessibilityLabel={mapVisible ? "Hide map" : "Show map"}
        accessibilityRole="button"
      >
        <Ionicons
          name={mapVisible ? "map" : "map-outline"}
          size={16}
          color={mapVisible ? colors.brand : colors.muted}
        />
        <Text style={[gStyles.mapToggleText, mapVisible && { color: colors.brand }]}>
          {mapVisible ? "Hide map" : "Show map"}
        </Text>
        <Ionicons
          name={mapVisible ? "chevron-up" : "chevron-down"}
          size={14}
          color={mapVisible ? colors.brand : colors.muted}
        />
      </Pressable>

      {mapVisible ? (
        <>
          <MapErrorBoundary testID="daily-route-map-error-boundary">
            <DailyRouteMap jobs={dayJobs || jobs} userId={userId} />
          </MapErrorBoundary>

          {/* List | Map toggle */}
          <View style={gStyles.subModeRow} testID="grid-sub-mode-toggle">
            {(["list", "map"] as const).map((sm) => {
              const active = gridSubMode === sm;
              return (
                <Pressable
                  key={sm}
                  onPress={() => setGridSubMode(sm)}
                  style={[gStyles.subModeBtn, active && gStyles.subModeBtnActive]}
                  testID={`grid-sub-mode-${sm}`}
                >
                  <Ionicons
                    name={sm === "list" ? "list-outline" : "map-outline"}
                    size={12}
                    color={active ? "#fff" : colors.onSurfaceSecondary}
                  />
                  <Text style={[gStyles.subModeText, active && { color: "#fff" }]}>
                    {sm === "list" ? "List" : "Map"}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </>
      ) : null}

      {gridSubMode === "map" && mapVisible ? (
        <ScheduleMapLazy jobs={dayJobs || jobs} techs={mapTechs} crews={crews} testID="schedule-day-map" />
      ) : (
        <>
      {moveOpen ? (
        <View style={gStyles.moveBox} testID="grid-move-box">
          <Text style={gStyles.moveLabel}>Move {checked.size} job{checked.size === 1 ? "" : "s"} to:</Text>
          <AppTextInput
            value={moveDate}
            onChangeText={setMoveDate}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            style={gStyles.moveInput}
            testID="grid-move-input"
          />
          <View style={{ flexDirection: "row", gap: spacing.xs }}>
            <Pressable
              onPress={() => { setMoveOpen(false); setMoveDate(""); }}
              style={[gStyles.moveBtn, gStyles.moveBtnCancel]}
              testID="grid-move-cancel"
            >
              <Text style={gStyles.moveBtnCancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={onConfirmMove}
              disabled={busy}
              style={[gStyles.moveBtn, gStyles.moveBtnGo, busy && { opacity: 0.5 }]}
              testID="grid-move-confirm"
            >
              <Text style={gStyles.moveBtnGoText}>Move</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {loading ? (
        loadingTimedOut ? (
          <View style={gStyles.timeoutBox} testID="schedule-loading-timeout">
            <Ionicons name="hourglass-outline" size={28} color={colors.muted} />
            <Text style={gStyles.timeoutTitle}>Schedule is taking longer than usual</Text>
            <Text style={gStyles.timeoutHint}>
              This can happen on a slow network or right after signing in. Retry the load, or continue in offline mode with your cached jobs.
            </Text>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable
                onPress={onLoadRetry}
                style={[gStyles.timeoutBtn, { backgroundColor: colors.brand }]}
                testID="schedule-loading-timeout-retry"
              >
                <Ionicons name="refresh" size={14} color="#fff" />
                <Text style={gStyles.timeoutBtnText}>Retry</Text>
              </Pressable>
              <Pressable
                onPress={onLoadCancel}
                style={[gStyles.timeoutBtn, { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border }]}
                testID="schedule-loading-timeout-continue"
              >
                <Text style={[gStyles.timeoutBtnText, { color: colors.onSurface }]}>Continue offline</Text>
              </Pressable>
            </View>
          </View>
        ) : (
          <View style={{ padding: spacing.xl, alignItems: "center" }} testID="schedule-loading-spinner">
            <ActivityIndicator color={colors.brand} />
          </View>
        )
      ) : jobs.length === 0 ? (
        <View style={gStyles.empty} testID="grid-empty">
          <Ionicons name="calendar-outline" size={28} color={colors.muted} />
          <Text style={gStyles.emptyTitle}>Nothing on {focusISO}</Text>
          {isAdmin ? (
            <Pressable onPress={onNewJob} style={gStyles.newBtn} testID="grid-new-job">
              <Ionicons name="add-circle" size={14} color="#fff" />
              <Text style={gStyles.newBtnText}>New job</Text>
            </Pressable>
          ) : null}
        </View>
      ) : rearrangeMode && Platform.OS !== "web" ? (
        <DraggableFlatList
          data={jobs}
          keyExtractor={(item: Job) => item.id}
          scrollEnabled={false}
          onDragEnd={({ data }: { data: Job[] }) => {
            setReorderList(data);
            // Auto-save reorder on drop (admin only)
            if (isAdmin) {
              api.post("/jobs/reorder", { ordered_job_ids: data.map((j: Job) => j.id), tech_user_id: userId, date: focusISO })
                .then(() => {})
                .catch((e: any) => {
                  // Snap back to original order
                  setReorderList(dayJobs || jobs);
                  Alert.alert("Reorder failed", e?.message || "Could not save new order.");
                });
            }
          }}
          renderItem={({ item, getIndex, drag, isActive }: RenderItemParams<Job>) => {
            const idx = getIndex() ?? 0;
            return (
              <ScaleDecorator>
                <JobRow
                  key={item.id}
                  job={item}
                  idx={idx}
                  checked={checked.has(item.id)}
                  onCheck={() => onToggle(item.id)}
                  onOpen={() => onOpenJob(item.id)}
                  rearrangeMode={rearrangeMode}
                  onShift={onShift}
                  first={idx === 0}
                  last={idx === jobs.length - 1}
                  hourlyData={hourlyData}
                  isAdminForCard={isAdmin}
                  onEdit={isAdmin ? onOpenEdit : undefined}
                  role={role}
                  onDrag={drag}
                  isDragging={isActive}
                  cachedForOffline={cachedJobIds?.has(item.id)}
                  pendingSync={pendingEntityIds?.has(item.id)}
                />
              </ScaleDecorator>
            );
          }}
          testID="grid-dnd-list"
        />
      ) : (
        <FlatList
          data={jobs}
          keyExtractor={(item: Job) => item.id}
          initialNumToRender={10}
          maxToRenderPerBatch={10}
          windowSize={7}
          removeClippedSubviews={Platform.OS === "android"}
          testID="grid-job-list"
          renderItem={({ item, index }: { item: Job; index: number }) => (
            <JobRow
              job={item}
              idx={index}
              checked={checked.has(item.id)}
              onCheck={() => onToggle(item.id)}
              onOpen={() => onOpenJob(item.id)}
              rearrangeMode={rearrangeMode}
              onShift={onShift}
              first={index === 0}
              last={index === jobs.length - 1}
              hourlyData={hourlyData}
              isAdminForCard={isAdmin}
              onEdit={isAdmin ? onOpenEdit : undefined}
              role={role}
              cachedForOffline={cachedJobIds?.has(item.id)}
              pendingSync={pendingEntityIds?.has(item.id)}
            />
          )}
        />
      )}
        </>
      )}
      {weatherWidget ? (
        <View style={{ paddingHorizontal: spacing.xs, paddingTop: spacing.lg }} testID="schedule-weather-bottom">
          {weatherWidget}
        </View>
      ) : null}
    </View>
  );
}

function JobRow({ job, idx, checked, onCheck, onOpen, rearrangeMode, onShift, first, last, hourlyData, isAdminForCard, onEdit, role, onDrag, isDragging, cachedForOffline, pendingSync }: any) {
  const pill = STATUS_PILL[(job.status || "scheduled").toLowerCase()] || STATUS_PILL.scheduled;
  const svc = SERVICE_COLOR(job.service_type);
  // Feb-2026 · Schedule-UI · colored left border.
  const statusBorder = getStatusBorderColor(job.status);
  const k50CardBg = k50JobStatusColor(job.status) || colors.surface;
  // Phase 3 · bold-red completed card → white text/icons (web index.css cascade parity).
  const onRed = isBoldRedStatus(job.status);
  const fg = onRed ? { color: K50_ON_BOLD_RED_FG } : null;
  const _TERMINAL_STATUS = new Set(["completed", "canceled", "cancelled", "skipped", "could_not_service"]);
  const showOnMyWay = !_TERMINAL_STATUS.has((job.status || "").toLowerCase());
  const showDragHandle = rearrangeMode && isAdminForCard && onDrag;

  return (
    <Pressable
      style={[gStyles.card, { borderLeftWidth: 4, borderLeftColor: statusBorder, backgroundColor: k50CardBg }, isDragging && { opacity: 0.7, shadowOpacity: 0.3 }]}
      onPress={rearrangeMode ? undefined : onOpen}
      onLongPress={showDragHandle ? onDrag : undefined}
      testID={`grid-job-${job.id}`}
      hitSlop={4}
    >
      {rearrangeMode ? (
        <View style={gStyles.reorderBadge} testID={`grid-reorder-badge-${job.id}`}>
          <Text style={gStyles.reorderBadgeText}>{idx + 1}</Text>
        </View>
      ) : (
        <Pressable
          onPress={onCheck}
          style={[gStyles.checkbox, checked && gStyles.checkboxOn]}
          hitSlop={8}
          testID={`grid-check-${job.id}`}
        >
          {checked ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
        </Pressable>
      )}
      <View style={{ flex: 1 }}>
        <Text style={[gStyles.svcTag, { color: svc.tag }, fg]} numberOfLines={1}>
          {isRecurring(job) ? "🔁 " : ""}
          {(job.service_type || "General").toUpperCase()}
        </Text>
        {/* Phase 27 · Feb-2026 — inline tech avatar chip next to
            customer line. 20dp footprint stays under the existing
            line-height so row height is unchanged. Feb-2026 · the
            per-card tech avatar that rendered the tech's initials
            (e.g. "MR") before the customer name was removed —
            the schedule day view is already tech-scoped in the
            header, so the per-card avatar was redundant clutter. */}
        {/* ITEM 3 — Customer name + VIP pill; tapping name opens native map */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 }}>
          <Pressable
            onPress={() => {
              const c = resolveJobCoords(job);
              if (c) openNativeNavTo(c.lat, c.lng, formatCustomerName(job));
              else if (job.address) Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(job.address)}`);
            }}
            hitSlop={8}
            accessibilityLabel={`Open directions to ${formatCustomerName(job)}`}
            testID={`job-card-name-nav-${job.id}`}
          >
            <Text style={[gStyles.cust, { flexShrink: 1 }, fg]} numberOfLines={1}>{formatCustomerName(job)}</Text>
          </Pressable>
          {job.customer_is_vip ? (
            <View style={gStyles.vipBadgeInline} testID={`job-vip-badge-${job.id}`}>
              <Ionicons name="star" size={9} color="#92400E" />
              <Text style={gStyles.vipText}>VIP</Text>
            </View>
          ) : null}
          {/* CREW-SCHEDULE-FANOUT — crew role badge */}
          {job.crew_id && (job._crew_role === "direct" || job._crew_role === "member") ? (
            <View
              style={job._crew_role === "direct" ? gStyles.crewBadgeDirect : gStyles.crewBadgeMember}
              testID={`schedule-card-crew-badge-${job.id}`}
              accessibilityLabel={job._crew_role === "direct" ? "Crew lead" : "Crew member"}
            >
              <Ionicons name="people-outline" size={10} color={job._crew_role === "direct" ? "#1E3A8A" : "#3730A3"} />
              <Text style={job._crew_role === "direct" ? gStyles.crewBadgeDirectText : gStyles.crewBadgeMemberText}>
                {job._crew_role === "direct" ? "Crew lead" : "Crew member"}
              </Text>
            </View>
          ) : null}
        </View>
        {/* Address — directly below customer name, tapping opens native map */}
        {job.address ? (
          <Pressable
            onPress={() => {
              const c = resolveJobCoords(job);
              if (c) openNativeNavTo(c.lat, c.lng, formatCustomerName(job));
              else Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(job.address)}`);
            }}
            hitSlop={6}
            accessibilityLabel={`Open directions to ${job.address}`}
            testID={`job-card-addr-nav-${job.id}`}
          >
            <Text style={onRed ? { ...gStyles.addr, color: K50_ON_BOLD_RED_FG } : gStyles.addr} numberOfLines={1} ellipsizeMode="tail" testID={`job-card-addr-${job.id}`}>{job.address}</Text>
          </Pressable>
        ) : null}
        {job.property_label ? (
          <View
            style={{
              alignSelf: "flex-start",
              marginTop: 3,
              paddingHorizontal: 8,
              paddingVertical: 2,
              borderRadius: 999,
              backgroundColor: "#E0F2FE",
              borderWidth: 1,
              borderColor: "#7DD3FC",
            }}
            testID={`job-property-chip-${job.id}`}
          >
            <Text style={{ fontSize: 10, fontWeight: "700", color: "#075985" }}>
              🏠 {job.property_label}
            </Text>
          </View>
        ) : null}
        {hourlyData.length > 0 && (
          <RainFlag
            jobId={job.id}
            scheduledDate={job.scheduled_date}
            scheduledTime={job.scheduled_time}
            hourlyData={hourlyData}
          />
        )}
        {/* Feb-2026 · schedule polish — gate-code amber badge +
            optional access-instructions bullet. */}
        {(job.customer_gate_code || job.gate_code || job.access_notes) ? (
          <View style={gStyles.gateChip} testID={`job-gate-code-${job.id}`}>
            <Ionicons name="key-outline" size={11} color="#78350F" />
            {(job.customer_gate_code || job.gate_code) ? (
              <Text style={gStyles.gateText}>
                Gate: {job.customer_gate_code || job.gate_code}
              </Text>
            ) : (
              <Text style={gStyles.gateText}>Access</Text>
            )}
            {job.access_notes ? (
              <Text
                style={gStyles.gateAccessText}
                numberOfLines={1}
                testID={`job-access-notes-${job.id}`}
              >
                {` · ${job.access_notes}`}
              </Text>
            ) : null}
          </View>
        ) : null}
        {/* Feb-2026 · schedule polish — combined notes call-out.
            Job-level ``notes`` render first; ``customer_notes`` /
            ``account_notes`` follow with a "Customer note:"
            prefix.  Tap the call-out to see the full text via
            an Alert.  Empty on all three ⇒ nothing rendered. */}
        <JobNotesCallout
          jobId={job.id}
          note={job.notes}
          customerNote={job.customer_notes || job.account_notes}
          poolNote={job.service_notes_pool}
          landscapeNote={job.service_notes_landscape}
          truncated={job.notes_truncated}
        />
        {/* Phase 1 Offline Read — "Cached ✓" pill */}
        {cachedForOffline ? (
          <View style={gStyles.cachedPill} testID={`job-cached-pill-${job.id}`}>
            <Ionicons name="checkmark-circle" size={10} color="#065F46" />
            <Text style={gStyles.cachedPillText}>Cached</Text>
          </View>
        ) : null}
        {/* Phase 2 — "Pending sync" pill when job has queued writes */}
        {pendingSync ? (
          <PendingSyncPill testID={`job-pending-sync-${job.id}`} />
        ) : null}
        <View style={gStyles.metaRow}>
          <Ionicons name="reader-outline" size={12} color={onRed ? K50_ON_BOLD_RED_FG : colors.muted} />
          <Text style={[gStyles.metaText, fg]}>{jobHours(job)}</Text>
          {/* Phase 30X · time-of-day removed. Schedule is per-day. */}
        </View>
        {showOnMyWay ? (
          <OnMyWayButton
            jobId={job.id}
            customerName={job.customer_name}
            variant="compact"
            role={role}
          />
        ) : null}
        {showOnMyWay ? (
          <CouldNotServiceButton
            jobId={job.id}
            jobStatus={job.status}
            role={role}
            variant="compact"
          />
        ) : null}
        {/* Phase 3b · Navigate (Google Maps) — LAST in the action row,
            same terminal-status gate as OMW / CNS (web parity). */}
        {showOnMyWay ? <NavigateMapsButton job={job} /> : null}
      </View>
      {rearrangeMode ? (
        <View style={gStyles.reorderActions}>
          <View style={gStyles.arrowCol}>
            <Pressable onPress={() => onShift(job.id, -1)} disabled={first}
                       style={[gStyles.reorderBtn, first && { opacity: 0.3 }]}
                       testID={`grid-reorder-up-${job.id}`}>
              <Ionicons name="chevron-up" size={16} color={colors.brand} />
            </Pressable>
            <Pressable onPress={() => onShift(job.id, 1)} disabled={last}
                       style={[gStyles.reorderBtn, last && { opacity: 0.3 }]}
                       testID={`grid-reorder-down-${job.id}`}>
              <Ionicons name="chevron-down" size={16} color={colors.brand} />
            </Pressable>
          </View>
          {showDragHandle ? (
            <Pressable
              onPressIn={onDrag}
              style={gStyles.dragHandleRight}
              testID={`grid-drag-handle-${job.id}`}
            >
              <Ionicons name="reorder-three" size={20} color={colors.muted} />
            </Pressable>
          ) : null}
        </View>
      ) : (
        <View style={gStyles.cardRight}>
          <View style={[gStyles.statusPill, { backgroundColor: pill.bg }]}>
            <Text style={[gStyles.statusText, { color: pill.fg }]}>{pill.label}</Text>
          </View>
          <View style={{ flexDirection: "row", alignItems: "center" }}>
            <View testID={`grid-open-${job.id}`}>
              <Ionicons name="chevron-forward" size={20} color={onRed ? K50_ON_BOLD_RED_FG : colors.muted} />
            </View>
            {isAdminForCard && onEdit ? (
              <Pressable
                onPress={() => onEdit(job)}
                hitSlop={8}
                testID={`grid-edit-${job.id}`}
                accessibilityLabel="Edit job"
                style={gStyles.editBtn}
              >
                <Ionicons name="pencil-outline" size={16} color={onRed ? K50_ON_BOLD_RED_FG : colors.muted} />
              </Pressable>
            ) : null}
          </View>
        </View>
      )}
    </Pressable>
  );
}

/* ═══ Calendar view ══════════════════════════════════════════════════ */
function CalendarView({
  weekDays, weekTitle, jobsByDay, showBH, onToggleBH, onPrev, onNext, onOpenJob,
  weatherWidget, isAdmin, isTech, onNewJob,
}: any) {
  return (
    <View style={{ flexGrow: 1 }}>
      <View style={cStyles.head}>
        <Pressable onPress={onPrev} style={cStyles.navBtn} testID="calendar-prev-week">
          <Ionicons name="chevron-back" size={18} color={colors.onSurface} />
        </Pressable>
        <Text style={cStyles.headTitle} testID="calendar-week-title">{weekTitle}</Text>
        <Pressable onPress={onNext} style={cStyles.navBtn} testID="calendar-next-week">
          <Ionicons name="chevron-forward" size={18} color={colors.onSurface} />
        </Pressable>
        <Pressable
          onPress={onToggleBH}
          style={[cStyles.bhPill, showBH && cStyles.bhPillOn]}
          testID="calendar-toggle-bh"
        >
          <Ionicons name={showBH ? "eye-outline" : "eye-off-outline"}
                    size={12} color={showBH ? "#fff" : colors.onSurfaceSecondary} />
          <Text style={[cStyles.bhPillText, showBH && { color: "#fff" }]}>BH</Text>
        </Pressable>
        {onNewJob ? (
          <Pressable onPress={onNewJob} style={gStyles.newBtn} testID="mobile-schedule-add-job-btn-calendar" accessibilityLabel="Add job">
            <Ionicons name="add-circle" size={14} color="#fff" />
            <Text style={gStyles.newBtnText}>Add job</Text>
          </Pressable>
        ) : null}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} nestedScrollEnabled>
        <View style={{ flexDirection: "row" }}>
          {weekDays.map((d: Date) => {
            const key = iso(d);
            const dayJ: Job[] = (jobsByDay[key] || []).slice();
            const isToday = key === iso(new Date());
            return (
              <View key={key} style={cStyles.col} testID={`calendar-col-${key}`}>
                <View style={[cStyles.colHead, isToday && cStyles.colHeadToday]}>
                  <Text style={[cStyles.colDow, isToday && { color: "#fff" }]}>
                    {d.toLocaleDateString(undefined, { weekday: "short" }).toUpperCase()}
                  </Text>
                  <Text style={[cStyles.colDay, isToday && { color: "#fff" }]}>{d.getDate()}</Text>
                </View>
                {dayJ.length === 0 ? (
                  <Text style={cStyles.colEmpty}>—</Text>
                ) : (() => {
                  // Phase SRL sort kept for visual consistency only.
                  dayJ.sort((a: Job, b: Job) =>
                    (a.route_index ?? a.route_order ?? 999) - (b.route_index ?? b.route_order ?? 999));
                  return dayJ.map((j) => {
                  const svc = SERVICE_COLOR(j.service_type);
                  return (
                    <Pressable
                      key={j.id}
                      onPress={() => onOpenJob(j.id)}
                      style={[cStyles.eventCard, { backgroundColor: svc.bg, borderLeftColor: svc.tag }]}
                      testID={`calendar-event-${j.id}`}
                    >
                      <Text style={[cStyles.eventTitle, { color: svc.fg }]} numberOfLines={2}>
                        {isRecurring(j) ? "🔁 " : ""}
                        {j.service_type || j.title || "Job"}
                      </Text>
                      <Text style={[cStyles.eventCust, { color: svc.fg }]} numberOfLines={1}>
                        {j.customer_is_vip ? "★ " : ""}{formatCustomerName(j)}
                      </Text>
                      {/* CREW-SCHEDULE-FANOUT — compact crew badge in calendar card */}
                      {j.crew_id && (j._crew_role === "direct" || j._crew_role === "member") ? (
                        <View
                          style={j._crew_role === "direct" ? gStyles.crewBadgeDirect : gStyles.crewBadgeMember}
                          testID={`schedule-card-crew-badge-${j.id}`}
                          accessibilityLabel={j._crew_role === "direct" ? "Crew lead" : "Crew member"}
                        >
                          <Ionicons name="people-outline" size={9} color={j._crew_role === "direct" ? "#1E3A8A" : "#3730A3"} />
                          <Text style={j._crew_role === "direct" ? gStyles.crewBadgeDirectText : gStyles.crewBadgeMemberText}>
                            {j._crew_role === "direct" ? "Lead" : "Member"}
                          </Text>
                        </View>
                      ) : null}
                      {showBH ? (
                        <Text style={[cStyles.eventBH, { color: svc.fg }]}>{jobHours(j)}</Text>
                      ) : null}
                    </Pressable>
                  );
                  });
                })()}
              </View>
            );
          })}
        </View>
      </ScrollView>

      {weatherWidget ? (
        <View style={{ paddingHorizontal: spacing.md, paddingTop: spacing.lg, paddingBottom: spacing["3xl"] }} testID="calendar-weather-bottom">
          {weatherWidget}
        </View>
      ) : null}

      {/* P37c · GPS consent modal — shown once per session for techs without active consent */}
      {isTech ? <GpsConsentModal /> : null}
    </View>
  );
}

/* ═══ Styles ═════════════════════════════════════════════════════════ */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  modeSwitch: {
    flexDirection: "row",
    gap: spacing.xs,
    padding: spacing.md,
    paddingBottom: spacing.xs,
  },
  modeBtn: {
    flex: 1, height: 38,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  modeBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  modeBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  errBar: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    margin: spacing.md, marginTop: 0,
    padding: spacing.sm, borderRadius: radius.md,
    backgroundColor: "#FEE2E2",
  },
  errText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B" },
  // K15 · prominent error card with retry action
  errCard: {
    marginHorizontal: spacing.lg, marginBottom: spacing.md,
    padding: spacing.md, borderRadius: radius.lg,
    backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FCA5A5",
    gap: spacing.sm,
  },
  noProfileCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    marginHorizontal: spacing.lg, marginBottom: spacing.md,
    padding: spacing.md, borderRadius: radius.lg,
    backgroundColor: "#FFFBEB", borderWidth: 1, borderColor: "#FCD34D",
  },
  noProfileText: {
    flex: 1, fontFamily: font.medium, fontSize: fontSize.sm,
    color: "#92400E", lineHeight: 20,
  },
  errCardRow: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm,
  },
  errCardText: {
    flex: 1, fontFamily: font.medium, fontSize: fontSize.sm,
    color: "#991B1B", lineHeight: 20,
  },
  errCardActions: {
    flexDirection: "row", gap: spacing.sm,
  },
  errRetryBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 8,
  },
  errRetryText: {
    fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff",
  },
  // Phase S1 — Tech filter dropdown
  techFilterRow: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xs,
  },
  techFilterBtn: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  techFilterLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    maxWidth: 160,
  },
  cancelledToggleRow: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xs,
  },
  cancelledToggleBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingVertical: 6,
  },
  cancelledToggleText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  cancelledCountPill: {
    backgroundColor: colors.error,
    borderRadius: 999,
    minWidth: 18,
    height: 18,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 5,
  },
  cancelledCountText: {
    fontFamily: font.bold,
    fontSize: 10,
    color: "#fff",
  },
});

const gStyles = StyleSheet.create({
  mapToggleBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: spacing.sm,
    marginBottom: spacing.xs,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  mapToggleText: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  vipBadge: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    gap: 2, backgroundColor: "#FEF3C7", borderColor: "#F59E0B", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill,
    marginTop: 2,
  },
  vipBadgeInline: {
    flexDirection: "row", alignItems: "center",
    gap: 2, backgroundColor: "#FEF3C7", borderColor: "#F59E0B", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill,
  },
  refreshBtn: {
    width: 34, height: 34, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  syncToast: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#F0FDF4", borderWidth: 1, borderColor: "#BBF7D0",
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
    marginHorizontal: spacing.lg, marginTop: spacing.xs,
  },
  syncToastText: {
    fontFamily: font.medium, fontSize: 12, color: "#166534",
  },
  cacheFreshnessRow: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.lg, paddingTop: 4, paddingBottom: 2,
  },
  cacheFreshnessText: {
    fontFamily: font.regular, fontSize: 10, color: colors.muted,
  },
  cachedPill: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    gap: 3, backgroundColor: "#ECFDF5", borderColor: "#A7F3D0", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill,
    marginTop: 3,
  },
  cachedPillText: {
    fontFamily: font.bold, fontSize: 9, color: "#065F46",
    letterSpacing: 0.4, textTransform: "uppercase",
  },
  vipText: {
    fontFamily: font.bold, fontSize: 9, color: "#92400E",
    letterSpacing: 0.8, textTransform: "uppercase",
  },
  // CREW-SCHEDULE-FANOUT — crew role badge styles
  crewBadgeDirect: {
    flexDirection: "row", alignItems: "center",
    gap: 3, backgroundColor: "#DBEAFE", borderColor: "#3B82F6", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill,
  },
  crewBadgeMember: {
    flexDirection: "row", alignItems: "center",
    gap: 3, backgroundColor: "#E0E7FF", borderColor: "#6366F1", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill,
  },
  crewBadgeDirectText: {
    fontFamily: font.bold, fontSize: 9, color: "#1E3A8A",
    letterSpacing: 0.4, textTransform: "uppercase",
  },
  crewBadgeMemberText: {
    fontFamily: font.bold, fontSize: 9, color: "#3730A3",
    letterSpacing: 0.4, textTransform: "uppercase",
  },
  gateChip: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 4,
    backgroundColor: "#FEF3C7", borderColor: "#FCD34D", borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6, marginTop: 4,
    maxWidth: "100%",
  },
  gateText: {
    fontFamily: font.bold, fontSize: 10, color: "#78350F",
    letterSpacing: 0.5,
  },
  gateAccessText: {
    fontFamily: font.medium, fontSize: 10, color: "#78350F",
    flexShrink: 1,
  },
  notesCallout: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    backgroundColor: "#EFF6FF", borderColor: "#BFDBFE", borderWidth: 1,
    borderLeftColor: "#3B82F6", borderLeftWidth: 4,
    paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6,
    marginTop: 4,
  },
  notesCalloutJobText: {
    fontFamily: font.medium, fontSize: 11, color: "#1E3A8A", lineHeight: 15,
  },
  notesCalloutCustText: {
    fontFamily: font.regular, fontSize: 11, color: "#3730A3", lineHeight: 15,
    marginTop: 2,
  },
  notePreview: {
    fontFamily: font.regular, fontSize: 10, color: colors.onSurfaceSecondary,
    marginTop: 2,
  },
  dayHead: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  navBtn: {
    width: 34, height: 34, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  todayPill: {
    paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  todayPillActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  todayText: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.onSurface },
  dayLabel: {
    flex: 1, textAlign: "right",
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
  },
  pillRow: {
    flexDirection: "row", gap: spacing.xs, flexWrap: "wrap",
    marginBottom: spacing.sm,
  },
  pill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, height: 34,
    borderRadius: radius.pill,
  },
  pillGreen:  { backgroundColor: "#059669" },
  pillBlue:   { backgroundColor: "#2563EB" },
  pillRed:    { backgroundColor: "#DC2626" },
  pillOrange: { backgroundColor: "#D97706" },
  pillPurple: { backgroundColor: "#7C3AED" },
  pillGrey:   { backgroundColor: "#6B7280" },
  pillText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
  moveBox: {
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    gap: spacing.xs, marginBottom: spacing.sm,
  },
  moveLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  moveInput: {
    height: 42, borderRadius: radius.md,
    borderWidth: 1.5, borderColor: colors.border,
    paddingHorizontal: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  moveBtn: { flex: 1, height: 38, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  moveBtnCancel: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  moveBtnCancelText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  moveBtnGo: { backgroundColor: colors.brand },
  moveBtnGoText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  card: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm,
    padding: spacing.md, marginBottom: spacing.xs,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  cardRight: {
    alignSelf: "stretch",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: 6,
    paddingLeft: 4,
  },
  checkbox: {
    width: 22, height: 22, borderRadius: 11,
    borderWidth: 1.5, borderColor: colors.muted,
    alignItems: "center", justifyContent: "center",
  },
  checkboxOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  reorderCol: { alignItems: "center", justifyContent: "center", gap: 2, width: 32 },
  reorderBtn: { padding: 2, borderRadius: 4 },
  reorderIdx: { fontFamily: font.bold, fontSize: 10, color: colors.brand },
  svcTag: {
    fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5,
  },
  cust: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  addr: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 1 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  metaText: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.muted },
  statusPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.pill },
  statusText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.4 },
  empty: {
    alignItems: "center", justifyContent: "center",
    padding: spacing["3xl"], gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border,
  },
  emptyTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  // K36 · Loading watchdog fallback card.
  timeoutBox: {
    alignItems: "center",
    padding: spacing.xl,
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginHorizontal: spacing.md,
  },
  timeoutTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    textAlign: "center",
  },
  timeoutHint: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 18,
  },
  timeoutBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    height: 38,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    marginTop: spacing.xs,
  },
  timeoutBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  subModeRow: {
    flexDirection: "row", gap: spacing.xs, marginBottom: spacing.sm,
  },
  subModeBtn: {
    flex: 1, height: 32,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 4,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  subModeBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  subModeText: { fontFamily: font.bold, fontSize: 11, color: colors.onSurfaceSecondary },
  dragHandle: {
    justifyContent: "center", alignItems: "center",
    width: 28, marginRight: 2,
  },
  dragHandleRight: {
    justifyContent: "center", alignItems: "center",
    width: 32, height: 44,
  },
  reorderBadge: {
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: "#059669",
    alignItems: "center", justifyContent: "center",
  },
  reorderBadgeText: {
    fontFamily: font.bold, fontSize: 11, color: "#fff",
  },
  reorderActions: {
    flexDirection: "row", alignItems: "center", gap: 4, marginLeft: 4,
  },
  arrowCol: {
    alignItems: "center", justifyContent: "center", gap: 2,
  },
  reorderHeader: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    marginBottom: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: "#ECFDF5",
    borderWidth: 1, borderColor: "#A7F3D0",
  },
  reorderHeaderTitle: {
    fontFamily: font.bold, fontSize: fontSize.base, color: "#059669",
  },
  reorderHeaderSub: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: "#065F46",
    marginTop: 1,
  },
  reorderBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "flex-end",
    gap: spacing.sm, marginBottom: spacing.sm,
  },
  reorderCancelBtn: {
    paddingHorizontal: spacing.md, height: 36, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  reorderCancelText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  reorderSaveBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.lg, height: 36, borderRadius: radius.md,
    backgroundColor: "#059669",
  },
  reorderSaveText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  filterRow: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm,
    marginBottom: spacing.sm, flexWrap: "wrap",
  },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, height: 36, borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  newBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  // Feb-2026 · Schedule inline-edit — Pencil affordance on admin cards.
  editBtn: { padding: spacing.xs, marginLeft: spacing.xs, alignSelf: "center" },
});

const cStyles = StyleSheet.create({
  head: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    paddingHorizontal: spacing.md, paddingBottom: spacing.xs,
  },
  navBtn: {
    width: 32, height: 32, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  headTitle: { flex: 1, textAlign: "center", fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  bhPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, height: 30, borderRadius: radius.pill,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  bhPillOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  bhPillText: { fontFamily: font.bold, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  col: { width: 148, marginHorizontal: 4 },
  colHead: {
    paddingVertical: spacing.xs, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", marginBottom: spacing.xs,
  },
  colHeadToday: { backgroundColor: colors.brand, borderColor: colors.brand },
  colDow: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.8 },
  colDay: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  colEmpty: { textAlign: "center", fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: spacing.sm },
  eventCard: {
    padding: spacing.sm, marginBottom: spacing.xs,
    borderRadius: radius.md,
    borderLeftWidth: 3,
  },
  eventTitle: { fontFamily: font.bold, fontSize: fontSize.xs, lineHeight: 14 },
  eventCust: { fontFamily: font.regular, fontSize: 10, marginTop: 2 },
  eventBH: { fontFamily: font.semibold, fontSize: 10, marginTop: 2, opacity: 0.85 },
});


/* Phase P18 — Actions dropdown menu styles. */
const actMenuStyles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.35)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.xl,
  },
  sheet: {
    width: "100%",
    maxWidth: 320,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: 2,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.18, shadowRadius: 12 },
      android: { elevation: 8 },
      default: {},
    }),
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: 12,
    paddingHorizontal: spacing.xs,
    borderRadius: radius.md,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  rowLabel: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
});

// Phase S1 — Tech filter picker modal styles.
const techPickerStyles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.35)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.xl,
  },
  sheet: {
    width: "100%",
    maxWidth: 340,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.18, shadowRadius: 12 },
      android: { elevation: 8 },
      default: {},
    }),
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: 12,
    paddingHorizontal: spacing.xs,
    borderRadius: radius.md,
  },
  rowActive: {
    backgroundColor: colors.brandTertiary || "#EFF6FF",
  },
  rowLabel: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  empty: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: 20,
  },
});


/**
 * K36 · Default export is now wrapped in `ScheduleErrorBoundary` so
 * a render throw inside the Schedule screen surfaces as an
 * actionable card + a diagnostic breadcrumb instead of tanking the
 * whole tab (and, on iOS, tripping the 0x8badf00d watchdog).
 */
export default function ScheduleCalendar() {
  return (
    <ScheduleErrorBoundary>
      <ScheduleCalendarInner />
    </ScheduleErrorBoundary>
  );
}
