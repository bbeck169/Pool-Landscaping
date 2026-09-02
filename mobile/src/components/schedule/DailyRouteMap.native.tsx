/**
 * Daily Route Map — Feb-2026 · Mobile-only tech schedule feature.
 *
 * Renders numbered @rnmapbox/maps pins for the currently-focused day's
 * jobs. Sits above the day's job list on the tech schedule screen.
 *
 *   • Collapsible header (chevron) — expand/collapse state persisted
 *     in AsyncStorage keyed by user_id. Default = expanded on the
 *     first load for that tech; only user-driven toggles write to
 *     storage.
 *   • Numbered pins based on job.route_index (fallback = 1-based
 *     position in the incoming ``jobs`` array).
 *   • Pin appearance maps to job status:
 *       – pending / upcoming  → brand blue with white index number
 *       – completed           → gray with white check + tiny index
 *       – could_not_service   → amber with warning icon + tiny index
 *   • Pin tap → floating callout card (Customer name, Service
 *     address, Scheduled time window, "Open" → /job/{id}/checklist).
 *   • Coords: reads job.property.location.{lat,lng} first; falls
 *     back to flat location_lat/location_lng, then a couple of
 *     legacy shapes (job.location, job.service_address.coordinates).
 *     Jobs missing coords stay OFF the map — they still render in
 *     the list. No client-side geocoding.
 *   • Camera: auto-fit bounds with padding for >1 pin, zoom ~15 on
 *     the single-pin case.
 *   • Fallback banner rendered when process.env.EXPO_PUBLIC_MAPBOX_TOKEN
 *     is missing OR the @rnmapbox/maps native module cannot be
 *     required (plain Expo Go).
 *   • If 0 jobs are scheduled for the day, the entire component
 *     returns null (parent doesn't need to gate the render).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
// Feb-2026 · Optimize Route (tech→admin approval + 10s undo).
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { geolocate } from "@/src/utils/geolocate";
import OptimizeRoutePreview from "@/src/components/schedule/OptimizeRoutePreview";
import { hasMapboxToken, MapUnavailablePlaceholder } from "@/src/utils/mapsKey";

const PINNED_STATUSES = new Set([
  "completed", "could_not_service", "skipped", "canceled", "cancelled",
]);
const UNDO_WINDOW_MS = 10_000;

// Dynamic require — throws in Expo Go without the dev-client. We
// catch and render the fallback banner instead of crashing.
let MapboxGL: any = null;
let mapboxImportError: string | null = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  MapboxGL = require("@rnmapbox/maps").default;
} catch (e: any) {
  mapboxImportError = e?.message || String(e);
}

/* ── Types ─────────────────────────────────────────────────────────── */

export type RouteMapJob = {
  id: string;
  status?: string | null;
  route_index?: number | null;
  route_order?: number | null;
  scheduled_date?: string | null;
  customer_name?: string | null;
  address?: string | null;
  service_address?: any;
  scheduled_time?: string | null;
  scheduled_time_end?: string | null;
  time_window?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
  location?: { lat?: number | null; lng?: number | null; lon?: number | null } | null;
  property?: {
    location?: { lat?: number | null; lng?: number | null; lon?: number | null } | null;
  } | null;
};

export interface DailyRouteMapProps {
  jobs: RouteMapJob[];
  userId: string;
  /** Optional override — defaults to router.push(`/job/{id}/checklist`). */
  onOpenJob?: (jobId: string) => void;
  testID?: string;
}

/* ── Helpers ───────────────────────────────────────────────────────── */

const STORAGE_KEY_PREFIX = "schedule_daily_map_expanded_v1:";

/**
 * Resolve pin coordinates from a job, tolerating the legacy shapes
 * that exist in this codebase. Preference order (per the Feb-2026
 * brief): property.location → flat location_lat/lng → job.location
 * → service_address.coordinates. First hit wins.
 */
export function resolveJobCoords(job: RouteMapJob): { lat: number; lng: number } | null {
  const trySet = (lat: any, lng: any): { lat: number; lng: number } | null => {
    const la = Number(lat);
    const lo = Number(lng);
    if (Number.isFinite(la) && Number.isFinite(lo) && (la !== 0 || lo !== 0)) {
      return { lat: la, lng: lo };
    }
    return null;
  };
  const canonical = job.property?.location;
  if (canonical) {
    const hit = trySet(canonical.lat, canonical.lng ?? canonical.lon);
    if (hit) return hit;
  }
  const flat = trySet(job.location_lat, job.location_lng);
  if (flat) return flat;
  if (job.location) {
    const hit = trySet(job.location.lat, job.location.lng ?? job.location.lon);
    if (hit) return hit;
  }
  const sa = job.service_address?.coordinates;
  if (sa) {
    const hit = trySet(sa.lat ?? sa.latitude, sa.lng ?? sa.lon ?? sa.longitude);
    if (hit) return hit;
  }
  return null;
}

type PinKind = "pending" | "completed" | "cns";

export function statusKind(status?: string | null): PinKind {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "completed";
  if (s === "could_not_service" || s === "skipped" || s === "canceled" || s === "cancelled") return "cns";
  return "pending";
}

const PIN_BG: Record<PinKind, string> = {
  pending: "#2563EB",    // brand blue — mirrors STATUS_PILL.scheduled
  completed: "#6B7280",  // slate/gray
  cns: "#F59E0B",        // amber
};

/** Prefer scheduled_time / scheduled_time_end range, else time_window, else scheduled_time alone. */
function formatTimeWindow(job: RouteMapJob): string {
  if (job.scheduled_time && job.scheduled_time_end) {
    return `${job.scheduled_time} – ${job.scheduled_time_end}`;
  }
  if (job.time_window) return job.time_window;
  if (job.scheduled_time) return job.scheduled_time;
  return "";
}

function jobAddress(job: RouteMapJob): string {
  if (job.address) return job.address;
  const sa: any = job.service_address;
  if (typeof sa === "string") return sa;
  if (sa && typeof sa === "object") {
    return [sa.line1, sa.city, sa.state].filter(Boolean).join(", ");
  }
  return "";
}

/* ── Component ─────────────────────────────────────────────────────── */

export default function DailyRouteMap({ jobs, userId, onOpenJob, testID }: DailyRouteMapProps) {
  const router = useRouter();
  const { user } = useAuth();
  const role = ((user?.role as string) || "").toLowerCase();
  const isAdmin = role === "admin" || role === "super_admin";
  const cameraRef = useRef<any>(null);
  const [expanded, setExpanded] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // ── Optimize Route state (Feb-2026) ───────────────────────────────
  type Preview = {
    proposed_order: string[];
    miles_saved: number;
    minutes_saved: number;
    stops_affected: number;
    no_change: boolean;
    fallback_origin: boolean;
  };
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [applyBusy, setApplyBusy] = useState(false);
  const [pendingSubmitted, setPendingSubmitted] = useState(false);
  const [undoState, setUndoState] = useState<{ appliedId: string; expiresAt: number } | null>(null);
  const [undoBusy, setUndoBusy] = useState(false);
  const [suggestionToast, setSuggestionToast] = useState(false);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suggestionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate persisted expand/collapse state — only if a value was
  // ever written. First-load default is expanded.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!userId) return;
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY_PREFIX + userId);
        if (!cancelled && raw != null) setExpanded(raw === "1");
      } catch {
        /* keep default */
      }
    })();
    return () => { cancelled = true; };
  }, [userId]);

  // Numbered, coord-bearing pins in stable order (input list order,
  // so route_index labels stay aligned with the parent's list).
  const pins = useMemo(() => {
    return jobs
      .map((j, idx) => {
        const coords = resolveJobCoords(j);
        if (!coords) return null;
        const num = Number.isFinite(j.route_index as any)
          ? Number(j.route_index)
          : Number.isFinite(j.route_order as any)
            ? Number(j.route_order)
            : idx + 1;
        return { job: j, coords, num, kind: statusKind(j.status) };
      })
      .filter(Boolean) as {
        job: RouteMapJob;
        coords: { lat: number; lng: number };
        num: number;
        kind: PinKind;
      }[];
  }, [jobs]);

  // Camera fit — bounds w/ padding for >1 pin, zoom 15 for single.
  useEffect(() => {
    if (!expanded || !cameraRef.current || pins.length === 0) return;
    if (pins.length === 1) {
      cameraRef.current.setCamera?.({
        centerCoordinate: [pins[0].coords.lng, pins[0].coords.lat],
        zoomLevel: 15,
        animationDuration: 350,
      });
      return;
    }
    const lats = pins.map((p) => p.coords.lat);
    const lngs = pins.map((p) => p.coords.lng);
    const ne: [number, number] = [Math.max(...lngs), Math.max(...lats)];
    const sw: [number, number] = [Math.min(...lngs), Math.min(...lats)];
    cameraRef.current.fitBounds?.(ne, sw, [48, 48, 48, 48], 350);
  }, [pins, expanded]);

  /* ── Optimize Route — auto-preview + handlers ───────────────────── */

  const scheduleDate = useMemo(() => {
    // Every job in ``jobs`` shares the currently-focused day; take the
    // first non-empty scheduled_date. Falls back to today so /preview
    // never receives an empty date string.
    const d = jobs.find((j) => (j.scheduled_date || "").length >= 10)?.scheduled_date;
    if (d && d.length >= 10) return d.slice(0, 10);
    return new Date().toISOString().slice(0, 10);
  }, [jobs]);

  const reshufflableCount = useMemo(
    () => pins.filter((p) => !PINNED_STATUSES.has((p.job.status || "").toLowerCase())).length,
    [pins],
  );

  // Auto-fetch preview when the map is expanded and there are enough
  // reshufflable stops to matter. Uses first pending stop as origin so
  // no GPS request happens on mount. On-tap we re-fetch with real GPS.
  useEffect(() => {
    if (pendingSubmitted || undoState) { setPreview(null); return; }
    if (!expanded || reshufflableCount < 2 || !scheduleDate) { setPreview(null); return; }
    const firstPending = pins.find((p) => !PINNED_STATUSES.has((p.job.status || "").toLowerCase()));
    if (!firstPending) { setPreview(null); return; }
    let cancelled = false;
    (async () => {
      setPreviewLoading(true);
      try {
        const res: any = await api.post("/jobs/route-optimization/preview", {
          date: scheduleDate,
          current_lat: firstPending.coords.lat,
          current_lng: firstPending.coords.lng,
        });
        if (!cancelled) {
          setPreview({
            proposed_order: res.proposed_order || [],
            miles_saved: Number(res.miles_saved || res.estimated_miles_saved || 0),
            minutes_saved: Number(res.minutes_saved || res.estimated_minutes_saved || 0),
            stops_affected: Number(res.stops_affected || 0),
            no_change: !!res.no_change,
            fallback_origin: true,
          });
        }
      } catch {
        if (!cancelled) setPreview(null);
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [expanded, reshufflableCount, scheduleDate, pendingSubmitted, undoState, pins]);

  // Cleanup any pending timers on unmount.
  useEffect(() => {
    return () => {
      if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
      if (suggestionTimerRef.current) clearTimeout(suggestionTimerRef.current);
    };
  }, []);

  const showPill =
    reshufflableCount >= 2 &&
    !pendingSubmitted &&
    !undoState &&
    preview !== null &&
    !preview.no_change &&
    preview.miles_saved > 0;

  const onOptimizePillTap = useCallback(async () => {
    // Ask for real GPS. Fall back to first-pending on denial.
    const gps = await geolocate();
    let usedFallback = false;
    let lat = gps.lat;
    let lng = gps.lng;
    if (lat == null || lng == null) {
      const firstPending = pins.find((p) => !PINNED_STATUSES.has((p.job.status || "").toLowerCase()));
      if (!firstPending) return;
      lat = firstPending.coords.lat;
      lng = firstPending.coords.lng;
      usedFallback = true;
    }
    try {
      const res: any = await api.post("/jobs/route-optimization/preview", {
        date: scheduleDate,
        current_lat: lat,
        current_lng: lng,
      });
      setPreview({
        proposed_order: res.proposed_order || [],
        miles_saved: Number(res.miles_saved || res.estimated_miles_saved || 0),
        minutes_saved: Number(res.minutes_saved || res.estimated_minutes_saved || 0),
        stops_affected: Number(res.stops_affected || 0),
        no_change: !!res.no_change,
        fallback_origin: usedFallback,
      });
      setModalOpen(true);
    } catch {
      /* silent — preview banner will remain in prior state */
    }
  }, [pins, scheduleDate]);

  const onApply = useCallback(async () => {
    if (!preview) return;
    setApplyBusy(true);
    try {
      if (isAdmin) {
        const res: any = await api.post("/jobs/route-optimization/apply", {
          tech_user_id: userId,
          date: scheduleDate,
          proposed_order: preview.proposed_order,
          miles_saved: preview.miles_saved,
          minutes_saved: preview.minutes_saved,
        });
        setModalOpen(false);
        setPreview(null);
        // Start the 10s undo countdown.
        const appliedId = res.applied_id;
        const expiresAt = Date.now() + UNDO_WINDOW_MS;
        setUndoState({ appliedId, expiresAt });
        if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
        undoTimerRef.current = setTimeout(() => {
          setUndoState(null);
        }, UNDO_WINDOW_MS);
      } else {
        // Tech request path.
        await api.post("/jobs/route-optimization/request", {
          date: scheduleDate,
          current_lat: undefined,
          current_lng: undefined,
        });
        setModalOpen(false);
        setPendingSubmitted(true);
        setSuggestionToast(true);
        if (suggestionTimerRef.current) clearTimeout(suggestionTimerRef.current);
        suggestionTimerRef.current = setTimeout(() => setSuggestionToast(false), 4000);
      }
    } catch {
      /* swallow — parent list still shows original order */
    } finally {
      setApplyBusy(false);
    }
  }, [preview, isAdmin, userId, scheduleDate]);

  const onUndo = useCallback(async () => {
    if (!undoState) return;
    setUndoBusy(true);
    try {
      await api.post("/jobs/route-optimization/undo", { applied_id: undoState.appliedId });
    } catch {
      /* client can't do anything meaningful — server enforces the window */
    } finally {
      if (undoTimerRef.current) { clearTimeout(undoTimerRef.current); undoTimerRef.current = null; }
      setUndoState(null);
      setUndoBusy(false);
    }
  }, [undoState]);

  // Feature-level guard — 0 jobs scheduled = hide entire map.
  if (!jobs || jobs.length === 0) return null;

  const hasToken = hasMapboxToken();

  const toggleExpanded = async () => {
    setSelectedId(null);
    setExpanded((prev) => {
      const next = !prev;
      // Persist only on user-driven toggle.
      if (userId) {
        AsyncStorage.setItem(STORAGE_KEY_PREFIX + userId, next ? "1" : "0").catch(() => {});
      }
      return next;
    });
  };

  const openJob = (id: string) => {
    setSelectedId(null);
    if (onOpenJob) return onOpenJob(id);
    router.push(`/job/${id}/checklist` as any);
  };

  const selectedPin = selectedId ? pins.find((p) => p.job.id === selectedId) : null;

  /* ── Header (chevron toggle) ─────────────────────────────────────── */
  const header = (
    <View style={s.header}>
      <View style={s.headerLeft}>
        <Ionicons name="navigate-outline" size={14} color={colors.onSurface} />
        <Text style={s.headerTitle} testID="schedule-daily-route-map-title">
          Route ({pins.length}{pins.length !== jobs.length ? ` of ${jobs.length}` : ""})
        </Text>
      </View>
      <View style={s.headerRight}>
        {showPill ? (
          <Pressable
            onPress={onOptimizePillTap}
            style={s.optimizePill}
            hitSlop={6}
            testID="optimize-route-pill"
            accessibilityLabel="Optimize route order"
          >
            <Ionicons name="flash-outline" size={12} color="#fff" />
            <Text style={s.optimizePillText} testID="optimize-route-pill-savings">
              Optimize · {preview!.miles_saved.toFixed(1)} mi
            </Text>
          </Pressable>
        ) : null}
        {previewLoading && !showPill ? (
          <ActivityIndicator size="small" color={colors.muted}
                              testID="optimize-route-preview-loading" />
        ) : null}
        <Pressable
          onPress={toggleExpanded}
          style={s.toggle}
          hitSlop={8}
          testID="schedule-daily-route-map-toggle"
          accessibilityLabel={expanded ? "Collapse route map" : "Expand route map"}
        >
          <Ionicons
            name={expanded ? "chevron-up" : "chevron-down"}
            size={18}
            color={colors.onSurface}
          />
        </Pressable>
      </View>
    </View>
  );

  return (
    <View style={s.container} testID={testID || "schedule-daily-route-map"}>
      {header}

      {!expanded ? null : !hasToken || !MapboxGL ? (
        <MapUnavailablePlaceholder
          provider="Mapbox"
          testID="schedule-daily-route-map-token-banner"
          message="Mapbox token not configured. Route map requires a valid access token."
        />
      ) : (
        <View style={s.mapWrap} testID="schedule-daily-route-map-canvas">
          <MapboxGL.MapView
            style={s.map}
            styleURL="mapbox://styles/mapbox/streets-v12"
            logoEnabled={false}
            attributionEnabled={false}
            testID="schedule-daily-route-map-view"
          >
            <MapboxGL.Camera
              ref={cameraRef}
              zoomLevel={pins.length === 1 ? 15 : 10}
              centerCoordinate={
                pins.length > 0
                  ? [pins[0].coords.lng, pins[0].coords.lat]
                  : [-112.074, 33.4484]
              }
            />
            {pins.map((p) => (
              <MapboxGL.PointAnnotation
                key={p.job.id}
                id={`schedule-daily-route-map-pin-${p.job.id}`}
                coordinate={[p.coords.lng, p.coords.lat]}
                onSelected={() => setSelectedId(p.job.id)}
              >
                <RoutePinView pinKind={p.kind} num={p.num} jobId={p.job.id} />
              </MapboxGL.PointAnnotation>
            ))}
          </MapboxGL.MapView>

          {pins.length === 0 ? (
            <View style={s.emptyOverlay} testID="schedule-daily-route-map-no-coords">
              <Text style={s.emptyOverlayText}>No mapped stops for this day</Text>
            </View>
          ) : null}

          {selectedPin ? (
            <View style={s.callout} testID="schedule-daily-route-map-callout">
              <View style={s.calloutHeader}>
                <View style={{ flex: 1 }}>
                  <Text
                    style={s.calloutName}
                    numberOfLines={1}
                    testID="schedule-daily-route-map-callout-name"
                  >
                    {selectedPin.job.customer_name || "Job"}
                  </Text>
                  {jobAddress(selectedPin.job) ? (
                    <Text
                      style={s.calloutAddr}
                      numberOfLines={2}
                      testID="schedule-daily-route-map-callout-address"
                    >
                      {jobAddress(selectedPin.job)}
                    </Text>
                  ) : null}
                  {formatTimeWindow(selectedPin.job) ? (
                    <Text
                      style={s.calloutTime}
                      numberOfLines={1}
                      testID="schedule-daily-route-map-callout-time"
                    >
                      {formatTimeWindow(selectedPin.job)}
                    </Text>
                  ) : null}
                </View>
                <Pressable
                  onPress={() => setSelectedId(null)}
                  hitSlop={8}
                  testID="schedule-daily-route-map-callout-close"
                  accessibilityLabel="Close route pin details"
                >
                  <Ionicons name="close" size={18} color={colors.muted} />
                </Pressable>
              </View>
              <Pressable
                onPress={() => openJob(selectedPin.job.id)}
                style={s.openBtn}
                testID="schedule-daily-route-map-callout-open"
              >
                <Ionicons name="open-outline" size={14} color="#fff" />
                <Text style={s.openBtnLabel}>Open</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      )}

      {/* Feb-2026 · Optimize Route — undo toast (10 s auto-dismiss). */}
      {undoState ? (
        <View style={s.undoToast} testID="optimize-route-undo-toast">
          <Ionicons name="checkmark-circle" size={16} color="#fff" />
          <Text style={s.undoText}>Route optimized</Text>
          <Pressable
            onPress={onUndo}
            disabled={undoBusy}
            style={[s.undoBtn, undoBusy && { opacity: 0.6 }]}
            testID="optimize-route-undo-btn"
            accessibilityLabel="Undo route optimization"
          >
            {undoBusy
              ? <ActivityIndicator size="small" color="#fff" />
              : <Text style={s.undoBtnLabel}>Undo</Text>}
          </Pressable>
        </View>
      ) : null}

      {/* Feb-2026 · Optimize Route — tech "suggestion sent" toast. */}
      {suggestionToast ? (
        <View style={s.suggestionToast} testID="optimize-route-suggestion-toast">
          <Ionicons name="paper-plane-outline" size={14} color="#fff" />
          <Text style={s.suggestionText}>
            Suggestion sent to dispatcher — you'll be notified when approved.
          </Text>
        </View>
      ) : null}

      {/* Feb-2026 · Optimize Route — preview modal. */}
      <OptimizeRoutePreview
        visible={modalOpen}
        stopsAffected={preview?.stops_affected || 0}
        milesSaved={preview?.miles_saved || 0}
        minutesSaved={preview?.minutes_saved || 0}
        role={role}
        fallbackOrigin={!!preview?.fallback_origin}
        busy={applyBusy}
        onApply={onApply}
        onCancel={() => setModalOpen(false)}
      />
    </View>
  );
}

/* ── Pin subview ───────────────────────────────────────────────────── */

function RoutePinView({
  pinKind, num, jobId,
}: { pinKind: PinKind; num: number; jobId: string }) {
  const bg = PIN_BG[pinKind];
  return (
    <View
      style={[s.pin, { backgroundColor: bg }]}
      testID={`schedule-daily-route-map-pin-view-${jobId}`}
      accessibilityLabel={`Route stop ${num} (${pinKind})`}
    >
      <Text style={s.pinNumber} testID={`schedule-daily-route-map-pin-num-${jobId}`}>
        {num}
      </Text>
      {pinKind === "completed" ? (
        <View style={[s.pinBadge, { backgroundColor: "#fff" }]} testID={`schedule-daily-route-map-pin-badge-completed-${jobId}`}>
          <Ionicons name="checkmark" size={9} color={PIN_BG.completed} />
        </View>
      ) : null}
      {pinKind === "cns" ? (
        <View style={[s.pinBadge, { backgroundColor: "#fff" }]} testID={`schedule-daily-route-map-pin-badge-cns-${jobId}`}>
          <Ionicons name="warning" size={9} color={PIN_BG.cns} />
        </View>
      ) : null}
    </View>
  );
}

/* ── Styles ────────────────────────────────────────────────────────── */

const s = StyleSheet.create({
  container: {
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginBottom: spacing.md,
    overflow: "hidden",
  },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 6 },
  headerRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  headerTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  toggle: { padding: 4 },
  optimizePill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: radius.pill, backgroundColor: colors.brand,
  },
  optimizePillText: {
    fontFamily: font.bold, fontSize: 11, color: "#fff", letterSpacing: 0.3,
  },
  undoToast: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    backgroundColor: "#111827",
  },
  undoText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: "#fff" },
  undoBtn: {
    paddingHorizontal: spacing.md, height: 30, borderRadius: radius.md,
    backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
  },
  undoBtnLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff",
                    letterSpacing: 0.3 },
  suggestionToast: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    backgroundColor: "#065F46",
  },
  suggestionText: {
    flex: 1, fontFamily: font.medium, fontSize: fontSize.xs, color: "#fff", lineHeight: 16,
  },
  banner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: spacing.md,
    backgroundColor: "#FEF3C7",
  },
  bannerText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#92400E", flex: 1 },
  mapWrap: { height: 280, width: "100%" },
  map: { flex: 1 },
  pin: {
    width: 28, height: 28, borderRadius: 14,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: "#fff",
    shadowColor: "#000", shadowOpacity: 0.25, shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 3,
  },
  pinNumber: { fontFamily: font.bold, fontSize: 12, color: "#fff", lineHeight: 14 },
  pinBadge: {
    position: "absolute", right: -2, bottom: -2,
    width: 14, height: 14, borderRadius: 7,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "#fff",
  },
  emptyOverlay: {
    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.85)",
  },
  emptyOverlayText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  callout: {
    position: "absolute", left: spacing.sm, right: spacing.sm, bottom: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.sm, gap: spacing.xs,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.18, shadowRadius: 6, elevation: 5,
    borderWidth: 1, borderColor: colors.border,
  },
  calloutHeader: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  calloutName: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  calloutAddr: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 2 },
  calloutTime: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.muted, marginTop: 2 },
  openBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 4,
    height: 36, borderRadius: radius.md, backgroundColor: colors.brand,
  },
  openBtnLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
