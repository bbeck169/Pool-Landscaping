// Phase 38b · Feb-2026 — Mobile Live Tech Pins wrapper.
//
// Wraps the real @rnmapbox/maps map component in a try/catch dynamic
// require so plain Expo Go doesn't crash — devs on Expo Go get a
// fallback banner explaining they need the dev-client rebuild (see
// mobile/EXPO_GO_RUNBOOK.md), while everything else on the dispatch
// board keeps working.
//
// Also owns:
//   • the 15s poll on GET /api/gps/live-positions
//   • the collapsible top-region toggle (persisted in AsyncStorage)
//   • the "GPS feed offline" chip state
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, Dimensions } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useFocusEffect, router } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import type { LivePosition } from "@/src/components/dispatch/LiveTechPinsMap";

const EXPANDED_KEY = "dispatch_map_expanded_v1";
const POLL_MS = 15_000;

// Attempt the native-module require at module load. If it throws —
// Expo Go, unlinked dev client, or missing token — we render the
// fallback banner instead of crashing. `MapImpl` is `null` on failure.
let MapImpl: any = null;
let importError: string | null = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  MapImpl = require("@/src/components/dispatch/LiveTechPinsMap").default;
} catch (e: any) {
  importError = e?.message || String(e);
}

export function LiveTechPinsWrapper({
  onNavigateToShift,
}: {
  onNavigateToShift?: (userId: string, userName: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [positions, setPositions] = useState<LivePosition[]>([]);
  const [offline, setOffline] = useState(false);
  const pollRef = useRef<any>(null);

  // Hydrate persisted expanded state.
  useEffect(() => {
    (async () => {
      const raw = await AsyncStorage.getItem(EXPANDED_KEY);
      if (raw != null) setExpanded(raw === "1");
    })();
  }, []);

  const toggleExpanded = useCallback(async () => {
    setExpanded((v) => {
      const next = !v;
      AsyncStorage.setItem(EXPANDED_KEY, next ? "1" : "0").catch(() => {});
      return next;
    });
  }, []);

  const pollOnce = useCallback(async () => {
    try {
      const r: any = await api.get("/gps/live-positions");
      const rows: LivePosition[] = Array.isArray(r?.positions) ? r.positions : [];
      setPositions((prev) => {
        // If new poll returned zero pins but we had some, dim the
        // previous set instead of blanking the map — keeps last-known
        // context per the spec's error-handling requirements.
        if (rows.length === 0 && prev.length > 0) {
          return prev.map((p) => ({ ...p, is_stale: true }));
        }
        return rows;
      });
      setOffline(false);
    } catch {
      setOffline(true);
      // Mark existing pins stale rather than dropping them.
      setPositions((prev) => prev.map((p) => ({ ...p, is_stale: true })));
    }
  }, []);

  // Poll only while the tab is focused.
  useFocusEffect(useCallback(() => {
    pollOnce();
    pollRef.current = setInterval(pollOnce, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [pollOnce]));

  // Fallback banner — no map module OR no token.
  const hasToken = !!(
    process.env.EXPO_PUBLIC_MAPBOX_TOKEN ||
    // Constants.expoConfig?.extra?.mapboxToken populated at build time
    (globalThis as any).__EXPO_MAPBOX_TOKEN__
  );

  if (!MapImpl) {
    return (
      <View style={styles.fallback} testID="dispatch-live-map-fallback">
        <Ionicons name="map-outline" size={18} color={colors.muted} />
        <Text style={styles.fallbackTitle}>Live map requires the dev client</Text>
        <Text style={styles.fallbackSub}>
          Expo Go can&apos;t load @rnmapbox/maps. Rebuild the dev client
          per mobile/EXPO_GO_RUNBOOK.md to enable this section.
        </Text>
      </View>
    );
  }

  return (
    <View
      style={[
        styles.container,
        expanded ? styles.expanded : styles.collapsed,
      ]}
      testID="dispatch-live-map"
    >
      <View style={styles.header}>
        <Text style={styles.title}>
          Live positions ({positions.length}
          {offline ? " · offline" : ""})
        </Text>
        <Pressable
          onPress={toggleExpanded}
          style={styles.toggle}
          testID="dispatch-live-map-toggle"
        >
          <Ionicons
            name={expanded ? "chevron-up" : "chevron-down"}
            size={16}
            color={colors.onSurface}
          />
        </Pressable>
      </View>
      {expanded ? (
        !hasToken ? (
          <View style={styles.noToken} testID="dispatch-live-map-no-token">
            <Text style={styles.noTokenText}>
              Live map unavailable — set EXPO_PUBLIC_MAPBOX_TOKEN to enable.
            </Text>
          </View>
        ) : (
          <MapImpl
            positions={positions}
            onPinTap={(uid: string, uname: string) => {
              if (onNavigateToShift) return onNavigateToShift(uid, uname);
              router.push({
                pathname: "/dispatch/shift-route",
                params: { source: uid, sourceName: uname, scope: "whole_route" },
              } as any);
            }}
            offline={offline}
          />
        )
      ) : (
        <View style={styles.strip} testID="dispatch-live-map-strip">
          <Text style={styles.stripText}>
            {positions.length === 0
              ? "No live positions"
              : `${positions.length} tech${positions.length === 1 ? "" : "s"} on the map · tap ▼ to expand`}
          </Text>
        </View>
      )}
    </View>
  );
}

const VIEWPORT_H = Dimensions.get("window").height;

const styles = StyleSheet.create({
  container: { borderRadius: radius.md, overflow: "hidden", borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md, backgroundColor: colors.surface },
  expanded: { height: Math.max(280, Math.round(VIEWPORT_H * 0.4)) },
  collapsed: { height: 60 },
  header: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  title: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  toggle: { padding: 4 },
  strip: { flex: 1, alignItems: "center", justifyContent: "center" },
  stripText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  fallback: {
    marginBottom: spacing.md, padding: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary, gap: spacing.xs,
  },
  fallbackTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  fallbackSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  noToken: {
    flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.md,
  },
  noTokenText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
});
