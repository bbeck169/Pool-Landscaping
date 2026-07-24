import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const KIND_META: Record<string, { icon: any; bg: string; fg: string }> = {
  company_profile: { icon: "business-outline", bg: "#DBEAFE", fg: "#1E40AF" },
  faq: { icon: "help-circle-outline", bg: "#FCE7F3", fg: "#9D174D" },
  policy: { icon: "shield-checkmark-outline", bg: "#FEF3C7", fg: "#92400E" },
  custom: { icon: "document-text-outline", bg: "#E0E7FF", fg: "#4338CA" },
};

function SkeletonRows() {
  return (
    <View style={s.skelWrap} testID="ai-brain-skeleton">
      {[1, 2, 3].map((i) => (
        <View key={i} style={s.skelCard}>
          <View style={s.skelIcon} />
          <View style={{ flex: 1, gap: 6 }}>
            <View style={[s.skelBar, { width: "60%" }]} />
            <View style={[s.skelBar, { width: "90%" }]} />
          </View>
        </View>
      ))}
    </View>
  );
}

export default function AIBrainPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [items, setItems] = useState<any[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/ai/knowledge");
      setItems(r?.items || []);
    } catch {
      setItems([]);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { if (isAdmin) load(); }, [isAdmin, load]));

  if (!isAdmin) {
    return (
      <View style={s.root}>
        <Header title="AI Brain" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  const renderItem = ({ item }: { item: any }) => {
    const km = KIND_META[item.kind] || KIND_META.custom;
    const isOpen = expanded === item.id;
    return (
      <Pressable
        testID={`ai-brain-entry-${item.id}`}
        style={[s.card, isOpen && s.cardExpanded]}
        onPress={() => setExpanded(isOpen ? null : item.id)}
      >
        <View style={s.cardHeader}>
          <View style={[s.kindIcon, { backgroundColor: km.bg }]}>
            <Ionicons name={km.icon} size={16} color={km.fg} />
          </View>
          <View style={{ flex: 1 }}>
            <View style={s.chipRow}>
              <View style={[s.kindChip, { backgroundColor: km.bg }]}>
                <Text style={[s.kindChipText, { color: km.fg }]}>
                  {(item.kind || "custom").replace(/_/g, " ")}
                </Text>
              </View>
            </View>
            <Text style={s.entryTitle} numberOfLines={isOpen ? undefined : 1}>
              {item.title}
            </Text>
          </View>
          <Ionicons name={isOpen ? "chevron-up" : "chevron-down"} size={18} color={colors.muted} />
        </View>
        {isOpen && item.content ? (
          <View style={s.contentWrap}>
            <Text style={s.contentText}>{item.content}</Text>
          </View>
        ) : null}
      </Pressable>
    );
  };

  return (
    <View style={s.root}>
      <Header title="AI Brain" subtitle="Knowledge base entries (read-only)" back />
      {items === null ? (
        <SkeletonRows />
      ) : items.length === 0 ? (
        <EmptyState
          icon="bulb-outline"
          title="No knowledge entries"
          subtitle="Add entries from the web admin to train the AI."
          testID="ai-brain-empty"
        />
      ) : (
        <FlatList
          testID="ai-brain-list"
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />
          }
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm,
  },
  cardExpanded: { borderColor: colors.brand },
  cardHeader: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  kindIcon: { width: 36, height: 36, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  chipRow: { flexDirection: "row", gap: spacing.sm },
  kindChip: { paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill },
  kindChipText: { fontFamily: font.bold, fontSize: 9, textTransform: "uppercase" },
  entryTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  contentWrap: {
    marginTop: spacing.md, paddingTop: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.divider,
  },
  contentText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, lineHeight: 20 },
  skelWrap: { padding: spacing.lg, gap: spacing.sm },
  skelCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.lg, borderRadius: radius.lg, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  skelIcon: { width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary },
  skelBar: { height: 12, borderRadius: 6, backgroundColor: colors.surfaceTertiary },
});
