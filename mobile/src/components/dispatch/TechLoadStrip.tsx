// Phase 38 · Feb-2026 — Mobile TechLoadStrip (P1.4).
//
// Web parity: `frontend/src/pages/dispatch/TechLoadStrip.jsx`.
// A compact strip rendering one chip per tech with a color swatch
// and drop count; tapping filters the parent board.
import React from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export type TechLoad = {
  tech_user_id: string;
  name: string;
  drop_count: number;
  color_hex?: string;
};

export function TechLoadStrip({
  loads = [],
  selectedTechId = null,
  onSelect = () => {},
}: {
  loads: TechLoad[];
  selectedTechId?: string | null;
  onSelect?: (techUserId: string | null) => void;
}) {
  if (!loads.length) {
    return (
      <View style={styles.empty} testID="dispatch-tech-load-empty">
        <Text style={styles.emptyText}>No techs assigned to visible pins.</Text>
      </View>
    );
  }
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.list}
      testID="dispatch-tech-load-list"
    >
      {loads.map((t) => {
        const active = selectedTechId === t.tech_user_id;
        return (
          <Pressable
            key={t.tech_user_id}
            onPress={() => onSelect(active ? null : t.tech_user_id)}
            style={[styles.chip, active && styles.chipOn]}
            testID={`dispatch-tech-load-${t.tech_user_id}`}
          >
            <View style={[styles.swatch, { backgroundColor: t.color_hex || colors.brand }]} />
            <Text style={[styles.name, active && styles.nameOn]} numberOfLines={1}>
              {t.name}
            </Text>
            <Text style={styles.count}>{t.drop_count}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  empty: {
    padding: spacing.sm, borderRadius: radius.sm,
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.border,
    alignItems: "center",
  },
  emptyText: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  list: { flexDirection: "row", gap: spacing.xs, paddingVertical: 4 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: radius.pill, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  swatch: { width: 10, height: 10, borderRadius: 5 },
  name: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, maxWidth: 100 },
  nameOn: { color: colors.brand },
  count: {
    fontFamily: font.bold, fontSize: 11, color: colors.muted,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: 8,
    backgroundColor: colors.surfaceSecondary,
  },
});
