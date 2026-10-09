/**
 * Phase 25 · Customer profile skeleton loader (mobile parity with web
 * Phase 22 · 0a176aeeb).
 *
 * Renders IMMEDIATELY on mount — before the slim profile resolves — in
 * the same silhouette as the real profile so there's no blank frame and
 * no layout jump: the Phase-20 action row (Edit / Call / View-as /
 * Delete), header card (avatar + name bar + address line), the tile
 * area (status-pill strip + contact card), then body rows — section
 * labels with placeholder count badges (Job History / Documents /
 * Communication).
 *
 * Pulse: one shared ``Animated.loop(Animated.sequence(...))`` on
 * opacity (native driver) — the mobile ``animate-pulse`` analogue.
 * Region testIDs mirror web Phase 22 (cd-skeleton-action-row,
 * cd-skeleton-header-card, cd-skeleton-content, …).
 */
import React, { useEffect, useRef } from "react";
import { Animated, ScrollView, StyleSheet, View } from "react-native";

import { Header } from "@/src/components/widgets";
import { colors, spacing, radius } from "@/src/theme";

export const SKELETON_SECTIONS = ["jobs", "documents", "timeline"] as const;
export const ACTION_SLOTS = ["edit", "call", "impersonate", "delete"] as const;

function Bar({ w, h = 12, round = false, testID, style }: {
  w: number | `${number}%`; h?: number; round?: boolean; testID?: string; style?: any;
}) {
  return (
    <View
      testID={testID}
      style={[s.bar, { width: w, height: h, borderRadius: round ? h / 2 : radius.sm }, style]}
    />
  );
}

export default function CustomerProfileSkeleton() {
  const pulse = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 0.45, duration: 700, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  return (
    <View style={s.root} testID="customer-detail-skeleton" accessibilityLabel="Loading customer">
      <Header title="Customer" back />
      <ScrollView contentContainerStyle={s.content} scrollEnabled={false}>
        <Animated.View style={{ opacity: pulse }} testID="cd-skeleton-pulse">
          <View style={s.actionRow} testID="cd-skeleton-action-row">
            {ACTION_SLOTS.map((k) => (
              <View key={k} style={s.actionSlot} testID={`cd-skeleton-action-${k}`} />
            ))}
          </View>
          <View style={s.card} testID="cd-skeleton-header-card">
            <View style={s.headerRow}>
              <Bar w={56} h={56} round testID="cd-skeleton-avatar" />
              <View style={{ flex: 1, gap: spacing.sm }}>
                <Bar w="70%" h={18} testID="cd-skeleton-name" />
                <Bar w="90%" testID="cd-skeleton-address" />
              </View>
            </View>
          </View>
          <View testID="cd-skeleton-tile-area">
            <View style={s.pillRow} testID="cd-skeleton-status-strip">
              <Bar w={96} h={28} round />
              <Bar w={120} h={28} round />
            </View>
            <View style={[s.card, { gap: spacing.md }]} testID="cd-skeleton-contact-card">
              <Bar w="60%" />
              <Bar w="80%" />
              <Bar w="50%" />
            </View>
          </View>
          <View testID="cd-skeleton-content">
          <View testID="cd-skeleton-sections">
            {SKELETON_SECTIONS.map((k) => (
              <View key={k} style={s.sectionRow} testID={`cd-skeleton-section-${k}`}>
                <Bar w={140} h={18} />
                <Bar w={26} h={20} round testID={`cd-skeleton-badge-${k}`} />
              </View>
            ))}
          </View>
          </View>
        </Animated.View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  content: { padding: spacing.lg },
  bar: { backgroundColor: colors.divider },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  actionRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  actionSlot: {
    flexGrow: 1, flexBasis: "45%", minHeight: 44, borderRadius: radius.md,
    backgroundColor: colors.divider,
  },
  pillRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  sectionRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    marginTop: spacing.xl, minHeight: 44,
  },
});
