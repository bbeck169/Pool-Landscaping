/**
 * Dashboard parity · row parts for `app/properties.tsx` — mirrors web
 * `PropertiesListPage.jsx` CategoryChip / ActiveBadge / PropertyRow /
 * CustomerGroup header (same copy + testIDs).
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export function formatAddress(addr: any): string {
  if (!addr) return "";
  return [addr.line1, addr.city, addr.state, addr.postal_code].filter(Boolean).join(", ");
}

// Web Tailwind tokens: sky/emerald/violet 100 bg + 800 fg; muted for "Not set".
const CHIP: Record<string, { label: string; icon: any; bg: string; fg: string }> = {
  pool: { label: "Pool", icon: "water-outline", bg: "#E0F2FE", fg: "#075985" },
  landscaping: { label: "Landscaping", icon: "leaf-outline", bg: "#D1FAE5", fg: "#065F46" },
  both: { label: "Both", icon: "ellipse", bg: "#EDE9FE", fg: "#5B21B6" },
};

export function CategoryChip({ category }: { category?: string | null }) {
  const canon = String(category || "").toLowerCase();
  const m = CHIP[canon];
  const key = m ? canon : "unset";
  return (
    <View style={[s.chip, { backgroundColor: m?.bg || colors.surfaceSecondary }]} testID={`property-category-chip-${key}`}>
      {m ? <Ionicons name={m.icon} size={11} color={m.fg} /> : null}
      <Text style={[s.chipText, { color: m?.fg || colors.muted }]}>{m?.label || "Not set"}</Text>
    </View>
  );
}

export function ActiveBadge({ active }: { active?: boolean }) {
  const off = active === false;
  return (
    <View style={s.badge} testID={`property-active-badge-${off ? "inactive" : "active"}`}>
      <Ionicons name={off ? "close-circle-outline" : "checkmark-circle-outline"} size={12} color={off ? colors.muted : "#065F46"} />
      <Text style={[s.badgeText, { color: off ? colors.muted : "#065F46" }]}>{off ? "Inactive" : "Active"}</Text>
    </View>
  );
}

export function PropertyRow({ property, onOpen }: { property: any; onOpen: () => void }) {
  return (
    <Pressable style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]} onPress={onOpen} testID={`property-row-${property.id}`}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={s.labelRow}>
          <Ionicons name="home-outline" size={14} color={colors.onSurface} />
          <Text style={s.label} numberOfLines={1}>{property.label || "(unlabelled)"}</Text>
        </View>
        <Text style={s.addr} numberOfLines={2}>{formatAddress(property.address) || "No address"}</Text>
      </View>
      <View style={s.right}>
        <CategoryChip category={property.service_category} />
        <ActiveBadge active={property.active} />
      </View>
    </Pressable>
  );
}

export function GroupHeader({ customerId, customerName, count }: { customerId: string; customerName: string; count: number }) {
  return (
    <View style={s.group} testID={`properties-group-${customerId}`}>
      <Ionicons name="people-outline" size={14} color={colors.onSurface} />
      <Text style={s.groupName} numberOfLines={1} testID={`properties-group-name-${customerId}`}>
        {customerName || "(unknown customer)"}
      </Text>
      <Text style={s.groupCount}>{`· ${count} ${count === 1 ? "property" : "properties"}`}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  chip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  chipText: { fontFamily: font.semibold, fontSize: 11 },
  badge: { flexDirection: "row", alignItems: "center", gap: 4 },
  badgeText: { fontFamily: font.regular, fontSize: 12 },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56,
    backgroundColor: colors.surface, paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  labelRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  label: { flexShrink: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  addr: { fontFamily: font.regular, fontSize: 13, color: colors.muted, marginTop: 2 },
  right: { alignItems: "flex-end", gap: 6 },
  group: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.border, marginTop: spacing.md,
  },
  groupName: { flexShrink: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  groupCount: { fontFamily: font.regular, fontSize: 13, color: colors.muted },
});
