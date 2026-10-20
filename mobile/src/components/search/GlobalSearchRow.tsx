/**
 * TD-90 · one shared global-search result row (kind variant).
 * Search rows are `{ id, primary, secondary }` only, so the existing
 * full-record rows (JobCard, customer list rows) don't fit.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import type { SearchHit } from "@/src/hooks/useGlobalSearch";
import type { SearchKind } from "@/src/lib/globalSearchRoutes";

type Props = { kind: SearchKind; icon: string; hit: SearchHit; onPress: () => void };

export default function GlobalSearchRow({ kind, icon, hit, onPress }: Props) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}
      testID={`global-search-row-${kind}-${hit.id}`}
      accessibilityRole="button"
      accessibilityLabel={`${hit.primary}${hit.secondary ? `, ${hit.secondary}` : ""}`}
    >
      <View style={s.icon}>
        <Ionicons name={icon as any} size={16} color={colors.brand} />
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={s.primary} numberOfLines={1}>{hit.primary}</Text>
        {hit.secondary ? <Text style={s.secondary} numberOfLines={1}>{hit.secondary}</Text> : null}
      </View>
      <Ionicons name="chevron-forward" size={14} color={colors.muted} />
    </Pressable>
  );
}

const s = StyleSheet.create({
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 52,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm, marginBottom: spacing.xs,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
  },
  icon: { width: 32, height: 32, borderRadius: radius.sm, alignItems: "center", justifyContent: "center", backgroundColor: colors.brandTertiary },
  primary: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  secondary: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 1 },
});
