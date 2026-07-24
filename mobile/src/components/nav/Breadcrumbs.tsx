/**
 * Breadcrumbs — horizontal breadcrumb navigation strip.
 *
 * Renders `Home › Section › Current`. Each segment except the last is
 * tappable. When the trail exceeds 3 items on narrow screens, the
 * middle collapses to `Home › … › Current` with a tappable ellipsis
 * that expands an ActionSheet showing intermediate items.
 */
import React, { useState, useCallback } from "react";
import {
  View, Text, Pressable, StyleSheet, useWindowDimensions, Modal,
  TouchableOpacity, ScrollView,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, spacing, radius } from "@/src/theme";
import type { BreadcrumbItem } from "@/src/hooks/useBreadcrumbs";

const SEPARATOR = " › ";
const COLLAPSE_THRESHOLD_WIDTH = 420; // collapse when screen < 420px and > 3 items

export default function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const [popoverVisible, setPopoverVisible] = useState(false);

  const navigate = useCallback(
    (route: string) => {
      router.push(route as any);
    },
    [router],
  );

  if (!items || items.length === 0) return null;

  // Should we collapse?
  const shouldCollapse = items.length > 3 && width < COLLAPSE_THRESHOLD_WIDTH;

  const renderSegment = (item: BreadcrumbItem, idx: number, isLast: boolean) => {
    if (isLast) {
      return (
        <Text
          key={`bc-${idx}`}
          style={styles.currentText}
          numberOfLines={1}
          testID={`breadcrumb-current`}
        >
          {item.label}
        </Text>
      );
    }
    return (
      <Pressable
        key={`bc-${idx}`}
        onPress={() => item.route && navigate(item.route)}
        hitSlop={6}
        testID={`breadcrumb-${idx}`}
      >
        <Text style={styles.linkText} numberOfLines={1}>
          {item.label}
        </Text>
      </Pressable>
    );
  };

  const renderSeparator = (key: string) => (
    <Text key={key} style={styles.sep}>{SEPARATOR}</Text>
  );

  // Collapsed view: Home › … › Current
  if (shouldCollapse) {
    const first = items[0];
    const last = items[items.length - 1];
    const middle = items.slice(1, -1);

    return (
      <View style={styles.container} testID="breadcrumbs-strip">
        {renderSegment(first, 0, false)}
        {renderSeparator("sep-0")}
        <Pressable
          onPress={() => setPopoverVisible(true)}
          hitSlop={8}
          testID="breadcrumb-ellipsis"
        >
          <Text style={styles.ellipsis}>…</Text>
        </Pressable>
        {renderSeparator("sep-e")}
        {renderSegment(last, items.length - 1, true)}

        {/* Popover modal for collapsed items */}
        <Modal
          visible={popoverVisible}
          transparent
          animationType="fade"
          onRequestClose={() => setPopoverVisible(false)}
        >
          <Pressable
            style={styles.overlay}
            onPress={() => setPopoverVisible(false)}
          >
            <View style={styles.popover} testID="breadcrumb-popover">
              <Text style={styles.popoverTitle}>Navigate to</Text>
              <ScrollView style={{ maxHeight: 300 }}>
                {[first, ...middle].map((item, i) => (
                  <TouchableOpacity
                    key={`pop-${i}`}
                    style={styles.popoverItem}
                    onPress={() => {
                      setPopoverVisible(false);
                      if (item.route) navigate(item.route);
                    }}
                    testID={`breadcrumb-popover-${i}`}
                  >
                    <Ionicons
                      name={i === 0 ? "home-outline" : "chevron-forward-outline"}
                      size={14}
                      color={colors.brand}
                    />
                    <Text style={styles.popoverText}>{item.label}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            </View>
          </Pressable>
        </Modal>
      </View>
    );
  }

  // Full view: all segments visible
  const elements: React.ReactNode[] = [];
  items.forEach((item, idx) => {
    if (idx > 0) elements.push(renderSeparator(`sep-${idx}`));
    elements.push(renderSegment(item, idx, idx === items.length - 1));
  });

  return (
    <View style={styles.container} testID="breadcrumbs-strip">
      {elements}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingTop: 2,
    paddingBottom: spacing.xs,
    flexWrap: "nowrap",
  },
  linkText: {
    fontFamily: font.medium,
    fontSize: 13,
    color: colors.brand,
    maxWidth: 140,
  },
  currentText: {
    fontFamily: font.semibold,
    fontSize: 13,
    color: colors.onSurfaceSecondary,
    maxWidth: 160,
    flexShrink: 1,
  },
  sep: {
    fontFamily: font.regular,
    fontSize: 13,
    color: colors.muted,
    marginHorizontal: 1,
  },
  ellipsis: {
    fontFamily: font.bold,
    fontSize: 15,
    color: colors.brand,
    paddingHorizontal: 4,
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.35)",
    justifyContent: "flex-start",
    paddingTop: 100,
    paddingHorizontal: spacing.lg,
  },
  popover: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
  },
  popoverTitle: {
    fontFamily: font.bold,
    fontSize: 13,
    color: colors.muted,
    marginBottom: spacing.sm,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  popoverItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xs,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  popoverText: {
    fontFamily: font.medium,
    fontSize: 14,
    color: colors.onSurface,
  },
});
