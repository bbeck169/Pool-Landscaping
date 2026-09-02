// Phase 38b · Feb-2026 — Mobile Live Tech Position Pins map.
//
// Uses @rnmapbox/maps@^10 (native module — requires the dev-client
// rebuild described in `mobile/EXPO_GO_RUNBOOK.md`). Wrapped in a
// try/catch dynamic require so plain Expo Go doesn't crash — the
// fallback banner is rendered by the parent when this module fails
// to import.
//
// Contract with the parent (`dispatch/board.tsx`):
//   * Positions are polled by the parent at 15s cadence.
//   * The parent hands us positions + a `onPinTap(user_id)` callback.
//   * We only render UI — no fetching, no side effects other than
//     the AsyncStorage persistence for the style + expanded toggles.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { hasMapboxToken, MapUnavailablePlaceholder } from "@/src/utils/mapsKey";

// Dynamic require — throws in Expo Go where the native module isn't
// present. Parent catches and renders the fallback banner.
 
const MapboxGL: any = require("@rnmapbox/maps").default;

const STYLES: { url: string; label: string; icon: string }[] = [
  { url: "mapbox://styles/mapbox/streets-v12",           label: "Streets",    icon: "map-outline" },
  { url: "mapbox://styles/mapbox/satellite-streets-v12", label: "Satellite",  icon: "earth-outline" },
  { url: "mapbox://styles/mapbox/dark-v11",              label: "Dark",       icon: "moon-outline" },
];

const STYLE_KEY = "dispatch_map_style_v1";

// Deterministic color per user_id — mirrors the same idea as
// TechAvatar so pins match the load-strip swatches.
function _colorFromId(id: string): string {
  let h = 0;
  for (let i = 0; i < (id || "").length; i++) h = ((h << 5) - h) + id.charCodeAt(i);
  const palette = ["#EF4444","#F97316","#EAB308","#22C55E","#06B6D4","#3B82F6","#8B5CF6","#EC4899"];
  return palette[Math.abs(h) % palette.length];
}

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

  // Boot: token config + hydrate the persisted style.
  useEffect(() => {
    const token =
      process.env.EXPO_PUBLIC_MAPBOX_TOKEN ||
      (Constants.expoConfig?.extra as any)?.mapboxToken ||
      "";
    if (MapboxGL && typeof MapboxGL.setAccessToken === "function") {
      MapboxGL.setAccessToken(token);
    }
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

  // Phase K20 — safety guard: graceful fallback when Mapbox token
  // is missing (prevents blank map or runtime errors). Placed after
  // hooks to satisfy the rules-of-hooks requirement.
  if (!hasMapboxToken()) {
    return (
      <MapUnavailablePlaceholder
        provider="Mapbox"
        testID="dispatch-live-map-no-token"
        message="Mapbox access token not configured. Live map requires a valid token."
      />
    );
  }

  // Center on the first position (or a US-ish default).
  const center: [number, number] = positions.length
    ? [positions[0].lon, positions[0].lat]
    : [-112.0740, 33.4484];  // Phoenix — safe default for this tenant.

  return (
    <View style={styles.wrap} testID="dispatch-live-map-inner">
      <MapboxGL.MapView
        style={styles.map}
        styleURL={STYLES[styleIdx].url}
        logoEnabled={false}
        attributionEnabled={false}
      >
        <MapboxGL.Camera zoomLevel={10} centerCoordinate={center} />
        {positions.map((p) => (
          <MapboxGL.PointAnnotation
            key={p.user_id}
            id={`pin-${p.user_id}`}
            coordinate={[p.lon, p.lat]}
            onSelected={() => onPinTap(p.user_id, p.user_name)}
          >
            <View
              style={[
                styles.pin,
                { backgroundColor: _colorFromId(p.user_id) },
                p.is_stale && styles.pinStale,
              ]}
              // testID is duplicated on the inner view — pin annotations
              // don't forward accessibility props on all platforms.
              testID={`dispatch-live-pin-${p.user_id}`}
            >
              <Text style={styles.pinText}>{_initials(p.user_name)}</Text>
            </View>
          </MapboxGL.PointAnnotation>
        ))}
      </MapboxGL.MapView>

      {/* Theme toggle */}
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
  pin: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: "#fff",
    shadowColor: "#000", shadowOpacity: 0.25, shadowRadius: 3, shadowOffset: { width: 0, height: 1 },
    elevation: 3,
  },
  pinStale: { opacity: 0.55 },
  pinText: { fontFamily: font.bold, fontSize: 11, color: "#fff" },
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
