/**
 * M4 · per-property category chip-group (web Ticket AA PropertyCategorySelector).
 * Interactive when `onPick` is given (admin): tap to set, tap the active chip to
 * clear. Without `onPick` the chips are read-only (no press handler).
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";

import { colors, font } from "@/src/theme";
import { PROPERTY_CATEGORIES, PROPERTY_CATEGORY_LABEL, type PropertyCategory } from "@/src/lib/combinedCategory";

type Props = { propertyId: string; current?: string | null; onPick?: (c: PropertyCategory) => void };

export default function PropertyCategorySelector({ propertyId, current, onPick }: Props) {
  const cur = String(current || "").toLowerCase();
  return (
    <View style={st.row} accessibilityRole="radiogroup" accessibilityLabel="Property service category" testID={`pc-category-group-${propertyId}`}>
      {PROPERTY_CATEGORIES.map((c) => {
        const active = cur === c;
        const chipStyle = [st.chip, active && st.chipOn, !onPick && st.chipRO];
        const label = <Text style={[st.text, active && st.textOn]}>{PROPERTY_CATEGORY_LABEL[c]}</Text>;
        return onPick ? (
          <Pressable key={c} onPress={() => onPick(c)} style={chipStyle} hitSlop={4} accessibilityRole="radio" accessibilityState={{ selected: active }} testID={`pc-cat-${c}-${propertyId}`}>
            {label}
          </Pressable>
        ) : (
          <View key={c} style={chipStyle} accessibilityRole="radio" accessibilityState={{ selected: active, disabled: true }} testID={`pc-cat-${c}-${propertyId}`}>
            {label}
          </View>
        );
      })}
    </View>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  chip: { minHeight: 36, paddingHorizontal: 12, justifyContent: "center", borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipOn: { backgroundColor: "#DBEAFE", borderColor: "#93C5FD" },
  chipRO: { opacity: 0.85 },
  text: { fontFamily: font.medium, fontSize: 12, color: colors.onSurfaceSecondary },
  textOn: { color: "#1E3A8A", fontFamily: font.bold },
});
