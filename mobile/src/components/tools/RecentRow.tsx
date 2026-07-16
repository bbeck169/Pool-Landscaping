/**
 * Phase 42 · Tools Hub — horizontal row of the 5 most-recent tools.
 *
 * Auto-populated by `markUsed()` in `useToolsPreferences` whenever a tool
 * card is tapped. Deliberately compact (icon + short label) so it doesn't
 * dominate a small screen. Empty state gives an honest hint rather than
 * a fake placeholder.
 */
import React from "react";
import { View, Text, FlatList, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { ToolCard, type ToolCardTile } from "./ToolCard";

type Props = {
  allTiles: ToolCardTile[]; // RBAC-filtered universe
  recents: { slug: string; at: string }[];
  onOpen: (tile: ToolCardTile) => void;
};

export const RecentRow: React.FC<Props> = ({ allTiles, recents, onOpen }) => {
  const bySlug: Record<string, ToolCardTile> = {};
  for (const t of allTiles) bySlug[t.key] = t;
  const tiles = recents.map((r) => bySlug[r.slug]).filter(Boolean);

  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>Recent</Text>
      {tiles.length === 0 ? (
        <View style={styles.empty} testID="tools-recents-empty">
          <Ionicons name="time-outline" size={18} color={colors.muted} />
          <Text style={styles.emptyText}>
            Recently opened tools will land here.
          </Text>
        </View>
      ) : (
        <FlatList
          data={tiles}
          horizontal
          keyExtractor={(t) => t.key}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.list}
          renderItem={({ item }) => (
            <ToolCard
              tile={item}
              variant="compact"
              testIDPrefix="tools-recent"
              onPress={() => onOpen(item)}
            />
          )}
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { marginTop: spacing.xl },
  title: {
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.onSurfaceSecondary,
  },
  list: { paddingHorizontal: spacing.lg },
  empty: {
    marginHorizontal: spacing.lg,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
  },
  emptyText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
