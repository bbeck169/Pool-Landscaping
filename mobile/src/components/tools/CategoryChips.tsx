/**
 * Phase 42 · Tools Hub — horizontal chip row for category filtering.
 *
 * Renders a leading "All" chip plus one chip per section derived from
 * the current role's IA. Selected chip flips to the brand-accent fill.
 * A tap on the currently-selected chip is a no-op (parent keeps its own
 * state; we just call onSelect).
 */
import React from "react";
import { FlatList, Pressable, Text, StyleSheet, View } from "react-native";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export type CategoryChip = { key: string; label: string };

type Props = {
  chips: CategoryChip[];
  selected: string; // "all" or a section key
  onSelect: (key: string) => void;
};

export const CategoryChips: React.FC<Props> = ({ chips, selected, onSelect }) => {
  const data: CategoryChip[] = [{ key: "all", label: "All" }, ...chips];
  return (
    <View style={styles.wrap}>
      <FlatList
        data={data}
        horizontal
        keyExtractor={(c) => c.key}
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => {
          const active = item.key === selected;
          return (
            <Pressable
              onPress={() => onSelect(item.key)}
              testID={`tools-chip-${item.key}`}
              style={[styles.chip, active ? styles.chipActive : null]}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              accessibilityLabel={`Filter: ${item.label}`}
            >
              <Text style={[styles.label, active ? styles.labelActive : null]}>
                {item.label}
              </Text>
            </Pressable>
          );
        }}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { marginTop: spacing.md },
  list: { paddingHorizontal: spacing.lg, gap: spacing.sm },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginRight: spacing.sm,
    minHeight: 34,
    justifyContent: "center",
  },
  chipActive: {
    borderColor: colors.brand,
    backgroundColor: colors.brand,
  },
  label: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  labelActive: {
    color: "#FFFFFF",
    fontFamily: font.semibold,
  },
});
