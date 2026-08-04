// Phase 38 · Feb-2026 — Mobile UnroutedPanel (P1.4).
//
// Web parity: `frontend/src/pages/dispatch/UnroutedPanel.jsx`.
// Compact list of pins that have no assigned tech — dispatchers
// see them at a glance and can navigate to the shift-route / assign
// flow. Backend derivation happens in the parent (filter on the
// `/dispatch/board` response); this component is presentational.
import React from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export type UnroutedPin = {
  customer_id: string;
  customer_name: string;
  service_days?: string[];
  category_ids?: string[];
};

export function UnroutedPanel({
  pins = [],
  onSelect = () => {},
}: {
  pins: UnroutedPin[];
  onSelect?: (customer_id: string) => void;
}) {
  return (
    <View style={styles.container} testID="dispatch-unrouted-panel">
      <View style={styles.head}>
        <Ionicons name="warning-outline" size={16} color={colors.warning || colors.brand} />
        <Text style={styles.title}>Unrouted ({pins.length})</Text>
      </View>
      {pins.length === 0 ? (
        <Text style={styles.empty} testID="dispatch-unrouted-empty">
          Every visible pin is on a tech's route.
        </Text>
      ) : (
        <ScrollView style={styles.scroll} nestedScrollEnabled>
          {pins.map((p) => (
            <Pressable
              key={p.customer_id}
              onPress={() => onSelect(p.customer_id)}
              style={styles.row}
              testID={`dispatch-unrouted-row-${p.customer_id}`}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={1}>{p.customer_name}</Text>
                {(p.service_days || []).length > 0 && (
                  <Text style={styles.meta} numberOfLines={1}>
                    {(p.service_days || []).join(" · ")}
                  </Text>
                )}
              </View>
              <Ionicons name="chevron-forward" size={14} color={colors.muted} />
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.sm, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface, gap: spacing.xs,
  },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  title: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, fontStyle: "italic" },
  scroll: { maxHeight: 200 },
  row: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: spacing.xs, paddingHorizontal: spacing.xs,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  name: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
});
