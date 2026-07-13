import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const when = (iso?: string) => {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
};

export default function AccessHistory() {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLogs(await api.get("/admin/access-history"));
    } catch {
      setLogs([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Access History" back subtitle="Admin 'view as customer' sessions" />
      {loading ? (
        <Loading testID="access-history-loading" />
      ) : logs.length === 0 ? (
        <EmptyState icon="eye-outline" title="No access yet" subtitle="Admin customer-portal views will appear here." testID="access-history-empty" />
      ) : (
        <FlatList
          testID="access-history-list"
          data={logs}
          keyExtractor={(l, i) => l.id || String(i)}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => {
            const started = item.event === "impersonation_started";
            return (
              <View style={styles.row} testID={`access-${item.id}`}>
                <View style={[styles.icon, { backgroundColor: started ? "#FEF3C7" : "#DCFCE7" }]}>
                  <Ionicons name={started ? "eye" : "exit-outline"} size={16} color={started ? "#B45309" : "#16A34A"} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.title}>
                    {started
                      ? `${item.admin_name || "Admin"} viewed ${item.customer_name || "a customer"}`
                      : `Session ended`}
                  </Text>
                  <Text style={styles.meta}>{when(item.created_at)}</Text>
                </View>
                <View style={[styles.badge, { backgroundColor: started ? "#FEF3C7" : "#F1F5F9" }]}>
                  <Text style={[styles.badgeText, { color: started ? "#B45309" : "#64748B" }]}>{started ? "Viewed" : "Ended"}</Text>
                </View>
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
  icon: { width: 36, height: 36, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.pill },
  badgeText: { fontFamily: font.bold, fontSize: fontSize.sm },
});
