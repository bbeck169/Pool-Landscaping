/**
 * Phase 42 · Tools Hub — horizontal row of pinned tools.
 *
 * The user maintains a personal pin list (up to 6). Tapping "Edit" opens
 * a bottom modal listing every tile with a per-item toggle so the tech
 * can curate without leaving the screen. Tiles hidden by RBAC never
 * reach this component — the hub screen filters `allTiles` first.
 */
import React, { useState } from "react";
import {
  View, Text, FlatList, StyleSheet, Pressable, Modal, ScrollView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { ToolCard, type ToolCardTile } from "./ToolCard";

type Props = {
  allTiles: ToolCardTile[];       // full visible-tile universe (already RBAC-filtered)
  pins: string[];                 // ordered slug list
  onOpen: (tile: ToolCardTile) => void;
  onTogglePin: (slug: string) => void;
  maxPins: number;
};

export const PinnedRow: React.FC<Props> = ({
  allTiles, pins, onOpen, onTogglePin, maxPins,
}) => {
  const [editOpen, setEditOpen] = useState(false);
  const tileBySlug: Record<string, ToolCardTile> = {};
  for (const t of allTiles) tileBySlug[t.key] = t;
  const pinnedTiles = pins.map((s) => tileBySlug[s]).filter(Boolean);

  return (
    <View style={styles.wrap}>
      <View style={styles.header}>
        <Text style={styles.title}>Pinned</Text>
        <Pressable
          onPress={() => setEditOpen(true)}
          testID="tools-pins-edit"
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Edit pinned tools"
        >
          <Text style={styles.editLink}>Edit</Text>
        </Pressable>
      </View>

      {pinnedTiles.length === 0 ? (
        <View style={styles.empty} testID="tools-pins-empty">
          <Ionicons name="pin-outline" size={18} color={colors.muted} />
          <Text style={styles.emptyText}>
            Pin your most-used tools for one-tap access.
          </Text>
        </View>
      ) : (
        <FlatList
          data={pinnedTiles}
          horizontal
          keyExtractor={(t) => t.key}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.list}
          renderItem={({ item }) => (
            <ToolCard
              tile={item}
              variant="compact"
              testIDPrefix="tools-pin"
              onPress={() => onOpen(item)}
            />
          )}
        />
      )}

      <Modal
        visible={editOpen}
        animationType="slide"
        transparent
        onRequestClose={() => setEditOpen(false)}
      >
        <Pressable
          style={styles.backdrop}
          onPress={() => setEditOpen(false)}
          accessibilityLabel="Close pin editor"
        />
        <View style={styles.sheet}>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Edit pins</Text>
            <Text style={styles.sheetCap}>
              {pins.length} / {maxPins}
            </Text>
            <Pressable
              onPress={() => setEditOpen(false)}
              hitSlop={8}
              testID="tools-pins-edit-close"
            >
              <Ionicons name="close" size={22} color={colors.onSurface} />
            </Pressable>
          </View>
          <ScrollView style={styles.sheetBody}>
            {allTiles.map((t) => {
              const pinned = pins.includes(t.key);
              const disabled = !pinned && pins.length >= maxPins;
              return (
                <Pressable
                  key={t.key}
                  style={[styles.pinRow, disabled ? styles.pinRowDisabled : null]}
                  onPress={() => !disabled && onTogglePin(t.key)}
                  testID={`tools-pins-toggle-${t.key}`}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: pinned, disabled }}
                >
                  <View style={styles.pinRowIcon}>
                    <Ionicons name={t.icon} size={20} color={colors.brand} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.pinRowLabel}>{t.label}</Text>
                    <Text style={styles.pinRowDesc} numberOfLines={1}>{t.desc}</Text>
                  </View>
                  <Ionicons
                    name={pinned ? "checkbox" : "square-outline"}
                    size={22}
                    color={pinned ? colors.brand : colors.muted}
                  />
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { marginTop: spacing.xl },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  title: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.onSurfaceSecondary,
  },
  editLink: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
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
  backdrop: {
    ...(Platform.OS === "web"
      ? { position: "fixed" as any, top: 0, left: 0, right: 0, bottom: 0 }
      : { ...StyleSheet.absoluteFillObject }),
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  sheet: {
    position: "absolute",
    left: 0, right: 0, bottom: 0,
    maxHeight: "80%",
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingBottom: spacing["2xl"],
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: spacing.md,
  },
  sheetTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    flex: 1,
  },
  sheetCap: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  sheetBody: { paddingHorizontal: spacing.lg },
  pinRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  pinRowDisabled: { opacity: 0.4 },
  pinRowIcon: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  pinRowLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pinRowDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
