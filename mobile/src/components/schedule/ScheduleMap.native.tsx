/**
 * Schedule Map — native implementation.
 *
 * Renders job pins on a react-native-maps MapView with color-coded
 * markers. Tap a pin to show a bottom info card with Directions + Open job.
 */
import React, { useState, useEffect, useMemo, useRef } from "react";
import { View, Text, StyleSheet, Pressable, Linking, Platform } from "react-native";
import MapView, { Marker, Region } from "react-native-maps";
import * as Location from "expo-location";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { hasGoogleMapsKey, MapUnavailablePlaceholder } from "@/src/utils/mapsKey";

interface Job {
  id: string;
  status?: string;
  customer_name?: string;
  address?: string;
  scheduled_time?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
}

interface Props {
  jobs: Job[];
  testID?: string;
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

export default function ScheduleMap({ jobs, testID }: Props) {
  const router = useRouter();
  const mapRef = useRef<MapView>(null);
  const [selected, setSelected] = useState<Job | null>(null);

  const geocoded = useMemo(
    () => jobs.filter((j) => j.location_lat != null && j.location_lng != null),
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
  const initialRegion: Region | undefined = useMemo(() => {
    if (geocoded.length === 0) return undefined;
    const lats = geocoded.map((j) => j.location_lat!);
    const lngs = geocoded.map((j) => j.location_lng!);
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
  }, [geocoded]);

  if (geocoded.length === 0) {
    return (
      <View style={s.empty} testID="schedule-map-empty">
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
            coordinate={{ latitude: j.location_lat!, longitude: j.location_lng! }}
            pinColor={pinColor(j.status)}
            title={j.customer_name || "Job"}
            onPress={() => setSelected(j)}
            testID={`schedule-map-pin-${j.id}`}
          />
        ))}
      </MapView>

      {selected ? (
        <View style={s.card} testID="schedule-map-info-card">
          <View style={s.cardHeader}>
            <View style={{ flex: 1 }}>
              <Text style={s.cardName} numberOfLines={1}>{selected.customer_name || "Job"}</Text>
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
  actionBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 4, height: 38, borderRadius: radius.md, backgroundColor: "#059669",
  },
  actionLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
