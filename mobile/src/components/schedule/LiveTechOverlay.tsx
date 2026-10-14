/**
 * Live-tech overlay pieces for the Schedule map (mobile parity for
 * web 6db3c4f57). Kept separate so ScheduleMap.native stays small.
 *
 *  - <LiveTechToggle>  — "Show live techs" / "Live techs on" chip.
 *  - <LiveTechMarkers> — one round pin per ping, colored by staleness.
 *                        Rendered OUTSIDE any job-pin grouping so a tech
 *                        standing on a job pin stays individually visible.
 *  - <LiveTechCard>    — name + "updated Xm ago" + staleness chip.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { Marker } from "@/src/lib/maps";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  colorForStaleness,
  formatAge,
  type LiveTechPing,
} from "@/src/hooks/useLiveTechLocations";

export function LiveTechToggle({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <Pressable
      onPress={onToggle}
      accessibilityRole="switch"
      accessibilityState={{ checked: enabled }}
      accessibilityLabel="Show live technician locations"
      hitSlop={8}
      style={[s.toggle, enabled && s.toggleOn]}
      testID="schedule-map-live-tech-toggle"
    >
      <View style={[s.toggleDot, { backgroundColor: enabled ? "#FFFFFF" : "#94a3b8" }]} />
      <Text style={[s.toggleText, enabled && s.toggleTextOn]}>
        {enabled ? "Live techs on" : "Show live techs"}
      </Text>
    </Pressable>
  );
}

export function LiveTechMarkers({
  pings,
  onSelect,
}: {
  pings: LiveTechPing[];
  onSelect: (p: LiveTechPing) => void;
}) {
  return (
    <>
      {pings.map((p) => (
        <Marker
          // Staleness in the key → remount on bucket change so the color
          // refreshes even with tracksViewChanges={false}.
          key={`live-${p.user_id}-${p.staleness}`}
          coordinate={{ latitude: p.lat, longitude: p.lon }}
          anchor={{ x: 0.5, y: 0.5 }}
          title={`${p.user_name} · ${formatAge(p.age_seconds)}`}
          onPress={() => onSelect(p)}
          tracksViewChanges={false}
          testID={`schedule-map-live-tech-pin-${p.user_id}`}
        >
          <View
            style={[s.dot, { backgroundColor: colorForStaleness(p.staleness) }]}
            testID={`schedule-map-live-tech-dot-${p.user_id}`}
          />
        </Marker>
      ))}
    </>
  );
}

export function LiveTechCard({ ping, onClose }: { ping: LiveTechPing; onClose: () => void }) {
  const c = colorForStaleness(ping.staleness);
  return (
    <View style={s.card} testID={`schedule-map-live-tech-info-${ping.user_id}`}>
      <View style={{ flex: 1 }}>
        <Text style={s.name} numberOfLines={1}>{ping.user_name}</Text>
        <Text style={s.age}>updated {formatAge(ping.age_seconds)}</Text>
        <View style={[s.chip, { borderColor: c }]} testID={`schedule-map-live-tech-staleness-${ping.user_id}`}>
          <View style={[s.chipDot, { backgroundColor: c }]} />
          <Text style={[s.chipText, { color: c }]}>{ping.staleness}</Text>
        </View>
      </View>
      <Pressable onPress={onClose} hitSlop={8} testID="schedule-map-live-tech-close">
        <Ionicons name="close" size={20} color={colors.muted} />
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  toggle: {
    position: "absolute", top: spacing.sm, left: spacing.sm, zIndex: 5,
    flexDirection: "row", alignItems: "center", gap: 6, minHeight: 32,
    paddingHorizontal: 12, borderRadius: 999, backgroundColor: "rgba(255,255,255,0.94)",
    shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.18,
    shadowRadius: 3, elevation: 3,
  },
  toggleOn: { backgroundColor: "#22c55e" },
  toggleDot: { width: 8, height: 8, borderRadius: 4 },
  toggleText: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  toggleTextOn: { color: "#FFFFFF" },
  dot: {
    width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: "#FFFFFF",
    shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.3,
    shadowRadius: 2, elevation: 3,
  },
  card: {
    position: "absolute", bottom: spacing.md, left: spacing.md, right: spacing.md,
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15,
    shadowRadius: 6, elevation: 4,
  },
  name: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  age: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start",
    marginTop: 6, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, borderWidth: 1,
  },
  chipDot: { width: 6, height: 6, borderRadius: 3 },
  chipText: { fontFamily: font.semibold, fontSize: 11, textTransform: "capitalize" },
});
