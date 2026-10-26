/** M3a · All / Pool / Landscaping / Both chip-group (web Ticket Y). Single-select radio group. */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";

import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { SERVICE_CATEGORY_BUCKETS, type ServiceCategoryBucket } from "@/src/lib/scheduleServiceCategory";

type Props = { value: ServiceCategoryBucket; onChange: (b: ServiceCategoryBucket) => void };

export default function ServiceCategoryChips({ value, onChange }: Props) {
  return (
    <View style={st.row} accessibilityRole="radiogroup" accessibilityLabel="Service category filter" testID="schedule-service-category-filter">
      {SERVICE_CATEGORY_BUCKETS.map((b) => {
        const active = value === b;
        return (
          <Pressable
            key={b}
            onPress={() => { if (!active) onChange(b); }}
            style={[st.chip, active && st.chipActive]}
            hitSlop={4}
            accessibilityRole="radio"
            accessibilityState={{ selected: active }}
            testID={`schedule-service-category-${b.toLowerCase()}`}
          >
            <Text style={[st.text, active && st.textActive]} numberOfLines={1}>{b}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", gap: 6, paddingHorizontal: spacing.md, paddingBottom: spacing.xs },
  chip: { flexShrink: 1, minHeight: 36, paddingHorizontal: 12, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  text: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  textActive: { color: "#fff", fontFamily: font.bold },
});
