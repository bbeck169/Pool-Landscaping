import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, StatusChip } from "@/src/components/ui";
import { Header, FilterRow } from "@/src/components/widgets";
// Phase 30 · Feb-2026 — shared mobile TechAvatar for tech chips.
import TechAvatar from "@/components/common/TechAvatar";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "requested", label: "Requested" },
  { key: "pending", label: "Pending" },
  { key: "active", label: "Active" },
  { key: "completed", label: "Completed" },
];

export default function PortalServices() {
  const router = useRouter();
  const [jobs, setJobs] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (f: string) => {
    try {
      const q = f === "all" ? "" : `?status=${f}`;
      const data = await api.get(`/jobs${q}`);
      setJobs(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(filter); }, [filter, load]));

  const renderItem = ({ item }: { item: any }) => (
    <Pressable
      testID={`portal-service-${item.id}`}
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
      onPress={() => router.push(`/portal/service/${item.id}` as any)}
    >
      <View style={styles.cardIcon}>
        <Ionicons name="water-outline" size={18} color={colors.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.cardTitle} numberOfLines={1}>{item.title}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 }}>
          {item.technician_name ? (
            <TechAvatar
              user={{ name: item.technician_name }}
              size="xs"
              testID={`portal-tech-avatar-${item.id}`}
            />
          ) : null}
          <Text style={styles.cardMeta}>{item.scheduled_date || "TBD"} · {item.technician_name || "Unassigned"}</Text>
        </View>
      </View>
      <StatusChip status={item.status} />
    </Pressable>
  );

  return (
    <View style={styles.root}>
      <Header title="Service Records" subtitle="Your upcoming & past services" back />
      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="portal-services-filter" />
      {loading ? (
        <Loading testID="portal-services-loading" />
      ) : jobs.length === 0 ? (
        <EmptyState icon="clipboard-outline" title="No services yet" subtitle="Your service history will appear here." testID="portal-services-empty" />
      ) : (
        <FlatList
          testID="portal-services-list"
          data={jobs}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          renderItem={renderItem}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(filter); }} />}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  cardIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
