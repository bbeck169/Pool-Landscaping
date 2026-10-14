/**
 * Schedule Map — native implementation.
 *
 * Renders job pins on a react-native-maps MapView with color-coded
 * markers. Tap a pin to show a bottom info card with Directions + Open job.
 */
import React, { useState, useEffect, useMemo, useRef } from "react";
import { View, Text, StyleSheet, Pressable, Linking, Platform } from "react-native";
import { MapView, Marker, type Region } from "@/src/lib/maps";
import * as Location from "expo-location";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { hasGoogleMapsKey, MapUnavailablePlaceholder } from "@/src/utils/mapsKey";
import TeardropPin from "@/src/components/maps/TeardropPin";
// K58 · Feb-2026 — shared coord resolver so ScheduleMap and DailyRouteMap
// stay in lockstep on which jobs are "mapped".  See PHASE_K58_MAP_COORD_LADDER.md.
import { resolveJobCoords, type JobLikeForCoords } from "@/src/utils/jobCoords";
// Live-tech overlay (web parity 6db3c4f57) — polls every 30s, pauses on
// app background, admin-defaulted ON (persisted per user in AsyncStorage).
import { useLiveTechLocations, type LiveTechPing } from "@/src/hooks/useLiveTechLocations";
import { LiveTechToggle, LiveTechMarkers, LiveTechCard } from "@/src/components/schedule/LiveTechOverlay";
// Phase 4 multi-property pins (web parity 723e28204) — approximate signal
// + property-rung chip, driven by coord_source / property_id / property_label.
import {
  isApproximatePin,
  propertyChipLabel,
  jobPinWrapStyle,
  type JobCoordSourceFields,
} from "@/src/utils/jobPinCoordSource";
// Phase B.5 parity (web 9eb08b5c1) — per-tech numbering + color legend.
import { buildTechColorMap, UNASSIGNED_PIN_COLOR } from "@/src/utils/crewPalette";
import { buildPerTechSequence, perTechStopCounts } from "@/src/utils/perTechSequence";
import TechLegend from "@/src/components/schedule/TechLegend";

interface Job extends JobCoordSourceFields {
  id: string;
  status?: string;
  customer_name?: string;
  address?: string;
  scheduled_time?: string | null;
  technician_id?: string | null;
  route_index?: number | null;
  // K58 · Feb-2026 — coord fields consumed via ``resolveJobCoords``;
  // the shared helper tolerates the full ladder (location_lat/lng →
  // latitude/longitude → site_lat/lng → property.location.{lat,lng})
  // so ScheduleMap no longer keys strictly on ``location_*``.
  location_lat?: number | null;
  location_lng?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  site_lat?: number | null;
  site_lng?: number | null;
  property?: JobLikeForCoords["property"];
}

interface Props {
  jobs: Job[];
  testID?: string;
  /** Phase B.5 — when provided, pins fill by tech color + legend shows. */
  techs?: any[];
  crews?: any[];
}

const PIN_COLORS: Record<string, string> = {
  scheduled: "#2563EB",   // blue
  pending: "#2563EB",
  active: "#EAB308",      // yellow
  in_progress: "#EAB308",
  completed: "#16A34A",   // green
  skipped: "#DC2626",     // red
  could_not_service: "#DC2626",
  canceled: "#DC2626",
  cancelled: "#DC2626",
};

function pinColor(status?: string): string {
  return PIN_COLORS[(status || "scheduled").toLowerCase()] || "#2563EB";
}

// Phase K20 — Google Maps key check now centralized in mapsKey.ts.
// See hasGoogleMapsKey() for the full platform-aware logic.

function openDirections(address: string) {
  const encoded = encodeURIComponent(address);
  if (Platform.OS === "ios") {
    Linking.openURL(`https://maps.apple.com/?daddr=${encoded}`).catch(() =>
      Linking.openURL(`https://maps.google.com/?q=${encoded}`),
    );
  } else {
    Linking.openURL(`google.navigation:q=${encoded}`).catch(() =>
      Linking.openURL(`https://maps.google.com/?q=${encoded}`),
    );
  }
}

export default function ScheduleMap({ jobs, testID, techs, crews }: Props) {
  const router = useRouter();
  const mapRef = useRef<MapView>(null);
  const [selected, setSelected] = useState<Job | null>(null);
  const live = useLiveTechLocations();
  // Per-tech sequence is computed over ALL jobs (count-but-hide for
  // coord-less ones) and recomputes whenever the filtered list changes.
  const techColorMap = useMemo(() => (techs ? buildTechColorMap(techs, crews || []) : null), [techs, crews]);
  const seq = useMemo(() => buildPerTechSequence(jobs), [jobs]);
  const stopCounts = useMemo(() => perTechStopCounts(jobs), [jobs]);
  const fillFor = (j: Job) =>
    techColorMap ? (j.technician_id && techColorMap.get(j.technician_id)) || UNASSIGNED_PIN_COLOR : pinColor(j.status);
  const [liveSelId, setLiveSelId] = useState<string | null>(null);
  const livePings = useMemo(() => (live.enabled ? live.pings : []), [live.enabled, live.pings]);
  const liveSel = liveSelId ? livePings.find((p) => p.user_id === liveSelId) || null : null;
  const selectJob = (j: Job) => { setLiveSelId(null); setSelected(j); };
  const selectLive = (p: LiveTechPing) => { setSelected(null); setLiveSelId(p.user_id); };

  const geocoded = useMemo(
    // K58 · Feb-2026 — filter via the shared ``resolveJobCoords``
    // helper so a job is "mapped" when ANY rung of the coord ladder
    // yields coords, not just the strict ``location_lat/lng`` gate
    // that used to gate this component pre-K58.  Each geocoded entry
    // is annotated with its resolved ``__coords`` so the render loop
    // below doesn't recompute the ladder per marker.
    () => jobs.reduce<Array<Job & { __coords: { lat: number; lng: number } }>>(
      (acc, j) => {
        const coords = resolveJobCoords(j as JobLikeForCoords);
        if (coords) acc.push({ ...j, __coords: coords });
        return acc;
      },
      [],
    ),
    [jobs],
  );

  // Ask for location permission (best-effort for user dot)
  useEffect(() => {
    (async () => {
      const { status } = await Location.getForegroundPermissionsAsync();
      if (status === "undetermined") {
        await Location.requestForegroundPermissionsAsync();
      }
    })();
  }, []);

  // Compute initial region from pins
  // Jobs frame the map; with no mapped jobs, frame the live techs instead.
  const initialRegion: Region | undefined = useMemo(() => {
    const pts = geocoded.length
      ? geocoded.map((j) => j.__coords)
      : livePings.map((p) => ({ lat: p.lat, lng: p.lon }));
    if (pts.length === 0) return undefined;
    const lats = pts.map((p) => p.lat);
    const lngs = pts.map((p) => p.lng);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    return {
      latitude: (minLat + maxLat) / 2,
      longitude: (minLng + maxLng) / 2,
      latitudeDelta: Math.max(maxLat - minLat, 0.01) * 1.5,
      longitudeDelta: Math.max(maxLng - minLng, 0.01) * 1.5,
    };
  }, [geocoded, livePings]);

  const toggle = live.canRead ? (
    <LiveTechToggle enabled={live.enabled} onToggle={() => live.setEnabled(!live.enabled)} />
  ) : null;

  if (geocoded.length === 0 && livePings.length === 0) {
    return (
      <View style={s.empty} testID="schedule-map-empty">
        {toggle}
        <Ionicons name="map-outline" size={32} color={colors.muted} />
        <Text style={s.emptyText}>No mapped stops today</Text>
      </View>
    );
  }

  // Phase K20 — centralized safety guard for missing Google Maps key.
  if (!hasGoogleMapsKey()) {
    return (
      <MapUnavailablePlaceholder
        provider="Google Maps"
        testID="schedule-map-no-key"
        message="Google Maps API key not configured for this build."
      />
    );
  }

  return (
    <View style={s.wrap} testID={testID || "schedule-map"}>
      <MapView
        ref={mapRef}
        style={s.map}
        initialRegion={initialRegion}
        showsUserLocation
        showsMyLocationButton
        testID="schedule-map-view"
      >
        {geocoded.map((j) => (
          <Marker
            key={j.id}
            coordinate={{ latitude: j.__coords.lat, longitude: j.__coords.lng }}
            anchor={{ x: 0.5, y: 1.0 }}
            title={j.customer_name || "Job"}
            description={propertyChipLabel(j) ?? undefined}
            onPress={() => selectJob(j)}
            tracksViewChanges={false}
            testID={`schedule-map-pin-${j.id}`}
          >
            <View
              style={jobPinWrapStyle(j, fillFor(j))}
              accessibilityLabel={
                isApproximatePin(j)
                  ? `Job pin for ${j.customer_name || "job"} (approximate location — property coords missing)`
                  : `Job pin for ${j.customer_name || "job"}`
              }
              testID={`schedule-map-pin-wrap-${j.id}`}
            >
              <TeardropPin
                color={fillFor(j)}
                label={seq.get(j.id)}
                testID={`schedule-map-teardrop-${j.id}`}
              />
            </View>
          </Marker>
        ))}
        {/* Live-tech markers — outside the job-pin loop (web parity). */}
        <LiveTechMarkers pings={livePings} onSelect={selectLive} />
      </MapView>
      {toggle}
      {techColorMap && !selected && !liveSel ? (
        <TechLegend counts={stopCounts} colorMap={techColorMap} techs={techs || []} />
      ) : null}
      {liveSel ? <LiveTechCard ping={liveSel} onClose={() => setLiveSelId(null)} /> : null}

      {selected ? (
        <View style={s.card} testID="schedule-map-info-card">
          <View style={s.cardHeader}>
            <View style={{ flex: 1 }}>
              <Text style={s.cardName} numberOfLines={1}>{selected.customer_name || "Job"}</Text>
              {propertyChipLabel(selected) ? (
                <View style={s.propChip} testID={`schedule-map-info-property-${selected.id}`}>
                  <View style={s.propDot} />
                  <Text style={s.propText} numberOfLines={1}>
                    Property: <Text style={s.propLabel}>{propertyChipLabel(selected)}</Text>
                  </Text>
                </View>
              ) : null}
              {isApproximatePin(selected) ? (
                <Text style={s.approxText} testID={`schedule-map-info-approximate-${selected.id}`}>
                  Approximate location — property has no geocoded coords; showing the customer address.
                </Text>
              ) : null}
              {selected.scheduled_time ? (
                <Text style={s.cardTime}>{selected.scheduled_time}</Text>
              ) : null}
              {selected.address ? (
                <Text style={s.cardAddr} numberOfLines={1}>{selected.address}</Text>
              ) : null}
            </View>
            <Pressable onPress={() => setSelected(null)} hitSlop={8} testID="schedule-map-close-card">
              <Ionicons name="close" size={20} color={colors.muted} />
            </Pressable>
          </View>
          <View style={s.cardActions}>
            {selected.address ? (
              <Pressable
                style={s.actionBtn}
                onPress={() => openDirections(selected.address!)}
                testID="schedule-map-directions-btn"
              >
                <Ionicons name="navigate" size={14} color="#fff" />
                <Text style={s.actionLabel}>Directions</Text>
              </Pressable>
            ) : null}
            <Pressable
              style={[s.actionBtn, { backgroundColor: colors.brand }]}
              onPress={() => {
                setSelected(null);
                router.push(`/job/${selected.id}/checklist` as any);
              }}
              testID="schedule-map-open-job-btn"
            >
              <Ionicons name="open-outline" size={14} color="#fff" />
              <Text style={s.actionLabel}>Open job</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { height: 350, borderRadius: radius.md, overflow: "hidden", marginBottom: spacing.md },
  map: { flex: 1 },
  empty: {
    height: 200, alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderStyle: "dashed", borderColor: colors.border, marginBottom: spacing.md,
  },
  emptyText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  card: {
    position: "absolute", bottom: spacing.md, left: spacing.md, right: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, gap: spacing.sm,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15, shadowRadius: 6, elevation: 4,
  },
  cardHeader: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  cardName: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  cardTime: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  cardAddr: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 2 },
  cardActions: { flexDirection: "row", gap: spacing.sm },
  propChip: {
    flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", marginTop: 4,
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999,
    backgroundColor: "rgba(14,165,233,0.08)", borderWidth: 1, borderColor: "rgba(14,165,233,0.25)",
  },
  propDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#0EA5E9" },
  propText: { fontFamily: font.regular, fontSize: 11, color: colors.muted, flexShrink: 1 },
  propLabel: { fontFamily: font.bold, color: colors.onSurface },
  approxText: { fontFamily: font.regular, fontSize: 11, color: "#B45309", marginTop: 4 },
  actionBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 4, height: 38, borderRadius: radius.md, backgroundColor: "#059669",
  },
  actionLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
