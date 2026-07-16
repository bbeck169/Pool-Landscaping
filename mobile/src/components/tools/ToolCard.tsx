/**
 * Phase 42 · Tools Hub — reusable card.
 *
 * Bigger tap target than the legacy `Tile` (min 88pt height, larger icon
 * background) and role-agnostic — the hub screen is responsible for
 * gating what does/doesn't render. Optionally shows a compact variant
 * for the pinned / recent horizontal rows.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export type ToolCardTile = {
  key: string;
  icon: any;
  label: string;
  desc: string;
  route: string;
};

type Props = {
  tile: ToolCardTile;
  onPress: () => void;
  variant?: "row" | "compact";
  testIDPrefix?: string;
  rightSlot?: React.ReactNode;
};

export const ToolCard: React.FC<Props> = ({
  tile, onPress, variant = "row", testIDPrefix = "tools-card", rightSlot,
}) => {
  if (variant === "compact") {
    return (
      <Pressable
        style={styles.compactCard}
        onPress={onPress}
        testID={`${testIDPrefix}-${tile.key}`}
        android_ripple={{ color: colors.border }}
        accessibilityRole="button"
        accessibilityLabel={tile.label}
      >
        <View style={styles.compactIcon}>
          <Ionicons name={tile.icon} size={22} color={colors.brand} />
        </View>
        <Text style={styles.compactLabel} numberOfLines={2}>{tile.label}</Text>
      </Pressable>
    );
  }
  return (
    <Pressable
      style={styles.rowCard}
      onPress={onPress}
      testID={`${testIDPrefix}-${tile.key}`}
      android_ripple={{ color: colors.border }}
      accessibilityRole="button"
      accessibilityLabel={tile.label}
    >
      <View style={styles.rowIcon}>
        <Ionicons name={tile.icon} size={24} color={colors.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{tile.label}</Text>
        <Text style={styles.rowDesc} numberOfLines={2}>{tile.desc}</Text>
      </View>
      {rightSlot ?? (
        <Ionicons name="chevron-forward" size={18} color={colors.muted} />
      )}
    </Pressable>
  );
};

const styles = StyleSheet.create({
  rowCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    paddingVertical: 14, // Slightly taller than legacy `Tile` (11pt).
    minHeight: 88,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  rowIcon: {
    width: 52,
    height: 52,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  rowLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  rowDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 3 },
  compactCard: {
    width: 108,
    minHeight: 96,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    marginRight: spacing.sm,
  },
  compactIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  compactLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    textAlign: "center",
  },
});
