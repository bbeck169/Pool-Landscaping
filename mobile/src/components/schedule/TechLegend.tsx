/**
 * Per-tech color legend for the Schedule map (web 9eb08b5c1 parity).
 * Bottom-left overlay inside the map container (the map already sits
 * above the tab bar, so no extra inset is needed). One row per tech
 * with ≥ 1 stop, sorted by stop count desc.
 */
import React from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";

import { colors, font } from "@/src/theme";
import { UNASSIGNED_PIN_COLOR } from "@/src/utils/crewPalette";

export default function TechLegend({ counts, colorMap, techs }: {
  counts: Map<string, number>;
  colorMap: Map<string, string>;
  techs: any[];
}) {
  const rows = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  if (!rows.length) return null;
  return (
    <View style={s.box} testID="schedule-map-tech-legend" pointerEvents="box-none">
      <ScrollView style={{ maxHeight: 132 }} showsVerticalScrollIndicator={false}>
        {rows.map(([tid, n]) => {
          const t = (techs || []).find((x: any) => (x.id || x.user_id) === tid);
          const name = t?.name || t?.display_name || `Tech ${String(tid).slice(0, 6)}…`;
          return (
            <View key={tid} style={s.row} testID={`schedule-map-tech-legend-${tid}`}>
              <View style={[s.swatch, { backgroundColor: colorMap.get(tid) || UNASSIGNED_PIN_COLOR }]} testID={`schedule-map-tech-legend-swatch-${tid}`} />
              <Text style={s.name} numberOfLines={1}>{name}</Text>
              <Text style={s.count} testID={`schedule-map-tech-legend-count-${tid}`}>{n} stop{n === 1 ? "" : "s"}</Text>
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  box: {
    position: "absolute", bottom: 8, left: 8, zIndex: 4, maxWidth: 220,
    backgroundColor: "rgba(255,255,255,0.94)", borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6,
    shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.18, shadowRadius: 3, elevation: 3,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 20 },
  swatch: { width: 10, height: 10, borderRadius: 5, borderWidth: 1, borderColor: "rgba(0,0,0,0.15)" },
  name: { flexShrink: 1, fontFamily: font.semibold, fontSize: 11, color: colors.onSurface },
  count: { fontFamily: font.medium, fontSize: 11, color: colors.muted },
});
