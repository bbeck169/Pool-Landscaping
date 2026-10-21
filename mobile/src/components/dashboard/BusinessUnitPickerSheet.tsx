/**
 * TD-81 · Business Unit picker (bottom sheet). Lists tenant income
 * categories (`GET /income-categories` → `{items}`), current one checked.
 * Shared/TD-84-ready: no drill-down specifics in here.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Sheet } from "@/src/components/ui";
import { colors, spacing, font, fontSize } from "@/src/theme";
import type { IncomeCategory } from "@/src/lib/k48";

type Props = {
  visible: boolean;
  categories: IncomeCategory[];
  selectedId?: string;
  onSelect: (cat: IncomeCategory) => void;
  onClose: () => void;
};

export default function BusinessUnitPickerSheet({ visible, categories, selectedId, onSelect, onClose }: Props) {
  return (
    <Sheet visible={visible} onClose={onClose} title="Re-classify Business Unit" testID="bu-picker-sheet">
      {categories.length === 0 ? (
        <Text style={s.empty} testID="bu-picker-empty">No business units available.</Text>
      ) : (
        categories.map((c) => {
          const on = c.id === selectedId;
          return (
            <Pressable
              key={c.id} onPress={() => onSelect(c)} testID={`bu-option-${c.id}`}
              style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}
              accessibilityRole="radio" accessibilityState={{ selected: on }}
            >
              <Text style={[s.name, on && { color: colors.brand }]}>{c.name}</Text>
              {on ? <Ionicons name="checkmark" size={18} color={colors.brand} /> : <View style={{ width: 18 }} />}
            </Pressable>
          );
        })
      )}
    </Sheet>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 48, paddingHorizontal: spacing.lg, borderTopWidth: 1, borderTopColor: colors.divider },
  name: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  empty: { padding: spacing.xl, textAlign: "center", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
