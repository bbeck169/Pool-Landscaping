import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

function relTime(iso?: string) {
  if (!iso) return "";
  try {
    const then = new Date(iso).getTime();
    const diff = Math.max(0, Date.now() - then);
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    if (d < 7) return `${d}d ago`;
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

const TINT: Record<string, string> = {
  payment: colors.success,
  request: "#C2410C",
  job_done: colors.success,
  job: colors.brand,
  lead: colors.brandSecondary,
};

export default function WorkStream() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/activity"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Work Stream" back subtitle="Live activity feed" />
      {loading ? (
        <Loading testID="activity-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="pulse-outline" title="No activity yet" subtitle="Jobs, payments and leads appear here." testID="activity-empty" />
      ) : (
        <FlatList
          testID="activity-list"
          data={items}
          keyExtractor={(_, i) => String(i)}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => {
            const tint = TINT[item.type] || colors.brand;
            return (
              <View style={styles.row} testID={`activity-${item.type}`}>
                <View style={[styles.icon, { backgroundColor: tint + "1A" }]}>
                  <Ionicons name={item.icon as any} size={18} color={tint} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.title}>{item.title}</Text>
                  <Text style={styles.detail} numberOfLines={1}>{item.detail}</Text>
                </View>
                <Text style={styles.time}>{relTime(item.at)}</Text>
              </View>
            );
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  icon: { width: 40, height: 40, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  detail: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  time: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
});
