import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
// Phase 20 · Feb-2026 · Sub-item B — role-aware tap-through resolver.
import { resolveNotificationRoute } from "@/src/services/notificationRoutes";
import { useAuth } from "@/src/auth";

const ICON: Record<string, any> = {
  "Request approved": "checkmark-circle",
  "Technician assigned": "person",
  "Service scheduled": "calendar",
  "Technician on the way": "car",
};

function timeAgo(iso: string) {
  try {
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return "";
  }
}

export default function Notifications() {
  const router = useRouter();
  const { user } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get("/notifications");
      setItems(data);
      // Mark all as read once viewed
      if (data.some((n: any) => !n.read)) await api.post("/notifications/read-all");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  return (
    <View style={styles.root}>
      <Header title="Notifications" back />
      {loading ? (
        <Loading testID="notifications-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="notifications-outline" title="No notifications yet" subtitle="Updates about your services will appear here." testID="notifications-empty" />
      ) : (
        <FlatList
          testID="notifications-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Pressable
              style={[styles.row, !item.read && styles.unreadRow]}
              onPress={() => {
                // Phase 20 · Sub-item B — role-aware tap-through with
                // kind-based routing. Falls back to the existing
                // job_id / href behaviour when kind is unknown.
                const path = resolveNotificationRoute(item, user);
                if (path) router.push(path as any);
              }}
              testID={`notification-${item.id}`}
            >
              <View style={styles.icon}>
                <Ionicons name={ICON[item.title] || "information-circle"} size={20} color={colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{item.title}</Text>
                <Text style={styles.body}>{item.body}</Text>
                <Text style={styles.time}>{timeAgo(item.created_at)}</Text>
              </View>
              {!item.read ? <View style={styles.dot} /> : null}
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: {
    flexDirection: "row",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
    alignItems: "center",
  },
  unreadRow: { borderColor: colors.brandTertiary, backgroundColor: "#F7FCFF" },
  icon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  body: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 1 },
  time: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 3 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brand },
});
