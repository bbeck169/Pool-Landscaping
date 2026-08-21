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
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

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
  const cameraRef = useRef<any>(null);
  const [expanded, setExpanded] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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

  // Feature-level guard — 0 jobs scheduled = hide entire map.
  if (!jobs || jobs.length === 0) return null;

  const hasToken = !!process.env.EXPO_PUBLIC_MAPBOX_TOKEN;

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
  );

  return (
    <View style={s.container} testID={testID || "schedule-daily-route-map"}>
      {header}

      {!expanded ? null : !hasToken || !MapboxGL ? (
        <View style={s.banner} testID="schedule-daily-route-map-token-banner">
          <Ionicons name="alert-circle-outline" size={16} color="#92400E" />
          <Text style={s.bannerText}>Map unavailable — Mapbox token not configured</Text>
        </View>
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
  headerTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  toggle: { padding: 4 },
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
