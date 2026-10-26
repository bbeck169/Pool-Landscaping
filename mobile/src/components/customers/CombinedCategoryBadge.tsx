/** M4 · read-only combined category badge (web Ticket AA CombinedCategoryBadge). */
import React from "react";
import { View, Text, StyleSheet } from "react-native";

import { colors, font } from "@/src/theme";
import { computeCombinedCategory } from "@/src/lib/combinedCategory";

export default function CombinedCategoryBadge({ properties }: { properties: any[] }) {
  const label = computeCombinedCategory(properties);
  return (
    <View
      style={[st.badge, label ? st.on : st.off]}
      accessibilityRole="text"
      accessibilityHint="Set category per property below"
      testID="customer-combined-category-badge"
    >
      <Text style={[st.text, { color: label ? "#1E3A8A" : colors.muted }]} testID="customer-combined-category-text">
        {label ? label.toUpperCase() : "—"}
      </Text>
    </View>
  );
}

const st = StyleSheet.create({
  badge: { alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, borderWidth: 1 },
  on: { backgroundColor: "#DBEAFE", borderColor: "#93C5FD" },
  off: { backgroundColor: colors.surfaceSecondary, borderColor: colors.border },
  text: { fontFamily: font.bold, fontSize: 11, letterSpacing: 0.8 },
});
