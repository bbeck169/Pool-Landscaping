// Phase K46 · Feb-2026 — Live Tech Pins wrapper (Google-only).
//
// Post-K46 the wrapper no longer needs to dynamic-require the native
// map module inside a try/catch: ``react-native-maps`` ships with
// every Expo shell (Expo Go and dev client both include it), so a
// plain static import is safe. The Google Maps API key guard now
// lives inside ``LiveTechPinsMap.tsx`` itself via
// ``hasGoogleMapsKey()`` — this wrapper only owns:
//
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
import LiveTechPinsMap, {
  type LivePosition,
} from "@/src/components/dispatch/LiveTechPinsMap";

const EXPANDED_KEY = "dispatch_map_expanded_v1";
const POLL_MS = 15_000;

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
        <LiveTechPinsMap
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
});
