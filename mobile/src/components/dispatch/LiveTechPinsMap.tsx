/**
 * Phase K46 · Feb-2026 — Live Tech Position Pins map (Google-only).
 *
 * Migrated from ``@rnmapbox/maps`` to ``react-native-maps`` with the
 * Google provider as part of the Phase K46 map consolidation
 * (root cause of the Android white-screen crash — Mapbox's native
 * initializer threw before JS bundled, blanking the shell).
 *
 * Contract with the parent (``dispatch/board.tsx``):
 *   * Positions are polled by the parent at 15s cadence.
 *   * The parent hands us positions + a ``onPinTap(user_id)`` callback.
 *   * We only render UI — no fetching, no side effects other than
 *     the AsyncStorage persistence for the map style toggle.
 *
 * Style toggle: cycles ``standard`` → ``satellite`` → ``hybrid``
 * via ``react-native-maps``' built-in ``mapType`` prop (was three
 * Mapbox style URLs pre-K46). AsyncStorage key unchanged
 * (``dispatch_map_style_v1``) to preserve the tech's saved choice.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import MapView, { Marker, PROVIDER_GOOGLE } from "react-native-maps";

import { colors, spacing, radius, font } from "@/src/theme";
import { hasGoogleMapsKey, MapUnavailablePlaceholder } from "@/src/utils/mapsKey";
import TeardropPin, { colorFromId } from "@/src/components/maps/TeardropPin";

const STYLES: { mapType: "standard" | "satellite" | "hybrid"; label: string; icon: string }[] = [
  { mapType: "standard",  label: "Streets",   icon: "map-outline" },
  { mapType: "satellite", label: "Satellite", icon: "earth-outline" },
  { mapType: "hybrid",    label: "Hybrid",    icon: "layers-outline" },
];

const STYLE_KEY = "dispatch_map_style_v1";

function _initials(name: string): string {
  return (name || "?")
    .trim().split(/\s+/).slice(0, 2)
    .map((s) => s[0]?.toUpperCase() || "").join("") || "?";
}

export type LivePosition = {
  user_id: string;
  user_name: string;
  lat: number;
  lon: number;
  accuracy_m?: number | null;
  is_stale?: boolean;
};

export interface LiveTechPinsMapProps {
  positions: LivePosition[];
  onPinTap: (userId: string, userName: string) => void;
  offline?: boolean;
}

export default function LiveTechPinsMap({
  positions, onPinTap, offline = false,
}: LiveTechPinsMapProps) {
  const [styleIdx, setStyleIdx] = useState(0);

  // Hydrate the persisted style toggle. No native token setup needed
  // for Google Maps — the API key is resolved from ``app.config.js``'s
  // ``android.config.googleMaps.apiKey`` / ``ios.config.googleMapsApiKey``
  // at EAS build time.
  useEffect(() => {
    (async () => {
      const raw = await AsyncStorage.getItem(STYLE_KEY);
      const parsed = raw ? Number(raw) : 0;
      if (parsed >= 0 && parsed < STYLES.length) setStyleIdx(parsed);
    })();
  }, []);

  const cycleStyle = useCallback(async () => {
    const next = (styleIdx + 1) % STYLES.length;
    setStyleIdx(next);
    await AsyncStorage.setItem(STYLE_KEY, String(next));
  }, [styleIdx]);

  // K20 · Safety guard: graceful fallback when the Google Maps API
  // key is missing. Placed after hooks to satisfy rules-of-hooks.
  if (!hasGoogleMapsKey()) {
    return (
      <MapUnavailablePlaceholder
        provider="Google Maps"
        testID="dispatch-live-map-no-token"
        message="Google Maps API key not configured. Live map requires a valid key."
      />
    );
  }

  // Center on the first position (or a Phoenix-area default).
  const initialRegion = {
    latitude: positions.length ? positions[0].lat : 33.4484,
    longitude: positions.length ? positions[0].lon : -112.0740,
    latitudeDelta: 0.6,
    longitudeDelta: 0.6,
  };

  return (
    <View style={styles.wrap} testID="dispatch-live-map-inner">
      <MapView
        provider={PROVIDER_GOOGLE}
        style={styles.map}
        mapType={STYLES[styleIdx].mapType}
        initialRegion={initialRegion}
        showsUserLocation={false}
        showsMyLocationButton={false}
        toolbarEnabled={false}
        testID="dispatch-live-map-view"
      >
        {positions.map((p) => {
          const pinColor = colorFromId(p.user_id);
          const isFresh = !p.is_stale;
          return (
            <Marker
              key={p.user_id}
              identifier={`dispatch-live-pin-${p.user_id}`}
              coordinate={{ latitude: p.lat, longitude: p.lon }}
              onPress={() => onPinTap(p.user_id, p.user_name)}
              anchor={{ x: 0.5, y: 1.0 }}
              tracksViewChanges={isFresh}
            >
              <View
                style={[p.is_stale && styles.pinStale]}
                testID={`dispatch-live-pin-${p.user_id}`}
              >
                <TeardropPin
                  color={pinColor}
                  pulse={isFresh}
                  label={_initials(p.user_name)}
                  testID={`dispatch-live-teardrop-${p.user_id}`}
                />
              </View>
            </Marker>
          );
        })}
      </MapView>

      {/* Map-type toggle (standard / satellite / hybrid) */}
      <Pressable
        onPress={cycleStyle}
        style={styles.styleBtn}
        testID="dispatch-live-map-style-toggle"
      >
        <Ionicons name={STYLES[styleIdx].icon as any} size={14} color={colors.onSurface} />
        <Text style={styles.styleBtnText}>{STYLES[styleIdx].label}</Text>
      </Pressable>

      {/* GPS feed offline chip */}
      {offline && (
        <View style={styles.offlineChip} testID="dispatch-live-map-offline-chip">
          <Ionicons name="cloud-offline-outline" size={12} color={colors.error} />
          <Text style={styles.offlineText}>GPS feed offline</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surfaceSecondary },
  map: { flex: 1 },
  pinStale: { opacity: 0.55 },
  styleBtn: {
    position: "absolute", top: spacing.sm, right: spacing.sm,
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: radius.pill, backgroundColor: "rgba(255,255,255,0.92)",
    borderWidth: 1, borderColor: colors.border,
  },
  styleBtnText: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurface },
  offlineChip: {
    position: "absolute", top: spacing.sm, left: spacing.sm,
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: radius.pill, backgroundColor: "rgba(254,226,226,0.95)",
    borderWidth: 1, borderColor: colors.error,
  },
  offlineText: { fontFamily: font.medium, fontSize: 10, color: colors.error },
});
